import pytest
from fastapi.testclient import TestClient

from app import agent, catalog, core, db, planner, realize, workflow
from app.main import app

H = 'demo'
LIVE = {
    'id': 'live-brown-couch', 'retailer': 'Shop', 'title': 'Brown linen couch', 'category': 'sofa',
    'price_cents': 49900, 'currency': 'USD', 'dimensions_m': catalog.DEFAULT_DIMS['sofa'],
    'dimension_kind': 'estimated', 'source_type': 'live',
}


@pytest.fixture()
def client():
    with TestClient(app) as c:
        c.post('/demo/reset', params={'clear_handles': 'true'})
        yield c


def test_live_search_caches_serp_calls(monkeypatch):
    calls = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {'shopping_results': [
                {'title': 'Green accent chair', 'extracted_price': 89, 'link': 'https://shop.example/chair'}]}

    class FakeClient:
        def get(self, url, params=None, **kwargs):
            calls.append(params.get('q') if params else url)
            return FakeResponse()

    monkeypatch.setattr(catalog, '_http', FakeClient())
    monkeypatch.setattr(catalog.config, 'SHOPPING_API_KEY', 'test-key')
    catalog._live_cache.clear()
    first = catalog.live_search('green chair', limit=8)
    second = catalog.live_search('green chair', limit=8)
    assert calls == ['green chair']
    assert first and first == second


def test_search_uses_live_only_when_api_hits(client, monkeypatch):
    monkeypatch.setattr(catalog, 'live_search', lambda *a, **k: [dict(LIVE)])
    ids = [p['id'] for p in client.get('/products/search', params={'q': 'sofa'}).json()]
    assert ids[0] == 'live-brown-couch'
    assert all(p['category'] == 'sofa' for p in client.get('/products/search', params={'q': 'sofa'}).json())


def test_search_remembers_live_ids(client, monkeypatch):
    monkeypatch.setattr(catalog, 'live_search', lambda *a, **k: [dict(LIVE)])
    r = client.get('/products/search', params={'q': 'brown couch'})
    assert r.status_code == 200, r.text
    assert r.json()[0]['id'] == 'live-brown-couch'
    found = catalog.get('live-brown-couch')
    assert found is not None
    assert found['title'] == 'Brown linen couch'
    assert catalog.placeable(found)


def test_search_budget_filters_before_limit(client, monkeypatch):
    expensive = {**LIVE, 'id': 'live-expensive', 'title': 'Expensive sofa', 'price_cents': 100001}
    affordable = {**LIVE, 'id': 'live-affordable', 'title': 'Affordable sofa', 'price_cents': 100000}
    unknown = {**LIVE, 'id': 'live-unknown', 'title': 'Unpriced sofa', 'price_cents': 0}
    monkeypatch.setattr(catalog, 'live_search', lambda *a, **k: [expensive, unknown, affordable])
    monkeypatch.setattr(catalog, '_local_matches', lambda *a: [expensive, unknown, affordable])
    response = client.get('/products/search', params={'q': 'sofa', 'max_price_cents': 100000, 'limit': 1})
    assert response.status_code == 200
    assert [p['id'] for p in response.json()] == ['live-affordable']
    assert client.get('/products/search', params={'q': 'sofa', 'max_price_cents': -1}).status_code == 422


@pytest.mark.parametrize('saved,expected', [(123456, 123456), (0, 100000)])
def test_design_preserves_room_budget_or_defaults(client, monkeypatch, saved, expected):
    with db.tx() as connection:
        connection.execute('UPDATE households SET budget_cents=? WHERE id=?', (saved, H))
    budgets = []

    def plan(hid, cats, budget, *args, **kwargs):
        budgets.append(budget)
        return {'message': 'Test plan'}

    monkeypatch.setattr(workflow, 'run', plan)
    agent.furnish(H, 'emily', 'Furnish the room. Keep the door clear.', mode='design')
    assert budgets == [expected]
    assert core.household(H)['budget_cents'] == expected


def test_design_prompt_preserves_budget_cents():
    assert agent.parse_request('Furnish our room for $1,234.56.')['budget_cents'] == 123456


def test_sparse_live_listing_can_be_proposed(client, monkeypatch):
    monkeypatch.setattr(realize._pool, 'submit', lambda *a, **k: None)
    sparse = {
        'id': 'live-sparse-sofa', 'title': 'Sparse sofa', 'category': 'sofa',
        'price_cents': 40000, 'dimensions_m': catalog.DEFAULT_DIMS['sofa'], 'source_type': 'live',
        'variant': None, 'additional_costs': None, 'style': None,
    }
    catalog.remember([sparse])
    r = client.post(f'/households/{H}/chat', json={
        'member_id': 'emily', 'text': 'Just a sofa for $1500.',
        'pick_ids': ['live-sparse-sofa'], 'mode': 'design',
    })
    assert r.status_code == 200, r.text
    ids = [i['product_id'] for i in client.get(f'/households/{H}/state').json()['proposal']['items']]
    assert 'live-sparse-sofa' in ids


def test_design_with_picks_publishes_live_product(client, monkeypatch):
    monkeypatch.setattr(realize._pool, 'submit', lambda *a, **k: None)
    catalog.remember([LIVE])
    for mid, phone in [('emily', '+15550000001'), ('maya', '+15550000002'), ('alex', '+15550000003')]:
        assert client.put(f'/households/{H}/members/{mid}/handle', json={'handle': phone}).status_code == 200
    jobs_before = db.all_('SELECT job_id FROM outbound_jobs WHERE household_id=?', H)
    before = client.get(f'/households/{H}/state').json()['proposal']['version']
    r = client.post(f'/households/{H}/chat', json={
        'member_id': 'emily',
        'text': 'Just a brown couch for $1500.',
        'pick_ids': ['live-brown-couch'],
        'mode': 'design',
    })
    assert r.status_code == 200, r.text
    assert 'reply' in r.json()
    s = client.get(f'/households/{H}/state').json()
    assert s['proposal']['version'] > before
    ids = [i['product_id'] for i in s['proposal']['items']]
    assert 'live-brown-couch' in ids
    assert db.all_('SELECT job_id FROM outbound_jobs WHERE household_id=?', H) == jobs_before
    assert 'got their exact share privately' not in r.json()['reply']


def test_design_skips_owned_category(client, monkeypatch):
    monkeypatch.setattr(realize._pool, 'submit', lambda *a, **k: None)
    catalog.remember([LIVE])
    r = client.post(f'/households/{H}/chat', json={
        'member_id': 'emily',
        'text': 'Design the living room for $1500.',
        'pick_ids': ['live-brown-couch'],
        'skip_categories': ['sofa'],
        'mode': 'design',
    })
    assert r.status_code == 200, r.text
    items = client.get(f'/households/{H}/state').json()['proposal']['items']
    assert all(i['category'] != 'sofa' for i in items)
    assert 'live-brown-couch' not in [i['product_id'] for i in items]


def test_green_lamp_is_not_a_couch(client, monkeypatch):
    monkeypatch.setattr(catalog, 'live_search', lambda *a, **k: [])
    assert catalog.infer_category('green lamp') == 'lamp'
    r = client.get('/products/search', params={'q': 'green lamp'})
    assert r.status_code == 200
    assert all(p['category'] in ('lamp', 'other') for p in r.json())


def test_green_chair_does_not_return_catalog_dressers(client, monkeypatch):
    monkeypatch.setattr(catalog, 'live_search', lambda *a, **k: [])
    assert catalog.infer_category('green chair') == 'chair'
    assert catalog.infer_category('desk chair') == 'chair'
    r = client.get('/products/search', params={'q': 'green chair'})
    assert r.status_code == 200, r.text
    assert all(p['category'] != 'dresser' for p in r.json())
    assert all('dresser' not in p['title'].lower() for p in r.json())


def test_green_chair_returns_live_chairs(client, monkeypatch):
    chair = {
        'id': 'live-green-chair', 'retailer': 'Shop', 'title': 'Green velvet accent chair',
        'category': 'chair', 'price_cents': 18900, 'currency': 'USD',
        'dimensions_m': catalog.DEFAULT_DIMS['chair'], 'dimension_kind': 'estimated', 'source_type': 'live',
    }
    monkeypatch.setattr(catalog, 'live_search', lambda *a, **k: [dict(chair)])
    r = client.get('/products/search', params={'q': 'green chair'})
    assert r.status_code == 200, r.text
    assert r.json()[0]['id'] == 'live-green-chair'
    assert r.json()[0]['category'] == 'chair'
    assert catalog.get('live-green-chair')['title'] == 'Green velvet accent chair'


def test_refine_bumps_proposal_version(client):
    first = client.get(f'/households/{H}/state').json()['proposal']
    sofa = next(i['product_id'] for i in first['items'] if i['category'] == 'sofa')
    r = client.post(f'/households/{H}/chat', json={
        'member_id': 'emily',
        'text': 'cheaper sofa',
        'mode': 'refine',
    })
    assert r.status_code == 200, r.text
    second = client.get(f'/households/{H}/state').json()['proposal']
    assert second['version'] == first['version'] + 1
    new_sofa = next(i['product_id'] for i in second['items'] if i['category'] == 'sofa')
    assert new_sofa != sofa


def test_chat_without_mode_refines_existing_proposal(client):
    version = client.get(f'/households/{H}/state').json()['proposal']['version']
    r = client.post(f'/households/{H}/chat', json={'member_id': 'emily', 'text': 'swap the sofa'})
    assert r.status_code == 200, r.text
    assert client.get(f'/households/{H}/state').json()['proposal']['version'] >= version


def test_gemini_receives_only_current_rooms_photos_and_saved_description(client, monkeypatch, tmp_path):
    from types import SimpleNamespace

    own_image = tmp_path / 'own.png'
    other_image = tmp_path / 'other.jpg'
    own_image.write_bytes(b'current-room-photo')
    other_image.write_bytes(b'other-room-photo')
    with db.tx() as connection:
        connection.execute('INSERT INTO room_inspiration_images VALUES (?,?,?,?)', ('own', H, str(own_image), db.now()))
        connection.execute('INSERT INTO room_inspiration_images VALUES (?,?,?,?)', ('other', 'demo-bed-maya', str(other_image), db.now()))
        connection.execute('INSERT INTO room_inspiration VALUES (?,?)', (H, 'Warm oak with blue accents'))
    requests = []

    def generate_content(**kwargs):
        requests.append(kwargs)
        # Publish via the real tool so the test covers the normal Gemini success path.
        result = kwargs['config'].tools[-1](['sofa-blue'], 'Matches the uploaded inspiration.')
        assert result['ok'], result
        return SimpleNamespace(text='The inspired plan is ready.')

    monkeypatch.setattr(agent, '_gemini', lambda: SimpleNamespace(models=SimpleNamespace(generate_content=generate_content)))
    monkeypatch.setattr(agent, 'available', lambda: True)
    result = client.post(f'/households/{H}/chat', json={'member_id': 'emily', 'text': 'Just a sofa for $1000', 'mode': 'design'})
    assert result.status_code == 200 and result.json()['engine'] == 'gemini'
    contents = requests[0]['contents']
    assert 'Warm oak with blue accents' in contents[0]
    photos = [part.inline_data for part in contents[1:]]
    assert len(photos) == 1
    assert photos[0].data == b'current-room-photo' and photos[0].mime_type == 'image/png'
    assert not db.all_('SELECT job_id FROM outbound_jobs')


def test_remove_inspiration_updates_reference_and_cannot_remove_another_rooms_photo(client, tmp_path):
    paths = [tmp_path / name for name in ('first.png', 'second.png', 'other.png')]
    for path in paths:
        path.write_bytes(b'photo')
    with db.tx() as connection:
        for image_id, hid, path in [('first', H, paths[0]), ('second', H, paths[1]), ('other', 'demo-bed-maya', paths[2])]:
            connection.execute('INSERT INTO room_inspiration_images VALUES (?,?,?,?)', (image_id, hid, str(path), db.now()))
        connection.execute('UPDATE households SET inspiration_path=? WHERE id=?', (str(paths[1]), H))
    assert client.delete(f'/households/{H}/inspiration/other').status_code == 404
    assert client.delete(f'/households/{H}/inspiration/second').status_code == 200
    state = client.get(f'/households/{H}/state').json()
    assert [p['id'] for p in state['room']['inspiration_images']] == ['first']
    assert planner.room_image(core.household(H)) == paths[0]
    assert client.delete(f'/households/{H}/inspiration/first').status_code == 200
    assert planner.room_image(core.household(H)) is None
    assert client.get(f'/households/{H}/state').json()['room']['inspiration_images'] == []
    assert db.one('SELECT id FROM room_inspiration_images WHERE id=?', 'other')
