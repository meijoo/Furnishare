"""Reset clears saved demo contacts/jobs, reloads seed contacts, and sends no texts."""
import json

import pytest
from fastapi.testclient import TestClient

from app import apartment, core, db, seed, textures
from app.main import app


@pytest.mark.parametrize('seed_contacts', [{}, {'emily': '+15550000009'}])
def test_reset_contacts_and_outbox(monkeypatch, tmp_path, seed_contacts):
    monkeypatch.setattr(seed.config, 'DATA_DIR', tmp_path)
    (tmp_path / 'members.json').write_text(json.dumps(seed_contacts))
    with TestClient(app) as client:
        client.post('/demo/reset')
        with db.tx() as connection:
            connection.execute("UPDATE members SET handle=? WHERE household_id='demo' AND id='emily'",
                               ('+15550000001',))
            core.queue_message(connection, 'demo', 'emily', 'Old demo message')
            core.queue_message(connection, 'demo-bed-emily', '+15550000002', 'Old bedroom message')
        assert db.one("SELECT COUNT(*) AS n FROM outbound_jobs WHERE household_id LIKE 'demo%'")['n'] > 0

        response = client.post('/demo/reset')
        assert response.status_code == 200
        assert {m['id']: m['handle'] for m in core.members('demo')} == {
            mid: seed_contacts.get(mid) for mid, _ in seed.MEMBERS
        }
        assert db.one("SELECT COUNT(*) AS n FROM outbound_jobs WHERE household_id LIKE 'demo%'")['n'] == 0
        assert core.current_proposal('demo') is not None


def test_full_reset_leaves_rooms_empty_and_clears_saved_preferences():
    with TestClient(app) as client:
        client.post('/demo/reset')
        db.kv_set(apartment.PLAN_KEY, {**apartment.built_in_plan(), 'name': 'Custom plan'})
        db.kv_set(textures.KEY, {'demo': {'obj-sofa': {'image_path': 'old.jpg'}},
                                'unrelated-room': {'obj-bed': {'image_path': 'keep.jpg'}}})
        with db.tx() as connection:
            connection.execute('INSERT OR REPLACE INTO room_budgets VALUES (?,?,?,?)',
                               ('demo', 'emily', 42000, 'Previous description'))
            connection.execute('INSERT OR REPLACE INTO room_inspiration VALUES (?,?)', ('demo', 'Previous inspiration'))
            connection.execute('INSERT INTO room_inspiration_images VALUES (?,?,?,?)',
                               ('reset-photo', 'demo', 'old.jpg', db.now()))
            connection.execute('UPDATE households SET inspiration_path=? WHERE id=?', ('old.jpg', 'demo'))
        response = client.post('/demo/reset', params={'furnished': 'false', 'full_reset': 'true'})
        assert response.status_code == 200
        assert apartment.plan()['name'] == apartment.NAME
        for hid in apartment.scope_ids():
            state = client.get(f'/households/{hid}/state').json()
            assert state['proposal'] is None
            assert state['scene']['objects'] == []
            assert state['room']['inspiration_images'] == []
            assert state['room']['inspiration_description'] == ''
            assert state['room']['inspiration_image_url'] is None
        assert core.household('demo')['budget_cents'] == sum(seed.SEED_LIMITS.values())
        assert db.one("SELECT COUNT(*) AS n FROM room_budgets WHERE household_id='demo'")['n'] == 0
        assert db.one("SELECT COUNT(*) AS n FROM outbound_jobs WHERE household_id LIKE 'demo%'")['n'] == 0
        assert db.kv_get(textures.KEY) == {'unrelated-room': {'obj-bed': {'image_path': 'keep.jpg'}}}
