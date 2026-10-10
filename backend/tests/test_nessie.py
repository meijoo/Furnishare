"""Nessie client + the iPad Pay buttons (Buy, Pay share, Refresh)."""
import time
from datetime import date

import httpx
import pytest
from fastapi.testclient import TestClient

from app import config, db, finance, nessie
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
    last = None
    while time.time() < end:
        last = c.get(f'/households/{H}/state').json()
        if pred(last):
            return last
        time.sleep(0.2)
    raise AssertionError(last['finance'] if last else 'no state')


# --- status + mock client -------------------------------------------------


@pytest.mark.parametrize('raw,want', [
    ('completed', 'confirmed'), ('complete', 'confirmed'), ('executed', 'confirmed'),
    ('posted', 'confirmed'), ('confirmed', 'confirmed'), ('success', 'confirmed'),
    ('pending', 'pending'),
    ('cancelled', 'failed'), ('canceled', 'failed'), ('failed', 'failed'),
    ('declined', 'failed'), ('rejected', 'failed'),
    (None, 'unknown'), ('', 'unknown'), ('weird', 'unknown'),
])
def test_map_status(raw, want):
    assert nessie.map_status(raw) == want


def test_mock_setup_purchase_transfer_and_reconcile():
    mock = nessie.MockNessie()
    cid = mock.create_customer('Emily', 'Roommate')
    aid = mock.create_account(cid, 'checking', 200000)
    payee = mock.create_account(mock.create_customer('Maya', 'Roommate'), 'checking', 200000)
    mid = mock.create_merchant('Furniture')
    assert mock.balance_cents(aid) == 200000
    tid, status, body = mock.create_purchase(aid, mid, 45000, 'RAG to Rooms [purchase:demo:v1]')
    assert status == 'pending' and body['objectCreated']['_id'] == tid
    found = mock.find('purchase', aid, tid)
    assert found['status'] == 'pending'
    mock.txns[tid]['created'] = time.time() - 3
    found = mock.find('purchase', aid, tid)
    assert nessie.map_status(found['status']) == 'confirmed'
    assert mock.balance_cents(aid) == 155000
    xfer, _, _ = mock.create_transfer(payee, aid, 17500, 'RAG to Rooms [reimburse:liab]')
    mock.txns[xfer]['created'] = time.time() - 3
    found = mock.find('transfer', payee, description='reimburse:liab')
    assert found['_id'] == xfer
    assert mock.balance_cents(payee) == 182500
    assert mock.balance_cents(aid) == 172500
    assert mock.find('purchase', aid, 'missing') is None


# --- LiveNessie request contract (mocked HTTP) -----------------------------


class _Resp:
    def __init__(self, status, body, text=''):
        self.status_code = status
        self._body = body
        self.text = text or str(body)

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


class _Capture:
    def __init__(self, handler):
        self.handler = handler
        self.calls = []

    def request(self, method, url, params=None, json=None):
        self.calls.append({'method': method, 'url': url, 'params': params, 'json': json})
        return self.handler(method, url, params, json)


def _live(handler):
    client = nessie.LiveNessie('test-key', 'https://api.nessieisreal.com')
    cap = _Capture(handler)
    client.http = cap
    return client, cap


def test_live_setup_payloads():
    def handler(method, url, params, body):
        assert params == {'key': 'test-key'}
        if url.endswith('/customers'):
            assert body['first_name'] == 'Emily' and body['address']['zip'] == '22201'
            return _Resp(201, {'objectCreated': {'_id': 'cust-1'}})
        if '/accounts' in url:
            assert body == {'type': 'Checking', 'nickname': 'Emily checking', 'rewards': 0, 'balance': 2000}
            return _Resp(201, {'objectCreated': {'_id': 'acct-1'}})
        if url.endswith('/merchants'):
            assert body['category'] == 'furniture' and body['name'] == 'Shop'
            return _Resp(201, {'objectCreated': {'_id': 'merch-1'}})
        raise AssertionError(url)

    n, _ = _live(handler)
    assert n.create_customer('Emily', 'Roommate') == 'cust-1'
    assert n.create_account('cust-1', 'Emily checking', 200000) == 'acct-1'
    assert n.create_merchant('Shop') == 'merch-1'


def test_live_purchase_and_transfer_match_observed_contract():
    today = date.today().isoformat()

    def handler(method, url, params, body):
        if url.endswith('/purchases'):
            assert body['merchant_id'] == 'merch-1'
            assert body['medium'] == 'balance'
            assert body['amount'] == 45000
            assert body['status'] == 'completed'
            assert body['purchase_date'] == today
            assert 'USD cents' in body['description']
            assert 'payee_id' not in body
            return _Resp(201, {'objectCreated': {'_id': 'p-1', 'status': 'completed'}})
        if url.endswith('/transfers'):
            assert set(body) == {'amount', 'transaction_date', 'status', 'description'}
            assert body['amount'] == 17500
            assert 'acct-payer' in body['description']
            assert 'medium' not in body and 'payee_id' not in body
            return _Resp(201, {'objectCreated': {'_id': 't-1', 'status': 'completed'}})
        raise AssertionError(url)

    n, _ = _live(handler)
    ext, status, _ = n.create_purchase('acct-emily', 'merch-1', 45000, 'RAG to Rooms [purchase:demo:v1]')
    assert ext == 'p-1' and status == 'confirmed'
    ext, status, _ = n.create_transfer('acct-maya', 'acct-payer', 17500, 'RAG to Rooms [reimburse:x]')
    assert ext == 't-1' and status == 'confirmed'


def test_live_errors_are_rejected_or_uncertain():
    def handler(method, url, params, body):
        if 'timeout' in url:
            raise httpx.ReadTimeout('slow')
        if 'down' in url:
            return _Resp(503, {}, 'unavailable')
        return _Resp(400, {}, 'insufficient funds')

    n, _ = _live(handler)
    with pytest.raises(nessie.Uncertain, match='ReadTimeout'):
        n._req('GET', '/timeout')
    with pytest.raises(nessie.Uncertain, match='HTTP 503'):
        n._req('GET', '/down')
    with pytest.raises(nessie.Rejected, match='HTTP 400'):
        n._req('GET', '/bad')


def test_live_find_lists_account_when_get_by_id_is_forbidden():
    def handler(method, url, params, body):
        if url.endswith('/purchases/p-1'):
            return _Resp(403, {}, 'gateway auth')
        if url.endswith('/accounts/acct/purchases'):
            return _Resp(200, [{'_id': 'other'}, {'id': 'p-1', 'description': 'RAG to Rooms [purchase:demo:v1]',
                                                   'status': 'completed'}])
        raise AssertionError(url)

    n, _ = _live(handler)
    found = n.find('purchase', 'acct', 'p-1', 'RAG to Rooms [purchase:demo:v1]')
    assert found['_id'] == 'p-1'
    assert nessie.map_status(found['status']) == 'confirmed'


def test_live_find_missing_is_none():
    def handler(method, url, params, body):
        if url.endswith('/purchases/nope'):
            return _Resp(404, {}, 'missing')
        if url.endswith('/accounts/acct/purchases'):
            return _Resp(404, {}, 'no listing')
        raise AssertionError(url)

    n, _ = _live(handler)
    assert n.find('purchase', 'acct', 'nope') is None


# --- iPad buttons: setup, Buy, Pay share, Refresh --------------------------


def test_health_reports_mock_nessie_in_tests(client):
    h = client.get('/health').json()
    assert h['integrations']['nessie'] == 'mock'


def test_setup_button_creates_mock_accounts(client):
    r = client.post(f'/households/{H}/finance/setup')
    assert r.status_code == 200, r.text
    assert r.json()['mode'] == 'mock'
    accts = finance.setup_accounts(H)
    assert set(accts['members']) == {'emily', 'maya', 'alex'}
    assert accts['merchant_id']
    again = finance.setup_accounts(H)
    assert again['members']['emily'] == accts['members']['emily']


def test_buy_button_blocked_until_everyone_approves(client):
    v = client.get(f'/households/{H}/state').json()['proposal']['version']
    r = client.post(f'/households/{H}/purchase/authorize', json={'member_id': 'emily', 'proposal_version': v})
    assert r.status_code == 409
    client.post(f'/households/{H}/proposals/{v}/approve', json={'member_id': 'emily'})
    r = client.post(f'/households/{H}/purchase/authorize', json={'member_id': 'emily', 'proposal_version': v})
    assert r.status_code == 409


def test_buy_button_payer_only_then_confirms(client):
    v = approve_all(client)
    assert client.post(f'/households/{H}/purchase/authorize',
                       json={'member_id': 'maya', 'proposal_version': v}).status_code == 403
    r = client.post(f'/households/{H}/purchase/authorize', json={'member_id': 'emily', 'proposal_version': v})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body['kind'] == 'purchase' and body['from_member'] == 'emily'
    assert body['simulator'] == 'mock'
    again = client.post(f'/households/{H}/purchase/authorize', json={'member_id': 'emily', 'proposal_version': v})
    assert again.status_code == 200
    assert again.json()['op_key'] == body['op_key']
    s = wait(client, lambda s: (s['finance']['purchase'] or {}).get('state') == 'confirmed')
    assert s['proposal']['status'] == 'purchased'
    assert s['finance']['purchase']['external_id']
    assert {r['from_member'] for r in s['finance']['reimbursements']} == {'maya', 'alex'}


def test_refresh_button_advances_pending_purchase(client, monkeypatch):
    v = approve_all(client)
    mock = nessie.client()
    monkeypatch.setattr(mock, 'find', lambda *a, **k: None)
    assert client.post(f'/households/{H}/purchase/authorize',
                       json={'member_id': 'emily', 'proposal_version': v}).status_code == 200
    s = wait(client, lambda s: (s['finance']['purchase'] or {}).get('state') in ('pending', 'confirmed', 'unknown'))
    if s['finance']['purchase']['state'] == 'confirmed':
        return
    monkeypatch.undo()
    r = client.post(f'/households/{H}/finance/reconcile')
    assert r.status_code == 200, r.text
    wait(client, lambda s: (s['finance']['purchase'] or {}).get('state') == 'confirmed')


def test_pay_share_button_only_debtor_then_settles(client):
    v = approve_all(client)
    client.post(f'/households/{H}/purchase/authorize', json={'member_id': 'emily', 'proposal_version': v})
    s = wait(client, lambda s: (s['finance']['purchase'] or {}).get('state') == 'confirmed')
    by = {r['from_member']: r for r in s['finance']['reimbursements']}
    assert client.post(f"/households/{H}/reimbursements/{by['alex']['liability_id']}/authorize",
                       json={'member_id': 'maya'}).status_code == 403
    assert client.post(f"/households/{H}/reimbursements/{by['alex']['liability_id']}/authorize",
                       json={'member_id': 'alex'}).status_code == 200
    wait(client, lambda s: next(r for r in s['finance']['reimbursements']
                                if r['from_member'] == 'alex')['operation']['state'] == 'confirmed')
    assert client.get(f'/households/{H}/state').json()['finance']['settled'] is False
    assert client.post(f"/households/{H}/reimbursements/{by['maya']['liability_id']}/authorize",
                       json={'member_id': 'maya'}).status_code == 200
    s = wait(client, lambda s: s['finance']['settled'])
    assert s['proposal']['status'] == 'settled'
    assert all((r['operation'] or {}).get('state') == 'confirmed' for r in s['finance']['reimbursements'])


def test_buy_wrong_version_and_missing_household(client):
    v = approve_all(client)
    assert client.post(f'/households/{H}/purchase/authorize',
                       json={'member_id': 'emily', 'proposal_version': v + 9}).status_code == 409
    assert client.post('/households/nope/purchase/authorize',
                       json={'member_id': 'emily', 'proposal_version': 1}).status_code == 404
    assert client.post(f'/households/{H}/reimbursements/nope/authorize',
                       json={'member_id': 'maya'}).status_code == 404


def test_rejected_purchase_can_be_retried_with_new_op_key(client, monkeypatch):
    v = approve_all(client)
    monkeypatch.setattr(nessie.client(), 'create_purchase',
                        lambda *a, **k: (_ for _ in ()).throw(nessie.Rejected('HTTP 400: no')))
    assert client.post(f'/households/{H}/purchase/authorize',
                       json={'member_id': 'emily', 'proposal_version': v}).status_code == 200
    s = wait(client, lambda s: (s['finance']['purchase'] or {}).get('state') == 'failed')
    failed_key = s['finance']['purchase']['op_key']
    monkeypatch.undo()
    r = client.post(f'/households/{H}/purchase/authorize', json={'member_id': 'emily', 'proposal_version': v})
    assert r.status_code == 200
    assert r.json()['op_key'] != failed_key
    wait(client, lambda s: (s['finance']['purchase'] or {}).get('state') == 'confirmed')


# --- live sandbox (skipped without a key) ----------------------------------


@pytest.mark.skipif(not config.NESSIE_API_KEY, reason='NESSIE_API_KEY not set')
def test_live_sandbox_customer_account_merchant_purchase_transfer():
    n = nessie.LiveNessie(config.NESSIE_API_KEY, config.NESSIE_BASE_URL)
    payer = n.create_customer('Button', 'Payer')
    debtor = n.create_customer('Button', 'Debtor')
    pa = n.create_account(payer, 'button payer', 100000)
    da = n.create_account(debtor, 'button debtor', 100000)
    merch = n.create_merchant('Button Furniture')
    ext, status, _ = n.create_purchase(pa, merch, 45000, 'RAG to Rooms [test-buy]')
    assert ext and status == 'confirmed'
    ext, status, _ = n.create_transfer(da, pa, 17500, 'RAG to Rooms [test-pay]')
    assert ext and status == 'confirmed'
    listed = n.find('purchase', pa, description='test-buy')
    assert listed and listed.get('_id')
    assert n.balance_cents(pa) is not None
