"""Each member funds only rooms they select; room budgets sum saved contributions."""
from . import accounts, apartment, core, db


def rooms(aid):
    plan = accounts.apartment_snapshot(aid) if aid.startswith('grp_') else apartment.snapshot(aid)
    return {r['household_id']: r for r in plan['rooms'] if r.get('household_id')}


def snapshot(aid, member_id):
    available = rooms(aid)
    result = []
    for hid in available:
        if not db.one('SELECT 1 FROM members WHERE household_id=? AND id=?', hid, member_id):
            continue
        saved = db.one('SELECT amount_cents,description FROM room_budgets WHERE household_id=? AND member_id=?', hid, member_id)
        result.append({'household_id': hid, 'budget_cents': saved['amount_cents'] if saved else None,
                       'description': saved['description'] if saved else ''})
    return {'rooms': result}


def save(aid, member_id, preferences):
    available = rooms(aid)
    core.member(aid, member_id)
    if not preferences:
        raise ValueError('Select at least one room.')
    with db.tx() as c:
        for hid in preferences:
            if hid not in available:
                raise core.Forbidden('This room does not belong to your group.')
            core.member(hid, member_id)
            proposal = core.current_proposal(hid)
            if proposal and core.purchase_locked(hid, proposal['version']):
                raise core.Conflict('Finish the current purchase before changing setup.')
        for hid, preference in preferences.items():
            description = preference.get('description')
            prior = db.one('SELECT description FROM room_budgets WHERE household_id=? AND member_id=?', hid, member_id)
            if description is None:
                description = prior['description'] if prior else ''
            c.execute('INSERT INTO room_budgets VALUES (?,?,?,?) ON CONFLICT(household_id,member_id) '
                      'DO UPDATE SET amount_cents=excluded.amount_cents,description=excluded.description',
                      (hid, member_id, preference['budget_cents'], description.strip()))
            c.execute('UPDATE members SET limit_cents=? WHERE household_id=? AND id=?',
                      (preference['budget_cents'], hid, member_id))
            total = c.execute('SELECT SUM(amount_cents) AS total FROM room_budgets WHERE household_id=?', (hid,)).fetchone()['total']
            c.execute('UPDATE households SET budget_cents=? WHERE id=?', (total, hid))
            notes = c.execute('SELECT m.name,b.description FROM room_budgets b JOIN members m '
                              'ON m.household_id=b.household_id AND m.id=b.member_id '
                              "WHERE b.household_id=? AND b.description!='' ORDER BY b.member_id", (hid,)).fetchall()
            combined = '\n\n'.join(f"{r['name']}: {r['description']}" for r in notes)
            c.execute('INSERT INTO room_inspiration VALUES (?,?) ON CONFLICT(household_id) '
                      'DO UPDATE SET description=excluded.description', (hid, combined))
            c.execute('UPDATE households SET style_text=? WHERE id=?', (combined, hid))
            db.log(c, hid, 'Room contribution and inspiration saved')
            db.bump(c, hid)
    return snapshot(aid, member_id)
