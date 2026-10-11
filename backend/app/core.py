"""Households, immutable proposal versions, approvals, scene objects, outbound messages."""
import json

from . import assets, db, geometry
from .money import dollars, validate_split


class Forbidden(ValueError):
    pass


class Conflict(ValueError):
    pass


# Reads

def household(hid: str) -> dict:
    h = db.one('SELECT * FROM households WHERE id = ?', hid)
    if not h:
        raise KeyError(f'Unknown household {hid}')
    h['room'] = json.loads(h.pop('room_json'))
    h['needs'] = json.loads(h.pop('needs_json'))
    return h


def members(hid: str) -> list[dict]:
    return db.all_('SELECT * FROM members WHERE household_id = ? ORDER BY rowid', hid)


def member(hid: str, mid: str) -> dict:
    m = db.one('SELECT * FROM members WHERE household_id = ? AND id = ?', hid, mid)
    if not m:
        raise Forbidden(f'{mid} is not a member of this household')
    return m


def member_by_handle(handle: str) -> dict | None:
    phone = normalize_handle(handle)
    account_member = db.one('SELECT m.* FROM users u JOIN members m ON m.id=u.id AND m.household_id=u.active_group_id WHERE u.phone=?', phone)
    return account_member or db.one('SELECT * FROM members WHERE handle = ?', phone)


def normalize_handle(handle: str) -> str:
    h = (handle or '').strip().lower()
    if '@' in h:
        return h
    digits = ''.join(ch for ch in h if ch.isdigit())
    if len(digits) == 10:
        digits = '1' + digits
    return '+' + digits if digits else h


def limits(hid: str) -> dict[str, int | None]:
    return {m['id']: m['limit_cents'] for m in members(hid)}


def current_proposal(hid: str) -> dict | None:
    p = db.one("SELECT * FROM proposals WHERE household_id = ? AND status != 'superseded' ORDER BY version DESC LIMIT 1", hid)
    return _hydrate(p) if p else None


def proposal(hid: str, version: int) -> dict | None:
    p = db.one('SELECT * FROM proposals WHERE household_id = ? AND version = ?', hid, version)
    return _hydrate(p) if p else None


def _hydrate(p: dict) -> dict:
    hid, v = p['household_id'], p['version']
    p['unknown_costs'] = json.loads(p.pop('unknown_costs_json'))
    p['items'] = [{**json.loads(i['product_json']), 'price_cents': i['price_cents']} for i in
                  db.all_('SELECT * FROM proposal_items WHERE household_id = ? AND version = ? ORDER BY rowid', hid, v)]
    p['shares'] = {r['member_id']: r['amount_cents'] for r in
                   db.all_('SELECT * FROM shares WHERE household_id = ? AND version = ? ORDER BY rowid', hid, v)}
    p['decisions'] = {r['member_id']: r for r in
                      db.all_('SELECT * FROM decisions WHERE household_id = ? AND version = ?', hid, v)}
    p['approvals'] = {m: p['decisions'].get(m, {}).get('decision') == 'approve' for m in p['shares']}
    return p


def fully_approved(p: dict) -> bool:
    return bool(p['shares']) and all(p['approvals'].values())


def scene_objects(hid: str) -> list[dict]:
    out = []
    for r in db.all_('SELECT * FROM scene_objects WHERE household_id = ? ORDER BY rowid', hid):
        out.append({'object_id': r['object_id'], 'product_id': r['product_id'], 'category': r['category'],
                    'position_m': [r['x'], 0.0, r['z']], 'rotation_y_rad': r['rotation'],
                    'dimensions_m': json.loads(r['dims_json']), 'color_hex': r['color_hex'],
                    'asset_url': r['asset_url'], 'proposal_version': r['proposal_version']})
    return out


def purchase_locked(hid: str, version: int) -> bool:
    return bool(db.one("SELECT 1 FROM financial_ops WHERE household_id = ? AND kind = 'purchase' AND proposal_version = ? "
                       "AND state != 'failed'", hid, version))


# Messages

def queue_message(c, hid: str | None, mid_or_handle: str, text: str, dedupe_key: str | None = None) -> None:
    handle = mid_or_handle
    if hid and not mid_or_handle.startswith('+') and '@' not in mid_or_handle:
        row = c.execute('SELECT handle FROM members WHERE household_id = ? AND id = ?', (hid, mid_or_handle)).fetchone()
        handle = row['handle'] if row else None
    if not handle and hid:
        user = c.execute('SELECT phone FROM users WHERE id=?', (mid_or_handle,)).fetchone()
        handle = user['phone'] if user else None
    if not handle:
        return
    c.execute('INSERT OR IGNORE INTO outbound_jobs (household_id, to_handle, text, dedupe_key, status, created_at) '
              "VALUES (?, ?, ?, ?, 'pending', ?)", (hid, handle, text, dedupe_key, db.now()))


def names(hid: str) -> dict[str, str]:
    return {m['id']: m['name'] for m in members(hid)}


# Proposals

def create_proposal(hid: str, items: list[dict], shares: dict[str, int], explanation: str,
                    scene: list[dict] | None = None, activity: str | None = None, notify: bool = True) -> dict:
    """Write a new immutable version, supersede the previous one, and request approvals."""
    total = sum(i['price_cents'] for i in items)
    if not items or any(not i.get('dimensions_m') for i in items):
        raise Conflict('Every proposed item needs confirmed assembled dimensions')
    validate_split(total, shares, limits(hid))
    if set(shares) != {m['id'] for m in members(hid)}:
        raise Conflict('Every member needs exactly one share')
    from . import catalog
    items = [catalog._rememberable(i) for i in items]
    unknown = sorted({k.replace('_cents', '') for i in items for k, v in i['additional_costs'].items() if v is None})
    known_extra = sum(v for i in items for v in i['additional_costs'].values() if isinstance(v, int))
    who = names(hid)
    with db.tx() as c:
        prev = c.execute("SELECT version FROM proposals WHERE household_id = ? AND status != 'superseded' "
                         'ORDER BY version DESC LIMIT 1', (hid,)).fetchone()
        if prev and purchase_locked(hid, prev['version']):
            raise Conflict(f"A purchase was already authorized for v{prev['version']}; it can no longer be revised")
        version = (c.execute('SELECT COALESCE(MAX(version), 0) AS v FROM proposals WHERE household_id = ?',
                             (hid,)).fetchone()['v']) + 1
        c.execute("UPDATE proposals SET status = 'superseded' WHERE household_id = ? AND status != 'superseded'", (hid,))
        c.execute('INSERT INTO proposals VALUES (?, ?, ?, ?, ?, ?, ?)', (
            hid, version, 'awaiting_approval', total + known_extra, json.dumps(unknown), explanation, db.now()))
        for i in items:
            snapshot = {k: i.get(k) for k in ('id', 'title', 'retailer', 'variant', 'category', 'source_url', 'image_url',
                                              'dimensions_m', 'source_type', 'retrieved_at', 'additional_costs', 'style')}
            c.execute('INSERT INTO proposal_items VALUES (?, ?, ?, ?, ?, ?)',
                      (hid, version, i['id'], i['category'], i['price_cents'], json.dumps(snapshot)))
        for mid, amount in shares.items():
            c.execute('INSERT INTO shares VALUES (?, ?, ?, ?)', (hid, version, mid, amount))
        if scene is not None:
            c.execute('DELETE FROM scene_objects WHERE household_id = ?', (hid,))
            for o in scene:
                _insert_object(c, hid, o, version)
        db.log(c, hid, activity or f'Proposal v{version} created')
        summary = ', '.join(f"{i['title']} ({dollars(i['price_cents'])})" for i in items)
        for mid, amount in (shares.items() if notify else []):
            queue_message(c, hid, mid, (
                f"RAG to Rooms - proposal v{version}: {summary}. Total {dollars(total)}. "
                f"{explanation} Your share: {dollars(amount)}. Reply YES to approve v{version} or NO to object."),
                dedupe_key=f'approve-request:{hid}:v{version}:{mid}')
        db.bump(c, hid)
    for o in scene or []:
        product = {**o['product']} if 'product' in o else None
        if product:
            assets.request(product)
    return current_proposal(hid)


def _insert_object(c, hid, o, version):
    c.execute('INSERT INTO scene_objects VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', (
        hid, o['object_id'], o['product_id'], o['category'], o['position_m'][0], o['position_m'][2],
        o.get('rotation_y_rad', 0.0), version, json.dumps(o['dimensions_m']), o.get('color_hex'), o.get('asset_url')))


def decide(hid: str, version: int, mid: str, decision: str, reason: str | None = None, via: str = 'app') -> dict:
    """Record approve/object for one member on one exact version."""
    member(hid, mid)
    if decision not in ('approve', 'object'):
        raise ValueError('decision must be approve or object')
    with db.tx() as c:
        cur = c.execute("SELECT version, status FROM proposals WHERE household_id = ? AND status != 'superseded' "
                        'ORDER BY version DESC LIMIT 1', (hid,)).fetchone()
        if not cur or cur['version'] != version:
            raise Conflict(f'v{version} is not the current proposal' + (f" (current is v{cur['version']})" if cur else ''))
        if cur['status'] not in ('awaiting_approval', 'approved'):
            raise Conflict(f"v{version} is {cur['status']} and no longer accepts decisions")
        c.execute('INSERT INTO decisions VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(household_id, version, member_id) '
                  'DO UPDATE SET decision = excluded.decision, reason = excluded.reason, via = excluded.via, at = excluded.at',
                  (hid, version, mid, decision, reason, via, db.now()))
        approvals = c.execute("SELECT COUNT(*) AS n FROM decisions WHERE household_id = ? AND version = ? AND decision = 'approve'",
                              (hid, version)).fetchone()['n']
        needed = c.execute('SELECT COUNT(*) AS n FROM shares WHERE household_id = ? AND version = ?', (hid, version)).fetchone()['n']
        status = 'approved' if approvals == needed else 'awaiting_approval'
        c.execute('UPDATE proposals SET status = ? WHERE household_id = ? AND version = ?', (status, hid, version))
        who = names(hid).get(mid, mid)
        db.log(c, hid, f'{who} approved v{version}' if decision == 'approve' else f'{who} objected to v{version}')
        if status == 'approved':
            payer = c.execute('SELECT payer_id FROM households WHERE id = ?', (hid,)).fetchone()['payer_id']
            total = c.execute('SELECT known_total_cents FROM proposals WHERE household_id = ? AND version = ?',
                              (hid, version)).fetchone()['known_total_cents']
            db.log(c, hid, f'Everyone approved v{version}')
            queue_message(c, hid, payer, (
                f'Everyone approved proposal v{version}. Reply PAY to authorize the simulated Nessie purchase of '
                f'{dollars(total)} from your account. No real money moves.'), dedupe_key=f'pay-request:{hid}:v{version}')
        db.bump(c, hid)
    return proposal(hid, version)


def set_limit(hid: str, mid: str, limit_cents: int | None, note: str | None = None) -> None:
    member(hid, mid)
    if limit_cents is not None and (type(limit_cents) is not int or limit_cents < 0):
        raise ValueError('Limit must be nonnegative integer cents')
    with db.tx() as c:
        c.execute('UPDATE members SET limit_cents = ?, limit_note = ? WHERE household_id = ? AND id = ?',
                  (limit_cents, note, hid, mid))
        db.log(c, hid, 'A roommate updated their contribution limit')
        db.bump(c, hid)


def move_object(hid: str, object_id: str, position_m: list[float], rotation_y_rad: float) -> dict:
    h = household(hid)
    with db.tx() as c:
        n = c.execute('UPDATE scene_objects SET x = ?, z = ?, rotation = ? WHERE household_id = ? AND object_id = ?',
                      (float(position_m[0]), float(position_m[2]), float(rotation_y_rad), hid, object_id)).rowcount
        if not n:
            raise KeyError(object_id)
        db.bump(c, hid)
    return geometry.validate_scene(h['room'], scene_objects(hid))
