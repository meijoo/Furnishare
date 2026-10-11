"""Onboarding preferences persist per group and inspiration persists per room."""
from test_accounts import client, signup, create
from app import db, config


def test_saved_setup_survives_new_client_and_is_private(client):
    _, session, headers = signup(client)
    group = create(client, headers)
    gid = group['id']
    uid = session['user']['id']
    body = {'member_id': uid, 'group_budget_cents': 120000,
            'individual_budget_cents': 45000, 'solo': False,
            'rooms': {gid: 'Warm wood and green furniture'}}
    response = client.put(f'/apartments/{gid}/setup', headers=headers, json=body)
    assert response.status_code == 200, response.text
    assert db.one('SELECT budget_cents FROM households WHERE id=?', gid)['budget_cents'] == 120000
    assert db.one('SELECT limit_cents FROM members WHERE household_id=? AND id=?', gid, uid)['limit_cents'] == 45000
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as restarted:
        saved = restarted.get(f'/apartments/{gid}/setup', headers=headers, params={'member_id': uid}).json()
        assert saved['individual_budget_cents'] == 45000
        assert saved['rooms'][0]['description'] == 'Warm wood and green furniture'
        state = restarted.get(f'/households/{gid}/state', headers=headers, params={'member_id': uid}).json()
        assert state['room']['inspiration_description'] == 'Warm wood and green furniture'
    _, other, other_headers = signup(client)
    assert client.get(f'/apartments/{gid}/setup', headers=other_headers, params={'member_id': uid}).status_code == 403
    assert client.get(f'/apartments/{gid}/setup', headers=headers, params={'member_id': other['user']['id']}).status_code == 403
    body['individual_budget_cents'] = 130000
    assert client.put(f'/apartments/{gid}/setup', headers=headers, json=body).status_code == 422
    assert db.kv_get(f'setup:{gid}')['individual_budgets'][uid] == 45000
    body['individual_budget_cents'] = 45000
    body['rooms'] = {'demo': 'Wrong room'}
    assert client.put(f'/apartments/{gid}/setup', headers=headers, json=body).status_code == 403


def test_solo_and_multiple_room_photos(client, tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'UPLOADS_DIR', tmp_path)
    _, session, headers = signup(client)
    gid = create(client, headers)['id']
    uid = session['user']['id']
    response = client.put(f'/apartments/{gid}/setup', headers=headers, json={
        'member_id': uid, 'group_budget_cents': 60000, 'solo': True, 'rooms': {gid: ''}})
    assert response.status_code == 200, response.text
    assert response.json()['individual_budget_cents'] == 60000
    for content in [b'one', b'two', b'one']:
        response = client.post(f'/households/{gid}/inspiration', headers=headers,
                               files={'file': ('inspiration.png', b'\x89PNG\r\n\x1a\n' + content, 'image/png')})
        assert response.status_code == 200, response.text
    state = client.get(f'/households/{gid}/state', headers=headers, params={'member_id': uid}).json()
    assert len(state['room']['inspiration_images']) == 2
    assert len(list(tmp_path.iterdir())) == 2
    assert db.one('SELECT COUNT(*) AS n FROM proposals WHERE household_id=?', gid)['n'] == 0
