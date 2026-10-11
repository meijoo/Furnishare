"""SQLite persistence. One process; mutations serialize on LOCK."""
import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone

from . import config

LOCK = threading.RLock()
_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL DEFAULT '',
  phone TEXT NOT NULL UNIQUE, username TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL, created_at TEXT NOT NULL, active_group_id TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
  expires_at REAL NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS groups (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, location TEXT NOT NULL,
  owner_id TEXT NOT NULL REFERENCES users(id), group_code TEXT NOT NULL UNIQUE,
  request_id TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(owner_id, request_id)
);
CREATE TABLE IF NOT EXISTS group_members (
  group_id TEXT NOT NULL REFERENCES groups(id), user_id TEXT NOT NULL REFERENCES users(id),
  role TEXT NOT NULL, joined_at TEXT NOT NULL, PRIMARY KEY(group_id, user_id)
);
CREATE TABLE IF NOT EXISTS group_rooms (
  household_id TEXT PRIMARY KEY, group_id TEXT NOT NULL REFERENCES groups(id)
);
CREATE TABLE IF NOT EXISTS group_invitees (
  group_id TEXT NOT NULL REFERENCES groups(id), phone TEXT NOT NULL, name TEXT NOT NULL,
  PRIMARY KEY(group_id, phone)
);
CREATE TABLE IF NOT EXISTS households (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, budget_cents INTEGER NOT NULL,
  payer_id TEXT, state_version INTEGER NOT NULL DEFAULT 0,
  room_json TEXT NOT NULL, inspiration_path TEXT, needs_json TEXT NOT NULL DEFAULT '[]', style_text TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS members (
  household_id TEXT NOT NULL, id TEXT NOT NULL, name TEXT NOT NULL, handle TEXT,
  limit_cents INTEGER, limit_note TEXT, PRIMARY KEY (household_id, id)
);
CREATE UNIQUE INDEX IF NOT EXISTS members_handle ON members(handle) WHERE handle IS NOT NULL;
CREATE TABLE IF NOT EXISTS proposals (
  household_id TEXT NOT NULL, version INTEGER NOT NULL, status TEXT NOT NULL,
  known_total_cents INTEGER NOT NULL, unknown_costs_json TEXT NOT NULL, explanation TEXT NOT NULL,
  created_at TEXT NOT NULL, PRIMARY KEY (household_id, version)
);
CREATE TABLE IF NOT EXISTS proposal_items (
  household_id TEXT NOT NULL, version INTEGER NOT NULL, product_id TEXT NOT NULL,
  category TEXT NOT NULL, price_cents INTEGER NOT NULL, product_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS shares (
  household_id TEXT NOT NULL, version INTEGER NOT NULL, member_id TEXT NOT NULL, amount_cents INTEGER NOT NULL,
  PRIMARY KEY (household_id, version, member_id)
);
CREATE TABLE IF NOT EXISTS decisions (
  household_id TEXT NOT NULL, version INTEGER NOT NULL, member_id TEXT NOT NULL,
  decision TEXT NOT NULL, reason TEXT, via TEXT, at TEXT NOT NULL,
  PRIMARY KEY (household_id, version, member_id)
);
CREATE TABLE IF NOT EXISTS scene_objects (
  household_id TEXT NOT NULL, object_id TEXT NOT NULL, product_id TEXT NOT NULL, category TEXT NOT NULL,
  x REAL NOT NULL, z REAL NOT NULL, rotation REAL NOT NULL, proposal_version INTEGER,
  dims_json TEXT NOT NULL, color_hex TEXT, asset_url TEXT, PRIMARY KEY (household_id, object_id)
);
CREATE TABLE IF NOT EXISTS liabilities (
  id TEXT PRIMARY KEY, household_id TEXT NOT NULL, version INTEGER NOT NULL,
  from_member TEXT NOT NULL, to_member TEXT NOT NULL, amount_cents INTEGER NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS financial_ops (
  op_key TEXT PRIMARY KEY, household_id TEXT NOT NULL, kind TEXT NOT NULL,
  from_member TEXT NOT NULL, to_member TEXT, amount_cents INTEGER NOT NULL, currency TEXT NOT NULL,
  proposal_version INTEGER NOT NULL, liability_id TEXT, authorized_by TEXT NOT NULL, authorized_at TEXT NOT NULL,
  authorized_via TEXT, state TEXT NOT NULL, external_id TEXT, error TEXT, updated_at TEXT NOT NULL,
  request_json TEXT, response_json TEXT
);
CREATE TABLE IF NOT EXISTS inbound_events (
  event_id TEXT PRIMARY KEY, sender_handle TEXT NOT NULL, conversation_id TEXT, text TEXT NOT NULL,
  received_at TEXT, processed_at TEXT, result TEXT
);
CREATE TABLE IF NOT EXISTS outbound_jobs (
  job_id INTEGER PRIMARY KEY AUTOINCREMENT, household_id TEXT, to_handle TEXT NOT NULL, conversation_id TEXT,
  text TEXT NOT NULL, dedupe_key TEXT UNIQUE, status TEXT NOT NULL, lease_until REAL, worker_id TEXT,
  provider_message_id TEXT, error TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS activity (
  id INTEGER PRIMARY KEY AUTOINCREMENT, household_id TEXT NOT NULL, at TEXT NOT NULL, text TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS timings (
  id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, stage TEXT NOT NULL, ms REAL NOT NULL, detail TEXT
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def conn() -> sqlite3.Connection:
    c = getattr(_local, 'conn', None)
    if c is None:
        c = sqlite3.connect(config.DB_PATH, timeout=30, isolation_level=None, check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute('PRAGMA journal_mode=WAL')
        c.execute('PRAGMA foreign_keys=ON')
        _local.conn = c
    return c


def init() -> None:
    with LOCK:
        c = conn()
        c.executescript(SCHEMA)
        migrate_account_email(c)


def migrate_account_email(c) -> None:
    """Remove the old email uniqueness constraint without losing account references."""
    indexes = c.execute('PRAGMA index_list(users)').fetchall()
    if not any(row['unique'] and [r['name'] for r in c.execute(f'PRAGMA index_info("{row["name"]}")')] == ['email']
               for row in indexes):
        return
    c.execute('PRAGMA foreign_keys=OFF')
    try:
        c.execute('BEGIN IMMEDIATE')
        c.execute("""CREATE TABLE users_email_migration (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL DEFAULT '',
          phone TEXT NOT NULL UNIQUE, username TEXT NOT NULL UNIQUE,
          password_hash TEXT NOT NULL, created_at TEXT NOT NULL, active_group_id TEXT
        )""")
        c.execute('INSERT INTO users_email_migration SELECT id,name,email,phone,username,password_hash,created_at,active_group_id FROM users')
        c.execute('DROP TABLE users')
        c.execute('ALTER TABLE users_email_migration RENAME TO users')
        if c.execute('PRAGMA foreign_key_check').fetchone():
            raise sqlite3.IntegrityError('Account migration would break existing references')
        c.execute('COMMIT')
    except BaseException:
        c.execute('ROLLBACK')
        raise
    finally:
        c.execute('PRAGMA foreign_keys=ON')


@contextmanager
def tx():
    """Serialized write transaction."""
    with LOCK:
        c = conn()
        c.execute('BEGIN IMMEDIATE')
        try:
            yield c
            c.execute('COMMIT')
        except BaseException:
            c.execute('ROLLBACK')
            raise


def one(sql, *args):
    row = conn().execute(sql, args).fetchone()
    return dict(row) if row else None


def all_(sql, *args):
    return [dict(r) for r in conn().execute(sql, args).fetchall()]


def bump(c, household_id: str) -> None:
    c.execute('UPDATE households SET state_version = state_version + 1 WHERE id = ?', (household_id,))


def log(c, household_id: str, text: str) -> None:
    c.execute('INSERT INTO activity (household_id, at, text) VALUES (?, ?, ?)', (household_id, now(), text))


def kv_get(key, default=None):
    row = one('SELECT value FROM kv WHERE key = ?', key)
    return json.loads(row['value']) if row else default


def kv_set(key, value) -> None:
    with tx() as c:
        c.execute('INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value',
                  (key, json.dumps(value)))


def record_timing(stage: str, ms: float, detail: str = '') -> None:
    with tx() as c:
        c.execute('INSERT INTO timings (at, stage, ms, detail) VALUES (?, ?, ?, ?)', (now(), stage, ms, detail))
