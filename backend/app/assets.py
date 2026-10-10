"""Background USDZ builds through integrations/blender_mcp. The scene shows placeholders until assets exist."""
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from . import config, db

sys.path.insert(0, str(config.REPO_DIR / 'integrations'))
try:
    from blender_mcp import assets as blender_assets  # type: ignore
except Exception:  # noqa: BLE001 - the integration is optional at runtime
    blender_assets = None

_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='assets')
_inflight: set[str] = set()
_failed: set[str] = set()
_lock = threading.Lock()


def available() -> bool:
    return blender_assets is not None and config.BUILD_ASSETS


def cached_url(product: dict) -> str | None:
    if blender_assets is None or not product.get('dimensions_m'):
        return None
    try:
        path = config.ASSETS_DIR / f'{blender_assets.asset_key(product)}.usdz'
    except Exception:  # noqa: BLE001
        return None
    return f'/assets/{path.name}' if path.exists() else None


def request(product: dict) -> None:
    """Build the asset if needed, then attach it to the product and any scene objects using it."""
    if not available() or not product.get('dimensions_m'):
        return
    url = cached_url(product)
    if url:
        _attach(product['id'], url)
        return
    with _lock:
        if product['id'] in _inflight:
            return
        _inflight.add(product['id'])
    _pool.submit(_build, product)


def _build(product: dict) -> None:
    started = time.perf_counter()
    try:
        path = blender_assets.ensure_asset(product, config.ASSETS_DIR)
        if path:
            _attach(product['id'], f'/assets/{path.name}')
        db.record_timing('asset_build', (time.perf_counter() - started) * 1000, f"{product['id']} ok={bool(path)}")
    finally:
        with _lock:
            _inflight.discard(product['id'])


def variant_failed(product_id: str) -> bool:
    return product_id in _failed


def request_variant(product: dict, hid: str) -> None:
    """Build a one-off asset (e.g. a textured product) once; bump the household when it finishes either way."""
    if not available():
        return
    with _lock:
        if product['id'] in _inflight or product['id'] in _failed:
            return
        _inflight.add(product['id'])
    _pool.submit(_build_variant, product, hid)


def _build_variant(product: dict, hid: str) -> None:
    started = time.perf_counter()
    path = None
    try:
        path = blender_assets.ensure_asset(product, config.ASSETS_DIR)
        if not path:
            _failed.add(product['id'])
        with db.tx() as c:
            db.bump(c, hid)
        db.record_timing('asset_build', (time.perf_counter() - started) * 1000, f"{product['id']} ok={bool(path)}")
    finally:
        with _lock:
            _inflight.discard(product['id'])


def _attach(product_id: str, url: str) -> None:
    urls = db.kv_get('asset_urls', {})
    changed = urls.get(product_id) != url
    if changed:
        urls[product_id] = url
        db.kv_set('asset_urls', urls)
    with db.tx() as c:
        rows = c.execute('SELECT DISTINCT household_id FROM scene_objects WHERE product_id = ? AND '
                         '(asset_url IS NULL OR asset_url != ?)', (product_id, url)).fetchall()
        c.execute('UPDATE scene_objects SET asset_url = ? WHERE product_id = ?', (url, product_id))
        for r in rows:
            db.bump(c, r['household_id'])
