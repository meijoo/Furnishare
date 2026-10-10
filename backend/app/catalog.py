"""Product records: verified catalog first, fictional demo fixtures as a last resort, live search as evidence only."""
import json
import os
import threading
from pathlib import Path

import httpx

from . import config, db, forms
from .geometry import fits_room

LIVING_CATEGORIES = ('sofa', 'coffee_table', 'tv', 'rug')
BEDROOM_CATEGORIES = ('bed', 'nightstand', 'dresser', 'desk')
CATEGORIES = LIVING_CATEGORIES + BEDROOM_CATEGORIES
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

_lock = threading.Lock()
_cache = {'mtime': None, 'products': []}


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
    if p.get('category') not in CATEGORIES or type(p.get('price_cents')) is not int:
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


def get(product_id: str) -> dict | None:
    return next((p for p in products() if p['id'] == product_id), None)


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


def catalog_mode() -> str:
    ps = products()
    return 'verified' if ps and ps[0]['source_type'] == 'verified' else 'demo'


def live_search(query: str, limit: int = 8) -> list[dict]:
    """Google Shopping via SerpAPI. Results lack confirmed dimensions, so they are evidence only."""
    if not config.SHOPPING_API_KEY:
        return []
    try:
        r = httpx.get('https://serpapi.com/search.json', timeout=12, params={
            'engine': 'google_shopping', 'q': query, 'api_key': config.SHOPPING_API_KEY, 'gl': 'us', 'hl': 'en'})
        r.raise_for_status()
    except httpx.HTTPError:
        return []
    out = []
    for item in r.json().get('shopping_results', [])[:limit]:
        price = item.get('extracted_price')
        out.append({
            'title': item.get('title'), 'retailer': item.get('source'),
            'price_cents': round(price * 100) if isinstance(price, (int, float)) else None,
            'source_url': item.get('product_link') or item.get('link'), 'image_url': item.get('thumbnail'),
            'dimensions_m': None, 'source_type': 'live', 'retrieved_at': db.now(),
            'note': 'Live result: dimensions not confirmed, so it cannot enter the scale-aware layout.',
        })
    return out
