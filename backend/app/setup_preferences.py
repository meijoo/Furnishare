"""Saved onboarding budgets and per-room inspiration, without generating proposals."""
import json

from . import accounts, apartment, core, db


def rooms(aid):
    plan = accounts.apartment_snapshot(aid) if aid.startswith('grp_') else apartment.snapshot(aid)
    return {r['household_id']: r for r in plan['rooms'] if r.get('household_id')}


def snapshot(aid, member_id):
    available = rooms(aid)
    saved = db.kv_get(f'setup:{aid}', {})
    return {'group_budget_cents': saved.get('group_budget_cents'),
            'individual_budget_cents': saved.get('individual_budgets', {}).get(member_id),
            'solo': saved.get('solo', False),
            'rooms': [{'household_id': hid, 'description': (db.one('SELECT description FROM room_inspiration WHERE household_id=?', hid) or {}).get('description', '')}
                      for hid in available if db.one('SELECT 1 FROM members WHERE household_id=? AND id=?', hid, member_id)]}


def save(aid, member_id, group_budget, individual_budget, solo, descriptions):
    available = rooms(aid)
    core.member(aid, member_id)
    if solo and len(core.members(aid)) != 1:
        raise ValueError('Solo setup requires a group with one member.')
    if individual_budget > group_budget:
        raise ValueError('Your individual budget must not exceed the group budget.')
    if not descriptions:
        raise ValueError('Select at least one room.')
    for hid in descriptions:
        if hid not in available:
            raise core.Forbidden('This room does not belong to your group.')
        core.member(hid, member_id)
        proposal = core.current_proposal(hid)
        if proposal and core.purchase_locked(hid, proposal['version']):
            raise core.Conflict('Finish the current purchase before changing setup.')
    with db.tx() as c:
        saved = db.kv_get(f'setup:{aid}', {})
        saved.update(group_budget_cents=group_budget, solo=solo)
        saved.setdefault('individual_budgets', {})[member_id] = individual_budget
        c.execute('INSERT INTO kv VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (f'setup:{aid}', json.dumps(saved)))
        # Allocate the overall caps across selected rooms so room plans cannot each use the full total.
        ordered = sorted(descriptions)
        for i, hid in enumerate(ordered):
            room_budget = group_budget // len(ordered) + (i < group_budget % len(ordered))
            member_budget = individual_budget // len(ordered) + (i < individual_budget % len(ordered))
            if not available[hid].get('shared'):
                room_budget = min(room_budget, member_budget)
            c.execute('UPDATE households SET budget_cents=? WHERE id=?', (room_budget, hid))
            c.execute('UPDATE members SET limit_cents=? WHERE household_id=? AND id=?', (member_budget, hid, member_id))
            description = descriptions[hid].strip()
            c.execute('INSERT INTO room_inspiration VALUES (?,?) ON CONFLICT(household_id) DO UPDATE SET description=excluded.description', (hid, description))
            c.execute('UPDATE households SET style_text=? WHERE id=?', (description, hid))
            db.log(c, hid, 'Budget and inspiration saved')
            db.bump(c, hid)
    return snapshot(aid, member_id)
