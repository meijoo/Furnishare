"""Gemini coordination. Gemini proposes; backend code validates every argument and owns money/authorization."""
import json
import re
import time

from . import catalog, config, core, db, planner, ranking, workflow
from .money import dollars

SYSTEM = """You are the RAG to Rooms furnishing agent for roommates furnishing a shared apartment, one room at a time.
Use tools to search the catalog and live listings, rank candidates, and propose ONE bundle with one product per requested category.
Rules: only use product ids returned by tools or supplied as picks; never invent dimensions, prices, or products; the backend rejects bundles over
budget, over combined contribution limits, without placeable sizes, or failing layout checks. Live listings with sizes may be proposed.
Prefer the user's selected pick ids when they fit. Skip categories they already own. If a proposal is rejected,
adjust and retry at most 3 times, then explain which constraints conflict. You cannot approve, pay, or settle anything.
Never reveal one roommate's private limit to others. After a successful proposal, call render_room_preview once.
Finish with a short friendly explanation grounded in retrieved evidence."""

START_OVER = re.compile(r'\b(start over|start again|from scratch|new plan|redesign)\b', re.I)

_client = None


def available() -> bool:
    return config.GEMINI_BACKEND is not None


def _gemini():
    global _client
    if _client is None:
        from google import genai
        if config.GEMINI_BACKEND == 'vertex' and config.VERTEX_API_KEY:
            _client = genai.Client(vertexai=True, api_key=config.VERTEX_API_KEY)
        elif config.GEMINI_BACKEND == 'vertex':
            _client = genai.Client(vertexai=True, project=config.GOOGLE_CLOUD_PROJECT,
                                   location=config.GOOGLE_CLOUD_LOCATION)
        else:
            _client = genai.Client(api_key=config.GEMINI_API_KEY)
    return _client


def parse_request(text: str, allowed: list[str] | None = None) -> dict:
    """Budget and categories from free text, limited to the categories this room scope furnishes."""
    budget = re.search(r'\$\s*(\d[\d,]*)', text)
    words = {'sofa': r'sofa|couch|loveseat', 'coffee_table': r'coffee table|table', 'tv': r'tv|television', 'rug': r'rug|carpet',
             'bed': r'bed|bed frame|mattress', 'nightstand': r'nightstand|night stand|bedside table',
             'dresser': r'dresser|chest of drawers|drawers', 'desk': r'desk|workspace',
             'chair': r'chairs?|armchairs?|accent chair'}
    allowed = list(allowed or catalog.CATEGORIES)
    found = [c for c, pat in words.items() if re.search(rf'\b({pat})s?\b', text, re.I)]
    if 'nightstand' in found and 'coffee_table' in found and not re.search(r'coffee', text, re.I):
        found.remove('coffee_table')
    cats = [c for c in found if c in allowed or c == 'chair'] or allowed
    return {'budget_cents': int(budget.group(1).replace(',', '')) * 100 if budget else None, 'categories': cats,
            'style_text': text}


def room_categories(h: dict) -> list[str]:
    """Bedroom scopes furnish bedroom categories; everything else is a living room."""
    if h['room'].get('kind') == 'bedroom':
        return list(catalog.BEDROOM_CATEGORIES)
    return list(catalog.LIVING_CATEGORIES)


def _product_summary(p: dict, score: float | None = None) -> dict:
    style = p.get('style') or {}
    out = {'id': p['id'], 'title': p.get('title'), 'retailer': p.get('retailer'), 'variant': p.get('variant'),
           'price': dollars(p.get('price_cents') or 0), 'dimensions_m': p.get('dimensions_m'),
           'tags': style.get('tags', []), 'source_type': p.get('source_type'),
           'evidence': [e.get('quote') for e in (p.get('evidence') or [])[:3]]}
    if score is not None:
        out['visual_score'] = round(score, 4)
    return out


def _focus_category(text: str, allowed: list[str]) -> str | None:
    words = {'sofa': r'sofa|couch|loveseat', 'coffee_table': r'coffee table', 'tv': r'tv|television',
             'rug': r'rug|carpet', 'bed': r'bed|mattress', 'nightstand': r'nightstand|bedside',
             'dresser': r'dresser|drawers', 'desk': r'desk|workspace',
             'chair': r'chairs?|armchairs?|accent chair'}
    found = [c for c, pat in words.items() if (c in allowed or c == 'chair')
             and re.search(rf'\b({pat})s?\b', text, re.I)]
    return found[0] if found else None


def _resolve_picks(pick_ids: list[str] | None) -> list[dict]:
    out, seen = [], set()
    for pid in pick_ids or []:
        p = catalog.get(pid)
        if p and p['id'] not in seen:
            seen.add(p['id'])
            out.append(p)
    return out


def _realize_live(products: list[dict] | None) -> None:
    from . import realize
    for p in products or []:
        if not p:
            continue
        if p.get('source_type') == 'live' or str(p.get('id', '')).startswith('live-'):
            try:
                realize.start(p)
            except ValueError:
                pass


def furnish(hid: str, mid: str | None, text: str, pick_ids: list[str] | None = None,
            mode: str | None = None, skip_categories: list[str] | None = None) -> dict:
    """Design a room from a prompt, or refine the current proposal."""
    skip = [c for c in (skip_categories or []) if c]
    start_over = bool(START_OVER.search(text or ''))
    has = core.current_proposal(hid)
    if mode != 'design' and has and not start_over:
        return _refine(hid, text)
    return _design(hid, text, pick_ids, skip)


def _design(hid: str, text: str, pick_ids: list[str] | None, skip: list[str]) -> dict:
    started = time.perf_counter()
    h = core.household(hid)
    req = parse_request(text, room_categories(h))
    cats = [c for c in req['categories'] if c not in skip] or [c for c in room_categories(h) if c not in skip]
    with db.tx() as c:
        c.execute('UPDATE households SET budget_cents = COALESCE(?, budget_cents), needs_json = ?, style_text = ? WHERE id = ?',
                  (req['budget_cents'], json.dumps(cats), text, hid))
        db.bump(c, hid)
    picks = _resolve_picks(pick_ids)
    if available():
        try:
            reply = _furnish_with_gemini(hid, text, picks=picks, skip=skip)
            db.record_timing('gemini_furnish', (time.perf_counter() - started) * 1000)
            return {'reply': reply, 'engine': 'gemini'}
        except Exception as e:  # noqa: BLE001 - fall back to the deterministic workflow
            print(f'gemini furnish failed, using deterministic planner: {e!r}', flush=True)
    result = workflow.run(hid, cats, core.household(hid)['budget_cents'], text, picks=picks, skip_categories=skip)
    _realize_live(result.get('products'))
    db.record_timing('deterministic_furnish', (time.perf_counter() - started) * 1000)
    return {'reply': result['message'], 'engine': 'deterministic'}


def _refine(hid: str, text: str) -> dict:
    started = time.perf_counter()
    with db.tx() as c:
        c.execute('UPDATE households SET style_text = ? WHERE id = ?', (text, hid))
        db.bump(c, hid)
    if available():
        try:
            reply = _furnish_with_gemini(hid, text, refine=True)
            db.record_timing('gemini_refine', (time.perf_counter() - started) * 1000)
            return {'reply': reply, 'engine': 'gemini'}
        except Exception as e:  # noqa: BLE001
            print(f'gemini refine failed, using deterministic planner: {e!r}', flush=True)
    focus = _focus_category(text, room_categories(core.household(hid)))
    result = planner.revise(hid, trigger='object', focus_category=focus)
    db.record_timing('deterministic_refine', (time.perf_counter() - started) * 1000)
    return {'reply': result['message'], 'engine': 'deterministic'}


def _furnish_with_gemini(hid: str, text: str, picks: list[dict] | None = None,
                         skip: list[str] | None = None, refine: bool = False) -> str:
    from google.genai import types
    state = {'published': None, 'products': []}

    def search_products(category: str, max_price_dollars: float = 0, query: str = '') -> dict:
        """Search catalog and live listings that have placeable sizes. category: one of the requested categories."""
        allowed = room_categories(core.household(hid))
        if category not in allowed:
            return {'error': f'category must be one of {allowed} for this room'}
        room = core.household(hid)['room']
        cap = round(max_price_dollars * 100) if max_price_dollars and max_price_dollars > 0 else None
        found = catalog.search(query or category.replace('_', ' '), limit=12)
        pool = catalog.design_pool(category, room, cap, extra=found + (picks or []))
        return {'products': [_product_summary(p) for p in pool][:15]}

    def rank_candidates(category: str) -> dict:
        """Rank placeable products in one category by visual compatibility with the room/inspiration image."""
        h = core.household(hid)
        ranked, mode = ranking.rank(catalog.design_pool(category, h['room'], extra=picks),
                                   planner.room_image(h), style_text=h['style_text'] or '')
        return {'mode': mode, 'note': 'Scores only compare items within this category.',
                'ranked': [_product_summary(p, s) for p, s in ranked[:8]]}

    def search_live_listings(query: str) -> dict:
        """Live shopping results. Listings with sizes can be proposed."""
        found = catalog.search(query, limit=12)
        return {'results': [_product_summary(p) for p in found]}

    def propose_bundle(product_ids: list[str], explanation: str) -> dict:
        """Propose one product per category. The backend validates budget, limits, dimensions and layout, then shows it on the iPad."""
        if state['published']:
            return {'error': 'A bundle was already published in this turn'}
        h = core.household(hid)
        products = [catalog.get(pid) for pid in product_ids]
        if any(p is None for p in products):
            return {'error': 'Unknown product id; use ids returned by search_products or the supplied picks'}
        cats = [p['category'] for p in products]
        if len(set(cats)) != len(cats):
            return {'error': 'Only one product per category'}
        if skip and any(c in skip for c in cats):
            return {'error': f'Skip owned categories: {skip}'}
        if any(not catalog.placeable(p, h['room']) for p in products):
            return {'error': 'A product lacks placeable sizes or does not fit the room'}
        total = sum(p['price_cents'] for p in products)
        if total > h['budget_cents']:
            return {'error': f"Total {dollars(total)} exceeds the {dollars(h['budget_cents'])} budget"}
        try:
            p = planner.propose(hid, products, explanation.strip()[:400], activity='New furnishing plan proposed')
        except (ValueError, core.Conflict) as e:
            return {'error': str(e)}
        state['published'] = p['version']
        state['products'] = products
        _realize_live(products)
        return {'ok': True, 'version': p['version'], 'total': dollars(p['known_total_cents']),
                'unknown_costs': p['unknown_costs'], 'note': 'Shares are private to each roommate; do not list limits.'}

    def render_room_preview() -> dict:
        """After proposing, rebuild the layout in Blender through the custom Blender MCP server and render a preview."""
        from . import blender_mcp_client
        try:
            return blender_mcp_client.render_scene_preview(hid)
        except Exception as e:  # noqa: BLE001
            return {'error': f'Blender preview unavailable: {e}'}

    h = core.household(hid)
    lims = core.limits(hid)
    cap = None if any(v is None for v in lims.values()) else sum(lims.values())
    kind = h['room'].get('kind', 'living')
    owner = ', a private room paid entirely by its owner' if len(lims) == 1 else ', shared by all roommates'
    pick_line = ''
    if picks:
        pick_line = ' Selected picks: ' + ', '.join(f"{p['id']} ({p.get('title')}, {p.get('category')})" for p in picks) + '.'
    skip_line = f" Skip owned categories: {', '.join(skip)}." if skip else ''
    current = core.current_proposal(hid)
    refine_line = ''
    if refine and current:
        refine_line = (' Refine the current proposal; keep it unless the user asks to change a piece. Current items: '
                       + ', '.join(f"{i.get('title')} ({i.get('category')})" for i in current.get('items', [])) + '.')
    context = (f"Room: {h['name']} ({kind}{owner}), {h['room']['width_m']} m x {h['room']['depth_m']} m. Budget {dollars(h['budget_cents'])}. "
               f"Requested categories: {', '.join(h['needs'])}. "
               + (f'Combined contribution limits: {dollars(cap)}. ' if cap is not None else '')
               + ('An inspiration image is uploaded. ' if planner.room_image(h) else 'No inspiration image yet. ')
               + pick_line + skip_line + refine_line)
    response = _gemini().models.generate_content(
        model=config.GEMINI_MODEL,
        contents=f'{context}\nRequest: {text}',
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM,
            tools=[search_products, rank_candidates, search_live_listings, propose_bundle, render_room_preview],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(maximum_remote_calls=12),
            temperature=0.3,
        ))
    reply = (response.text or '').strip()
    if not state['published']:
        if refine:
            focus = _focus_category(text, room_categories(h))
            result = planner.revise(hid, trigger='object', focus_category=focus)
            return (reply + '\n\n' if reply else '') + result['message']
        result = workflow.run(hid, [c for c in h['needs'] if c not in (skip or [])], h['budget_cents'], text,
                              picks=picks, skip_categories=skip)
        _realize_live(result.get('products'))
        return (reply + '\n\n' if reply else '') + result['message']
    return reply or f"Proposal v{state['published']} is ready on the iPad."


def chat(hid: str, mid: str | None, text: str, pick_ids: list[str] | None = None,
         mode: str | None = None, skip_categories: list[str] | None = None) -> dict:
    return furnish(hid, mid, text, pick_ids=pick_ids, mode=mode, skip_categories=skip_categories)


def interpret(text: str, status: str) -> dict | None:
    """Map free-form text to one strict intent; messaging re-validates and money still needs PAY/SEND."""
    if not available():
        return None
    from google.genai import types
    schema = {
        'type': 'OBJECT',
        'properties': {
            'intent': {'type': 'STRING', 'enum': ['set_limit', 'approve', 'object', 'authorize_purchase',
                                                  'authorize_reimbursement', 'status', 'design_request', 'unknown']},
            'amount_dollars': {'type': 'NUMBER'},
            'category': {'type': 'STRING', 'enum': ['sofa', 'coffee_table', 'tv', 'rug']},
            'reason': {'type': 'STRING'},
        },
        'required': ['intent'],
    }
    prompt = ('Classify one text message from a roommate to a shared-furniture purchase agent. '
              f'Current status for this person: {status}\nMessage: {text!r}')
    try:
        r = _gemini().models.generate_content(model=config.GEMINI_MODEL, contents=prompt, config=types.GenerateContentConfig(
            response_mime_type='application/json', response_schema=schema, temperature=0))
        data = json.loads(r.text)
    except Exception:  # noqa: BLE001
        return None
    amount = data.get('amount_dollars')
    if data.get('intent') == 'set_limit' and (not isinstance(amount, (int, float)) or amount < 0):
        return None
    return data
