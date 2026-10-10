"""The demo apartment: a floor plan grouping room scopes (households). Shared rooms split; bedrooms are owner-paid."""
import json

from . import catalog, config, core, db, floorplan, planner, seed

AID = 'demo'
NAME = '3 bed / 3 bath apartment'
WIDTH_M, DEPTH_M = 10.5, 9.5
BEDROOM_SIZE = 3.5


def bedroom_room(width_m: float = BEDROOM_SIZE, depth_m: float = BEDROOM_SIZE) -> dict:
    """A bedroom with its door on the front wall toward the right corner and a window opposite."""
    door = round(min(1.0, width_m / 2 - 0.55), 2)
    return {
        'kind': 'bedroom', 'width_m': width_m, 'depth_m': depth_m, 'height_m': 2.5,
        'openings': [{'kind': 'door', 'wall': 'front', 'offset_m': door, 'width_m': 0.9},
                     {'kind': 'window', 'wall': 'back', 'offset_m': 0.0, 'width_m': round(min(1.2, width_m - 0.6), 2)}],
        'clearances': [{'label': 'door swing', 'x_m': door, 'z_m': depth_m / 2 - 0.45, 'width_m': 0.9, 'depth_m': 0.9}],
    }


BEDROOM_ROOM = bedroom_room()
BEDROOM_BUDGETS = {'emily': 120000, 'maya': 100000, 'alex': 80000}
BEDROOM_STYLES = {
    'emily': 'Light wood with blue accents: calm scandinavian pine and oak',
    'maya': 'Warm walnut and dark wood, cozy mid-century',
    'alex': 'Black metal, industrial and modern, white minimalist',
}
BEDROOM_STYLE = BEDROOM_STYLES['emily']

# Plan coordinates: x to the right, z toward the front door, origin at the apartment's back-left corner.
ROOMS = [
    {'id': 'bed-emily', 'name': "Emily's bedroom", 'kind': 'bedroom', 'owner_id': 'emily', 'household_id': 'demo-bed-emily',
     'x_m': 0.0, 'z_m': 0.0, 'width_m': 3.5, 'depth_m': 3.5},
    {'id': 'bed-maya', 'name': "Maya's bedroom", 'kind': 'bedroom', 'owner_id': 'maya', 'household_id': 'demo-bed-maya',
     'x_m': 3.5, 'z_m': 0.0, 'width_m': 3.5, 'depth_m': 3.5},
    {'id': 'bed-alex', 'name': "Alex's bedroom", 'kind': 'bedroom', 'owner_id': 'alex', 'household_id': 'demo-bed-alex',
     'x_m': 7.0, 'z_m': 0.0, 'width_m': 3.5, 'depth_m': 3.5},
    {'id': 'bath-1', 'name': 'Bathroom', 'kind': 'bathroom', 'x_m': 0.0, 'z_m': 3.5, 'width_m': 2.5, 'depth_m': 2.0},
    {'id': 'bath-2', 'name': 'Bathroom', 'kind': 'bathroom', 'x_m': 2.5, 'z_m': 3.5, 'width_m': 2.5, 'depth_m': 2.0},
    {'id': 'hall', 'name': 'Hall', 'kind': 'hall', 'x_m': 5.0, 'z_m': 3.5, 'width_m': 3.0, 'depth_m': 2.0},
    {'id': 'bath-3', 'name': 'Bathroom', 'kind': 'bathroom', 'x_m': 8.0, 'z_m': 3.5, 'width_m': 2.5, 'depth_m': 2.0},
    {'id': 'living', 'name': 'Living room', 'kind': 'living', 'shared': True, 'household_id': seed.HID,
     'x_m': 0.0, 'z_m': 5.5, 'width_m': 4.5, 'depth_m': 4.0},
    {'id': 'kitchen', 'name': 'Kitchen', 'kind': 'kitchen', 'shared': True,
     'x_m': 4.5, 'z_m': 5.5, 'width_m': 3.0, 'depth_m': 4.0},
    {'id': 'entry', 'name': 'Entry', 'kind': 'hall', 'x_m': 7.5, 'z_m': 5.5, 'width_m': 3.0, 'depth_m': 4.0},
]


PLAN_KEY = 'apartment_plan'


def plan() -> dict:
    """The current floor plan: an imported one if present, else the built-in demo apartment."""
    stored = db.kv_get(PLAN_KEY)
    if stored:
        return stored
    return {'name': NAME, 'source': 'built_in', 'width_m': WIDTH_M, 'depth_m': DEPTH_M, 'rooms': ROOMS,
            'image_url': None, 'image_frame_m': None, 'warnings': []}


def rooms() -> list[dict]:
    return plan()['rooms']


def scope_ids() -> list[str]:
    return [r['household_id'] for r in rooms() if r.get('household_id')]


def _bedroom_size(room: dict) -> tuple[float, float]:
    """The printed interior size when the plan has one, else the drawn size."""
    size = room.get('interior_m') or room
    return size['width_m'], size['depth_m']


def reset_bedroom(room: dict) -> dict:
    hid, owner = room['household_id'], room['owner_id']
    name = dict(seed.MEMBERS)[owner]
    with db.tx() as c:
        row = c.execute('SELECT state_version FROM households WHERE id = ?', (hid,)).fetchone()
        version = row['state_version'] if row else 0
        for table in ('proposals', 'proposal_items', 'shares', 'decisions', 'scene_objects', 'liabilities',
                      'financial_ops', 'activity', 'members'):
            c.execute(f'DELETE FROM {table} WHERE household_id = ?', (hid,))
        c.execute('DELETE FROM outbound_jobs WHERE household_id = ?', (hid,))
        c.execute('DELETE FROM households WHERE id = ?', (hid,))
        c.execute('INSERT INTO households (id, name, budget_cents, payer_id, state_version, room_json, needs_json, style_text) '
                  'VALUES (?, ?, ?, ?, ?, ?, ?, ?)', (hid, room['name'], BEDROOM_BUDGETS[owner], owner, version + 1,
                                                      json.dumps(bedroom_room(*_bedroom_size(room))),
                                                      json.dumps(list(catalog.BEDROOM_CATEGORIES)),
                                                      BEDROOM_STYLES.get(owner, BEDROOM_STYLE)))
        # Handles are globally unique and bound to the living room, so bedroom members act through the app.
        c.execute('INSERT INTO members (household_id, id, name, handle, limit_cents) VALUES (?, ?, ?, NULL, NULL)',
                  (hid, owner, name))
        db.log(c, hid, f"{room['name']} created; {name} pays for it alone")
    if config.SHOPPING_API_KEY:
        return {'ok': True, 'household_id': hid, 'proposal_version': None, 'total_cents': 0}
    pick = planner.select_bundle(hid, list(catalog.BEDROOM_CATEGORIES), BEDROOM_BUDGETS[owner],
                                BEDROOM_STYLES.get(owner, BEDROOM_STYLE))
    if not pick['ok'] or not pick['products']:
        return {'ok': False, 'household_id': hid, 'notes': pick.get('notes') or ['No bedroom products fit']}
    titles = ', '.join(p['title'] for p in pick['products'])
    p = planner.propose(hid, pick['products'], f"A starter bedroom for {name}: {titles}. {name} pays the whole amount.",
                        activity='Bedroom plan proposed')
    return {'ok': True, 'household_id': hid, 'proposal_version': p['version'], 'total_cents': p['known_total_cents']}


def _owned_bedrooms() -> list[dict]:
    return [r for r in rooms() if r['kind'] == 'bedroom' and r.get('household_id')]


def _seed(room: dict) -> dict:
    try:
        result = reset_bedroom(room)
    except Exception as e:  # noqa: BLE001 - one bad bedroom must not take down the apartment
        result = {'ok': False, 'household_id': room['household_id'], 'notes': [str(e)]}
    if not result['ok']:
        print(f"apartment: could not seed {room['id']}: {result['notes']}")
    return result


def reset(clear_handles: bool = False) -> dict:
    out = {'living': seed.reset(seed.HID, clear_handles=clear_handles)}
    for room in _owned_bedrooms():
        out[room['id']] = _seed(room)
    return out


def ensure() -> None:
    """Seed bedrooms that are missing or have no proposal. Never fails startup; the living room must stay up."""
    for room in _owned_bedrooms():
        if not db.one('SELECT 1 FROM proposals WHERE household_id = ?', room['household_id']):
            _seed(room)


def import_plan(data: bytes, mime: str, image_url: str, plan_width_m: float | None = None) -> dict:
    """Replace the floor plan from an image, then re-seed every bedroom at its new size. The living room's
    live demo scope keeps its own room geometry."""
    reads = floorplan.extract(data, mime)
    w, h = floorplan.image_size(data)
    built = floorplan.build_plan(reads, w, h, [mid for mid, _ in seed.MEMBERS], plan_width_m)
    names = dict(seed.MEMBERS)
    for r in built['rooms']:
        if r.get('owner_id'):
            r['label'], r['name'] = r['name'], f"{names[r['owner_id']]}'s bedroom"
    stored = {'name': f"Imported {sum(r['kind'] == 'bedroom' for r in built['rooms'])}-bedroom plan",
              'source': 'imported', 'image_url': image_url, **built}
    db.kv_set(PLAN_KEY, stored)
    seeded = {r['id']: _seed(r) for r in _owned_bedrooms()}
    return {'apartment': snapshot(), 'warnings': built['warnings'], 'seeded': seeded,
            'scale_m_per_px': built['scale_m_per_px']}


def restore_built_in() -> dict:
    with db.tx() as c:
        c.execute('DELETE FROM kv WHERE key = ?', (PLAN_KEY,))
    for room in _owned_bedrooms():
        _seed(room)
    return snapshot()


def _summary(hid: str) -> dict:
    p = core.current_proposal(hid)
    if not p:
        return {'proposal_version': None, 'status': 'empty', 'known_total_cents': 0, 'shares': {}, 'item_count': 0,
                'approvals_done': 0, 'approvals_needed': len(core.members(hid)), 'settled': False}
    return {'proposal_version': p['version'], 'status': p['status'], 'known_total_cents': p['known_total_cents'],
            'shares': p['shares'], 'item_count': len(p['items']),
            'approvals_done': sum(p['approvals'].values()), 'approvals_needed': len(p['approvals']),
            'settled': p['status'] == 'settled'}


def snapshot(aid: str = AID) -> dict:
    if aid != AID:
        raise KeyError(f'Unknown apartment {aid}')
    members = [{'id': mid, 'name': name} for mid, name in seed.MEMBERS]
    by_member = {m['id']: 0 for m in members}
    total = 0
    current = plan()
    out = []
    for r in current['rooms']:
        hid = r.get('household_id')
        entry = {'id': r['id'], 'name': r['name'], 'kind': r['kind'], 'shared': bool(r.get('shared')),
                 'owner_id': r.get('owner_id'), 'household_id': hid,
                 **{k: r[k] for k in ('x_m', 'z_m', 'width_m', 'depth_m')}, 'summary': None}
        if r.get('label'):
            entry['label'] = r['label']
        if r.get('interior_m'):
            entry['interior_m'] = r['interior_m']
        if hid and db.one('SELECT 1 FROM households WHERE id = ?', hid):
            scope_room = core.household(hid)['room']
            entry['room_m'] = {'width_m': scope_room['width_m'], 'depth_m': scope_room['depth_m']}
            entry['summary'] = _summary(hid)
            total += entry['summary']['known_total_cents']
            for mid, cents in entry['summary']['shares'].items():
                by_member[mid] = by_member.get(mid, 0) + cents
        out.append(entry)
    return {'id': AID, 'name': current['name'], 'source': current['source'], 'width_m': current['width_m'],
            'depth_m': current['depth_m'], 'image_url': current.get('image_url'),
            'image_frame_m': current.get('image_frame_m'), 'warnings': current.get('warnings', []),
            'members': members, 'rooms': out, 'totals': {'known_total_cents': total, 'by_member_cents': by_member}}
