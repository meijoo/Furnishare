"""Explicit room actions from linked members; authorization remains in finance."""
import hashlib
import json
import re
from . import core, db, finance, planner, design_links
from .money import dollars

BOUGHT = re.compile(r"^\s*(?:i(?:'ve| have)?\s+(?:already\s+)?(?:bought|purchased)|we\s+(?:bought|purchased))\s+(?:the\s+)?(?:proposal|furniture|room(?:'s furniture)?)(?:\s+v(\d+))?[.!\s]*$", re.I)
PAY = re.compile(r'^\s*pay(?:\s+v(\d+))?[.!\s]*$', re.I)
BUDGET = re.compile(r'\bbudget\b[^\d$+\-]{0,40}([+-]?\s*\$?\s*\d[\d,]*(?:\.\d+)?)', re.I)


def shared_links(hid):
    return db.kv_get(f'shared-furniture:{hid}', [])


def link_confirmation(count):
    return 'Added your furniture link' + ('s' if count > 1 else '') + ' to this room’s Design tab.'


def update_link(hid, link_id, enabled=None):
    core.household(hid)
    with db.tx() as c:
        saved = shared_links(hid)
        item = next((item for item in saved if item['id'] == link_id), None)
        if item is None:
            raise KeyError('Furniture link not found')
        if enabled is None:
            saved.remove(item)
        else:
            item['enabled'] = enabled
        c.execute('INSERT INTO kv VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                  (f'shared-furniture:{hid}', json.dumps(saved)))
        db.bump(c, hid)


def handle(hid, member, text):
    core.member(hid, member['id'])
    links = list(dict.fromkeys(url.rstrip('.,;!?)') for url in re.findall(r'https?://[^\s<>]+', text)))
    if links:
        links = [url for url in links if len(url) <= 4000 and design_links.safe_link(url)]
        if not links:
            return 'Please send a valid furniture shopping link.'
        from . import catalog, agent
        category = agent._focus_category(text, list(catalog.CATEGORIES)) or 'other'
        with db.tx() as c:
            saved = shared_links(hid)
            existing = {item['url'] for item in saved}
            for url in links:
                if url in existing:
                    continue
                product = next((p for p in catalog.products() + catalog.remembered() if p.get('source_url') == url), None)
                saved.append({'id': hashlib.sha256(url.encode()).hexdigest()[:24], 'url': url,
                              'title': product['title'] if product else 'Shared furniture',
                              'category': product['category'] if product else category,
                              'member_name': member['name'], 'enabled': True,
                              'image_url': (product.get('local_image') or product.get('image_url')) if product else None,
                              'price_cents': product.get('price_cents') if product else None})
            c.execute('INSERT INTO kv VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                      (f'shared-furniture:{hid}', json.dumps(saved)))
            db.log(c, hid, f"{member['name']} added furniture links to Design")
            db.bump(c, hid)
        if re.search(r'\b(like|prefer|want|vibe|style)\b', text, re.I):
            from . import invitations
            invitations.preference(hid, member, text)
        return link_confirmation(len(links))
    pay = PAY.fullmatch(text)
    if pay and member['id'] != core.household(hid)['payer_id']:
        liabilities = db.all_('SELECT * FROM liabilities WHERE household_id=? AND from_member=?', hid, member['id'])
        if pay.group(1):
            liabilities = [item for item in liabilities if item['version'] == int(pay.group(1))]
        pending = [item for item in liabilities if not db.one(
            "SELECT 1 FROM financial_ops WHERE liability_id=? AND state='confirmed'", item['id'])]
        if len(pending) > 1:
            return 'You have multiple payment requests. Pay in the app or reply PAY v followed by the proposal number.'
        if not pending:
            return 'Payment complete. Your share has already been paid.' if liabilities else 'There is no payment request waiting for you in this room.'
        operation = finance.authorize_reimbursement(hid, pending[0]['id'], member['id'], via='imessage-pay')
        if operation['state'] == 'confirmed':
            return 'Payment complete. Your simulated payment to the payer is confirmed.'
        return 'Payment authorized. I’ll confirm when your simulated payment to the payer is complete.'
    bought = BOUGHT.fullmatch(text) or pay
    if bought:
        proposal = core.current_proposal(hid)
        if not proposal:
            raise core.Conflict('There is no room proposal to buy yet.')
        version = int(bought.group(1)) if bought.group(1) else proposal['version']
        operation = finance.authorize_purchase(hid, member['id'], version, via='imessage', request_payment=True)
        if operation['state'] == 'confirmed':
            finance.send_auto_payment_request(hid, version, member['id'])
            return 'Payment complete. Your simulated purchase is confirmed. Room payment requests are processed automatically.'
        return 'Purchase authorized. Once it is confirmed, I’ll automatically ask the other room members to pay you.'
    budget = BUDGET.search(text)
    if budget:
        from decimal import Decimal
        number = budget.group(1).replace('$', '').replace(' ', '').strip()
        if not re.fullmatch(r'(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d{1,2})?', number):
            return 'Enter a budget of zero or more dollars, with at most two decimal places.'
        amount = int(Decimal(number.replace(',', '')) * 100)
        if amount > 50_000_000:
            raise ValueError('Enter a room budget of $500,000 or less.')
        core.set_limit(hid, member['id'], amount)
        if core.current_proposal(hid):
            planner.revise(hid, trigger='limit')
        return f'Your budget for this room is now {dollars(amount)}. The total room budget has been updated.'
    return None
