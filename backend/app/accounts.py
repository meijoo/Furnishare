"""Persistent accounts and real groups, separate from demo personas."""
import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import time

from fastapi import HTTPException

from . import catalog, core, db, seed

SESSION_SECONDS = 30 * 24 * 60 * 60


def public_user(user):
    return {key: user[key] for key in ('id', 'name', 'email', 'phone', 'username')}


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    value = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return f'scrypt${salt}${value}'


def issue_session(user):
    token = secrets.token_urlsafe(32)
    with db.tx() as c:
        c.execute('INSERT INTO sessions VALUES (?, ?, ?, ?)',
                  (hashlib.sha256(token.encode()).hexdigest(), user['id'], time.time() + SESSION_SECONDS, db.now()))
    return {'token': token, 'user': public_user(user), 'groups': groups_for(user['id'])}


def signup(name, email, phone, username, password):
    name, email, username = name.strip(), email.strip().lower(), username.strip().lower()
    phone = core.normalize_handle(phone)
    if not name:
        raise ValueError('Enter your name.')
    if not re.fullmatch(r'\+[1-9][0-9]{7,14}', phone):
        raise ValueError('Enter a valid international phone number.')
    if len(username) < 3:
        raise ValueError('Username needs at least 3 characters.')
    if not re.fullmatch(r'[a-z0-9_.-]{3,40}', username):
        raise ValueError('Username must use letters, numbers, dots, hyphens, or underscores, up to 40 characters.')
    if not 8 <= len(password) <= 256:
        raise ValueError('Password must contain 8–256 characters.')
    uid = 'usr_' + secrets.token_hex(12)
    hashed = password_hash(password)
    try:
        with db.tx() as c:
            c.execute('INSERT INTO users (id,name,email,phone,username,password_hash,created_at) VALUES (?,?,?,?,?,?,?)',
                      (uid, name, email, phone, username, hashed, db.now()))
    except sqlite3.IntegrityError as e:
        if db.one('SELECT 1 FROM users WHERE username=?', username):
            raise core.Conflict('That username is already taken.') from e
        raise core.Conflict('That phone number already has an account.') from e
    return issue_session(db.one('SELECT * FROM users WHERE id = ?', uid))


def login(username, password):
    user = db.one('SELECT * FROM users WHERE username = ?', username.strip().lower())
    # Compute the same cost for missing accounts to avoid a cheap enumeration path.
    stored = user['password_hash'] if user else password_hash('missing-account-password', '00' * 16)
    _, salt, _ = stored.split('$')
    if not hmac.compare_digest(password_hash(password, salt), stored) or not user:
        raise HTTPException(401, 'Username or password is incorrect.')
    return issue_session(user)


def authenticate(authorization):
    if not authorization or not authorization.startswith('Bearer '):
        raise HTTPException(401, 'Sign in to continue.')
    token_hash = hashlib.sha256(authorization[7:].encode()).hexdigest()
    user = db.one('SELECT u.* FROM users u JOIN sessions s ON s.user_id=u.id WHERE s.token_hash=? AND s.expires_at>?',
                  token_hash, time.time())
    if not user:
        raise HTTPException(401, 'Your session expired. Sign in again.')
    return user


def logout(authorization):
    authenticate(authorization)
    with db.tx() as c:
        c.execute('DELETE FROM sessions WHERE token_hash=?', (hashlib.sha256(authorization[7:].encode()).hexdigest(),))


def require_member(gid, uid):
    if not db.one('SELECT 1 FROM group_members WHERE group_id=? AND user_id=?', gid, uid):
        raise core.Forbidden('You are not a member of this group.')


def group_for_room(hid):
    row = db.one('SELECT group_id FROM group_rooms WHERE household_id=?', hid)
    return row['group_id'] if row else None


def snapshot(gid):
    group = db.one('SELECT * FROM groups WHERE id=?', gid)
    if not group:
        raise KeyError('Group')
    return {key: group[key] for key in ('id', 'name', 'location', 'owner_id', 'group_code')} | {
        'household_id': gid,
        'members': db.all_('SELECT u.id,u.name,gm.role FROM group_members gm JOIN users u ON u.id=gm.user_id WHERE gm.group_id=? ORDER BY gm.joined_at', gid),
    }


def groups_for(uid):
    return [snapshot(row['group_id']) for row in db.all_('SELECT group_id FROM group_members WHERE user_id=? ORDER BY joined_at DESC', uid)]


def new_code(c):
    for _ in range(100):
        code = f'{secrets.randbelow(1000000):06d}'
        if (not c.execute('SELECT 1 FROM groups WHERE group_code=?', (code,)).fetchone()
                and not c.execute('SELECT 1 FROM kv WHERE key=?', (f'group-code:{code}',)).fetchone()):
            return code
    raise ValueError('Could not allocate a group code; try again.')


def create_room(c, gid, hid, name, owner, room, user_ids):
    c.execute('INSERT INTO households (id,name,budget_cents,payer_id,room_json,needs_json) VALUES (?,?,?,?,?,?)',
              (hid, name, 150000, owner, json.dumps(room), json.dumps(list(catalog.BEDROOM_CATEGORIES if room.get('kind') == 'bedroom' else catalog.LIVING_CATEGORIES))))
    c.execute('INSERT INTO group_rooms VALUES (?,?)', (hid, gid))
    for uid in user_ids:
        user = c.execute('SELECT name FROM users WHERE id=?', (uid,)).fetchone()
        c.execute('INSERT INTO members (household_id,id,name) VALUES (?,?,?)', (hid, uid, user['name']))


def create_group(uid, name, location, request_id):
    name, location = name.strip(), location.strip()
    if not name:
        raise ValueError('Enter a group name.')
    with db.tx() as c:
        prior = c.execute('SELECT id FROM groups WHERE owner_id=? AND request_id=?', (uid, request_id)).fetchone()
        if prior:
            return snapshot(prior['id'])
        gid = 'grp_' + secrets.token_hex(12)
        c.execute('INSERT INTO groups VALUES (?,?,?,?,?,?,?)', (gid, name, location, uid, new_code(c), request_id, db.now()))
        c.execute('INSERT INTO group_members VALUES (?,?,?,?)', (gid, uid, 'owner', db.now()))
        create_room(c, gid, gid, 'Living room', uid, {**seed.ROOM, 'kind': 'living'}, [uid])
        c.execute('UPDATE users SET active_group_id=? WHERE id=?', (gid, uid))
        db.log(c, gid, 'Group created')
        db.bump(c, gid)
    return snapshot(gid)


def join_group(uid, code):
    group = db.one('SELECT * FROM groups WHERE group_code=?', code)
    if not group:
        raise KeyError('Group code not found.')
    gid = group['id']
    with db.tx() as c:
        exists = c.execute('SELECT 1 FROM group_members WHERE group_id=? AND user_id=?', (gid, uid)).fetchone()
        if not exists:
            if c.execute("SELECT 1 FROM financial_ops WHERE household_id IN (SELECT household_id FROM group_rooms WHERE group_id=?) AND kind='purchase' AND state!='failed'", (gid,)).fetchone():
                raise core.Conflict('A purchase is already in progress. Finish it before adding roommates.')
            c.execute('INSERT INTO group_members VALUES (?,?,?,?)', (gid, uid, 'member', db.now()))
            user = c.execute('SELECT name FROM users WHERE id=?', (uid,)).fetchone()
            for row in c.execute('SELECT household_id FROM group_rooms WHERE group_id=?', (gid,)).fetchall():
                hid = row['household_id']
                room = core.household(hid)['room']
                if room.get('kind') == 'bedroom':
                    continue
                c.execute('INSERT INTO members (household_id,id,name) VALUES (?,?,?)', (hid, uid, user['name']))
                c.execute("UPDATE proposals SET status='superseded' WHERE household_id=? AND status!='settled'", (hid,))
                c.execute('DELETE FROM scene_objects WHERE household_id=?', (hid,))
                db.log(c, hid, f"{user['name']} joined the group; request a new proposal including all roommates")
                db.bump(c, hid)
        c.execute('UPDATE users SET active_group_id=? WHERE id=?', (gid, uid))
    return {'household_id': gid, 'group_name': group['name'], 'group_code': code, 'group_id': gid}


def apartment_snapshot(gid):
    from . import apartment
    group = snapshot(gid)
    plan = db.kv_get(f'group-plan:{gid}') or {
        'width_m': 4.5, 'depth_m': 4.0, 'source': 'built_in',
        'rooms': [{'id': 'living', 'name': 'Living room', 'kind': 'living', 'shared': True,
                   'owner_id': None, 'household_id': gid, 'x_m': 0, 'z_m': 0, 'width_m': 4.5, 'depth_m': 4.0}],
    }
    total, shares = 0, {}
    rooms = []
    for room in plan['rooms']:
        entry = dict(room)
        hid = room.get('household_id')
        entry['summary'] = apartment._summary(hid) if hid else None
        if hid:
            h = core.household(hid)
            entry['room_m'] = {key: h['room'][key] for key in ('width_m', 'depth_m')}
            total += entry['summary']['known_total_cents']
            for uid, cents in entry['summary']['shares'].items():
                shares[uid] = shares.get(uid, 0) + cents
        rooms.append(entry)
    return {**plan, 'id': gid, 'name': group['name'], 'members': group['members'], 'rooms': rooms,
            'totals': {'known_total_cents': total, 'by_member_cents': shares}}


def import_plan(gid, data, mime, image_url, width_m=None):
    from . import floorplan
    group = snapshot(gid)
    users = [m['id'] for m in group['members']]
    image_width, image_height = floorplan.image_size(data)
    plan = floorplan.build_plan(floorplan.extract(data, mime), image_width, image_height, users, width_m)
    names = {m['id']: m['name'] for m in group['members']}
    with db.tx() as c:
        for room in plan['rooms']:
            old_hid = room.get('household_id')
            if not old_hid:
                continue
            hid = gid if old_hid == 'demo' else f"{gid}-bed-{room['owner_id']}"
            room['household_id'] = hid
            if room.get('owner_id'):
                room['name'] = f"{names[room['owner_id']]}'s bedroom"
            if not c.execute('SELECT 1 FROM households WHERE id=?', (hid,)).fetchone():
                size = room.get('interior_m') or room
                geometry = {'width_m': size['width_m'], 'depth_m': size['depth_m'], 'height_m': 2.5,
                            'kind': room['kind'], 'openings': [], 'clearances': []}
                owner = room.get('owner_id') or group['owner_id']
                create_room(c, gid, hid, room['name'], owner, geometry, [owner] if room.get('owner_id') else users)
        if not any(r.get('household_id') == gid for r in plan['rooms']):
            plan['rooms'].append({'id': 'living', 'name': 'Living room', 'kind': 'living', 'shared': True,
                                  'owner_id': None, 'household_id': gid, 'x_m': 0, 'z_m': plan['depth_m'],
                                  'width_m': 4.5, 'depth_m': 4.0})
            plan['depth_m'] += 4.0
            plan['width_m'] = max(4.5, plan['width_m'])
        plan.update(source='imported', image_url=image_url)
        c.execute('INSERT INTO kv VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                  (f'group-plan:{gid}', json.dumps(plan)))
        db.bump(c, gid)
    return {'apartment': apartment_snapshot(gid), 'warnings': plan['warnings'], 'seeded': {}, 'scale_m_per_px': plan['scale_m_per_px']}


def restore_plan(gid):
    snapshot(gid)
    with db.tx() as c:
        c.execute('DELETE FROM kv WHERE key=?', (f'group-plan:{gid}',))
        db.bump(c, gid)
    return apartment_snapshot(gid)
