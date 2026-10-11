"""Reset clears saved demo contacts/jobs, reloads seed contacts, and sends no texts."""
import json

import pytest
from fastapi.testclient import TestClient

from app import core, db, seed
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
