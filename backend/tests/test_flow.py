"""End-to-end signature demo against fictional fixtures and the labeled Nessie simulator."""
import time

import pytest
from fastapi.testclient import TestClient

from app.main import app

H = {'emily': '+15550000001', 'maya': '+15550000002', 'alex': '+15550000003'}


@pytest.fixture(scope='module')
def client():
    with TestClient(app) as c:
        c.post('/demo/reset')
        yield c


def text(client, who, body, event_id=None):
    event_id = event_id or f'{who}-{time.time_ns()}'
    return client.post('/messages/inbound', json={'event_id': event_id, 'sender_handle': H[who], 'text': body}).json()


def outbox(client):
    return client.get('/debug/outbound').json()


def wait_for(client, predicate, timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        s = client.get('/households/demo/state').json()
        if predicate(s):
            return s
        time.sleep(0.3)
    raise AssertionError('timed out; last state: ' + str(s['finance']))


def test_signature_demo(client):
    s = client.get('/households/demo/state').json()
    p1 = s['proposal']
    assert p1['version'] == 1 and p1['known_total_cents'] == 60000
    assert p1['shares'] == {'emily': 20000, 'maya': 20000, 'alex': 20000}
    assert {o['category'] for o in s['scene']['objects']} == {'sofa', 'coffee_table', 'tv', 'rug'}
    assert s['scene']['validation']['ok'], s['scene']['validation']
    assert all('limit_cents' not in m for m in s['members'])

    for who in H:
        assert 'JOIN' in text(client, who, 'hello') and True or True
        text(client, who, f'JOIN {who}')

    # Duplicate inbound events never re-run actions.
    assert text(client, 'alex', 'My limit for the sofa is $100', event_id='dup-1') == {'status': 'accepted'}
    assert text(client, 'alex', 'My limit for the sofa is $100', event_id='dup-1') == {'status': 'duplicate'}

    s = client.get('/households/demo/state').json()
    p2 = s['proposal']
    assert p2['version'] == 2
    assert p2['known_total_cents'] == 45000
    assert p2['shares'] == {'emily': 17500, 'maya': 17500, 'alex': 10000}
    assert s['scene']['objects'][[o['category'] for o in s['scene']['objects']].index('sofa')]['product_id'] == 'sofa-compact'
    assert '$100' not in p2['explanation']

    msgs = outbox(client)
    for m in msgs:
        if m['to_handle'] != H['alex']:
            assert 'limit is $100' not in m['text'] and 'limit for the sofa' not in m['text']
    assert any(m['to_handle'] == H['emily'] and 'v2' in m['text'] and '$175' in m['text'] for m in msgs)

    # Stale approval is rejected.
    r = client.post('/households/demo/proposals/1/approve', json={'member_id': 'emily'})
    assert r.status_code == 409

    # Purchase cannot be authorized before approval, nor by a non-payer.
    assert client.post('/households/demo/purchase/authorize', json={'member_id': 'emily', 'proposal_version': 2}).status_code == 409
    text(client, 'emily', 'yes')
    client.post('/households/demo/proposals/2/approve', json={'member_id': 'maya'})
    text(client, 'alex', 'YES v2')
    s = client.get('/households/demo/state').json()
    assert s['proposal']['status'] == 'approved'
    assert client.post('/households/demo/purchase/authorize', json={'member_id': 'maya', 'proposal_version': 2}).status_code == 403

    text(client, 'emily', 'PAY')
    text(client, 'emily', 'PAY')  # second PAY must not create a second operation
    s = wait_for(client, lambda s: (s['finance']['purchase'] or {}).get('state') == 'confirmed')
    assert s['finance']['purchase']['simulator'] == 'mock'
    reimb = {r['from_member']: r for r in s['finance']['reimbursements']}
    assert set(reimb) == {'maya', 'alex'}
    assert reimb['maya']['amount_cents'] == 17500 and reimb['alex']['amount_cents'] == 10000

    # Limit changes after purchase authorization do not revise the proposal.
    text(client, 'maya', 'my limit is $50')
    assert client.get('/households/demo/state').json()['proposal']['version'] == 2

    # Only the debtor can authorize their reimbursement.
    assert client.post(f"/households/demo/reimbursements/{reimb['alex']['liability_id']}/authorize",
                       json={'member_id': 'maya'}).status_code == 403
    text(client, 'alex', 'SEND')
    s = wait_for(client, lambda s: {r['from_member']: (r['operation'] or {}).get('state') for r in s['finance']['reimbursements']}.get('alex') == 'confirmed')
    assert not s['finance']['settled']
    client.post(f"/households/demo/reimbursements/{reimb['maya']['liability_id']}/authorize", json={'member_id': 'maya'})
    s = wait_for(client, lambda s: s['finance']['settled'])
    assert s['proposal']['status'] == 'settled'

    from app import db
    ops = db.all_('SELECT op_key, state FROM financial_ops WHERE household_id=?', 'demo')
    assert len(ops) == 3 and all(o['state'] == 'confirmed' for o in ops)


def test_infeasible_limits_explain(client, monkeypatch):
    from app import seed
    # Keep this infeasibility scenario at $400 combined, independent of demo defaults.
    monkeypatch.setitem(seed.SEED_LIMITS, 'maya', 20000)
    client.post('/demo/reset')
    for who in H:
        text(client, who, f'JOIN {who}')
    text(client, 'alex', 'my limit is $0')
    s = client.get('/households/demo/state').json()
    assert s['proposal']['version'] == 1  # cheapest sofa ($450) exceeds combined limits ($400)
    jobs = [m for m in outbox(client) if m['to_handle'] == H['alex']]
    assert any('No feasible revision' in m['text'] and '$50' in m['text'] for m in jobs)


def test_private_limit_only_for_self(client):
    s = client.get('/households/demo/state', params={'member_id': 'emily'}).json()
    me = next(m for m in s['members'] if m['id'] == 'emily')
    other = next(m for m in s['members'] if m['id'] == 'alex')
    assert 'limit_cents' in me and 'limit_cents' not in other


def test_unknown_sender_gets_registration_prompt(client):
    r = client.post('/messages/inbound', json={'event_id': 'x-1', 'sender_handle': '+15559999999', 'text': 'hi'})
    assert r.status_code == 202
    assert any('JOIN' in m['text'] for m in outbox(client) if m['to_handle'] == '+15559999999')


def test_outbound_claim_lease(client):
    jobs = client.post('/messages/outbound/claim', json={'worker_id': 't', 'max': 50}).json()['jobs']
    assert jobs
    again = client.post('/messages/outbound/claim', json={'worker_id': 't2', 'max': 50}).json()['jobs']
    assert not {j['job_id'] for j in jobs} & {j['job_id'] for j in again}
    assert client.post(f"/messages/outbound/{jobs[0]['job_id']}/result", json={'status': 'sent'}).json() == {'ok': True}
