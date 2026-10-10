"""Demo household: three roommates, one living room, a $600-ish sofa split three ways."""
import json

from . import catalog, config, core, db, planner
from .money import solve_split

HID = 'demo'
ROOM = {
    'width_m': 4.5, 'depth_m': 4.0, 'height_m': 2.5,
    'openings': [{'kind': 'door', 'wall': 'right', 'offset_m': 1.2, 'width_m': 0.9},
                 {'kind': 'window', 'wall': 'left', 'offset_m': 0.0, 'width_m': 1.4}],
    'clearances': [{'label': 'door swing', 'x_m': 1.8, 'z_m': 1.2, 'width_m': 0.9, 'depth_m': 0.9}],
}
MEMBERS = [('emily', 'Emily'), ('maya', 'Maya'), ('alex', 'Alex')]
# Emily and Maya told the agent privately they can each put in up to $200 for the sofa; Alex has not set a limit yet.
SEED_LIMITS = {'emily': 20000, 'maya': 20000, 'alex': None}
BUDGET_CENTS = 150000
STYLE = 'Light wood and blue accents'


def _handles() -> dict:
    path = config.DATA_DIR / 'members.json'
    return json.loads(path.read_text()) if path.exists() else {}


def demo_sofa() -> dict | None:
    sofas = [p for p in catalog.products() if p['category'] == 'sofa' and p['dimensions_m']]
    tagged = [p for p in sofas if 'demo-primary' in p['style'].get('tags', [])]
    if tagged:
        return tagged[0]
    near = sorted(sofas, key=lambda p: abs(p['price_cents'] - 60000))
    return near[0] if near else None


def reset(hid: str = HID, clear_handles: bool = False) -> dict:
    keep = {} if clear_handles else {
        m['id']: m['handle'] for m in db.all_('SELECT id, handle FROM members WHERE household_id = ?', hid)}
    handles = {**_handles(), **{k: v for k, v in keep.items() if v}}
    with db.tx() as c:
        version = (c.execute('SELECT state_version FROM households WHERE id = ?', (hid,)).fetchone() or {'state_version': 0})['state_version']
        for table in ('proposals', 'proposal_items', 'shares', 'decisions', 'scene_objects', 'liabilities',
                      'financial_ops', 'activity', 'members'):
            c.execute(f'DELETE FROM {table} WHERE household_id = ?', (hid,))
        c.execute("DELETE FROM outbound_jobs WHERE household_id = ? OR status IN ('pending', 'leased')", (hid,))
        c.execute('DELETE FROM households WHERE id = ?', (hid,))
        c.execute('INSERT INTO households (id, name, budget_cents, payer_id, state_version, room_json, needs_json, style_text) '
                  'VALUES (?, ?, ?, ?, ?, ?, ?, ?)', (hid, 'Our living room', BUDGET_CENTS, 'emily', version + 1,
                                                      json.dumps(ROOM), json.dumps(list(catalog.CATEGORIES)), STYLE))
        for mid, name in MEMBERS:
            c.execute('INSERT INTO members (household_id, id, name, handle, limit_cents) VALUES (?, ?, ?, ?, ?)',
                      (hid, mid, name, core.normalize_handle(handles[mid]) if handles.get(mid) else None, SEED_LIMITS[mid]))
        db.log(c, hid, 'Demo household created')
    catalog.clear_remembered()
    from . import nessie
    client = nessie.client()
    if client.mode == 'mock' and hasattr(client, 'reset'):
        client.reset()
        db.kv_set('nessie_accounts:mock', {})
    if config.SHOPPING_API_KEY:
        return {'ok': True, 'proposal_version': None, 'sofa': None, 'shares': {}, 'scene': []}
    sofa = demo_sofa()
    if not sofa:
        return {'ok': False, 'error': 'No sofa with confirmed dimensions in the catalog'}
    rest = planner.select_bundle(hid, ['coffee_table', 'tv', 'rug'], BUDGET_CENTS - sofa['price_cents'], STYLE)
    scene, _ = planner.layout([sofa] + (rest['products'] if rest['ok'] else []), core.household(hid)['room'])
    shares = solve_split(sofa['price_cents'], [m for m, _ in MEMBERS], SEED_LIMITS)
    p = core.create_proposal(hid, [sofa], shares,
                             f"The {sofa['title']} anchors the room; splitting it evenly.", scene=scene,
                             activity='Sofa proposal shared with the household')
    return {'ok': True, 'proposal_version': p['version'], 'sofa': sofa['id'], 'shares': shares,
            'scene': [o['product_id'] for o in scene]}
