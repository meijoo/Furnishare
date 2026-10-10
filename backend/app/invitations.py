"""Durable invitations and room-bound, non-financial group preferences."""
import json
import re
import secrets

from . import agent, catalog, core, db, planner, ranking, accounts


def create(hid, members, request_id):
    core.household(hid)
    if accounts.group_for_room(hid):
        return create_account_invitation(hid, members, request_id)
    key = f'invitation-request:{hid}:{request_id}'
    existing = db.kv_get(key)
    if existing:
        return get(existing)
    known = {m['id'] for m in core.members(hid)}
    ids = [m['member_id'] for m in members]
    phones = [m['phone'].strip() for m in members]
    if len(phones) < 2 or len(set(phones)) != len(phones) or len(set(ids)) != len(ids):
        raise ValueError('Choose at least two different roommates with distinct phone numbers, including yourself.')
    if any(mid not in known for mid in ids):
        raise ValueError('Every invited roommate must belong to this room.')
    if any(not re.fullmatch(r'\+[1-9]\d{7,14}', phone) for phone in phones):
        raise ValueError('Use international phone numbers, such as +15551234567.')
    token = secrets.token_urlsafe(24)
    with db.tx() as c:
        # Recheck under the write lock to make repeated requests idempotent.
        prior = c.execute('SELECT value FROM kv WHERE key = ?', (key,)).fetchone()
        if prior:
            return get(json.loads(prior['value']))
        for _ in range(100):
            code = f'{secrets.randbelow(1000000):06d}'
            if (not c.execute('SELECT 1 FROM kv WHERE key = ?', (f'group-code:{code}',)).fetchone()
                    and not c.execute('SELECT 1 FROM groups WHERE group_code=?', (code,)).fetchone()):
                break
        else:
            raise ValueError('Could not allocate a group code; try again.')
        for mid, phone in zip(ids, phones):
            conflict = c.execute('SELECT household_id, id FROM members WHERE handle = ?', (phone,)).fetchone()
            if conflict and (conflict['household_id'], conflict['id']) != (hid, mid):
                raise ValueError('A phone number is already linked to another member.')
            c.execute('UPDATE members SET handle = ? WHERE household_id = ? AND id = ?', (phone, hid, mid))
        job_ids = []
        for mid, phone in zip(ids, phones):
            cursor = c.execute("INSERT INTO outbound_jobs (household_id, to_handle, text, dedupe_key, status, created_at) VALUES (?, ?, ?, ?, 'pending', ?)",
                               (hid, phone, f'Welcome to Furnishare! Your group code is {code}. Open Furnishare, choose Join a group, and enter this six-digit code.\nReply here with furniture links and the vibe you want. Your ideas will appear in our shared room in the app.', f'invite:{token}:{mid}', db.now()))
            job_ids.append(cursor.lastrowid)
        value = {'token': token, 'household_id': hid, 'group_code': code,
                 'job_id': job_ids[0], 'job_ids': job_ids, 'member_ids': ids}
        for k, v in [(key, token), (f'group-code:{code}', token), (f'invitation:{token}', value)]:
            c.execute('INSERT INTO kv (key, value) VALUES (?, ?)', (k, json.dumps(v)))
        db.bump(c, hid)
    return get(token)


def create_account_invitation(hid, members, request_id):
    gid = accounts.group_for_room(hid)
    group = accounts.snapshot(gid)
    key = f'invitation-request:{hid}:{request_id}'
    token = secrets.token_urlsafe(24)
    phones = [core.normalize_handle(m['phone']) for m in members]
    if not phones or len(set(phones)) != len(phones) or any(not re.fullmatch(r'\+[1-9][0-9]{7,14}', phone) for phone in phones):
        raise ValueError('Enter distinct international phone numbers.')
    with db.tx() as c:
        prior = c.execute('SELECT value FROM kv WHERE key=?', (key,)).fetchone()
        if prior:
            return get(json.loads(prior['value']))
        jobs, labels = [], []
        for index, (member, phone) in enumerate(zip(members, phones)):
            mid = member.get('member_id')
            if mid:
                account = c.execute('SELECT u.* FROM users u JOIN group_members gm ON gm.user_id=u.id WHERE gm.group_id=? AND u.id=?', (gid, mid)).fetchone()
                if not account or account['phone'] != phone:
                    raise ValueError('A registered member must use their account phone number.')
                label = account['name']
            else:
                label = member.get('name', '').strip() or f'Roommate {index + 1}'
            c.execute('INSERT INTO group_invitees VALUES (?,?,?) ON CONFLICT(group_id,phone) DO UPDATE SET name=excluded.name', (gid, phone, label))
            cursor = c.execute("INSERT INTO outbound_jobs (household_id,to_handle,text,dedupe_key,status,created_at) VALUES (?,?,?,?,'pending',?)",
                               (hid, phone, f"Join {group['name']} in Furnishare! Your group code is {group['group_code']}. Create an account, choose Join a group, and enter this code. Reply here with furniture preferences after joining.", f'invite:{token}:{index}', db.now()))
            jobs.append(cursor.lastrowid)
            labels.append(label)
        value = {'token': token, 'household_id': hid, 'group_code': group['group_code'],
                 'job_id': jobs[0], 'job_ids': jobs, 'recipient_names': labels}
        for k, v in [(key, token), (f'invitation:{token}', value)]:
            c.execute('INSERT INTO kv VALUES (?,?)', (k, json.dumps(v)))
    return get(token)


def get(token):
    invitation = db.kv_get(f'invitation:{token}')
    if not invitation:
        raise KeyError('Invitation')
    job_ids = invitation.get('job_ids', [invitation['job_id']])
    jobs = [db.one('SELECT status, error FROM outbound_jobs WHERE job_id = ?', job_id) for job_id in job_ids]
    if any(job is None for job in jobs):
        raise KeyError('Invitation expired after demo reset')
    statuses = [job['status'] for job in jobs]
    if all(status == 'sent' for status in statuses):
        status = 'sent'
    elif any(status in ('pending', 'leased') for status in statuses):
        status = 'pending'
    elif any(status == 'sent' for status in statuses):
        status = 'partial'
    else:
        status = 'failed'
    names = core.names(invitation['household_id'])
    labels = invitation.get('recipient_names') or [names.get(mid, 'Roommate') for mid in invitation.get('member_ids', [''] * len(jobs))]
    recipients = [{'member_name': label, **job} for label, job in zip(labels, jobs)]
    errors = [f"{r['member_name']}: {r['error']}" for r in recipients if r['error']]
    return {k: invitation[k] for k in ('token', 'household_id', 'job_id')} | {
        'group_code': invitation.get('group_code'), 'job_ids': job_ids,
        'status': status, 'error': '; '.join(errors) or None, 'recipients': recipients,
    }


def join(code):
    if not re.fullmatch(r'[0-9]{6}', code):
        raise ValueError('Enter exactly six digits.')
    token = db.kv_get(f'group-code:{code}')
    if not token:
        raise KeyError('Group code not found. Ask your roommate to check the code.')
    invitation = get(token)
    household = core.household(invitation['household_id'])
    return {'household_id': household['id'], 'group_name': household['name'], 'group_code': code}


def bind(job_id, conversation_id, line_phone):
    payload = db.kv_get(f'job-payload:{job_id}')
    if not payload or not conversation_id or ';+;' not in conversation_id:
        raise ValueError('Group invitation result requires a group conversation id.')
    invitation = db.kv_get(f"invitation:{payload['invitation_token']}")
    db.kv_set(f'group:{conversation_id}', {'household_id': invitation['household_id'],
                                         'participants': payload['participants'], 'line_phone': line_phone})


def suggestions(hid):
    core.household(hid)
    return db.kv_get(f'suggestions:{hid}', [])


def preference(hid, member, text):
    links = list(dict.fromkeys(link.rstrip('.,;!?)') for link in re.findall(r'https?://[^\s<>]+', text)))
    h = core.household(hid)
    records = suggestions(hid)
    context = '\n'.join([r['text'] for r in records[-19:]] + [text])
    categories = agent.parse_request(text, agent.room_categories(h))['categories']
    products = []
    for category in categories:
        ranked, _ = ranking.rank(catalog.eligible(category, h['room']), planner.room_image(h), style_text=context)
        products.extend({'title': p['title'], 'source_url': p.get('source_url'), 'product_id': p['id'],
                         'source_type': p['source_type']} for p, _ in ranked[:2])
    products += catalog.live_search(text, limit=3)
    record = {'id': secrets.token_hex(8), 'member_name': member['name'], 'text': text,
              'links': links, 'products': products}
    with db.tx() as c:
        current = c.execute('SELECT value FROM kv WHERE key = ?', (f'suggestions:{hid}',)).fetchone()
        records = json.loads(current['value']) if current else []
        records = (records + [record])[-50:]
        c.execute('INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                  (f'suggestions:{hid}', json.dumps(records)))
        c.execute('UPDATE households SET style_text = ? WHERE id = ?', (context, hid))
        db.log(c, hid, f"{member['name']} shared furniture preferences; suggestions updated")
        db.bump(c, hid)
    picks = '\n'.join(p['title'] + (f" — {p['source_url']}" if p.get('source_url') else '') for p in products[:3] if p.get('title'))
    return f'Saved your preferences{" and furniture links" if links else ""} in the app. ' + (f'Suggestions:\n{picks}' if picks else 'Share more details about the furniture you want.')


def group_reply(event):
    group = db.kv_get(f"group:{event.get('conversation_id')}")
    if not group:
        return None
    member = core.member_by_handle(event['sender_handle'])
    if not member or member['household_id'] != group['household_id'] or core.normalize_handle(event['sender_handle']) not in group['participants']:
        return 'Please ask the group creator to invite your phone number through the app.'
    text = event['text'].strip()
    if (re.search(r'\b(limit|budget|cap)\b|\$', text, re.I)
            or re.match(r'^(pay|send|reimburse|approve|yes|no|status)\s*(?:v\d+)?[.!?]*$', text, re.I)):
        return 'Please text me privately for budgets, limits, approvals, and payments. Share furniture preferences and links here.'
    return preference(group['household_id'], member, text)
