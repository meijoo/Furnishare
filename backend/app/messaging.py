"""Inbound iMessage handling. Deterministic parsing first; Gemini only interprets free-form text.

Financial actions require explicit keywords (PAY, SEND) from the member who owns the money.
"""
import re
import time

from . import agent, core, db, finance, planner, invitations, design_links, photon_actions
from .money import dollars

HID = 'demo'
CATEGORY_WORDS = {'sofa': 'sofa', 'couch': 'sofa', 'loveseat': 'sofa', 'table': 'coffee_table', 'tv': 'tv',
                  'television': 'tv', 'rug': 'rug', 'carpet': 'rug'}
HELP = ('RAG to Rooms commands: YES / NO <reason> on a proposal, "my limit is $X", PAY (payer), SEND (reimburse), STATUS. '
        'Or describe what you want, e.g. "furnish our living room for $1500 with light wood and blue".')

LIMIT_RE = re.compile(r'(?:limit|max(?:imum)?|cap|only (?:afford|pay|do|spend)|can (?:afford|pay|do|spend)|up to|budget)'
                      r'[^$\d]{0,40}\$?\s*(\d{1,6}(?:\.\d{1,2})?)', re.I)
MONEY_RE = re.compile(r'\$\s*(\d{1,6}(?:\.\d{1,2})?)')
VERSION_RE = re.compile(r'\bv(\d+)\b', re.I)


def category_in(text: str) -> str | None:
    for word, cat in CATEGORY_WORDS.items():
        if re.search(rf'\b{word}s?\b', text, re.I):
            return cat
    return None


def cents(amount: str) -> int:
    whole, _, frac = amount.partition('.')
    return int(whole) * 100 + int((frac + '00')[:2])


def handle_inbound(event: dict) -> dict:
    started = time.perf_counter()
    with db.tx() as c:
        inserted = c.execute('INSERT OR IGNORE INTO inbound_events (event_id, sender_handle, conversation_id, text, received_at) '
                             'VALUES (?, ?, ?, ?, ?)', (event['event_id'], core.normalize_handle(event['sender_handle']),
                                                        event.get('conversation_id'), event['text'], event.get('received_at'))).rowcount
    if not inserted:
        return {'status': 'duplicate'}
    try:
        reply = (invitations.group_reply(event) if ';+;' in (event.get('conversation_id') or '')
                 else process(event['sender_handle'], event['text'].strip()))
    except (core.Conflict, core.Forbidden, ValueError, KeyError) as e:
        reply = f'Sorry, I could not do that: {e}'
    with db.tx() as c:
        if reply:
            core.queue_message(c, None, core.normalize_handle(event['sender_handle']), reply,
                               dedupe_key=f"reply:{event['event_id']}")
            if ';+;' in (event.get('conversation_id') or ''):
                c.execute('UPDATE outbound_jobs SET conversation_id = ? WHERE dedupe_key = ?',
                          (event['conversation_id'], f"reply:{event['event_id']}"))
        c.execute('UPDATE inbound_events SET processed_at = ?, result = ? WHERE event_id = ?',
                  (db.now(), (reply or '')[:500], event['event_id']))
    db.record_timing('inbound_message', (time.perf_counter() - started) * 1000)
    return {'status': 'accepted'}


def register(handle: str, text: str) -> str:
    m = re.match(r'^\s*(?:join|i am|i\'m|im|this is)\s+(\w+)', text, re.I)
    if not m:
        names = ', '.join(x['name'] for x in core.members(HID) if not x['handle'])
        return f'Hi! I coordinate a shared furnishing plan. Reply JOIN <your name> to link this number ({names or "no open seats"}).'
    want = m.group(1).lower()
    target = next((x for x in core.members(HID) if x['id'] == want or x['name'].lower() == want), None)
    if not target:
        return 'I could not find that roommate in the household.'
    if target['handle']:
        return f"{target['name']} is already linked to another number."
    with db.tx() as c:
        c.execute('UPDATE members SET handle = ? WHERE household_id = ? AND id = ?', (core.normalize_handle(handle), HID, target['id']))
        db.log(c, HID, f"{target['name']} linked iMessage")
        db.bump(c, HID)
    return f"Welcome, {target['name']}! Your limits stay private. Text me \"my limit is $X\" anytime. " + status_text(target['id'])


def pending_actions(mid: str) -> list[tuple[str, object]]:
    out = []
    h = core.household(HID)
    p = core.current_proposal(HID)
    if p and p['status'] == 'awaiting_approval' and not p['approvals'].get(mid):
        out.append(('approve', p['version']))
    if p and p['status'] == 'approved' and mid == h['payer_id'] and not core.purchase_locked(HID, p['version']):
        out.append(('pay', p['version']))
    for liab in db.all_('SELECT * FROM liabilities WHERE household_id = ? AND from_member = ?', HID, mid):
        op = db.one("SELECT state FROM financial_ops WHERE liability_id = ? AND state != 'failed'", liab['id'])
        if not op:
            out.append(('send', liab['id']))
    return out


def status_text(mid: str) -> str:
    p = core.current_proposal(HID)
    if not p:
        return 'No proposal yet.'
    who = core.names(HID)
    waiting = [who[m] for m, ok in p['approvals'].items() if not ok]
    line = (f"Proposal v{p['version']} ({p['status'].replace('_', ' ')}): "
            + ', '.join(f"{i['title']} {dollars(i['price_cents'])}" for i in p['items'])
            + f". Your share: {dollars(p['shares'].get(mid, 0))}.")
    if waiting:
        line += f" Waiting on: {', '.join(waiting)}."
    acts = pending_actions(mid)
    if acts:
        line += ' You can reply: ' + ', '.join({'approve': 'YES or NO', 'pay': 'PAY', 'send': 'SEND'}[a] for a, _ in acts) + '.'
    return line


def process(handle: str, text: str) -> str | None:
    m = core.member_by_handle(handle)
    if not m:
        account = db.one('SELECT id FROM users WHERE phone=?', core.normalize_handle(handle))
        if account:
            return 'Join or create a group in Furnishare first, then text your furniture preferences here.'
        invite = db.one('SELECT g.group_code,g.name FROM group_invitees i JOIN groups g ON g.id=i.group_id WHERE i.phone=? ORDER BY g.created_at DESC LIMIT 1', core.normalize_handle(handle))
        if invite:
            return f"Create an account in Furnishare, then join {invite['name']} with code {invite['group_code']} before sharing preferences."
        return register(handle, text)
    mid = m['id']
    action_reply = photon_actions.handle(m['household_id'], m, text)
    if action_reply is not None:
        return action_reply
    design_reply = design_links.reply(m['household_id'], text)
    if design_reply is not None:
        return design_reply
    if m['household_id'] != HID:
        if re.search(r'\b(limit|budget|pay|send|approve|reimburse|status)\b|\$', text, re.I):
            return 'Use this room in the app for limits, approvals, and payments.'
        return invitations.preference(m['household_id'], m, text)
    low = text.lower().strip()
    version_match = VERSION_RE.search(text)
    acts = pending_actions(mid)

    limit = LIMIT_RE.search(text)
    if limit:
        return apply_limit(mid, cents(limit.group(1)), category_in(text))
    if re.match(r'^(status|where are we|\?)\b', low):
        return status_text(mid)
    if re.match(r'^(help|commands)\b', low):
        return HELP
    if re.match(r'^(pay|authorize purchase|buy it|purchase)\b', low):
        pay = [a for a in acts if a[0] == 'pay']
        if not pay:
            return 'There is no purchase waiting for your authorization.' if mid != core.household(HID)['payer_id'] else \
                'The purchase can be authorized only after everyone approves the current proposal.'
        op = finance.authorize_purchase(HID, mid, pay[0][1], via='imessage')
        return f"Authorized. Submitting the simulated purchase of {dollars(op['amount_cents'])} to Nessie; I'll confirm when it posts."
    if re.match(r'^(send|reimburse|pay back|transfer)\b', low):
        sends = [a for a in acts if a[0] == 'send']
        if not sends:
            return 'You have no reimbursement waiting for authorization.'
        if len(sends) > 1:
            return 'You have several reimbursements pending; please authorize them in the app.'
        op = finance.authorize_reimbursement(HID, sends[0][1], mid, via='imessage')
        return f"Authorized. Sending the simulated {dollars(op['amount_cents'])} transfer through Nessie."
    if re.match(r'^(yes|y|yep|yeah|approve|approved|ok|okay|sounds good|agree|lgtm|👍)\b', low):
        approvals = [a for a in acts if a[0] == 'approve']
        if version_match:
            version = int(version_match.group(1))
        elif len(approvals) == 1:
            version = approvals[0][1]
        else:
            return ("There's nothing awaiting your approval. " + status_text(mid)) if not approvals else \
                'Which proposal? Reply YES v<number>.'
        p = core.decide(HID, version, mid, 'approve', via='imessage')
        rest = [core.names(HID)[x] for x, ok in p['approvals'].items() if not ok]
        return f"Approved v{version} with your {dollars(p['shares'][mid])} share." + (
            f" Waiting on {', '.join(rest)}." if rest else ' Everyone has approved.')
    if re.match(r'^(no|n|nope|object|reject|decline)\b', low):
        p = core.current_proposal(HID)
        if not p:
            return 'There is no proposal to object to.'
        version = int(version_match.group(1)) if version_match else p['version']
        reason = re.sub(r'^(no|n|nope|object|reject|decline)\b[\s,:-]*', '', text, flags=re.I) or None
        core.decide(HID, version, mid, 'object', reason=reason, via='imessage')
        money = MONEY_RE.search(reason or '')
        if money:
            return apply_limit(mid, cents(money.group(1)), category_in(reason or ''))
        result = planner.revise(HID, trigger='object', focus_category=category_in(reason or ''))
        return ('Noted. ' + result['message']) if result['ok'] else ('Noted your objection. ' + result['message'])

    intent = agent.interpret(text, status_text(mid))
    if intent:
        kind = intent.get('intent')
        if kind == 'set_limit' and intent.get('amount_dollars'):
            return apply_limit(mid, round(float(intent['amount_dollars']) * 100), intent.get('category'))
        if kind == 'approve':
            return process(handle, 'yes')
        if kind == 'object':
            return process(handle, 'no ' + (intent.get('reason') or ''))
        if kind == 'status':
            return status_text(mid)
        if kind == 'design_request':
            invitations.preference(HID, m, text)
            return agent.chat(HID, mid, text)['reply']
        if kind in ('authorize_purchase', 'authorize_reimbursement'):
            return 'To authorize money movement, reply with exactly PAY (purchase) or SEND (reimbursement).'
    return invitations.preference(m['household_id'], m, text)


def apply_limit(mid: str, limit_cents: int, category: str | None) -> str:
    core.set_limit(HID, mid, limit_cents, note=category)
    result = planner.revise(HID, trigger='limit', focus_category=category)
    private = f"Got it: your limit is {dollars(limit_cents)}. I'll keep that private. "
    if result.get('changed'):
        p = result['proposal']
        return private + f"{result['message']} Your share is now {dollars(p['shares'][mid])}; everyone will be asked to approve v{p['version']}."
    return private + result['message']


def claim(worker_id: str, limit: int = 10) -> list[dict]:
    """Lease pending outbound jobs for 60 s so a crashed adapter's jobs are retried by the next claim."""
    now = time.time()
    with db.tx() as c:
        rows = c.execute("SELECT * FROM outbound_jobs WHERE status = 'pending' OR (status = 'leased' AND lease_until < ?) "
                         'ORDER BY job_id LIMIT ?', (now, limit)).fetchall()
        for r in rows:
            c.execute("UPDATE outbound_jobs SET status = 'leased', lease_until = ?, worker_id = ? WHERE job_id = ?",
                      (now + 60, worker_id, r['job_id']))
    return [{'job_id': r['job_id'], 'to_handle': r['to_handle'], 'conversation_id': r['conversation_id'], 'text': r['text'], **db.kv_get(f"job-payload:{r['job_id']}", {}),
             'line_phone': db.kv_get(f"group:{r['conversation_id']}", {}).get('line_phone')}
            for r in rows]


def result(job_id: int, status: str, provider_message_id: str | None, error: str | None) -> None:
    if status not in ('sent', 'failed'):
        raise ValueError('status must be sent or failed')
    with db.tx() as c:
        c.execute('UPDATE outbound_jobs SET status = ?, provider_message_id = ?, error = ? WHERE job_id = ?',
                  (status, provider_message_id, error, job_id))
