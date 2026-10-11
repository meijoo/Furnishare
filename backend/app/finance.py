"""Authorized financial operations, executed one at a time against Nessie and reconciled from observed state.

States: authorized -> submitting -> pending | confirmed | failed | unknown.
An operation is persisted before submission; uncertain writes become 'unknown' and are reconciled, never blindly retried.
"""
import json
import logging
import threading
import time

from . import core, db, nessie
from .money import dollars

log = logging.getLogger('finance')
_wake = threading.Event()
SEED_BALANCE_CENTS = 200000


def _accounts() -> dict:
    return db.kv_get(f'nessie_accounts:{nessie.client().mode}', {})


def setup_accounts(hid: str) -> dict:
    """Create (once) a Nessie customer + checking account per member and a furniture merchant."""
    client = nessie.client()
    key = f'nessie_accounts:{client.mode}'
    existing = db.kv_get(key, {})
    for m in core.members(hid):
        if m['id'] in existing.get('members', {}):
            continue
        customer = client.create_customer(m['name'], 'Roommate')
        account = client.create_account(customer, f"{m['name']} checking (demo)", SEED_BALANCE_CENTS)
        existing.setdefault('members', {})[m['id']] = {'customer_id': customer, 'account_id': account}
        db.kv_set(key, existing)
    if 'merchant_id' not in existing:
        existing['merchant_id'] = client.create_merchant('RAG to Rooms Furniture (simulated)')
        db.kv_set(key, existing)
    return existing


def ops(hid: str) -> list[dict]:
    return db.all_('SELECT * FROM financial_ops WHERE household_id = ? ORDER BY authorized_at', hid)


def public_op(op: dict | None) -> dict | None:
    if not op:
        return None
    return {k: op[k] for k in ('op_key', 'kind', 'from_member', 'to_member', 'amount_cents', 'proposal_version',
                               'state', 'external_id', 'error', 'updated_at')} | {'simulator': nessie.client().mode}


def _next_key(c, base: str) -> tuple[str, dict | None]:
    """Reuse a live op for this action; only a definitively failed op allows a new attempt."""
    rows = c.execute("SELECT * FROM financial_ops WHERE op_key = ? OR op_key LIKE ? ORDER BY authorized_at",
                     (base, base + '#%')).fetchall()
    live = [dict(r) for r in rows if r['state'] != 'failed']
    if live:
        return live[-1]['op_key'], live[-1]
    return (base if not rows else f'{base}#{len(rows) + 1}'), None


def authorize_purchase(hid: str, mid: str, version: int, via: str = 'app') -> dict:
    h = core.household(hid)
    if mid != h['payer_id']:
        raise core.Forbidden('Only the designated payer can authorize the purchase')
    p = core.proposal(hid, version)
    cur = core.current_proposal(hid)
    if not p or not cur or cur['version'] != version:
        raise core.Conflict(f'v{version} is not the current proposal')
    if not core.fully_approved(p):
        raise core.Conflict(f'Everyone must approve v{version} before purchase')
    from . import planner
    if not core.purchase_locked(hid, version):
        revised = planner.recheck_prices(hid)
        if revised:
            raise core.Conflict(f"Prices changed since approval; v{revised['version']} needs everyone's approval first")
    with db.tx() as c:
        op_key, existing = _next_key(c, f'purchase:{hid}:v{version}')
        if existing:
            return existing
        c.execute('INSERT INTO financial_ops (op_key, household_id, kind, from_member, to_member, amount_cents, currency, '
                  'proposal_version, liability_id, authorized_by, authorized_at, authorized_via, state, updated_at) '
                  "VALUES (?, ?, 'purchase', ?, NULL, ?, 'USD', ?, NULL, ?, ?, ?, 'authorized', ?)",
                  (op_key, hid, mid, p['known_total_cents'], version, mid, db.now(), via, db.now()))
        db.log(c, hid, f"{core.names(hid)[mid]} authorized the simulated purchase of {dollars(p['known_total_cents'])}")
        db.bump(c, hid)
    _wake.set()
    return db.one('SELECT * FROM financial_ops WHERE op_key = ?', op_key)


def authorize_reimbursement(hid: str, liability_id: str, mid: str, via: str = 'app') -> dict:
    liab = db.one('SELECT * FROM liabilities WHERE id = ? AND household_id = ?', liability_id, hid)
    if not liab:
        raise KeyError(liability_id)
    if liab['from_member'] != mid:
        raise core.Forbidden('Only the roommate who owes this amount can authorize its reimbursement')
    with db.tx() as c:
        op_key, existing = _next_key(c, f'reimburse:{liability_id}')
        if existing:
            return existing
        c.execute('INSERT INTO financial_ops (op_key, household_id, kind, from_member, to_member, amount_cents, currency, '
                  'proposal_version, liability_id, authorized_by, authorized_at, authorized_via, state, updated_at) '
                  "VALUES (?, ?, 'transfer', ?, ?, ?, 'USD', ?, ?, ?, ?, ?, 'authorized', ?)",
                  (op_key, hid, mid, liab['to_member'], liab['amount_cents'], liab['version'], liability_id, mid,
                   db.now(), via, db.now()))
        names = core.names(hid)
        db.log(c, hid, f"{names[mid]} authorized a {dollars(liab['amount_cents'])} reimbursement to {names[liab['to_member']]}")
        db.bump(c, hid)
    _wake.set()
    return db.one('SELECT * FROM financial_ops WHERE op_key = ?', op_key)


def _set(op_key, **fields):
    op = db.one('SELECT household_id FROM financial_ops WHERE op_key = ?', op_key)
    fields['updated_at'] = db.now()
    with db.tx() as c:
        c.execute(f"UPDATE financial_ops SET {', '.join(f'{k} = ?' for k in fields)} WHERE op_key = ?",
                  (*fields.values(), op_key))
        db.bump(c, op['household_id'])


def _execute(op: dict) -> None:
    """Submit one authorized operation exactly once from this process."""
    client = nessie.client()
    hid = op['household_id']
    accts = _accounts()
    if op['from_member'] not in accts.get('members', {}) or (op['to_member'] and op['to_member'] not in accts['members']):
        try:
            accts = setup_accounts(hid)
        except (nessie.Uncertain, nessie.Rejected) as e:
            _set(op['op_key'], state='failed', error=f'Nessie account setup failed: {e}'[:300])
            return
    src = accts.get('members', {}).get(op['from_member'], {}).get('account_id')
    if not src:
        _set(op['op_key'], state='failed', error='No Nessie account for this member; run account setup')
        return
    # Revalidate immediately before execution: approval does not reserve funds or freeze the proposal.
    if op['kind'] == 'purchase':
        cur = core.current_proposal(hid)
        if not cur or cur['version'] != op['proposal_version'] or not core.fully_approved(cur):
            _set(op['op_key'], state='failed', error='Proposal changed or lost approval before execution')
            return
        if cur['known_total_cents'] != op['amount_cents']:
            _set(op['op_key'], state='failed', error='Amount no longer matches the approved proposal')
            return
    try:
        balance = client.balance_cents(src)
    except (nessie.Uncertain, nessie.Rejected) as e:
        balance = None
        log.warning('balance check failed: %s', e)
    if balance is not None and balance < op['amount_cents']:
        _set(op['op_key'], state='failed', error=f'Insufficient simulated balance ({dollars(balance)})')
        return
    description = f"RAG to Rooms [{op['op_key']}]"
    _set(op['op_key'], state='submitting')
    try:
        if op['kind'] == 'purchase':
            ext, status, body = client.create_purchase(src, accts['merchant_id'], op['amount_cents'], description)
        else:
            dst = accts['members'][op['to_member']]['account_id']
            ext, status, body = client.create_transfer(src, dst, op['amount_cents'], description)
    except nessie.Rejected as e:
        _set(op['op_key'], state='failed', error=str(e)[:300])
        return
    except nessie.Uncertain as e:
        _set(op['op_key'], state='unknown', error=f'Outcome uncertain, reconciling: {e}'[:300])
        return
    state = status if status in ('pending', 'confirmed', 'failed') else ('pending' if ext else 'unknown')
    _set(op['op_key'], state=state, external_id=ext, response_json=json.dumps(body)[:4000], error=None)
    _after_state_change(op['op_key'])


def reconcile(hid: str | None = None) -> int:
    """Re-observe pending/unknown operations. Returns how many changed."""
    client = nessie.client()
    accts = _accounts()
    rows = db.all_("SELECT * FROM financial_ops WHERE state IN ('pending', 'unknown')" +
                   (' AND household_id = ?' if hid else ''), *([hid] if hid else []))
    changed = 0
    for op in rows:
        src = accts.get('members', {}).get(op['from_member'], {}).get('account_id')
        if not src:
            continue
        try:
            found = client.find(op['kind'], src, op['external_id'], f"RAG to Rooms [{op['op_key']}]")
        except (nessie.Uncertain, nessie.Rejected) as e:
            log.warning('reconcile %s failed: %s', op['op_key'], e)
            continue
        if found is None:
            if op['state'] == 'unknown':
                _set(op['op_key'], error='Not found in Nessie yet; not retrying automatically')
            continue
        state = nessie.map_status(found.get('status'))
        if state == 'unknown':
            state = 'pending'
        if state != op['state'] or found.get('_id') != op['external_id']:
            _set(op['op_key'], state=state, external_id=found.get('_id'), error=None)
            changed += 1
            _after_state_change(op['op_key'])
    return changed


def _after_state_change(op_key: str) -> None:
    op = db.one('SELECT * FROM financial_ops WHERE op_key = ?', op_key)
    hid, v = op['household_id'], op['proposal_version']
    names = core.names(hid)
    with db.tx() as c:
        if op['kind'] == 'purchase' and op['state'] == 'confirmed':
            c.execute("UPDATE proposals SET status = 'purchased' WHERE household_id = ? AND version = ?", (hid, v))
            shares = c.execute('SELECT member_id, amount_cents FROM shares WHERE household_id = ? AND version = ?',
                               (hid, v)).fetchall()
            for s in shares:
                if s['member_id'] == op['from_member'] or s['amount_cents'] == 0:
                    continue
                lid = f"liab-{hid}-v{v}-{s['member_id']}"
                inserted = c.execute('INSERT OR IGNORE INTO liabilities VALUES (?, ?, ?, ?, ?, ?, ?)', (
                    lid, hid, v, s['member_id'], op['from_member'], s['amount_cents'], db.now())).rowcount
                if inserted:
                    core.queue_message(c, hid, s['member_id'], (
                        f"{names[op['from_member']]}'s simulated purchase for v{v} is confirmed. You owe "
                        f"{names[op['from_member']]} {dollars(s['amount_cents'])}. Reply SEND to authorize that "
                        f"reimbursement (simulated Nessie transfer)."), dedupe_key=f'reimburse-request:{lid}')
            db.log(c, hid, f'Simulated purchase confirmed by Nessie ({nessie.client().mode})')
            owed = c.execute('SELECT COUNT(*) AS n FROM liabilities WHERE household_id = ? AND version = ?',
                             (hid, v)).fetchone()['n']
            if owed == 0:
                c.execute("UPDATE proposals SET status = 'settled' WHERE household_id = ? AND version = ?", (hid, v))
                db.log(c, hid, f'v{v} is settled: {names[op["from_member"]]} paid the whole amount')
        elif op['kind'] == 'transfer' and op['state'] == 'confirmed':
            db.log(c, hid, f"{names[op['from_member']]}'s {dollars(op['amount_cents'])} reimbursement confirmed")
            open_liabs = c.execute(
                'SELECT COUNT(*) AS n FROM liabilities l WHERE household_id = ? AND version = ? AND NOT EXISTS ('
                "SELECT 1 FROM financial_ops f WHERE f.liability_id = l.id AND f.state = 'confirmed')", (hid, v)).fetchone()['n']
            if open_liabs == 0:
                c.execute("UPDATE proposals SET status = 'settled' WHERE household_id = ? AND version = ?", (hid, v))
                db.log(c, hid, f'v{v} is fully settled')
                for m in c.execute('SELECT id FROM members WHERE household_id = ?', (hid,)).fetchall():
                    core.queue_message(c, hid, m['id'], f'All reimbursements for v{v} are confirmed. The furniture plan is settled.',
                                       dedupe_key=f'settled:{hid}:v{v}:{m["id"]}')
        elif op['state'] == 'failed':
            db.log(c, hid, f"A simulated {op['kind']} failed: {op['error']}")
            core.queue_message(c, hid, op['from_member'], f"The simulated {op['kind']} of {dollars(op['amount_cents'])} "
                               f"failed: {op['error']}", dedupe_key=f'failed:{op_key}')
        db.bump(c, hid)


def worker_loop(stop: threading.Event) -> None:
    """Single serialized worker: execute authorized ops, then reconcile pending/unknown ones."""
    last_reconcile = 0.0
    while not stop.is_set():
        try:
            op = db.one("SELECT * FROM financial_ops WHERE state = 'authorized' ORDER BY authorized_at LIMIT 1")
            if op:
                _execute(op)
                continue
            if time.time() - last_reconcile > 3:
                reconcile()
                last_reconcile = time.time()
        except Exception:  # noqa: BLE001 - keep the worker alive, surface in logs
            log.exception('finance worker error')
        _wake.wait(1.0)
        _wake.clear()


def recover_on_startup() -> None:
    """An op left 'submitting' by a crash may or may not have reached Nessie."""
    for op in db.all_("SELECT op_key FROM financial_ops WHERE state = 'submitting'"):
        _set(op['op_key'], state='unknown', error='Process restarted mid-submission; reconciling')


def request_room_payment(hid: str, mid: str, version: int, request_id: str) -> dict:
    """Payer explicitly queues a room-scoped request; retries do not duplicate texts."""
    with db.tx() as c:
        h = core.household(hid)
        core.member(hid, mid)
        if mid != h['payer_id']:
            raise core.Forbidden('Only the payer may request room payments.')
        proposal = core.current_proposal(hid)
        if not proposal or proposal['version'] != version:
            raise core.Conflict('The room proposal has changed. Refresh before sending.')
        purchase = c.execute("SELECT 1 FROM financial_ops WHERE household_id=? AND proposal_version=? "
                             "AND kind='purchase' AND state='confirmed'", (hid, version)).fetchone()
        if not purchase:
            raise core.Conflict('Purchase the furniture before requesting payment.')
        recipients = [m for m in core.members(hid) if m['id'] != mid]
        if hid.startswith('grp_'):
            recipients = [m for m in recipients if c.execute(
                'SELECT 1 FROM room_budgets WHERE household_id=? AND member_id=?', (hid, m['id'])).fetchone()]
        if not recipients:
            raise core.Conflict('No other members have selected this room.')
        for member in recipients:
            user = c.execute('SELECT phone FROM users WHERE id=?', (member['id'],)).fetchone()
            if not member['handle'] and not (user and user['phone']):
                raise core.Conflict('Add phone numbers for all room members before sending.')
        from . import accounts, apartment
        group_id = accounts.group_for_room(hid)
        plan = accounts.apartment_snapshot(group_id) if group_id else apartment.snapshot('demo')
        room_name = next((r['name'] for r in plan['rooms'] if r.get('household_id') == hid), h['name'].removeprefix('Our '))
        room_name = room_name[0].upper() + room_name[1:]
        text = (f"{room_name}'s furniture is purchased! Please send your share to {core.names(hid)[mid]}. "
                "Open Furnishare's Budget tab and tap Pay.")
        for member in recipients:
            core.queue_message(c, hid, member['id'], text,
                               dedupe_key=f"room-payment:{hid}:v{version}:{request_id}:{member['id']}")
        db.log(c, hid, 'Payer requested payment from room members')
        db.bump(c, hid)
    return {'queued': len(recipients), 'message': text}
