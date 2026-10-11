"""Visual ranking via the ml/ sidecar (separate venv with torch). Hard constraints are applied before this."""
import time
from pathlib import Path

import httpx

from . import config, db

_ranker_skip_until = 0.0


def _hex_rgb(h: str) -> tuple[float, float, float]:
    h = (h or '#888888').lstrip('#')
    if len(h) == 3:
        h = ''.join(c * 2 for c in h)
    try:
        return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    except ValueError:
        return (0.5, 0.5, 0.5)


def heuristic_similarity(product: dict, reference: dict | None, style_text: str) -> float:
    """Fallback when no learned or embedding ranker is reachable: color distance plus tag/style word overlap."""
    score = 0.0
    tags = {t.lower() for t in (product.get('style') or {}).get('tags', [])}
    words = {w.strip('.,!').lower() for w in style_text.split()}
    score += 0.3 * len(tags & words)
    if reference:
        a = _hex_rgb((product.get('style') or {}).get('color_hex'))
        b = _hex_rgb((reference.get('style') or {}).get('color_hex'))
        score += 1.0 - min(1.0, sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5)
        score += 0.2 * len(tags & {t.lower() for t in (reference.get('style') or {}).get('tags', [])})
    return score


def rank(products: list[dict], room_image: Path | None, reference: dict | None = None,
         style_text: str = '') -> tuple[list[tuple[dict, float]], str]:
    """Returns products sorted best-first with scores, and the ranking mode used."""
    if not products:
        return [], 'none'
    started = time.perf_counter()
    scores, mode = None, 'heuristic'
    global _ranker_skip_until
    if room_image is not None and time.monotonic() >= _ranker_skip_until:
        try:
            r = httpx.post(f'{config.RANKER_URL}/score', timeout=1.5, json={
                'room_image_path': str(room_image), 'product_ids': [p['id'] for p in products]})
            r.raise_for_status()
            body = r.json()
            if body.get('mode') in ('learned', 'cosine'):
                scores, mode = body['scores'], body['mode']
        except (httpx.HTTPError, ValueError, KeyError):
            _ranker_skip_until = time.monotonic() + 60
    if scores is None:
        scores = {p['id']: heuristic_similarity(p, reference, style_text) for p in products}
    ranked = sorted(products, key=lambda p: (-(scores.get(p['id']) or 0.0), p['price_cents']))
    db.record_timing('rank', (time.perf_counter() - started) * 1000, f'{mode} n={len(products)}')
    return [(p, float(scores.get(p['id']) or 0.0)) for p in ranked], mode


def ranker_health() -> str:
    try:
        return httpx.get(f'{config.RANKER_URL}/health', timeout=1).json().get('mode', 'unknown')
    except (httpx.HTTPError, ValueError):
        return 'offline'
