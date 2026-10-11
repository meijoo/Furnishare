"""TDD section 15 cases not covered by the signature-demo flow."""
import time

import pytest
from fastapi.testclient import TestClient

from app import catalog, db, nessie
from app.main import app

H = 'demo'


@pytest.fixture()
def client():
    with TestClient(app) as c:
        c.post('/demo/reset', params={'clear_handles': 'true'})
        yield c


def approve_all(c):
    v = c.get(f'/households/{H}/state').json()['proposal']['version']
    for m in ('emily', 'maya', 'alex'):
        assert c.post(f'/households/{H}/proposals/{v}/approve', json={'member_id': m}).status_code == 200
    return v


def wait(c, pred, timeout=12):
    end = time.time() + timeout
    while time.time() < end:
        s = c.get(f'/households/{H}/state').json()
        if pred(s):
            return s
        time.sleep(0.2)
    raise AssertionError(s['finance'])


def purchase_confirmed(c):
    v = approve_all(c)
    assert c.post(f'/households/{H}/purchase/authorize', json={'member_id': 'emily', 'proposal_version': v}).status_code == 200
    return wait(c, lambda s: (s['finance']['purchase'] or {}).get('state') == 'confirmed')


def test_package_only_and_missing_dimensions_never_enter_layout():
    base = {'id': 'x', 'category': 'sofa', 'price_cents': 100, 'style': {}}
    assert catalog._normalize({**base, 'dimension_kind': 'package', 'dimensions_m': {'width': 1, 'depth': 1, 'height': 1}})['dimensions_m'] is None
    assert catalog._normalize({**base, 'dimension_kind': 'assembled', 'dimensions_m': {'width': 1, 'depth': None, 'height': 1}})['dimensions_m'] is None
    assert catalog._normalize({**base, 'price_cents': 99.5, 'dimension_kind': 'assembled'}) is None


def test_unauthorized_actions(client):
    assert client.post(f'/households/{H}/proposals/1/approve', json={'member_id': 'mallory'}).status_code == 403
    v = approve_all(client)
    assert client.post(f'/households/{H}/purchase/authorize', json={'member_id': 'alex', 'proposal_version': v}).status_code == 403


def test_price_change_after_approval_requires_reapproval(client, monkeypatch):
    v = approve_all(client)
    sofa_id = client.get(f'/households/{H}/state').json()['proposal']['items'][0]['product_id']
    real = catalog.products

    def bumped():
        return [{**p, 'price_cents': p['price_cents'] + 2500} if p['id'] == sofa_id else p for p in real()]
    monkeypatch.setattr(catalog, 'products', bumped)
    r = client.post(f'/households/{H}/purchase/authorize', json={'member_id': 'emily', 'proposal_version': v})
    assert r.status_code == 409 and 'Prices changed' in r.json()['detail']
    s = client.get(f'/households/{H}/state').json()
    assert s['proposal']['version'] == v + 1 and not any(s['proposal']['approvals'].values())
    assert s['finance']['purchase'] is None


def test_uncertain_transfer_is_not_blindly_retried(client, monkeypatch):
    s = purchase_confirmed(client)
    calls = []

    def flaky(*a, **k):
        calls.append(a)
        raise nessie.Uncertain('ReadTimeout')
    monkeypatch.setattr(nessie.client(), 'create_transfer', flaky)
    liab = next(r for r in s['finance']['reimbursements'] if r['from_member'] == 'alex')
    client.post(f"/households/{H}/reimbursements/{liab['liability_id']}/authorize", json={'member_id': 'alex'})
    s = wait(client, lambda s: next(r for r in s['finance']['reimbursements'] if r['from_member'] == 'alex')['operation']['state'] == 'unknown')
    client.post(f'/households/{H}/finance/reconcile')
    time.sleep(1.5)
    assert len(calls) == 1
    again = client.post(f"/households/{H}/reimbursements/{liab['liability_id']}/authorize", json={'member_id': 'alex'}).json()
    assert again['state'] == 'unknown' and len(calls) == 1


def test_partial_reimbursement_failure_shows_each_operation(client, monkeypatch):
    s = purchase_confirmed(client)
    mock = nessie.client()
    real = mock.create_transfer

    def reject_maya(account_id, payee, amount, description):
        if 'maya' in description:
            raise nessie.Rejected('HTTP 400: insufficient funds')
        return real(account_id, payee, amount, description)
    monkeypatch.setattr(mock, 'create_transfer', reject_maya)
    for r in s['finance']['reimbursements']:
        client.post(f"/households/{H}/reimbursements/{r['liability_id']}/authorize", json={'member_id': r['from_member']})
    s = wait(client, lambda s: {r['from_member']: (r['operation'] or {}).get('state') for r in s['finance']['reimbursements']}
             == {'maya': 'failed', 'alex': 'confirmed'})
    assert not s['finance']['settled'] and s['proposal']['status'] == 'purchased'
    monkeypatch.setattr(mock, 'create_transfer', real)
    maya = next(r for r in s['finance']['reimbursements'] if r['from_member'] == 'maya')
    retry = client.post(f"/households/{H}/reimbursements/{maya['liability_id']}/authorize", json={'member_id': 'maya'}).json()
    assert retry['op_key'].endswith('#2')
    wait(client, lambda s: s['finance']['settled'])
    assert len(db.all_("SELECT 1 FROM financial_ops WHERE kind = 'transfer' AND state = 'confirmed'")) >= 2


def test_product_search_uses_catalog(client, monkeypatch):
    monkeypatch.setattr(catalog, 'live_search', lambda *a, **k: [])
    r = client.get('/products/search', params={'q': 'sofa'})
    assert r.status_code == 200, r.text
    ids = [p['id'] for p in r.json()]
    assert ids
    assert all(p['category'] == 'sofa' for p in r.json())
    assert catalog.infer_category('oak queen bed') == 'bed'
    assert catalog.infer_category('brown couch') == 'sofa'
    assert catalog.infer_category('green lamp') == 'lamp'
    assert catalog.infer_color('green table lamp') == '#3F7A45'
    assert client.get('/products/search', params={'q': ''}).status_code == 422


def test_brown_couch_prefers_live_matches(client, monkeypatch):
    monkeypatch.setattr(catalog, 'live_search', lambda *a, **k: [{
        'id': 'live-brown-couch', 'retailer': 'Shop', 'title': 'Brown linen couch', 'category': 'sofa',
        'price_cents': 49900, 'currency': 'USD', 'dimensions_m': catalog.DEFAULT_DIMS['sofa'],
        'dimension_kind': 'estimated', 'source_type': 'live',
    }])
    r = client.get('/products/search', params={'q': 'brown couch'})
    assert r.status_code == 200, r.text
    titles = [p['title'] for p in r.json()]
    assert titles[0] == 'Brown linen couch'
    assert r.json()[0]['id'] == 'live-brown-couch'
    assert catalog.get('live-brown-couch')['title'] == 'Brown linen couch'
    listed = {p['id']: p for p in client.get('/products').json()}
    assert listed['live-brown-couch']['title'] == 'Brown linen couch'


def test_put_budget(client):
    before = client.get(f'/households/{H}/state').json()
    assert before['budget_cents'] != 175000
    r = client.put(f'/households/{H}/budget', json={'budget_cents': 175000})
    assert r.status_code == 200, r.text
    assert r.json()['budget_cents'] == 175000
    assert client.get(f'/households/{H}/state').json()['budget_cents'] == 175000
    assert client.put(f'/households/{H}/budget', json={'budget_cents': -1}).status_code == 422
    assert client.put('/households/nope/budget', json={'budget_cents': 1000}).status_code == 404
