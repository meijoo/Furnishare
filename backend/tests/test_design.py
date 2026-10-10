import pytest
from fastapi.testclient import TestClient

from app import catalog, realize
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


def test_design_with_picks_publishes_live_product(client, monkeypatch):
    monkeypatch.setattr(realize._pool, 'submit', lambda *a, **k: None)
    catalog.remember([LIVE])
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
