"""Apartment floor plan: shared living room plus owner-paid bedrooms, against fictional fixtures and the mock simulator."""
import math
import time

import pytest
from fastapi.testclient import TestClient

from app import geometry
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
    assert a['width_m'] == 10.5 and a['depth_m'] == 9.5
    rooms = a['rooms']
    assert len(rooms) == 10
    assert sum(r['width_m'] * r['depth_m'] for r in rooms) == pytest.approx(a['width_m'] * a['depth_m'])
    for i, r in enumerate(rooms):
        assert 0 <= r['x_m'] and r['x_m'] + r['width_m'] <= a['width_m'] + 1e-9
        assert 0 <= r['z_m'] and r['z_m'] + r['depth_m'] <= a['depth_m'] + 1e-9
        for other in rooms[i + 1:]:
            assert not geometry.overlaps(
                geometry.rect(r['x_m'] + r['width_m'] / 2, r['z_m'] + r['depth_m'] / 2, r['width_m'], r['depth_m']),
                geometry.rect(other['x_m'] + other['width_m'] / 2, other['z_m'] + other['depth_m'] / 2,
                              other['width_m'], other['depth_m'])), (r['id'], other['id'])
    kinds = [r['kind'] for r in rooms]
    assert kinds.count('bedroom') == 3 and kinds.count('bathroom') == 3 and 'kitchen' in kinds and 'living' in kinds
    living = next(r for r in rooms if r['id'] == 'living')
    assert living['household_id'] == 'demo' and living['shared'] and living['summary']['proposal_version'] == 1
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
