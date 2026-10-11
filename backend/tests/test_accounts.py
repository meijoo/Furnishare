"""Real accounts and groups persist independently of demo memberships."""
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from app import accounts, config, db
from app.main import app


@pytest.fixture
def client():
    with TestClient(app) as client:
        yield client


def signup(client):
    tag = uuid.uuid4().hex[:12]
    phone = f'+1{int(tag, 16) % 10000000000:010d}'
    body = {'name': 'New Person', 'email': f'{tag}@example.com', 'phone': phone,
            'username': tag, 'password': 'test-password-123'}
    response = client.post('/auth/signup', json=body)
    assert response.status_code == 201, response.text
    session = response.json()
    return body, session, {'Authorization': 'Bearer ' + session['token']}


def create(client, headers, request_id=None):
    response = client.post('/groups', headers=headers, json={'name': 'Our real home', 'location': 'Chapel Hill',
                           'request_id': request_id or str(uuid.uuid4())})
    assert response.status_code == 201, response.text
    return response.json()


def test_signup_login_duplicate_and_password_storage(client):
    body, session, headers = signup(client)
    assert session['groups'] == []
    assert 'password_hash' not in session['user']
    assert session['user']['id'].startswith('usr_')
    row = db.one('SELECT * FROM users WHERE id=?', session['user']['id'])
    assert row['password_hash'].startswith('scrypt$')
    assert body['password'] not in row['password_hash']
    assert client.post('/auth/signup', json=body).status_code == 409
    bad = client.post('/auth/login', json={'email': body['email'], 'password': 'wrong-password'})
    assert bad.status_code == 401
    assert client.post('/auth/login', json={'email': body['email'].upper(), 'password': body['password']}).status_code == 200
    assert client.get('/auth/me', headers=headers).json()['user']['id'] == row['id']
    assert client.get('/auth/me').status_code == 401
    assert client.post('/auth/logout', headers=headers).status_code == 200
    assert client.get('/auth/me', headers=headers).status_code == 401


def test_group_creation_join_and_authorization(client):
    _, owner, owner_headers = signup(client)
    _, roommate, roommate_headers = signup(client)
    group = create(client, owner_headers, 'idempotent')
    assert create(client, owner_headers, 'idempotent')['id'] == group['id']
    assert [m['id'] for m in group['members']] == [owner['user']['id']]
    hid = group['household_id']
    url = f'/households/{hid}/state'
    assert client.get(url).status_code == 401
    assert client.get(url, headers=roommate_headers).status_code == 403
    state = client.get(url, headers=owner_headers).json()
    assert state['proposal'] is None and state['scene']['objects'] == []
    assert [m['id'] for m in state['members']] == [owner['user']['id']]
    assert client.get(f'/apartments/{group["id"]}', headers=owner_headers).json()['rooms'][0]['household_id'] == hid
    assert client.post('/groups/join', json={'code': group['group_code']}).status_code == 401
    for _ in range(2):
        joined = client.post('/groups/join', headers=roommate_headers, json={'code': group['group_code']})
        assert joined.status_code == 200
        assert joined.json()['group_id'] == group['id']
    assert len(client.get(f'/groups/{group["id"]}', headers=owner_headers).json()['members']) == 2
    assert client.get(url, headers=roommate_headers).status_code == 200
    assert client.get(url, headers=roommate_headers, params={'member_id': owner['user']['id']}).status_code == 403
    assert client.put(f'/households/{hid}/members/{owner["user"]["id"]}/limit', headers=roommate_headers,
                      json={'limit_cents': 500}).status_code == 403
    assert client.post(f'/households/{hid}/chat', headers=roommate_headers,
                       json={'member_id': owner['user']['id'], 'text': 'blue sofa'}).status_code == 403


def test_restart_and_demo_reset_preserve_real_records(client):
    body, session, headers = signup(client)
    group = create(client, headers)
    invitation = client.post(f'/households/{group["id"]}/invitations', headers=headers, json={
        'members': [{'phone': '+15559998888', 'name': 'Invited Person'}], 'request_id': str(uuid.uuid4())}).json()
    assert invitation['group_code'] == group['group_code']
    client.post('/demo/reset?clear_handles=true')
    assert db.one('SELECT status FROM outbound_jobs WHERE job_id=?', invitation['job_id'])['status'] == 'pending'
    with TestClient(app) as restarted:
        assert restarted.get('/auth/me', headers=headers).json()['user']['id'] == session['user']['id']
        assert restarted.get('/groups', headers=headers).json()['groups'][0]['id'] == group['id']
        assert restarted.post('/auth/login', json={'email': body['email'], 'password': body['password']}).status_code == 200


def test_demo_disabled_and_session_expiry(client, monkeypatch):
    monkeypatch.setattr(config, 'SEED_DEMO', False)
    _, session, headers = signup(client)
    group = create(client, headers)
    with TestClient(app) as restarted:
        assert restarted.get(f'/groups/{group["id"]}', headers=headers).status_code == 200
    with db.tx() as c:
        c.execute('UPDATE sessions SET expires_at=? WHERE user_id=?', (time.time() - 1, session['user']['id']))
    assert client.get('/auth/me', headers=headers).status_code == 401


def test_real_invite_does_not_create_an_account(client):
    _, owner, headers = signup(client)
    body, member, member_headers = signup(client)
    group = create(client, headers)
    count = db.one('SELECT COUNT(*) AS n FROM users')['n']
    invitation = client.post(f'/households/{group["id"]}/invitations', headers=headers, json={
        'members': [{'phone': body['phone'], 'name': 'Roommate'}], 'request_id': str(uuid.uuid4())})
    assert invitation.status_code == 200, invitation.text
    assert db.one('SELECT COUNT(*) AS n FROM users')['n'] == count
    assert len(accounts.snapshot(group['id'])['members']) == 1
    client.post('/groups/join', headers=member_headers, json={'code': group['group_code']})
    assert len(accounts.snapshot(group['id'])['members']) == 2
    assert accounts.group_for_room(group['id']) == group['id']


def test_group_floorplan_stays_separate_from_demo(client, monkeypatch):
    import json
    import struct
    from pathlib import Path
    from app import floorplan
    _, owner, headers = signup(client)
    group = create(client, headers)
    reads = json.loads((Path(__file__).parent / 'fixtures/floorplan_3bed_reads.json').read_text())
    monkeypatch.setattr(floorplan, 'extract', lambda *a: reads)
    data = b'\x89PNG\r\n\x1a\n' + b'\x00' * 8 + struct.pack('>II', 909, 790)
    result = accounts.import_plan(group['id'], data, 'image/png', '/uploads/test.png')
    rooms = result['apartment']['rooms']
    assert all(not (r.get('household_id') or '').startswith('demo') for r in rooms)
    bed = next(r for r in rooms if r.get('owner_id'))
    assert bed['owner_id'] == owner['user']['id']
    assert accounts.group_for_room(bed['household_id']) == group['id']
    assert db.kv_get(f'group-plan:{group["id"]}')['image_url'] == '/uploads/test.png'
    assert accounts.restore_plan(group['id'])['rooms'][0]['household_id'] == group['id']
