"""Payer-triggered Photon messages are room scoped and safe to retry."""
from test_edge_cases import client, purchase_confirmed
from app import core, db


def link(client):
    for mid, phone in [('emily', '+15551111111'), ('maya', '+15552222222'), ('alex', '+15553333333')]:
        response = client.put(f'/households/demo/members/{mid}/handle', json={'handle': phone})
        assert response.status_code == 200


def test_payer_requests_send_to_every_roommate_once(client):
    link(client)
    state = purchase_confirmed(client)
    version = state['proposal']['version']
    before = db.one('SELECT COUNT(*) AS n FROM outbound_jobs')['n']
    body = {'member_id': 'emily', 'proposal_version': version, 'request_id': 'payer-request-1'}
    first = client.post('/households/demo/payment-requests', json=body)
    assert first.status_code == 200, first.text
    assert first.json()['queued'] == 2
    assert first.json()['message'].startswith("Living room's furniture is purchased!")
    assert 'Please send your share to Emily' in first.json()['message']
    jobs = db.all_("SELECT * FROM outbound_jobs WHERE dedupe_key LIKE 'room-payment:%'")
    assert {r['to_handle'] for r in jobs} == {'+15552222222', '+15553333333'}
    assert all(r['household_id'] == 'demo' and r['text'] == first.json()['message'] for r in jobs)
    assert client.post('/households/demo/payment-requests', json=body).status_code == 200
    assert db.one('SELECT COUNT(*) AS n FROM outbound_jobs')['n'] == before + 2
    body['member_id'] = 'maya'
    assert client.post('/households/demo/payment-requests', json=body).status_code == 403
    body['member_id'] = 'emily'
    body['proposal_version'] += 1
    assert client.post('/households/demo/payment-requests', json=body).status_code == 409


def test_no_request_before_purchase_or_without_all_numbers(client):
    version = core.current_proposal('demo')['version']
    body = {'member_id': 'emily', 'proposal_version': version, 'request_id': 'blocked-request'}
    assert client.post('/households/demo/payment-requests', json=body).status_code == 409
    purchase_confirmed(client)
    with db.tx() as c:
        c.execute("UPDATE members SET handle=NULL WHERE household_id='demo'")
    assert client.post('/households/demo/payment-requests', json=body).status_code == 409
    assert db.all_("SELECT * FROM outbound_jobs WHERE dedupe_key LIKE 'room-payment:%'") == []


def test_real_group_requests_only_selected_room_members(client):
    import time
    from test_accounts import signup, create
    from app import finance, seed
    _, owner, owner_headers = signup(client)
    group = create(client, owner_headers)
    gid, payer = group['id'], owner['user']['id']
    people = []
    for _ in range(2):
        body, user, headers = signup(client)
        assert client.post('/groups/join', headers=headers, json={'code': group['group_code']}).status_code == 200
        people.append((body, user['user']['id'], headers))
    selected, unselected = people
    for uid, headers in [(payer, owner_headers), (selected[1], selected[2])]:
        assert client.put(f'/apartments/{gid}/setup', headers=headers, json={
            'member_id': uid, 'rooms': {gid: {'budget_cents': 30000}}}).status_code == 200
    proposal = core.create_proposal(gid, [seed.demo_sofa()],
                                   {payer: 30000, selected[1]: 30000, unselected[1]: 0},
                                   'Test room purchase', scene=[], notify=False)
    version = proposal['version']
    for uid in [payer, selected[1], unselected[1]]:
        core.decide(gid, version, uid, 'approve')
    finance.authorize_purchase(gid, payer, version)
    deadline = time.time() + 12
    while time.time() < deadline:
        if db.one("SELECT 1 FROM financial_ops WHERE household_id=? AND kind='purchase' AND state='confirmed'", gid):
            break
        time.sleep(.1)
    else:
        raise AssertionError('Mock purchase was not confirmed')
    response = client.post(f'/households/{gid}/payment-requests', headers=owner_headers, json={
        'member_id': payer, 'proposal_version': version, 'request_id': 'selected-room-only'})
    assert response.status_code == 200, response.text
    assert response.json()['queued'] == 1
    jobs = db.all_("SELECT * FROM outbound_jobs WHERE dedupe_key LIKE 'room-payment:%'")
    assert len(jobs) == 1 and jobs[0]['to_handle'] == selected[0]['phone']
    forged = client.post(f'/households/{gid}/payment-requests', headers=selected[2], json={
        'member_id': payer, 'proposal_version': version, 'request_id': 'forged'})
    assert forged.status_code == 403
