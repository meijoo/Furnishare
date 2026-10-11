"""Product records: verified catalog, live search cache, fictional demo fixtures as a last resort."""
import hashlib
import json
import os
import re
import threading
import time
from pathlib import Path

import httpx

from . import config, db, forms
from .geometry import fits_room

LIVING_CATEGORIES = ('sofa', 'coffee_table', 'tv', 'rug')
BEDROOM_CATEGORIES = ('bed', 'nightstand', 'dresser', 'desk')
CATEGORIES = LIVING_CATEGORIES + BEDROOM_CATEGORIES
# Searchable / placeable extras. Not in default room needs, so auto-design does not add a chair or lamp to every plan.
PLACEABLE_CATEGORIES = CATEGORIES + ('chair', 'lamp')
VERIFIED = Path(os.getenv('RTR_CATALOG', config.DATA_DIR / 'catalog_verified.json'))
EXTRA = [Path(p) for p in os.getenv('RTR_CATALOG_EXTRA', str(config.DATA_DIR / 'catalog_bedroom.json')).split(os.pathsep) if p]
DEMO = config.BACKEND_DIR / 'catalog.json'

DEMO_EXTRAS = [
    {'id': 'demo-pebble-table', 'name': 'Pebble table', 'category': 'coffee_table', 'price_cents': 12000,
     'dimensions_m': {'width': 1.0, 'height': 0.42, 'depth': 0.55}, 'color_hex': '#C8A27A'},
    {'id': 'demo-lagoon-rug', 'name': 'Lagoon rug', 'category': 'rug', 'price_cents': 8000,
     'dimensions_m': {'width': 2.3, 'height': 0.015, 'depth': 1.6}, 'color_hex': '#7FC4C9'},
    {'id': 'demo-horizon-tv', 'name': 'Horizon television', 'category': 'tv', 'price_cents': 30000,
     'dimensions_m': {'width': 1.12, 'height': 0.7, 'depth': 0.22}, 'color_hex': '#2B2F36'},
    {'id': 'demo-fjord-bed', 'name': 'Fjord queen bed', 'category': 'bed', 'price_cents': 32000,
     'dimensions_m': {'width': 1.63, 'height': 1.0, 'depth': 2.13}, 'color_hex': '#D8C3A0'},
    {'id': 'demo-cove-bed', 'name': 'Cove full bed', 'category': 'bed', 'price_cents': 21000,
     'dimensions_m': {'width': 1.42, 'height': 0.9, 'depth': 2.0}, 'color_hex': '#8FB3CF'},
    {'id': 'demo-pine-nightstand', 'name': 'Pine nightstand', 'category': 'nightstand', 'price_cents': 6000,
     'dimensions_m': {'width': 0.45, 'height': 0.55, 'depth': 0.4}, 'color_hex': '#C9A97C'},
    {'id': 'demo-harbor-dresser', 'name': 'Harbor dresser', 'category': 'dresser', 'price_cents': 18000,
     'dimensions_m': {'width': 1.2, 'height': 0.8, 'depth': 0.48}, 'color_hex': '#E6DED1'},
    {'id': 'demo-studio-desk', 'name': 'Studio desk', 'category': 'desk', 'price_cents': 11000,
     'dimensions_m': {'width': 1.2, 'height': 0.75, 'depth': 0.6}, 'color_hex': '#B98F62'},
]
DEMO_COLORS = {'sofa-blue': '#6FA8C7', 'sofa-compact': '#7DB2CF', 'sofa-green': '#8CC28C'}

LIVE_KEY = 'live_products'

_lock = threading.Lock()
_cache = {'mtime': None, 'products': []}
_LIVE_TTL = 15 * 60
_live_cache: dict[str, tuple[float, list]] = {}
_http: httpx.Client | None = None


def _http_client() -> httpx.Client:
    global _http
    if _http is None:
        _http = httpx.Client(timeout=6.0)
    return _http


def _demo_products() -> list[dict]:
    raw = json.loads(DEMO.read_text()) + DEMO_EXTRAS
    out = []
    for p in raw:
        out.append({
            'id': p['id'], 'retailer': 'Fictional demo', 'retailer_product_id': p['id'], 'title': p['name'],
            'variant': 'default', 'category': p['category'], 'description': 'Fictional demo fixture, not a real listing.',
            'image_url': None, 'local_image': None, 'source_url': None, 'price_cents': p['price_cents'],
            'currency': 'USD', 'dimensions_m': p['dimensions_m'], 'dimension_kind': 'assembled', 'evidence': [],
            'retrieved_at': None, 'additional_costs': {'shipping_cents': None, 'tax_cents': None, 'assembly_cents': None},
            'source_type': 'demo',
            'style': {'color_hex': p.get('color_hex') or DEMO_COLORS.get(p['id'], '#9AB'), 'material': 'fabric', 'tags': []},
            'asset_url': None,
        })
    return out


def _normalize(p: dict) -> dict | None:
    if p.get('category') not in PLACEABLE_CATEGORIES or type(p.get('price_cents')) is not int:
        return None
    p = dict(p)
    p.setdefault('currency', 'USD')
    p.setdefault('style', {})
    p['style'].setdefault('color_hex', '#AAB')
    p['style'].setdefault('tags', [])
    p.setdefault('additional_costs', {'shipping_cents': None, 'tax_cents': None, 'assembly_cents': None})
    dims = p.get('dimensions_m')
    if p.get('dimension_kind') != 'assembled' or not dims or not all(
            isinstance(dims.get(k), (int, float)) and dims[k] > 0 for k in ('width', 'depth', 'height')):
        p['dimensions_m'] = None
    if p['category'] == 'rug' and p.get('local_image') and 'texture_path' not in p['style']:
        photo = config.STATIC_DIR / p['local_image']
        if photo.is_file():
            # Retailer rug photos are top-down shots on white; Blender trims the backdrop and prints them.
            p['style'] = {**p['style'], 'texture_path': str(photo), 'texture_mode': 'print'}
    p['asset_url'] = None
    return p


def _load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        return [n for n in map(_normalize, json.loads(path.read_text())) if n]
    except (ValueError, OSError):
        return []


def products() -> list[dict]:
    """The verified catalog plus extra verified files (bedroom). Categories with no verified listing use the
    fictional fixtures (source_type 'demo'); without a verified catalog, fixtures only."""
    with _lock:
        mtime = tuple(p.stat().st_mtime if p.exists() else 0 for p in [VERIFIED, *EXTRA, forms.FORMS_PATH])
        if _cache['mtime'] != mtime:
            items = _load(VERIFIED)
            if items:
                seen = {p['id'] for p in items}
                for path in EXTRA:
                    items += [p for p in _load(path) if p['id'] not in seen and not seen.add(p['id'])]
                have = {p['category'] for p in items}
                items += [p for p in _demo_products() if p['category'] not in have]
            else:
                items = _demo_products()
            read = forms.load()
            for p in items:
                if p['id'] in read and 'form' not in p['style']:
                    p['style'] = {**p['style'], 'form': forms.clean(p['category'], read[p['id']])}
            _cache.update(mtime=mtime, products=items)
        items = _cache['products']
    assets = db.kv_get('asset_urls', {})
    return [{**p, 'asset_url': assets.get(p['id'])} for p in items]


def _rememberable(p: dict) -> dict:
    q = dict(p)
    q.setdefault('retailer', 'Live')
    q.setdefault('variant', 'default')
    q.setdefault('description', None)
    q.setdefault('image_url', None)
    q.setdefault('local_image', None)
    q.setdefault('source_url', None)
    q.setdefault('price_cents', 0)
    q.setdefault('currency', 'USD')
    q.setdefault('source_type', 'live')
    q.setdefault('retrieved_at', None)
    q.setdefault('asset_url', None)
    if not q.get('variant'):
        q['variant'] = 'default'
    if not isinstance(q.get('price_cents'), int):
        q['price_cents'] = int(q['price_cents'] or 0)
    costs = q.get('additional_costs')
    q['additional_costs'] = dict(costs) if isinstance(costs, dict) else {
        'shipping_cents': None, 'tax_cents': None, 'assembly_cents': None}
    style = q.get('style')
    q['style'] = dict(style) if isinstance(style, dict) else {}
    guessed = infer_color(' '.join(str(q.get(k) or '') for k in ('title', 'description', 'variant')))
    current = q['style'].get('color_hex')
    if guessed and (not current or current in ('#AAB', '#9AB', '#AABBCC')):
        q['style']['color_hex'] = guessed
    else:
        q['style'].setdefault('color_hex', guessed or '#AABBCC')
    q['style'].setdefault('tags', [])
    return q


def remember(items: list[dict] | None) -> None:
    """Keep live/session products so catalog.get and proposals can use them."""
    store = db.kv_get(LIVE_KEY, {})
    for raw in items or []:
        if not raw or not raw.get('id'):
            continue
        store[raw['id']] = _rememberable(raw)
    db.kv_set(LIVE_KEY, store)


def clear_remembered() -> None:
    db.kv_set(LIVE_KEY, {})


def remembered() -> list[dict]:
    assets = db.kv_get('asset_urls', {})
    return [{**p, 'asset_url': p.get('asset_url') or assets.get(p['id'])} for p in db.kv_get(LIVE_KEY, {}).values()]


def get(product_id: str) -> dict | None:
    hit = next((p for p in products() if p['id'] == product_id), None)
    if hit:
        return hit
    store = db.kv_get(LIVE_KEY, {})
    if product_id in store:
        assets = db.kv_get('asset_urls', {})
        rec = store[product_id]
        return {**rec, 'asset_url': rec.get('asset_url') or assets.get(product_id)}
    from . import realize
    rec = realize.get(product_id)
    if rec and rec.get('product'):
        remember([rec['product']])
        return get(product_id)
    return None


def placeable(product: dict | None, room: dict | None = None) -> bool:
    if not product:
        return False
    dims = product.get('dimensions_m')
    if not dims or not all(isinstance(dims.get(k), (int, float)) and dims[k] > 0 for k in ('width', 'depth', 'height')):
        return False
    return True if room is None else fits_room(dims, room)


def eligible(category: str, room: dict, max_price_cents: int | None = None) -> list[dict]:
    """Hard constraints only: known price, confirmed assembled dimensions, fits the room."""
    out = []
    for p in products():
        if p['category'] != category or not fits_room(p['dimensions_m'], room):
            continue
        if max_price_cents is not None and p['price_cents'] > max_price_cents:
            continue
        out.append(p)
    return out


def design_pool(category: str, room: dict, max_price_cents: int | None = None,
                extra: list[dict] | None = None) -> list[dict]:
    """Verified catalog plus remembered live items that have placeable sizes."""
    seen, out = set(), []
    for p in list(products()) + remembered() + list(extra or []):
        pid = p.get('id')
        if not pid or pid in seen or p.get('category') != category or not placeable(p, room):
            continue
        if max_price_cents is not None and (p.get('price_cents') or 0) > max_price_cents:
            continue
        seen.add(pid)
        out.append(p)
    return out


def catalog_mode() -> str:
    ps = products()
    return 'verified' if ps and ps[0]['source_type'] == 'verified' else 'demo'


DEFAULT_DIMS = {
    'bed': {'width': 1.60, 'depth': 2.10, 'height': 1.00},
    'nightstand': {'width': 0.50, 'depth': 0.40, 'height': 0.55},
    'dresser': {'width': 1.20, 'depth': 0.50, 'height': 0.85},
    'desk': {'width': 1.20, 'depth': 0.60, 'height': 0.75},
    'sofa': {'width': 2.00, 'depth': 0.90, 'height': 0.85},
    'coffee_table': {'width': 1.10, 'depth': 0.60, 'height': 0.42},
    'rug': {'width': 2.00, 'depth': 1.40, 'height': 0.02},
    'tv': {'width': 1.20, 'depth': 0.12, 'height': 0.75},
    'chair': {'width': 0.70, 'depth': 0.75, 'height': 0.85},
    'lamp': {'width': 0.35, 'depth': 0.35, 'height': 0.58},
    'other': {'width': 0.80, 'depth': 0.80, 'height': 0.80},
}

LAMP_DIMS = {
    'table': {'width': 0.35, 'depth': 0.35, 'height': 0.58},
    'floor': {'width': 0.30, 'depth': 0.30, 'height': 1.55},
    'desk': {'width': 0.20, 'depth': 0.24, 'height': 0.46},
    'accent': {'width': 0.14, 'depth': 0.14, 'height': 0.28},
    'arc': {'width': 0.42, 'depth': 0.78, 'height': 1.80},
    'torchiere': {'width': 0.32, 'depth': 0.32, 'height': 1.82},
}


def lamp_kind_from_text(text: str) -> str | None:
    t = (text or '').lower()
    if re.search(r'\barc\b', t):
        return 'arc'
    if re.search(r'\btorchiere\b|\buplight\b', t):
        return 'torchiere'
    if re.search(r'\b(floor|standing) lamps?\b', t):
        return 'floor'
    if re.search(r'\b(desk|task) lamps?\b', t):
        return 'desk'
    if re.search(r'\b(accent|mini) lamps?\b', t):
        return 'accent'
    if re.search(r'\b(table|bedside|night) lamps?\b', t):
        return 'table'
    if re.search(r'\bfloor\b', t) and 'lamp' in t:
        return 'floor'
    return None


def default_dims_for(category: str, text: str = '') -> dict:
    if category == 'lamp':
        return dict(LAMP_DIMS.get(lamp_kind_from_text(text) or 'table'))
    return dict(DEFAULT_DIMS.get(category, DEFAULT_DIMS['other']))

_CATEGORY_WORDS = (
    ('bed', r'\b(beds?|mattress)\b'),
    ('nightstand', r'\b(nightstands?|night table|bedside)\b'),
    ('dresser', r'\b(dressers?|chest of drawers)\b'),
    ('lamp', r'\b((?:floor|table|desk|accent|arc|task)\s+)?lamps?\b|\btorchieres?\b|\blighting\b'),
    ('chair', r'\b((?:arm|accent|dining|lounge|side|office|desk)\s+)?chairs?\b|\barmchairs?\b'),
    ('desk', r'\bdesks?\b'),
    ('sofa', r'\b(sofas?|couch(?:es)?|sectionals?|loveseats?)\b'),
    ('coffee_table', r'\bcoffee tables?\b'),
    ('rug', r'\b(rugs?|carpets?)\b'),
    ('tv', r'\b(tvs?|televisions?)\b'),
)

_IN = 0.0254
_CM = 0.01
_NUM = r'(\d+(?:\.\d+)?)'
_UNIT_IN = r'(?:["”]|in(?:ch(?:es)?)?\.?)'
_UNIT_CM = r'(?:cm|centimet(?:er|re)s?)'


def _to_metres(value: float, unit: str) -> float:
    return value * (_CM if unit == 'cm' else _IN)


def parse_listing_dimensions(text: str | None, category: str = 'other') -> dict | None:
    """Assembled W×D×H in metres from listing text. None when no size is written."""
    if not text:
        return None
    t = (text.lower().replace('×', 'x').replace('–', '-').replace('—', '-')
         .replace('′', "'").replace('″', '"').replace('”', '"'))
    labeled = re.search(
        rf'w(?:idth)?\s*[:=]?\s*{_NUM}\s*(?:{_UNIT_IN}|{_UNIT_CM})?'
        rf'\s*[x,;/]\s*d(?:epth|eep)?\s*[:=]?\s*{_NUM}\s*(?:{_UNIT_IN}|{_UNIT_CM})?'
        rf'\s*[x,;/]\s*h(?:eight|t)?\s*[:=]?\s*{_NUM}\s*({_UNIT_IN}|{_UNIT_CM})',
        t)
    if labeled:
        unit = 'cm' if 'cm' in labeled.group(4) else 'in'
        return _dims(float(labeled.group(1)), float(labeled.group(2)), float(labeled.group(3)), unit)
    numbered = re.search(
        rf'{_NUM}\s*(?:{_UNIT_IN}|{_UNIT_CM})?\s*w(?:idth)?'
        rf'\s*[x,;/]\s*{_NUM}\s*(?:{_UNIT_IN}|{_UNIT_CM})?\s*d(?:epth|eep)?'
        rf'\s*[x,;/]\s*{_NUM}\s*({_UNIT_IN}|{_UNIT_CM})\s*h(?:eight|t)?',
        t)
    if numbered:
        unit = 'cm' if 'cm' in numbered.group(4) else 'in'
        return _dims(float(numbered.group(1)), float(numbered.group(2)), float(numbered.group(3)), unit)
    triple_in = re.search(
        rf'{_NUM}\s*{_UNIT_IN}\s*[xby/]\s*{_NUM}\s*{_UNIT_IN}\s*[xby/]\s*{_NUM}\s*{_UNIT_IN}', t)
    if triple_in:
        return _dims(float(triple_in.group(1)), float(triple_in.group(2)), float(triple_in.group(3)), 'in')
    triple_u = re.search(
        rf'{_NUM}\s*[xby/]\s*{_NUM}\s*[xby/]\s*{_NUM}\s*({_UNIT_IN}|{_UNIT_CM})', t)
    if triple_u:
        unit = 'cm' if 'cm' in triple_u.group(4) else 'in'
        return _dims(float(triple_u.group(1)), float(triple_u.group(2)), float(triple_u.group(3)), unit)
    pair = re.search(rf'{_NUM}\s*{_UNIT_IN}\s*[xby/]\s*{_NUM}\s*{_UNIT_IN}', t)
    if pair and category in ('bed', 'rug', 'tv'):
        height = DEFAULT_DIMS.get(category, DEFAULT_DIMS['other'])['height']
        w, d = _to_metres(float(pair.group(1)), 'in'), _to_metres(float(pair.group(2)), 'in')
        return {'width': round(w, 3), 'depth': round(d, 3), 'height': height}
    return None


def _dims(a: float, b: float, c: float, unit: str) -> dict | None:
    w, d, h = _to_metres(a, unit), _to_metres(b, unit), _to_metres(c, unit)
    if min(w, d, h) < 0.02 or max(w, d, h) > 6:
        return None
    # Listings sometimes send H×W×D; keep the smallest as height when it is clearly the short axis.
    return {'width': round(w, 3), 'depth': round(d, 3), 'height': round(h, 3)}


def _listing_text(item: dict) -> str:
    bits = [item.get('title'), item.get('snippet')]
    ext = item.get('extensions')
    if isinstance(ext, list):
        bits.extend(str(x) for x in ext)
    for key in ('rich_snippet', 'tag', 'delivery'):
        val = item.get(key)
        if isinstance(val, str):
            bits.append(val)
        elif isinstance(val, list):
            bits.extend(str(x) for x in val)
        elif isinstance(val, dict):
            bits.extend(str(v) for v in val.values() if isinstance(v, (str, int, float)))
    return ' '.join(b for b in bits if b)


def _product_specs(product_id: str) -> dict | None:
    """SerpAPI google_product specifications, if the listing has a product id."""
    if not product_id or not config.SHOPPING_API_KEY:
        return None
    try:
        r = httpx.get('https://serpapi.com/search.json', timeout=8, params={
            'engine': 'google_product', 'product_id': product_id, 'api_key': config.SHOPPING_API_KEY,
            'gl': 'us', 'hl': 'en'})
        r.raise_for_status()
    except httpx.HTTPError:
        return None
    blob = []
    data = r.json()
    specs = (data.get('product_results') or {}).get('specifications') or data.get('specifications') or []
    if isinstance(specs, dict):
        specs = specs.get('specifications') or specs.get('items') or []
    for block in specs if isinstance(specs, list) else []:
        if isinstance(block, dict):
            blob.append(str(block.get('name') or ''))
            blob.append(str(block.get('value') or ''))
            for row in block.get('specifications') or block.get('items') or []:
                if isinstance(row, dict):
                    blob.append(str(row.get('name') or ''))
                    blob.append(str(row.get('value') or ''))
        elif isinstance(block, str):
            blob.append(block)
    about = (data.get('product_results') or {}).get('description') or ''
    blob.append(about)
    return parse_listing_dimensions(' '.join(blob)) or parse_listing_dimensions(about)


def infer_category(text: str) -> str:
    t = (text or '').lower()
    for cat, pat in _CATEGORY_WORDS:
        if re.search(pat, t):
            return cat
    return 'other'


_COLOR_WORDS = (
    ('navy', '#1E3A5F'), ('forest', '#2F5D3A'), ('charcoal', '#3A3D42'), ('mustard', '#C4A035'),
    ('terracotta', '#C46A45'), ('blush', '#D48AA6'), ('cream', '#EFE6D4'), ('beige', '#D4C4A8'),
    ('ivory', '#F3EFE4'), ('walnut', '#6B4226'), ('oak', '#C4A06A'), ('pine', '#C9B48A'),
    ('brass', '#B39260'), ('gold', '#C4A15A'), ('silver', '#C0C4C8'), ('natural', '#C9B48A'),
    ('olive', '#6B7A3F'), ('sage', '#7A8F6A'), ('teal', '#2F7A73'), ('green', '#3F7A45'),
    ('blue', '#3B6FA0'), ('brown', '#6B4423'), ('tan', '#C4A574'), ('white', '#F4F0E8'),
    ('black', '#2A2B2E'), ('grey', '#8A8D91'), ('gray', '#8A8D91'), ('red', '#A33A32'),
    ('pink', '#D48AA6'), ('yellow', '#D4B44A'), ('orange', '#D2782A'), ('purple', '#6A4A8A'),
)


def infer_color(text: str) -> str | None:
    """Named colour from a listing title, so generated assets are not a generic beige."""
    t = (text or '').lower()
    for word, hex_color in _COLOR_WORDS:
        if re.search(rf'\b{word}\b', t):
            return hex_color
    return None


def live_search(query: str, limit: int = 16) -> list[dict]:
    """Google Shopping via SerpAPI, shaped like catalog products so they can be placed."""
    if not config.SHOPPING_API_KEY:
        return []
    key = (query or '').strip().lower()
    now = time.monotonic()
    hit = _live_cache.get(key)
    if hit and now - hit[0] < _LIVE_TTL:
        return hit[1][:limit]
    want = max(1, min(limit, 12))
    try:
        r = _http_client().get('https://serpapi.com/search.json', params={
            'engine': 'google_shopping', 'q': query, 'api_key': config.SHOPPING_API_KEY,
            'gl': 'us', 'hl': 'en', 'num': want})
        r.raise_for_status()
    except httpx.HTTPError:
        return []
    category = infer_category(query)
    dims = default_dims_for(category, query)
    data = r.json()
    raw = list(data.get('shopping_results') or []) + list(data.get('inline_shopping_results') or [])
    out = []
    for item in raw[:want]:
        title = item.get('title') or 'Item'
        url = item.get('product_link') or item.get('link') or title
        price = item.get('extracted_price')
        item_cat = infer_category(title)
        if item_cat == 'other':
            item_cat = category
        listed = parse_listing_dimensions(_listing_text(item), item_cat)
        kind = 'assembled' if listed else 'estimated'
        out.append({
            'id': 'live-' + hashlib.sha256(url.encode()).hexdigest()[:16],
            'retailer': item.get('source') or 'Google',
            'title': title,
            'category': item_cat,
            'description': item.get('snippet'),
            'image_url': item.get('thumbnail'),
            'source_url': item.get('product_link') or item.get('link'),
            'price_cents': round(price * 100) if isinstance(price, (int, float)) else 0,
            'currency': 'USD',
            'dimensions_m': listed or default_dims_for(item_cat, title + ' ' + query),
            'dimension_kind': kind,
            'source_type': 'live',
            'retrieved_at': db.now(),
        })
    _live_cache[key] = (now, out)
    return out[:limit]


_STOP = {'the', 'and', 'for', 'a', 'an', 'of', 'with'}
_CATEGORY_ALIASES = {
    'sofa': {'sofa', 'sofas', 'couch', 'couches', 'sectional', 'sectionals', 'loveseat', 'loveseats'},
    'bed': {'bed', 'beds', 'mattress'},
    'nightstand': {'nightstand', 'nightstands', 'bedside'},
    'dresser': {'dresser', 'dressers'},
    'desk': {'desk', 'desks'},
    'chair': {'chair', 'chairs', 'armchair', 'armchairs'},
    'lamp': {'lamp', 'lamps', 'lighting', 'torchiere', 'torchieres'},
    'coffee_table': {'coffee', 'table', 'tables'},
    'rug': {'rug', 'rugs', 'carpet', 'carpets'},
    'tv': {'tv', 'tvs', 'television', 'televisions'},
}


def _hay(product: dict) -> str:
    return ' '.join(str(product.get(k) or '') for k in ('title', 'category', 'retailer', 'description')).lower()


def _score(product: dict, tokens: list[str]) -> int:
    title = (product.get('title') or '').lower()
    hay = _hay(product)
    return sum(3 if t in title else 1 if t in hay else 0 for t in tokens)


def _style_tokens(tokens: list[str], category: str) -> list[str]:
    aliases = set(_STOP)
    for words in _CATEGORY_ALIASES.values():
        aliases |= words
    aliases.update({category, category.replace('_', '')})
    return [t for t in tokens if t not in aliases]


def _local_matches(query: str, category: str, tokens: list[str]) -> list[dict]:
    """Same-category catalog hits. Unknown types must match every token so 'green chair' is not dressers."""
    style = _style_tokens(tokens, category)
    local = []
    for p in products():
        hay = _hay(p)
        if category != 'other':
            if p.get('category') != category:
                continue
        elif tokens and not all(t in hay for t in tokens):
            continue
        local.append(p)
    if category != 'other' and style:
        styled = [p for p in local if any(t in _hay(p) for t in style)]
        if styled:
            local = styled
    local.sort(key=lambda p: (-_score(p, tokens), p.get('price_cents') or 0))
    return local


def search(query: str, limit: int = 20) -> list[dict]:
    """Live shopping first, then catalog items that actually match the query (same type / all tokens)."""
    q = (query or '').strip()
    if not q:
        return []
    category = infer_category(q)
    tokens = [t for t in re.findall(r"[a-z0-9']+", q.lower()) if t not in _STOP]
    live, seen = [], set()
    for p in live_search(q, limit=limit):
        title = (p.get('title') or '').lower()
        if not p.get('id') or title in seen or p['id'] in seen:
            continue
        if category != 'other' and p.get('category') not in (category, 'other'):
            continue
        seen.add(title)
        seen.add(p['id'])
        live.append(p)
    live.sort(key=lambda p: -_score(p, tokens))
    chosen = list(live)
    for p in _local_matches(q, category, tokens):
        title = (p.get('title') or '').lower()
        if not p.get('id') or p['id'] in seen or title in seen:
            continue
        seen.add(p['id'])
        seen.add(title)
        chosen.append(p)
    remember(chosen[:limit])
    return [_rememberable(p) for p in chosen[:limit]]


def design_query(category: str, style_text: str = '') -> str:
    label = category.replace('_', ' ')
    tokens = [t for t in re.findall(r"[a-z0-9']+", (style_text or '').lower())
              if t not in _STOP and t not in _CATEGORY_ALIASES.get(category, set())
              and t not in {'furnish', 'living', 'room', 'bedroom', 'keep', 'door', 'clear', 'just'}]
    return ' '.join(tokens[:6] + [label]).strip() or label


def candidates_for_design(category: str, room: dict, style_text: str = '',
                          max_price_cents: int | None = None) -> list[dict]:
    """Live listings for this category when shopping works; catalog fixtures only as a fallback."""
    found = search(design_query(category, style_text), limit=10)
    pool = [p for p in found if p.get('category') == category and placeable(p, room)]
    if max_price_cents is not None:
        pool = [p for p in pool if (p.get('price_cents') or 0) <= max_price_cents]
    if pool:
        return pool
    return design_pool(category, room, max_price_cents)
