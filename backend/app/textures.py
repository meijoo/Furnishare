"""Image textures on scene objects. A texture is attached to (household, object id) and survives product swaps:
the textured USDZ is keyed by product + image, built in the background, and used once it exists."""
import threading

from . import assets, catalog, config, db

KEY = 'object_textures'
MODES = ('print', 'tile')
_keys: dict[tuple, str | None] = {}
_lock = threading.Lock()


def _all() -> dict:
    return db.kv_get(KEY, {})


def get(hid: str, object_id: str) -> dict | None:
    return _all().get(hid, {}).get(object_id)


def put(hid: str, object_id: str, image_path: str, image_url: str, mode: str | None, tile_m: float | None) -> dict:
    entry = {'image_path': image_path, 'image_url': image_url, 'mode': mode, 'tile_m': tile_m}
    data = _all()
    data.setdefault(hid, {})[object_id] = entry
    db.kv_set(KEY, data)
    return entry


def delete(hid: str, object_id: str) -> bool:
    data = _all()
    found = data.get(hid, {}).pop(object_id, None) is not None
    if found:
        db.kv_set(KEY, data)
    return found


def clear(hid: str) -> None:
    data = _all()
    if data.pop(hid, None) is not None:
        db.kv_set(KEY, data)


def textured_product(product: dict, entry: dict) -> dict:
    style = dict(product.get('style') or {}, texture_path=entry['image_path'])
    if entry.get('mode'):
        style['texture_mode'] = entry['mode']
    if entry.get('tile_m'):
        style['texture_tile_m'] = entry['tile_m']
    return {**product, 'id': f"{product['id']}+tex", 'style': style}


def _key(product: dict) -> str | None:
    """Asset key of a textured product; memoized because the key hashes the image file."""
    style = product['style']
    k = (product['id'], style.get('texture_path'), style.get('texture_mode'), style.get('texture_tile_m'),
         str(product.get('dimensions_m')))
    with _lock:
        if k not in _keys:
            try:
                _keys[k] = assets.blender_assets.asset_key(product) if assets.blender_assets else None
            except Exception:  # noqa: BLE001
                _keys[k] = None
        return _keys[k]


def apply(hid: str, objects: list[dict]) -> list[dict]:
    """Adds `texture` to rugs that have one and swaps in the textured asset once it is built."""
    entries = _all().get(hid)
    if not entries:
        return objects
    for o in objects:
        if o.get('category') != 'rug':
            continue
        entry = entries.get(o['object_id'])
        if not entry:
            continue
        status = 'unavailable'
        product = catalog.get(o['product_id'])
        if product and assets.available():
            tp = textured_product({**product, 'dimensions_m': o['dimensions_m']}, entry)
            key = _key(tp)
            if key:
                tp['id'] = f"{product['id']}+tex-{key[:12]}"
            if key and (config.ASSETS_DIR / f'{key}.usdz').exists():
                o['asset_url'] = f'/assets/{key}.usdz'
                status = 'ready'
            elif key and assets.variant_failed(tp['id']):
                status = 'failed'
            elif key:
                assets.request_variant(tp, hid)
                status = 'building'
        o['texture'] = {'image_url': entry['image_url'], 'mode': entry.get('mode'), 'status': status}
    return objects
