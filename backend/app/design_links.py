"""Read-only furniture questions use saved design items, never a new search."""
import re
from urllib.parse import urlsplit
from . import catalog, core, db


def is_couch_question(text):
    if not re.search(r'\b(couches|couch|sofas?|loveseats?)\b', text, re.I):
        return False
    return bool(re.search(r'\b(considering|consider|chosen|picked|selected|current|in (?:our |the )?design|looking at)\b', text, re.I)
                or re.search(r'\b(show|see|view|links?|which|what)\b', text, re.I)) and not re.search(
                    r'\b(find|search|replace|swap|new|different|recommend)\b', text, re.I)


def safe_link(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    return value if parsed.scheme in ('http', 'https') and parsed.netloc else None


def reply(hid, text):
    if not is_couch_question(text):
        return None
    core.household(hid)
    proposal = core.current_proposal(hid)
    saved = db.kv_get(f'design-links:{hid}', {})
    removed = set(saved.get('removed_product_ids', [])) if proposal and saved.get('proposal_version') == proposal['version'] else set()
    products = []
    if proposal:
        products.extend(p for p in proposal['items'] if p['id'] not in removed)
    for item in core.scene_objects(hid):
        if item['product_id'] not in removed:
            product = catalog.get(item['product_id'])
            if product:
                products.append(product)
    products.extend(saved.get('items', []))
    products.extend({**item, 'source_url': item['url']} for item in db.kv_get(f'shared-furniture:{hid}', [])
                    if item.get('enabled', True))
    lines, seen = [], set()
    for product in products:
        if product.get('category') != 'sofa' or product['id'] in seen:
            continue
        seen.add(product['id'])
        link = safe_link(product.get('source_url'))
        lines.append(f"{product['title']}\n{link}" if link else f"{product['title']} — no shopping link is saved for this couch.")
    if not lines:
        return 'There are no couches in this room’s design yet. Add a couch in Furnishare and ask me again.'
    return 'Here are the couches in this room’s current design:\n\n' + '\n\n'.join(lines)
