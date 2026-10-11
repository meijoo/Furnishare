"""Onboarding preferences persist per group and inspiration persists per room."""
from test_accounts import client, signup, create
from app import db, config


def test_saved_setup_survives_new_client_and_is_private(client):
    _, session, headers = signup(client)
    group = create(client, headers)
    gid = group['id']
    uid = session['user']['id']
    body = {'member_id': uid, 'rooms': {gid: {'budget_cents': 45000, 'description': 'Warm wood and green furniture'}}}
    response = client.put(f'/apartments/{gid}/setup', headers=headers, json=body)
    assert response.status_code == 200, response.text
    assert db.one('SELECT budget_cents FROM households WHERE id=?', gid)['budget_cents'] == 45000
    assert db.one('SELECT limit_cents FROM members WHERE household_id=? AND id=?', gid, uid)['limit_cents'] == 45000
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as restarted:
        saved = restarted.get(f'/apartments/{gid}/setup', headers=headers, params={'member_id': uid}).json()
        assert saved['rooms'][0]['budget_cents'] == 45000
        assert saved['rooms'][0]['description'] == 'Warm wood and green furniture'
        state = restarted.get(f'/households/{gid}/state', headers=headers, params={'member_id': uid}).json()
        assert state['room']['inspiration_description'] == 'New Person: Warm wood and green furniture'
    _, other, other_headers = signup(client)
    assert client.get(f'/apartments/{gid}/setup', headers=other_headers, params={'member_id': uid}).status_code == 403
    assert client.get(f'/apartments/{gid}/setup', headers=headers, params={'member_id': other['user']['id']}).status_code == 403
    body['rooms'][gid]['budget_cents'] = -1
    assert client.put(f'/apartments/{gid}/setup', headers=headers, json=body).status_code == 422
    assert db.one('SELECT amount_cents FROM room_budgets WHERE household_id=? AND member_id=?', gid, uid)['amount_cents'] == 45000
    body['rooms'][gid]['budget_cents'] = 45000
    body['rooms'] = {'demo': {'budget_cents': 1000}}
    assert client.put(f'/apartments/{gid}/setup', headers=headers, json=body).status_code == 403


def test_solo_and_multiple_room_photos(client, tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'UPLOADS_DIR', tmp_path)
    _, session, headers = signup(client)
    gid = create(client, headers)['id']
    uid = session['user']['id']
    response = client.put(f'/apartments/{gid}/setup', headers=headers, json={
        'member_id': uid, 'rooms': {gid: {'budget_cents': 60000, 'description': ''}}})
    assert response.status_code == 200, response.text
    assert response.json()['rooms'][0]['budget_cents'] == 60000
    for content in [b'one', b'two', b'one']:
        response = client.post(f'/households/{gid}/inspiration', headers=headers,
                               files={'file': ('inspiration.png', b'\x89PNG\r\n\x1a\n' + content, 'image/png')})
        assert response.status_code == 200, response.text
    state = client.get(f'/households/{gid}/state', headers=headers, params={'member_id': uid}).json()
    assert len(state['room']['inspiration_images']) == 2
    assert len(list(tmp_path.iterdir())) == 2
    assert db.one('SELECT COUNT(*) AS n FROM proposals WHERE household_id=?', gid)['n'] == 0


def test_shared_room_sums_selected_members_and_replaces_edits(client):
    _, owner, headers = signup(client)
    group = create(client, headers)
    gid, uid = group['id'], owner['user']['id']
    assert client.get(f'/households/{gid}/state', headers=headers).json()['budget_cents'] is None

    def save(member_headers, member_id, amount, description=None):
        response = client.put(f'/apartments/{gid}/setup', headers=member_headers, json={
            'member_id': member_id, 'rooms': {gid: {'budget_cents': amount, 'description': description}}})
        assert response.status_code == 200, response.text

    save(headers, uid, 20000, 'Wood furniture')
    _, roommate, roommate_headers = signup(client)
    mid = roommate['user']['id']
    joined = client.post('/groups/join', headers=roommate_headers, json={'code': group['group_code']})
    assert joined.status_code == 200, joined.text
    assert client.get(f'/households/{gid}/state', headers=headers).json()['budget_cents'] == 20000
    own = client.get(f'/apartments/{gid}/setup', headers=roommate_headers, params={'member_id': mid}).json()
    assert own['rooms'][0]['budget_cents'] is None
    save(roommate_headers, mid, 30000, 'Blue accents')
    assert client.get(f'/households/{gid}/state', headers=headers).json()['budget_cents'] == 50000
    save(roommate_headers, mid, 30000)  # retry replaces rather than adding again
    assert client.get(f'/households/{gid}/state', headers=headers).json()['budget_cents'] == 50000
    save(headers, uid, 25000)
    state = client.get(f'/households/{gid}/state', headers=headers, params={'member_id': uid}).json()
    assert state['budget_cents'] == 55000
    assert 'Wood furniture' in state['room']['inspiration_description']
    assert 'Blue accents' in state['room']['inspiration_description']
    assert all('limit_cents' not in m for m in state['members'] if m['id'] != uid)
    assert client.put(f'/households/{gid}/budget', headers=headers, json={'budget_cents': 99999}).status_code == 409
    from app import core
    core.set_limit(gid, mid, 35000)
    assert client.get(f'/households/{gid}/state', headers=headers).json()['budget_cents'] == 60000


def test_unselected_rooms_stay_unfunded_and_private_rooms_are_protected(client):
    from app import accounts, seed
    _, owner, headers = signup(client)
    group = create(client, headers)
    gid, uid = group['id'], owner['user']['id']
    private = gid + '-bed-' + uid
    with db.tx() as c:
        accounts.create_room(c, gid, private, 'My bedroom', uid, {**seed.ROOM, 'kind': 'bedroom'}, [uid])
    plan = accounts.apartment_snapshot(gid)
    plan['rooms'].append({'id': 'bed-owner', 'name': 'My bedroom', 'kind': 'bedroom',
                          'shared': False, 'owner_id': uid, 'household_id': private,
                          'x_m': 5, 'z_m': 0, 'width_m': 3, 'depth_m': 3})
    db.kv_set(f'group-plan:{gid}', plan)
    response = client.put(f'/apartments/{gid}/setup', headers=headers, json={
        'member_id': uid, 'rooms': {private: {'budget_cents': 80000}}})
    assert response.status_code == 200, response.text
    assert client.get(f'/households/{gid}/state', headers=headers).json()['budget_cents'] is None
    assert client.get(f'/households/{private}/state', headers=headers).json()['budget_cents'] == 80000
    _, roommate, roommate_headers = signup(client)
    client.post('/groups/join', headers=roommate_headers, json={'code': group['group_code']})
    response = client.put(f'/apartments/{gid}/setup', headers=roommate_headers, json={
        'member_id': roommate['user']['id'], 'rooms': {gid: {'budget_cents': 30000}, private: {'budget_cents': 50000}}})
    assert response.status_code == 403
    assert db.one('SELECT budget_cents FROM households WHERE id=?', gid)['budget_cents'] == 0


def test_budget_editor_only_changes_self_and_everyone_sees_room_budgets(client):
    _, owner, owner_headers = signup(client)
    group = create(client, owner_headers)
    gid = group['id']
    people = [(owner['user']['id'], owner_headers)]
    for _ in range(2):
        _, user, headers = signup(client)
        joined = client.post('/groups/join', headers=headers, json={'code': group['group_code']})
        assert joined.status_code == 200
        people.append((user['user']['id'], headers))
    for mid, headers in people:
        response = client.put(f'/apartments/{gid}/setup', headers=headers, json={
            'member_id': mid, 'rooms': {gid: {'budget_cents': 10000}}})
        assert response.status_code == 200
    me, my_headers = people[0]
    state = client.get(f'/households/{gid}/state', headers=my_headers, params={'member_id': me}).json()
    assert state['budget_cents'] == 30000
    assert [m['contribution_budget_cents'] for m in state['members']] == [10000] * 3
    other = people[1][0]
    assert client.put(f'/households/{gid}/members/{other}/limit', headers=my_headers,
                      json={'limit_cents': 20000}).status_code == 403
    response = client.put(f'/households/{gid}/members/{me}/limit', headers=my_headers,
                          json={'limit_cents': 20000})
    assert response.status_code == 200, response.text
    state = client.get(f'/households/{gid}/state', headers=my_headers, params={'member_id': me}).json()
    assert state['budget_cents'] == 40000
    assert {m['id']: m['contribution_budget_cents'] for m in state['members']} == {
        mid: 20000 if mid == me else 10000 for mid, _ in people}
