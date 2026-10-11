"""Group creation contract, scoped preferences, and private financial replies."""
import uuid

import pytest
from fastapi.testclient import TestClient

from app import db, invitations
from app.main import app


@pytest.fixture
def client():
    with TestClient(app) as client:
        client.post('/demo/reset?clear_handles=true')
        with db.tx() as c:
            c.execute("DELETE FROM kv WHERE key LIKE 'group:%' OR key LIKE 'suggestions:%'")
        yield client


def invite(client, hid='demo', request_id=None):
    return client.post(f'/households/{hid}/invitations', json={
        'request_id': request_id or str(uuid.uuid4()),
        'members': [{'member_id': 'emily', 'phone': '+15550000001'},
                    {'member_id': 'maya', 'phone': '+15550000002'}],
    })


def bind(client, invitation):
    # Retain coverage for existing dedicated-line group bindings.
    db.kv_set('group:any;+;test-room', {'household_id': 'demo',
              'participants': ['+15550000001', '+15550000002'], 'line_phone': '+15551111111'})


def test_invite_each_phone_and_idempotency(client):
    invitation = invite(client, request_id='same-request').json()
    assert invite(client, request_id='same-request').json()['job_ids'] == invitation['job_ids']
    jobs = client.post('/messages/outbound/claim', json={'worker_id': 'test', 'max': 50}).json()['jobs']
    jobs = [j for j in jobs if j['job_id'] in invitation['job_ids']]
    assert len(jobs) == 2
    assert {j['to_handle'] for j in jobs} == {'+15550000001', '+15550000002'}
    assert len(invitation['group_code']) == 6
    for job in jobs:
        assert 'participants' not in job
        assert 'invitation_token' not in job
        assert job['conversation_id'] is None
        assert invitation['group_code'] in job['text']
        assert 'ragtorooms://' not in job['text']
        assert client.post(f"/messages/outbound/{job['job_id']}/result", json={'status': 'sent'}).status_code == 200
    delivery = client.get(f"/invitations/{invitation['token']}").json()
    assert delivery['status'] == 'sent'
    assert len(delivery['recipients']) == 2


def test_partial_delivery(client):
    invitation = invite(client).json()
    first, second = invitation['job_ids']
    client.post(f'/messages/outbound/{first}/result', json={'status': 'sent'})
    assert invitations.get(invitation['token'])['status'] == 'pending'
    client.post(f'/messages/outbound/{second}/result', json={'status': 'failed', 'error': 'Target not allowed'})
    delivery = invitations.get(invitation['token'])
    assert delivery['status'] == 'partial'
    assert delivery['recipients'][0]['status'] == 'sent'
    assert delivery['recipients'][1]['status'] == 'failed'
    assert 'Target not allowed' in delivery['error']


def test_dm_preferences_from_roommates_accumulate(client, monkeypatch):
    invitation = invite(client).json()
    monkeypatch.setattr(invitations.catalog, 'live_search', lambda *a, **k: [])
    monkeypatch.setattr(invitations.agent, 'interpret', lambda *a: None)
    for i, phone in enumerate(['+15550000001', '+15550000002']):
        client.post('/messages/inbound', json={'event_id': f'dm-pref-{i}', 'sender_handle': phone,
                    'conversation_id': f'any;-;{phone}', 'text': f'I like blue sofas https://example.com/sofa{i}'})
    records = invitations.suggestions('demo')
    assert {r['member_name'] for r in records} == {'Emily', 'Michelle'}
    assert len(records) == 2
    assert all(r['links'] and r['products'] for r in records)
    assert all(db.one('SELECT conversation_id FROM outbound_jobs WHERE dedupe_key=?', f'reply:dm-pref-{i}')['conversation_id'] is None for i in range(2))


def test_group_preferences_saved_and_finances_private(client, monkeypatch):
    invitation = invite(client).json()
    bind(client, invitation)
    monkeypatch.setattr(invitations.catalog, 'live_search', lambda *a, **k: [])
    before = client.get('/households/demo/state').json()['state_version']
    body = {'event_id': 'group-pref', 'sender_handle': '+15550000002',
            'conversation_id': 'any;+;test-room', 'text': 'I like light wood sofas https://example.com/sofa'}
    assert client.post('/messages/inbound', json=body).json()['status'] == 'accepted'
    assert client.post('/messages/inbound', json=body).json()['status'] == 'duplicate'
    records = client.get('/households/demo/suggestions').json()['suggestions']
    assert len(records) == 1
    assert records[0]['links'] == ['https://example.com/sofa']
    assert records[0]['member_name'] == 'Michelle'
    assert records[0]['products']
    assert client.get('/households/demo/state').json()['state_version'] > before
    prior_limit = db.one("SELECT limit_cents FROM members WHERE household_id='demo' AND id='maya'")['limit_cents']
    body.update(event_id='group-money', text='my limit is $100')
    client.post('/messages/inbound', json=body)
    assert db.one("SELECT limit_cents FROM members WHERE household_id='demo' AND id='maya'")['limit_cents'] == prior_limit
    reply = db.one("SELECT * FROM outbound_jobs WHERE dedupe_key='reply:group-money'")
    assert 'privately' in reply['text']
    assert '$100' not in reply['text']
    assert reply['conversation_id'] == 'any;+;test-room'


def test_unknown_groups_and_nonmembers_cannot_change_room(client):
    invitation = invite(client).json()
    bind(client, invitation)
    for event_id, sender, chat in [('outsider', '+15550000999', 'any;+;test-room'),
                                   ('unbound', '+15550000002', 'any;+;unknown')]:
        client.post('/messages/inbound', json={'event_id': event_id, 'sender_handle': sender,
                                             'conversation_id': chat, 'text': 'I like blue'})
    assert invitations.suggestions('demo') == []


def test_validation_and_dm_result(client):
    bad = client.post('/households/demo/invitations', json={'request_id': 'invalid', 'members': [
        {'member_id': 'emily', 'phone': '5551234567'}, {'member_id': 'maya', 'phone': '+15550000002'}]})
    assert bad.status_code == 422
    assert invite(client, hid='missing').status_code == 404
    invitation = invite(client).json()
    result = client.post(f"/messages/outbound/{invitation['job_id']}/result", json={'status': 'sent'})
    assert result.status_code == 200
    assert invitations.get(invitation['token'])['status'] == 'pending'


def test_join_code_validation_and_room_lookup(client):
    invitation = invite(client).json()
    response = client.post('/groups/join', json={'code': invitation['group_code']})
    assert response.status_code == 200
    assert response.json()['household_id'] == 'demo'
    assert response.json()['group_code'] == invitation['group_code']
    assert response.json()['group_name']
    for code in ['12345', '1234567', 'abcdef', '１２３４５６']:
        assert client.post('/groups/join', json={'code': code}).status_code == 422
    assert client.post('/groups/join', json={'code': 'xxxxxx'}).status_code == 422
    unknown = next(f'{n:06d}' for n in range(1000000) if not db.kv_get(f'group-code:{n:06d}'))
    assert client.post('/groups/join', json={'code': unknown}).status_code == 404
    client.post('/demo/reset')
    assert client.post('/groups/join', json={'code': invitation['group_code']}).status_code == 404


def test_code_collision_and_leading_zeroes(client, monkeypatch):
    first = invite(client).json()
    choices = iter([int(first['group_code']), 7, 8])
    monkeypatch.setattr(invitations.secrets, 'randbelow', lambda n: next(choices))
    # Ensure the fixed test code isn't left over by another fixture.
    with db.tx() as c:
        c.execute("DELETE FROM kv WHERE key IN ('group-code:000007', 'group-code:000008')")
    second = invite(client).json()
    assert second['group_code'] == '000007'
    assert second['group_code'] != first['group_code']
    assert client.post('/groups/join', json={'code': '000007'}).json()['household_id'] == 'demo'
