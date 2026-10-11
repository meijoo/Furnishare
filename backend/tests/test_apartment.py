"""Apartment floor plan: shared living room plus owner-paid bedrooms, against fictional fixtures and the mock simulator."""
import math
import time

import pytest
from fastapi.testclient import TestClient

from app.main import app

BEDROOMS = {'bed-emily': 'emily', 'bed-maya': 'maya', 'bed-alex': 'alex'}


@pytest.fixture(scope='module')
def client():
    with TestClient(app) as c:
        c.post('/demo/reset')
        yield c


def apartment(client):
    r = client.get('/apartments/demo')
    assert r.status_code == 200
    return r.json()


def test_floor_plan_tiles_the_apartment(client):
    a = apartment(client)
    assert 12 < a['width_m'] < 14 and 9 < a['depth_m'] < 10.5
    assert a['source'] == 'built_in'
    rooms = a['rooms']
    assert len(rooms) >= 10
    for i, r in enumerate(rooms):
        assert 0 <= r['x_m'] and r['x_m'] + r['width_m'] <= a['width_m'] + 0.2
        assert 0 <= r['z_m'] and r['z_m'] + r['depth_m'] <= a['depth_m'] + 0.2
        for other in rooms[i + 1:]:
            ox = min(r['x_m'] + r['width_m'], other['x_m'] + other['width_m']) - max(r['x_m'], other['x_m'])
            oz = min(r['z_m'] + r['depth_m'], other['z_m'] + other['depth_m']) - max(r['z_m'], other['z_m'])
            assert ox <= 0.15 or oz <= 0.15, (r['id'], other['id'])
    kinds = [r['kind'] for r in rooms]
    assert kinds.count('bedroom') == 3 and 'kitchen' in kinds and 'living' in kinds and 'dining' in kinds
    living = next(r for r in rooms if r['id'] == 'living')
    assert living['household_id'] == 'demo' and living['shared'] and living['summary']['proposal_version'] == 1
    assert living.get('interior_m', living)['width_m'] >= 3.5
    assert all(r['summary'] is None for r in rooms if r['household_id'] is None)


def test_bedrooms_are_owner_paid_and_fit(client):
    a = apartment(client)
    for r in a['rooms']:
        if r['kind'] != 'bedroom':
            continue
        owner = BEDROOMS[r['id']]
        assert r['owner_id'] == owner and not r['shared']
        s = client.get(f"/households/{r['household_id']}/state").json()
        assert [m['id'] for m in s['members']] == [owner]
        p = s['proposal']
        assert p['status'] == 'awaiting_approval'
        assert {i['category'] for i in p['items']} == {'bed', 'nightstand', 'dresser', 'desk'}
        assert p['shares'] == {owner: p['known_total_cents']}
        assert s['scene']['validation']['ok'], s['scene']['validation']
        bed = next(o for o in s['scene']['objects'] if o['category'] == 'bed')
        hd = s['room']['depth_m'] / 2
        assert bed['rotation_y_rad'] == 0.0
        assert bed['position_m'][2] - bed['dimensions_m']['depth'] / 2 == pytest.approx(-hd, abs=0.05)
        for o in s['scene']['objects']:
            if o['category'] in ('dresser', 'desk'):
                assert abs(abs(o['rotation_y_rad']) - math.pi / 2) < 1e-9
        assert r['summary']['known_total_cents'] == p['known_total_cents']
        assert r['summary']['approvals_needed'] == 1


def test_totals_add_shared_shares_and_own_bedroom(client):
    a = apartment(client)
    living = next(r for r in a['rooms'] if r['id'] == 'living')['summary']
    expected = dict(living['shares'])
    for r in a['rooms']:
        if r['kind'] == 'bedroom':
            owner = r['owner_id']
            expected[owner] += r['summary']['known_total_cents']
    assert a['totals']['by_member_cents'] == expected
    assert a['totals']['known_total_cents'] == sum(expected.values())


def test_bedroom_settles_without_reimbursements(client):
    hid = 'demo-bed-maya'
    v = client.get(f'/households/{hid}/state').json()['proposal']['version']
    assert client.post(f'/households/{hid}/proposals/{v}/approve', json={'member_id': 'emily'}).status_code in (403, 404, 409)
    assert client.post(f'/households/{hid}/proposals/{v}/approve', json={'member_id': 'maya'}).status_code == 200
    assert client.post(f'/households/{hid}/purchase/authorize',
                       json={'member_id': 'maya', 'proposal_version': v}).status_code == 200
    deadline = time.time() + 15
    while time.time() < deadline:
        client.post(f'/households/{hid}/finance/reconcile')
        s = client.get(f'/households/{hid}/state').json()
        if s['finance']['settled']:
            break
        time.sleep(0.3)
    assert s['finance']['settled'], s['finance']
    assert s['finance']['purchase']['state'] == 'confirmed'
    assert s['finance']['reimbursements'] == []
    summary = next(r for r in apartment(client)['rooms'] if r['id'] == 'bed-maya')['summary']
    assert summary['settled'] and summary['status'] == 'settled'


def test_bedroom_chat_stays_in_bedroom_categories(client):
    from app import agent
    assert agent.parse_request('a cheaper desk please', ['bed', 'nightstand', 'dresser', 'desk'])['categories'] == ['desk']
    assert agent.parse_request('furnish my room', ['bed', 'nightstand', 'dresser', 'desk'])['categories'] == [
        'bed', 'nightstand', 'dresser', 'desk']
    assert agent.parse_request('a new sofa', ['bed', 'nightstand', 'dresser', 'desk'])['categories'] == [
        'bed', 'nightstand', 'dresser', 'desk']


def test_blank_clears_furniture_and_reset_puts_it_back(client):
    blank = client.post('/demo/blank')
    assert blank.status_code == 200, blank.text
    a = apartment(client)
    living = next(r for r in a['rooms'] if r['id'] == 'living')
    assert living['summary']['proposal_version'] is None
    assert living['summary']['item_count'] == 0
    for r in a['rooms']:
        if r['kind'] == 'bedroom':
            assert r['summary']['proposal_version'] is None
            assert client.get(f"/households/{r['household_id']}/state").json()['scene']['objects'] == []
    restored = client.post('/demo/reset')
    assert restored.status_code == 200, restored.text
    living = next(r for r in apartment(client)['rooms'] if r['id'] == 'living')
    assert living['summary']['proposal_version'] == 1
    assert living['summary']['item_count']


def test_unknown_apartment_is_404(client):
    assert client.get('/apartments/nope').status_code == 404


def test_verified_catalog_without_bedroom_listings_falls_back_to_fixtures(tmp_path, monkeypatch):
    from app import catalog
    sofa = {'id': 'real-sofa', 'retailer': 'Test', 'title': 'Real sofa', 'category': 'sofa', 'price_cents': 50000,
            'dimensions_m': {'width': 2.0, 'height': 0.8, 'depth': 0.9}, 'dimension_kind': 'assembled'}
    path = tmp_path / 'verified.json'
    path.write_text(__import__('json').dumps([sofa]))
    monkeypatch.setattr(catalog, 'VERIFIED', path)
    catalog._cache['mtime'] = None
    try:
        by_cat = {}
        for p in catalog.products():
            by_cat.setdefault(p['category'], set()).add(p['source_type'] if p['id'] != 'real-sofa' else 'real')
    finally:
        catalog._cache['mtime'] = None
    assert by_cat['sofa'] == {'real'}
    for cat in ('bed', 'nightstand', 'dresser', 'desk'):
        assert by_cat[cat] == {'demo'}
