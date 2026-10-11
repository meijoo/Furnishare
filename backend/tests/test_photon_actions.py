"""Furniture, budget and approved-purchase actions through Photon."""
import time
import pytest
from test_group_invitations import client, invite
from app import core, db


def inbound(client, event_id, phone, text):
    response = client.post('/messages/inbound', json={
        'event_id': event_id, 'sender_handle': phone, 'text': text})
    assert response.status_code == 202
    return db.one('SELECT text FROM outbound_jobs WHERE dedupe_key=?', f'reply:{event_id}')['text']


def test_shared_link_in_design_survives_restart_and_deduplicates(client):
    invite(client)
    text = 'https://shop.example/blue-couch'
    assert 'Design tab' in inbound(client, 'add-link', '+15550000001', text)
    assert 'Design tab' in inbound(client, 'add-link-again', '+15550000002', text)
    state = client.get('/households/demo/state').json()
    assert len(state['room']['shared_furniture_links']) == 1
    assert state['room']['shared_furniture_links'][0]['url'] == text
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as restarted:
        assert restarted.get('/households/demo/state').json()['room']['shared_furniture_links'][0]['url'] == text


def test_budget_text_updates_only_sender_and_room_total(client):
    invite(client)
    before = core.member('demo', 'emily')['limit_cents']
    assert '$300' in inbound(client, 'my-budget', '+15550000002', 'Update my budget to $300')
    assert core.member('demo', 'maya')['limit_cents'] == 30000
    assert core.member('demo', 'emily')['limit_cents'] == before
    assert core.household('demo')['budget_cents'] == sum(m['limit_cents'] or 0 for m in core.members('demo'))


@pytest.mark.parametrize('command', ['I bought the proposal', 'PAY'])
def test_bought_requires_payer_and_approval_then_auto_requests_once(client, command):
    def send(event_id, phone, text):
        return inbound(client, f'{event_id}-{command}', phone, text)
    invite(client)
    client.put('/households/demo/members/alex/handle', json={'handle': '+15550000003'})
    assert 'everyone' in send('too-early', '+15550000001', command).lower()
    expected = 'Only the designated payer' if command != 'PAY' else 'no payment request'
    assert expected in send('wrong-payer', '+15550000002', command)
    assert db.all_("SELECT * FROM financial_ops WHERE household_id='demo'") == []
    version = core.current_proposal('demo')['version']
    for mid in ['emily', 'maya', 'alex']:
        core.decide('demo', version, mid, 'approve')
    assert 'automatically' in send('bought-approved', '+15550000001', command)
    deadline = time.time() + 15
    while time.time() < deadline:
        jobs = db.all_("SELECT * FROM outbound_jobs WHERE dedupe_key LIKE 'room-payment:demo:%'")
        if len(jobs) == 2:
            break
        time.sleep(.1)
    else:
        raise AssertionError('Automatic room requests were not queued')
    assert {job['to_handle'] for job in jobs} == {'+15550000002', '+15550000003'}
    assert all("Living room's furniture is purchased!" in job['text'] for job in jobs)
    assert db.all_("SELECT * FROM outbound_jobs WHERE household_id='demo' AND dedupe_key LIKE 'reimburse-request:%'") == []
    send('bought-retry', '+15550000001', command)
    assert len(db.all_("SELECT * FROM outbound_jobs WHERE dedupe_key LIKE 'room-payment:demo:%'")) == 2
    assert len(db.all_("SELECT * FROM financial_ops WHERE household_id='demo' AND kind='purchase'")) == 1
    assert db.one("SELECT text FROM outbound_jobs WHERE dedupe_key=?", f'auto-payment-complete:demo:v{version}')['text'].startswith('Payment complete.')


def test_real_group_pay_reply_purchases_and_requests_payment(client):
    from test_accounts import signup, create
    from app import seed
    account, owner, headers = signup(client)
    group = create(client, headers)
    gid, payer = group['id'], owner['user']['id']
    roommate, other, other_headers = signup(client)
    assert client.post('/groups/join', headers=other_headers, json={'code': group['group_code']}).status_code == 200
    for uid, auth in [(payer, headers), (other['user']['id'], other_headers)]:
        assert client.put(f'/apartments/{gid}/setup', headers=auth, json={
            'member_id': uid, 'rooms': {gid: {'budget_cents': 30000}}}).status_code == 200
    proposal = core.create_proposal(gid, [seed.demo_sofa()], {payer: 30000, other['user']['id']: 30000},
                                    'Room purchase', scene=[], notify=False)
    for uid in [payer, other['user']['id']]:
        core.decide(gid, proposal['version'], uid, 'approve')
    assert 'automatically' in inbound(client, 'real-pay', account['phone'], 'PAY')
    deadline = time.time() + 15
    while time.time() < deadline:
        completion = db.one('SELECT * FROM outbound_jobs WHERE dedupe_key=?',
                            f"auto-payment-complete:{gid}:v{proposal['version']}")
        if completion:
            break
        time.sleep(.1)
    else:
        raise AssertionError('Payment completion was not queued')
    assert completion['to_handle'] == account['phone']
    assert completion['text'].startswith('Payment complete.')
    requests = db.all_("SELECT * FROM outbound_jobs WHERE household_id=? AND dedupe_key LIKE 'room-payment:%'", gid)
    assert len(requests) == 1 and requests[0]['to_handle'] == roommate['phone']
    assert 'Pay in Furnishare' in requests[0]['text'] and 'reply PAY' in requests[0]['text']
    assert core.current_proposal(gid)['status'] == 'purchased'
    assert 'no payment request' in inbound(client, 'wrong-payment-version', roommate['phone'], 'PAY v9999')
    reply = inbound(client, 'roommate-pay', roommate['phone'], 'PAY')
    assert 'Payment authorized' in reply or 'Payment complete' in reply
    deadline = time.time() + 15
    while time.time() < deadline:
        transfer = db.one("SELECT * FROM financial_ops WHERE household_id=? AND kind='transfer' AND state='confirmed'", gid)
        if transfer and db.one('SELECT 1 FROM outbound_jobs WHERE dedupe_key=?', f"reimbursement-complete:{transfer['op_key']}"):
            break
        time.sleep(.1)
    else:
        raise AssertionError('Roommate reimbursement was not confirmed')
    assert transfer['from_member'] == transfer['authorized_by'] == other['user']['id']
    assert transfer['to_member'] == payer and transfer['amount_cents'] == 30000
    assert 'Payment complete' in inbound(client, 'roommate-pay-again', roommate['phone'], 'PAY')
    assert len(db.all_("SELECT * FROM financial_ops WHERE household_id=? AND kind='transfer'", gid)) == 1


def test_real_user_can_update_budget_from_registered_phone(client):
    from test_accounts import signup, create
    account, session, headers = signup(client)
    group = create(client, headers)
    gid = group['id']
    reply = inbound(client, 'real-user-budget', account['phone'], 'Set my budget to 200')
    assert '$200' in reply
    assert core.member(gid, session['user']['id'])['limit_cents'] == 20000
    assert core.household(gid)['budget_cents'] == 20000


def test_budget_amounts_are_not_silently_truncated(client):
    invite(client)
    before = core.member('demo', 'maya')['limit_cents']
    for index, text in enumerate(['My budget is -200', 'My budget is $12.345', 'My budget is $1,20']):
        assert 'Enter a budget' in inbound(client, f'invalid-budget-{index}', '+15550000002', text)
        assert core.member('demo', 'maya')['limit_cents'] == before
    assert '$1,200.50' in inbound(client, 'comma-budget', '+15550000002', 'Update my budget to $1,200.50')
    assert core.member('demo', 'maya')['limit_cents'] == 120050


def test_shared_furniture_controls_persist_and_change_couch_replies(client):
    invite(client)
    url = 'https://shop.example/my-couch'
    inbound(client, 'card-link', '+15550000001', url)
    item = client.get('/households/demo/state').json()['room']['shared_furniture_links'][0]
    assert item['enabled'] is True
    assert item['image_url'] is None and item['price_cents'] is None
    path = f"/households/demo/shared-furniture/{item['id']}"
    assert url in inbound(client, 'card-query', '+15550000001', 'What couches are we considering?')
    assert client.put(path, json={'enabled': False}).status_code == 200
    assert client.get('/households/demo/state').json()['room']['shared_furniture_links'][0]['enabled'] is False
    assert url not in inbound(client, 'disabled-query', '+15550000001', 'What couches are we considering?')
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as restarted:
        assert restarted.get('/households/demo/state').json()['room']['shared_furniture_links'][0]['enabled'] is False
        assert restarted.put(path, json={'enabled': True}).status_code == 200
        assert restarted.delete(path).status_code == 200
        assert restarted.get('/households/demo/state').json()['room']['shared_furniture_links'] == []
        assert restarted.delete(path).status_code == 404


def test_link_with_preferences_gets_only_added_confirmation(client, monkeypatch):
    from app import invitations
    invite(client)
    monkeypatch.setattr(invitations.catalog, 'live_search', lambda *a, **k: [])
    before = {row['job_id'] for row in db.all_('SELECT job_id FROM outbound_jobs')}
    text = 'I like this couch https://shop.example/blue-sofa'
    expected = 'Added your furniture link to this room’s Design tab.'
    assert inbound(client, 'single-link-confirmation', '+15550000001', text) == expected
    jobs = [row for row in db.all_('SELECT * FROM outbound_jobs') if row['job_id'] not in before]
    assert len(jobs) == 1 and jobs[0]['text'] == expected
    assert invitations.suggestions('demo')
    assert invitations.preference('demo', core.member('demo', 'emily'), text) == expected
