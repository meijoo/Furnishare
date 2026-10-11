"""Build a unique-looking USDZ for a live or owned item: read the photo, match form, bake a mesh."""
import hashlib
import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

from . import agent, assets, catalog, config, db, forms

log = logging.getLogger('rag_to_rooms.realize')
KEY = 'realized_products'
_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='realize')
_lock = threading.Lock()
_inflight: set[str] = set()

_SURFACE_WORDS = (
    ('velvet', 'velvet'), ('boucle', 'boucle'), ('chenille', 'chenille'), ('linen', 'linen'),
    ('leather', 'leather'), ('faux leather', 'faux_leather'), ('walnut', 'walnut'),
    ('white oak', 'white_oak'), ('oak', 'oak'), ('pine', 'pine'), ('marble', 'marble'),
    ('glass', 'glass'), ('wool', 'wool'), ('metal', 'brushed_metal'),
)


def get(product_id: str) -> dict | None:
    return db.kv_get(KEY, {}).get(product_id)


def snapshot(product_id: str) -> dict | None:
    rec = get(product_id)
    if not rec:
        return None
    url = rec.get('asset_url') or assets.cached_url(rec.get('product') or {}) or db.kv_get('asset_urls', {}).get(product_id)
    if url and rec.get('status') != 'ready':
        rec = {**rec, 'status': 'ready', 'asset_url': url}
        _store(product_id, rec)
    return _public(rec)


def infer_form(category: str, title: str) -> dict:
    """Cheap title cues so a mesh can diverge before Gemini finishes."""
    t = (title or '').lower()
    raw: dict = {}
    for word, surface in _SURFACE_WORDS:
        if word in t:
            raw['surface'] = surface
            break
    if category == 'sofa':
        if any(w in t for w in ('rolled', 'english roll', 'camelback')):
            raw['arm_style'] = 'rolled'
        elif any(w in t for w in ('tuxedo', 'track', 'square arm')):
            raw['arm_style'] = 'track'
        elif 'flared' in t:
            raw['arm_style'] = 'flared'
        elif 'sloped' in t:
            raw['arm_style'] = 'sloped'
        elif any(w in t for w in ('armless', 'no arm')):
            raw['arm_style'] = 'none'
        if 'channel' in t:
            raw['back_style'] = 'channel'
        elif any(w in t for w in ('tuft', 'button')):
            raw['back_style'] = 'tufted'
            raw['tufted_seat'] = True
        elif 'pillow' in t:
            raw['back_style'] = 'pillow'
        if any(w in t for w in ('loveseat', '2-seat', '2 seat', 'two seat')):
            raw['seat_cushions'] = 2
        elif any(w in t for w in ('3-seat', '3 seat', 'three seat', '3-seater')):
            raw['seat_cushions'] = 3
        if any(w in t for w in ('sectional', 'chaise')):
            raw['chaise'] = 'right'
        if 'skirt' in t:
            raw['skirt'] = True
        if any(w in t for w in ('overstuffed', 'cloud', 'plush', 'deep seat')):
            raw['arm_bulk'] = 'plump'
            raw['back_bulk'] = 'thick'
        elif any(w in t for w in ('mid-century', 'midcentury', 'tuxedo', 'slim', 'apartment')):
            raw['arm_bulk'] = 'slim'
            raw['back_bulk'] = 'thin'
        if any(w in t for w in ('low profile', 'low-profile', 'midcentury', 'mid-century')):
            raw['seat_rise'] = 'low'
            raw['arm_rise'] = 'low'
        if any(w in t for w in ('hairpin', 'metal leg')):
            raw['leg_style'] = 'metal'
        elif 'bun' in t:
            raw['leg_style'] = 'bun'
    elif category == 'bed':
        if 'wingback' in t:
            raw['headboard'] = 'wingback'
        elif 'channel' in t:
            raw['headboard'] = 'channel'
        elif 'tuft' in t:
            raw['headboard'] = 'tufted'
        elif 'slat' in t:
            raw['headboard'] = 'slatted'
        elif 'spindle' in t:
            raw['headboard'] = 'spindle'
        if 'storage' in t:
            raw['frame'] = 'storage'
        elif 'platform' in t:
            raw['frame'] = 'platform'
    elif category == 'desk':
        if 'trestle' in t:
            raw['leg_style'] = 'trestle'
        elif 'hairpin' in t:
            raw['leg_style'] = 'hairpin'
        if 'drawer' in t:
            raw['drawers'] = 2
    elif category == 'coffee_table':
        if 'hairpin' in t:
            raw['leg_style'] = 'hairpin'
        elif 'pedestal' in t:
            raw['leg_style'] = 'pedestal'
        elif 'glass' in t:
            raw['top_style'] = 'glass'
        if 'round' in t or 'circle' in t:
            raw['shape'] = 'round'
    elif category == 'rug' and 'fringe' in t:
        raw['fringe'] = True
    elif category == 'lamp':
        kind = catalog.lamp_kind_from_text(title)
        if kind:
            raw['kind'] = kind
        if 'mushroom' in t:
            raw['shade'] = 'mushroom'
        elif 'empire' in t:
            raw['shade'] = 'empire'
        elif re.search(r'\b(cone|coolie)\b', t):
            raw['shade'] = 'cone'
        elif re.search(r'\b(square|rectangular) shade\b', t):
            raw['shade'] = 'square'
        elif re.search(r'\bbell\b', t):
            raw['shade'] = 'bell'
        elif 'drum' in t:
            raw['shade'] = 'drum'
        elif re.search(r'\b(no shade|exposed bulb|edison)\b', t):
            raw['shade'] = 'none'
        if 'tripod' in t:
            raw['base'] = 'tripod'
        elif re.search(r'\b(gourd|ginger jar)\b', t):
            raw['base'] = 'gourd'
        elif 'sculpt' in t:
            raw['base'] = 'sculpted'
        elif re.search(r'\bdisc(us)?\b|\bdisk base\b', t):
            raw['base'] = 'disc'
        elif re.search(r'\bsquare base\b', t):
            raw['base'] = 'square'
        if re.search(r'\b(wide|oversized) shade\b', t):
            raw['shade_scale'] = 'large'
        elif re.search(r'\bnarrow shade\b', t):
            raw['shade_scale'] = 'small'
    return forms.clean(category, raw)


def start(body: dict, image_bytes: bytes | None = None, mime: str = 'image/jpeg') -> dict:
    pid = (body.get('id') or '').strip()
    if not pid:
        raise ValueError('id is required')
    existing = get(pid)
    if existing and existing.get('status') in ('ready', 'building'):
        return snapshot(pid) or _public(existing)
    title = body.get('title') or 'Item'
    category = body.get('category') or catalog.infer_category(title)
    if category not in forms.SCHEMA:
        category = catalog.infer_category(title)
    if category not in forms.SCHEMA:
        category = 'sofa'
    listed = catalog.parse_listing_dimensions(title, category) or catalog.parse_listing_dimensions(body.get('description'), category)
    raw_dims = listed or body.get('dimensions_m') or catalog.default_dims_for(category, title)
    dims = _clamp_dims(category, raw_dims)
    dimension_kind = 'assembled' if listed else ('estimated' if not body.get('dimensions_m') else 'assembled')
    form = infer_form(category, title)
    image_path = _write_image(pid, image_bytes, mime) if image_bytes else None
    if image_path is None:
        image_path = _download(pid, body.get('image_url'))
    style = {'form': form}
    if form.get('primary_hex'):
        style['color_hex'] = form['primary_hex']
    if image_path and category == 'rug':
        style['texture_path'] = str(image_path)
        style['texture_mode'] = 'print'
        style['texture_tile_m'] = 0.5
    product = {
        'id': pid, 'title': title, 'category': category, 'retailer': body.get('retailer') or 'Live',
        'price_cents': body.get('price_cents') or 0, 'dimensions_m': dims, 'dimension_kind': dimension_kind,
        'image_url': body.get('image_url'), 'source_url': body.get('source_url'), 'style': style,
        'local_image': str(image_path.relative_to(config.STATIC_DIR)) if image_path else None,
    }
    rec = {'id': pid, 'status': 'building', 'asset_url': assets.cached_url(product), 'form': form,
           'product': product, 'image_path': str(image_path) if image_path else None}
    if rec['asset_url']:
        rec['status'] = 'ready'
    _store(pid, rec)
    catalog.remember([product])
    if rec['status'] != 'ready':
        with _lock:
            if pid not in _inflight:
                _inflight.add(pid)
                _pool.submit(_job, pid)
    return _public(rec)


def _job(pid: str) -> None:
    try:
        rec = get(pid)
        if not rec:
            return
        product = rec['product']
        image_path = rec.get('image_path')
        if image_path and agent.available() and product['category'] in forms.SCHEMA:
            try:
                read = forms.read_photo({
                    'category': product['category'], 'title': product.get('title', ''),
                    'local_image': product.get('local_image') or str(Path(image_path).relative_to(config.STATIC_DIR)),
                })
                form = {**((product.get('style') or {}).get('form') or {}), **read}
                product.setdefault('style', {})['form'] = form
                if form.get('primary_hex'):
                    product['style']['color_hex'] = form['primary_hex']
                rec['form'] = form
            except Exception as exc:  # noqa: BLE001
                log.warning('form read failed for %s: %s', pid, exc)
        if product.get('dimension_kind') != 'assembled' and image_path and agent.available():
            try:
                read_dims = forms.read_dimensions({
                    'title': product.get('title', ''),
                    'local_image': product.get('local_image') or str(Path(image_path).relative_to(config.STATIC_DIR)),
                })
                if read_dims:
                    product['dimensions_m'] = _clamp_dims(product['category'], read_dims)
                    product['dimension_kind'] = 'assembled'
            except Exception as exc:  # noqa: BLE001
                log.warning('dimension read failed for %s: %s', pid, exc)
        url = assets.cached_url(product)
        if not url and assets.available():
            path = assets.blender_assets.ensure_asset(product, config.ASSETS_DIR) if assets.blender_assets else None
            if path:
                url = f'/assets/{path.name}'
                assets._attach(product['id'], url)
        rec['product'] = product
        rec['asset_url'] = url
        rec['status'] = 'ready' if url else 'placeholder'
        _store(pid, rec)
    finally:
        with _lock:
            _inflight.discard(pid)


def _clamp_dims(category: str, dims: dict) -> dict:
    ranges = {
        'bed': {'width': (0.6, 2.2), 'depth': (1.2, 2.4), 'height': (0.2, 1.4)},
        'nightstand': {'width': (0.2, 1.0), 'depth': (0.2, 0.8), 'height': (0.2, 1.0)},
        'dresser': {'width': (0.4, 2.6), 'depth': (0.25, 0.9), 'height': (0.3, 1.8)},
        'desk': {'width': (0.5, 2.6), 'depth': (0.3, 1.4), 'height': (0.4, 1.3)},
        'sofa': {'width': (0.8, 3.2), 'depth': (0.5, 1.4), 'height': (0.4, 1.3)},
        'coffee_table': {'width': (0.3, 2.0), 'depth': (0.3, 1.4), 'height': (0.2, 0.7)},
        'rug': {'width': (0.5, 4.0), 'depth': (0.5, 3.0), 'height': (0.003, 0.08)},
        'tv': {'width': (0.4, 2.2), 'depth': (0.04, 0.4), 'height': (0.25, 1.2)},
        'chair': {'width': (0.35, 1.1), 'depth': (0.4, 1.1), 'height': (0.4, 1.3)},
        'lamp': {'width': (0.08, 0.8), 'depth': (0.08, 0.8), 'height': (0.2, 2.2)},
    }.get(category, {'width': (0.2, 3.0), 'depth': (0.2, 2.0), 'height': (0.05, 2.0)})
    out = {}
    for axis in ('width', 'depth', 'height'):
        lo, hi = ranges[axis]
        try:
            value = float(dims[axis])
        except (KeyError, TypeError, ValueError):
            value = catalog.DEFAULT_DIMS.get(category, catalog.DEFAULT_DIMS['other'])[axis]
        out[axis] = min(hi, max(lo, value))
    return out


def _write_image(pid: str, data: bytes, mime: str) -> Path | None:
    if not data:
        return None
    suffix = '.png' if 'png' in (mime or '') else '.jpg'
    path = config.UPLOADS_DIR / f'realize-{hashlib.sha256(pid.encode()).hexdigest()[:16]}{suffix}'
    path.write_bytes(data)
    return path


def _download(pid: str, url: str | None) -> Path | None:
    if not url or not url.startswith(('http://', 'https://')):
        return None
    try:
        r = httpx.get(url, timeout=12, follow_redirects=True)
        r.raise_for_status()
    except httpx.HTTPError as exc:
        log.warning('image download failed for %s: %s', pid, exc)
        return None
    mime = r.headers.get('content-type', 'image/jpeg')
    return _write_image(pid, r.content, mime)


def _store(pid: str, rec: dict) -> None:
    data = db.kv_get(KEY, {})
    data[pid] = rec
    db.kv_set(KEY, data)


def _public(rec: dict) -> dict:
    form = rec.get('form') or {}
    product = rec.get('product') or {}
    return {
        'id': rec['id'],
        'status': rec.get('status') or 'building',
        'asset_url': rec.get('asset_url'),
        'form': form,
        'color_hex': product.get('style', {}).get('color_hex') or form.get('primary_hex'),
        'dimensions_m': product.get('dimensions_m'),
        'dimension_kind': product.get('dimension_kind'),
    }
