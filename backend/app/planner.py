"""Deterministic planning: bundle selection, layout, and limit-driven revisions.

Gemini may choose among these operations, but every number here comes from structured records.
"""
import itertools
import time
from pathlib import Path

from . import catalog, core, db, geometry, ranking
from .money import InfeasibleSplit, dollars, solve_split

TOP_K = 6


def room_image(h: dict) -> Path | None:
    p = h.get('inspiration_path')
    return Path(p) if p and Path(p).exists() else None


def make_object(product: dict, room: dict, others: list[dict], keep: dict | None = None) -> dict:
    dims = product['dimensions_m']
    if keep:
        pos, rot = list(keep['position_m']), keep['rotation_y_rad']
        if product['category'] in ('sofa', 'tv'):
            # Keep the back of wall-mounted pieces against the same wall.
            default_pos, rot = geometry.default_position(product['category'], dims, room, others)
            pos[2] = default_pos[2]
        elif product['category'] in geometry.WALL_PIECES:
            pos, rot = geometry.default_position(product['category'], dims, room, others)
    else:
        pos, rot = geometry.default_position(product['category'], dims, room, others)
    obj = {'object_id': keep['object_id'] if keep else f"obj-{product['category']}", 'product_id': product['id'],
           'category': product['category'], 'position_m': pos, 'rotation_y_rad': rot, 'dimensions_m': dims,
           'color_hex': product['style'].get('color_hex'), 'asset_url': product.get('asset_url'), 'product': product}
    return geometry.place_without_conflicts(obj, room, others)


def layout(products: list[dict], room: dict, existing: list[dict] | None = None) -> tuple[list[dict], dict]:
    order = {'rug': 0, 'sofa': 1, 'tv': 2, 'coffee_table': 3, 'bed': 1, 'nightstand': 2, 'dresser': 3, 'desk': 4}
    existing = {o['category']: o for o in existing or []}
    placed = []
    for p in sorted(products, key=lambda p: order.get(p['category'], 9)):
        placed.append(make_object(p, room, placed, keep=existing.get(p['category'])))
    return placed, geometry.validate_scene(room, placed)


def select_bundle(hid: str, categories: list[str], budget_cents: int, style_text: str = '') -> dict:
    """Pick one product per category maximizing visual rank under the budget and the members' combined limits."""
    started = time.perf_counter()
    h = core.household(hid)
    lim = core.limits(hid)
    capacity = sum(lim.values()) if all(v is not None for v in lim.values()) else None
    cap = min(budget_cents, capacity) if capacity is not None else budget_cents
    pools, modes, notes = {}, set(), []
    for cat in categories:
        cands = catalog.eligible(cat, h['room'], max_price_cents=cap)
        if not cands:
            notes.append(f"No {cat.replace('_', ' ')} with confirmed dimensions fits the room under {dollars(cap)}.")
            continue
        ranked, mode = ranking.rank(cands, room_image(h), style_text=style_text)
        modes.add(mode)
        pools[cat] = [(p, 1.0 - i / TOP_K) for i, (p, _) in enumerate(ranked[:TOP_K])]
    best, best_key = None, None
    for combo in itertools.product(*pools.values()):
        total = sum(p['price_cents'] for p, _ in combo)
        if total > cap:
            continue
        objs, validation = layout([p for p, _ in combo], h['room'])
        if not validation['ok']:
            continue
        key = (sum(s for _, s in combo), -total)
        if best_key is None or key > best_key:
            best, best_key = [p for p, _ in combo], key
    db.record_timing('select_bundle', (time.perf_counter() - started) * 1000, f'cats={len(categories)}')
    if best is None:
        cheapest = sum(min(p['price_cents'] for p, _ in pool) for pool in pools.values()) if pools else 0
        return {'ok': False, 'notes': notes + [
            f'The cheapest combination that fits costs {dollars(cheapest)}, above the {dollars(cap)} cap '
            f'(budget {dollars(budget_cents)}' + (f', combined limits {dollars(capacity)}' if capacity is not None else '') + ').']}
    return {'ok': True, 'products': best, 'rank_mode': '/'.join(sorted(modes)) or 'none', 'notes': notes}


def propose(hid: str, products: list[dict], explanation: str, activity: str | None = None,
            replace_scene: bool = True) -> dict:
    h = core.household(hid)
    if len({p['category'] for p in products}) != len(products):
        raise core.Conflict('Propose at most one product per category')
    total = sum(p['price_cents'] for p in products)
    if total > h['budget_cents']:
        raise core.Conflict(f"Known total {dollars(total)} exceeds the {dollars(h['budget_cents'])} budget")
    member_ids = [m['id'] for m in core.members(hid)]
    shares = solve_split(total, member_ids, core.limits(hid))
    existing = core.scene_objects(hid)
    if replace_scene:
        objs, validation = layout(products, h['room'], existing)
    else:
        keep = [o for o in existing if o['category'] not in {p['category'] for p in products}]
        new, _ = layout(products, h['room'], existing)
        objs = keep + new
        validation = geometry.validate_scene(h['room'], objs)
    if not validation['ok']:
        raise core.Conflict('Layout check failed: ' + '; '.join(i['message'] for i in validation['issues']))
    return core.create_proposal(hid, products, shares, explanation, scene=objs, activity=activity)


def recheck_prices(hid: str) -> dict | None:
    """Re-read selected offers. A price change or a vanished/undimensioned item creates a new version needing approval."""
    cur = core.current_proposal(hid)
    if not cur:
        return None
    changes, items = [], []
    for item in cur['items']:
        fresh = catalog.get(item['id'])
        if not fresh or not fresh.get('dimensions_m'):
            raise core.Conflict(f"{item['title']} is no longer available with confirmed dimensions; a new plan is needed")
        if fresh['price_cents'] != item['price_cents']:
            changes.append(f"{item['title']} {dollars(item['price_cents'])} -> {dollars(fresh['price_cents'])}")
        items.append(fresh)
    if not changes:
        return None
    member_ids = [m['id'] for m in core.members(hid)]
    try:
        shares = solve_split(sum(i['price_cents'] for i in items), member_ids, core.limits(hid))
    except InfeasibleSplit as e:
        raise core.Conflict(f"Price changed ({'; '.join(changes)}) and the new total no longer fits everyone's limits: {e}")
    return core.create_proposal(hid, items, shares, f"Price changed since approval ({'; '.join(changes)}), so everyone needs to re-approve.",
                                scene=None, activity=f"Proposal v{cur['version'] + 1}: price recheck")


def revise(hid: str, trigger: str = 'limit', focus_category: str | None = None) -> dict:
    """Produce a feasible new version after limits change or someone objects, or explain why none exists."""
    started = time.perf_counter()
    h = core.household(hid)
    cur = core.current_proposal(hid)
    if not cur:
        return {'ok': False, 'message': 'There is no proposal to revise yet.'}
    if core.purchase_locked(hid, cur['version']):
        return {'ok': False, 'message': f"The purchase for v{cur['version']} is already authorized, so it can't be revised."}
    member_ids = [m['id'] for m in core.members(hid)]
    lim = core.limits(hid)
    reason = 'A roommate updated their contribution limit' if trigger == 'limit' else 'A roommate asked for a change'

    if trigger == 'limit':
        try:
            shares = solve_split(cur['known_total_cents'], member_ids, lim)
            if shares == cur['shares']:
                return {'ok': True, 'message': f"The current split for v{cur['version']} already fits everyone's limits.",
                        'proposal': cur}
            items = [catalog.get(i['id']) or i for i in cur['items']]
            p = core.create_proposal(hid, [{**i, 'price_cents': c['price_cents']} for i, c in zip(items, cur['items'])],
                                     shares, f'{reason}, so the split was rebalanced.', scene=None,
                                     activity=f"Proposal v{cur['version'] + 1}: split rebalanced")
            return {'ok': True, 'changed': True, 'message': 'Split rebalanced within everyone\'s limits.', 'proposal': p}
        except InfeasibleSplit:
            pass

    capacity = sum(lim.values()) if all(v is not None for v in lim.values()) else None
    total = cur['known_total_cents']
    over = max(0, total - capacity) if capacity is not None else 0
    items = sorted(cur['items'], key=lambda i: -i['price_cents'])
    if focus_category:
        items = sorted(items, key=lambda i: i['category'] != focus_category)
    image = room_image(h)
    tried = []
    for old in items:
        others = [i for i in cur['items'] if i['id'] != old['id']]
        if trigger == 'limit':
            max_price = old['price_cents'] - over
        else:
            headroom = (capacity - total) if capacity is not None else (h['budget_cents'] - total)
            max_price = old['price_cents'] + max(0, headroom) - over
        cands = [p for p in catalog.eligible(old['category'], h['room'], max_price_cents=max_price) if p['id'] != old['id']]
        if not cands:
            tried.append(old)
            continue
        ranked, mode = ranking.rank(cands, image, reference=old, style_text=h.get('style_text') or '')
        for new, score in ranked:
            new_items = [new] + [catalog.get(i['id']) or i for i in others]
            new_total = sum(i['price_cents'] for i in new_items)
            try:
                shares = solve_split(new_total, member_ids, lim)
            except InfeasibleSplit:
                continue
            existing = core.scene_objects(hid)
            keep = [o for o in existing if o['category'] != new['category']]
            obj = make_object(new, h['room'], keep, keep=next((o for o in existing if o['category'] == new['category']), None))
            scene = keep + [obj]
            validation = geometry.validate_scene(h['room'], scene)
            if not validation['ok']:
                continue
            ranked_by = {'learned': 'the trained visual ranker', 'cosine': 'SigLIP image similarity',
                         'heuristic': 'color and style similarity (visual ranker offline)'}.get(mode, mode)
            explanation = (f"{reason}, so the {old['title']} ({dollars(old['price_cents'])}) no longer fit. "
                           f"The {new['title']} ({dollars(new['price_cents'])}) is the best match that fits, ranked by {ranked_by}.")
            p = core.create_proposal(hid, new_items, shares, explanation, scene=[
                {**o, 'product': catalog.get(o['product_id'])} if 'product' not in o else o for o in scene],
                activity=f"Proposal v{cur['version'] + 1}: {new['title']} replaces {old['title']}")
            db.record_timing('revise', (time.perf_counter() - started) * 1000, f'{old["id"]}->{new["id"]}')
            return {'ok': True, 'changed': True, 'message': explanation, 'proposal': p, 'replaced': old['id'], 'with': new['id']}
        tried.append(old)
    if capacity is not None:
        cheapest = {}
        for old in cur['items']:
            pool = catalog.eligible(old['category'], h['room'])
            if pool:
                cheapest[old['category']] = min(p['price_cents'] for p in pool)
        floor = sum(cheapest.values())
        return {'ok': False, 'message': (
            f"No feasible revision: combined limits are {dollars(capacity)}, but the cheapest items that fit the room "
            f"for this purchase total {dollars(floor)}. Someone would need to raise their limit by at least "
            f"{dollars(max(0, floor - capacity))}, or we drop an item.")}
    return {'ok': False, 'message': 'No alternative fits the room and everyone\'s limits.'}
