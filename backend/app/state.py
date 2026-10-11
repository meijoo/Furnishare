"""Room budgets are shared; legacy private-limit fields remain viewer-specific."""
from . import catalog, core, db, finance, geometry, textures


def snapshot(hid: str, viewer: str | None = None) -> dict:
    h = core.household(hid)
    ms = core.members(hid)
    p = core.current_proposal(hid)
    scene = core.scene_objects(hid)
    room = dict(h['room'])
    room['inspiration_image_url'] = '/uploads/' + h['inspiration_path'].rsplit('/', 1)[-1] if h['inspiration_path'] else None
    room['inspiration_description'] = (db.one('SELECT description FROM room_inspiration WHERE household_id=?', hid) or {}).get('description', '')
    room['inspiration_images'] = [{'id': r['id'], 'url': '/uploads/' + r['path'].rsplit('/', 1)[-1]}
                                  for r in db.all_('SELECT id,path FROM room_inspiration_images WHERE household_id=? ORDER BY created_at,id', hid)]
    members = []
    for m in ms:
        entry = {'id': m['id'], 'name': m['name'], 'is_payer': m['id'] == h['payer_id'], 'has_limit': m['limit_cents'] is not None,
                 'connected': bool(m['handle'] or db.one('SELECT phone FROM users WHERE id=?', m['id']))}
        saved = db.one('SELECT amount_cents FROM room_budgets WHERE household_id=? AND member_id=?', hid, m['id'])
        entry['contribution_budget_cents'] = saved['amount_cents'] if saved else (m['limit_cents'] if not hid.startswith('grp_') else None)
        if viewer == m['id']:
            entry['limit_cents'] = m['limit_cents']
        members.append(entry)
    proposal = None
    if p:
        proposal = {
            'version': p['version'], 'status': p['status'],
            'items': [{'product_id': i['id'], 'category': i['category'], 'title': i['title'], 'price_cents': i['price_cents'],
                       'source_type': i['source_type']} for i in p['items']],
            'known_total_cents': p['known_total_cents'], 'unknown_costs': p['unknown_costs'],
            'shares': p['shares'], 'approvals': p['approvals'],
            'objections': {m: d['reason'] or '' for m, d in p['decisions'].items() if d['decision'] == 'object'},
            'explanation': p['explanation'], 'created_at': p['created_at'],
        }
    ops = {}
    for o in finance.ops(hid):  # later attempts (op_key#n) replace earlier failed ones
        ops[o['op_key'].split('#')[0]] = o
    purchase = None
    reimbursements = []
    settled = False
    if p:
        purchase = finance.public_op(ops.get(f"purchase:{hid}:v{p['version']}"))
        for l in db.all_('SELECT * FROM liabilities WHERE household_id = ? AND version = ? ORDER BY from_member', hid, p['version']):
            reimbursements.append({'liability_id': l['id'], 'from_member': l['from_member'], 'to_member': l['to_member'],
                                   'amount_cents': l['amount_cents'],
                                   'operation': finance.public_op(ops.get(f"reimburse:{l['id']}"))})
        settled = p['status'] == 'settled'
    return {
        'household_id': hid,
        'state_version': h['state_version'],
        'members': members,
        'room': room,
        'budget_cents': (None if hid.startswith('grp_') and not db.one('SELECT 1 FROM room_budgets WHERE household_id=?', hid) else h['budget_cents']),
        'proposal': proposal,
        'scene': {'objects': textures.apply(hid, scene), 'validation': geometry.validate_scene(h['room'], scene),
                  'preview': db.kv_get(f'preview:{hid}')},
        'finance': {'payer_id': h['payer_id'], 'purchase': purchase, 'reimbursements': reimbursements, 'settled': settled,
                    'simulator': finance.nessie.client().mode},
        'catalog_mode': catalog.catalog_mode(),
        'activity': [{'at': a['at'], 'text': a['text']} for a in
                     db.all_('SELECT at, text FROM activity WHERE household_id = ? ORDER BY id DESC LIMIT 30', hid)],
    }
