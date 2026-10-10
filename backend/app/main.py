"""FastAPI app. Run from backend/: ../.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000"""
import asyncio
import hashlib
import json
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from . import (agent, apartment, assets, blender_mcp_client, catalog, config, core, db, finance, floorplan, messaging,
               nessie, planner, ranking, realize, seed, state, textures, invitations)
from .core import Conflict, Forbidden
from .money import dollars


@asynccontextmanager
async def lifespan(_app):
    db.init()
    if not db.one('SELECT 1 FROM households WHERE id = ?', seed.HID):
        seed.reset()
    apartment.ensure()
    finance.recover_on_startup()
    stop = threading.Event()
    worker = threading.Thread(target=finance.worker_loop, args=(stop,), name='finance', daemon=True)
    worker.start()
    for p in catalog.products():
        assets.request(p)
    yield
    stop.set()
    worker.join(timeout=5)


app = FastAPI(title='RAG to Rooms', lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_methods=['*'], allow_headers=['*'])
app.mount('/assets', StaticFiles(directory=config.ASSETS_DIR), name='assets')
app.mount('/uploads', StaticFiles(directory=config.UPLOADS_DIR), name='uploads')
app.mount('/product_images', StaticFiles(directory=config.STATIC_DIR / 'product_images'), name='product_images')


@app.exception_handler(Forbidden)
async def _forbidden(_r, e):
    return JSONResponse({'detail': str(e)}, status_code=403)


@app.exception_handler(Conflict)
async def _conflict(_r, e):
    return JSONResponse({'detail': str(e)}, status_code=409)


@app.exception_handler(KeyError)
async def _missing(_r, e):
    return JSONResponse({'detail': f'Not found: {e}'}, status_code=404)


@app.exception_handler(ValueError)
async def _invalid(_r, e):
    return JSONResponse({'detail': str(e)}, status_code=422)


class MemberBody(BaseModel):
    member_id: str


class ObjectBody(MemberBody):
    reason: str | None = None


class PurchaseBody(MemberBody):
    proposal_version: int


class LimitBody(BaseModel):
    limit_cents: int | None = Field(default=None, ge=0)


class BudgetBody(BaseModel):
    budget_cents: int = Field(ge=0, le=50_000_000)


class HandleBody(BaseModel):
    handle: str


class ChatBody(BaseModel):
    member_id: str | None = None
    text: str = Field(min_length=1, max_length=2000)


class MoveBody(BaseModel):
    position_m: list[float] = Field(min_length=3, max_length=3)
    rotation_y_rad: float


class Opening(BaseModel):
    kind: str = Field(pattern='^(door|window)$')
    wall: str = Field(pattern='^(back|front|left|right)$')
    offset_m: float
    width_m: float = Field(gt=0, le=5)


class Clearance(BaseModel):
    label: str
    x_m: float
    z_m: float
    width_m: float = Field(gt=0, le=10)
    depth_m: float = Field(gt=0, le=10)


class RoomBody(BaseModel):
    width_m: float = Field(ge=1.5, le=15)
    depth_m: float = Field(ge=1.5, le=15)
    height_m: float = Field(default=2.5, ge=2, le=6)
    openings: list[Opening] = []
    clearances: list[Clearance] = []


class InboundBody(BaseModel):
    event_id: str = Field(min_length=1, max_length=200)
    sender_handle: str
    conversation_id: str | None = None
    text: str = Field(max_length=4000)
    received_at: str | None = None


class ClaimBody(BaseModel):
    worker_id: str
    max: int = Field(default=10, ge=1, le=50)


class JoinGroupBody(BaseModel):
    code: str = Field(pattern=r"^[0-9]{6}$")


class InviteMember(BaseModel):
    member_id: str
    phone: str


class InviteBody(BaseModel):
    members: list[InviteMember] = Field(min_length=2, max_length=20)
    request_id: str = Field(min_length=1, max_length=100)


class ResultBody(BaseModel):
    status: str
    provider_message_id: str | None = None
    conversation_id: str | None = None
    line_phone: str | None = None
    error: str | None = None


class RealizeBody(BaseModel):
    id: str
    title: str
    category: str
    image_url: str | None = None
    source_url: str | None = None
    retailer: str | None = None
    description: str | None = None
    price_cents: int = 0
    dimensions_m: dict[str, float]


@app.get('/')
def root():
    return {'service': 'RAG to Rooms backend', 'health': '/health', 'apartment': '/apartments/demo',
            'living_room': '/households/demo/state', 'docs': '/docs'}


@app.post('/groups/join')
def join_group(body: JoinGroupBody):
    return invitations.join(body.code)


@app.post('/households/{hid}/invitations')
def invite(hid: str, body: InviteBody):
    return invitations.create(hid, [m.model_dump() for m in body.members], body.request_id)


@app.get('/invitations/{token}')
def invitation(token: str):
    return invitations.get(token)


@app.get('/households/{hid}/suggestions')
def suggestions(hid: str):
    return {'suggestions': invitations.suggestions(hid)}


@app.get('/health')
def health():
    return {'status': 'ok', 'catalog': catalog.catalog_mode(), 'products': len(catalog.products()),
            'integrations': {'gemini': agent.available(), 'gemini_backend': config.GEMINI_BACKEND, 'nessie': nessie.client().mode, 'ranker': ranking.ranker_health(),
                             'blender_assets': assets.available(), 'shopping_search': bool(config.SHOPPING_API_KEY),
                             'photon': 'adapter process (integrations/photon)'}}


@app.get('/products')
def products(category: str | None = None):
    return [p for p in catalog.products() if not category or p['category'] == category]


@app.get('/products/search')
def search_products(q: str, limit: int = 20):
    q = (q or '').strip()
    if not q:
        raise HTTPException(422, 'q is required')
    return catalog.search(q, limit=max(1, min(limit, 30)))


@app.post('/products/realize')
def realize_product(body: RealizeBody):
    try:
        return realize.start(body.model_dump())
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


@app.post('/products/realize/upload')
async def realize_upload(id: str = Form(...), title: str = Form(...), category: str = Form(...),
                         width: float = Form(...), depth: float = Form(...), height: float = Form(...),
                         file: UploadFile = File(...), source_url: str | None = Form(None)):
    image = await file.read()
    try:
        return realize.start(
            {'id': id, 'title': title, 'category': category, 'source_url': source_url,
             'dimensions_m': {'width': width, 'depth': depth, 'height': height}},
            image_bytes=image, mime=file.content_type or 'image/jpeg')
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


@app.get('/products/realize/{pid}')
def realize_status(pid: str):
    rec = realize.snapshot(pid)
    if rec is None:
        raise HTTPException(404, f'No realized product {pid}')
    return rec


@app.get('/households/{hid}/state')
def get_state(hid: str, member_id: str | None = None):
    return state.snapshot(hid, member_id)


@app.get('/households/{hid}/events')
async def events(hid: str, request: Request):
    core.household(hid)

    async def stream():
        last = None
        while not await request.is_disconnected():
            row = db.one('SELECT state_version FROM households WHERE id = ?', hid)
            v = row['state_version'] if row else None
            if v != last:
                last = v
                yield {'event': 'state', 'data': f'{{"state_version": {v}}}'}
            await asyncio.sleep(0.4)
    return EventSourceResponse(stream(), ping=15)


@app.put('/households/{hid}/room')
def put_room(hid: str, body: RoomBody):
    kind = core.household(hid)['room'].get('kind')
    room = body.model_dump() | ({'kind': kind} if kind else {})
    with db.tx() as c:
        c.execute('UPDATE households SET room_json = ? WHERE id = ?', (json.dumps(room), hid))
        db.log(c, hid, f'Room updated to {body.width_m:.2f} m x {body.depth_m:.2f} m')
        db.bump(c, hid)
    return state.snapshot(hid)['scene']['validation']


async def _save_image(file: UploadFile) -> tuple[bytes, str, Path]:
    """Store an uploaded PNG/JPEG under /uploads by content hash."""
    data = await file.read()
    if len(data) > 15_000_000:
        raise HTTPException(413, 'Image too large')
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        mime, suffix = 'image/png', '.png'
    elif data[:2] == b'\xff\xd8':
        mime, suffix = 'image/jpeg', '.jpg'
    else:
        raise HTTPException(415, 'Upload a PNG or JPEG image')
    path = config.UPLOADS_DIR / f'{hashlib.sha256(data).hexdigest()[:16]}{suffix}'
    path.write_bytes(data)
    return data, mime, path


@app.post('/households/{hid}/inspiration')
async def inspiration(hid: str, file: UploadFile = File(...)):
    core.household(hid)
    _, _, path = await _save_image(file)
    with db.tx() as c:
        c.execute('UPDATE households SET inspiration_path = ? WHERE id = ?', (str(path), hid))
        db.log(c, hid, 'Inspiration image updated')
        db.bump(c, hid)
    return {'inspiration_image_url': f'/uploads/{path.name}'}


@app.post('/households/{hid}/chat')
def chat(hid: str, body: ChatBody):
    core.household(hid)
    if body.member_id:
        core.member(hid, body.member_id)
    return agent.furnish(hid, body.member_id, body.text)


@app.put('/households/{hid}/budget')
def put_budget(hid: str, body: BudgetBody):
    core.household(hid)
    with db.tx() as c:
        c.execute('UPDATE households SET budget_cents = ? WHERE id = ?', (body.budget_cents, hid))
        db.log(c, hid, f'Budget set to {dollars(body.budget_cents)}')
        db.bump(c, hid)
    return state.snapshot(hid)


@app.put('/households/{hid}/members/{mid}/limit')
def put_limit(hid: str, mid: str, body: LimitBody):
    core.set_limit(hid, mid, body.limit_cents)
    return _revision(planner.revise(hid, trigger='limit'))


def _revision(result: dict) -> dict:
    p = result.get('proposal')
    return {'revised': bool(result.get('changed')), 'proposal_version': p['version'] if p else None,
            'message': result['message']}


@app.put('/households/{hid}/members/{mid}/handle')
def put_handle(hid: str, mid: str, body: HandleBody):
    core.member(hid, mid)
    with db.tx() as c:
        c.execute('UPDATE members SET handle = ? WHERE household_id = ? AND id = ?', (core.normalize_handle(body.handle), hid, mid))
        db.bump(c, hid)
    return {'ok': True}


@app.post('/households/{hid}/proposals/{version}/approve')
def approve(hid: str, version: int, body: MemberBody):
    p = core.decide(hid, version, body.member_id, 'approve')
    return {'status': p['status'], 'approvals': p['approvals']}


@app.post('/households/{hid}/proposals/{version}/object')
def object_(hid: str, version: int, body: ObjectBody):
    core.decide(hid, version, body.member_id, 'object', body.reason)
    return _revision(planner.revise(hid, trigger='object', focus_category=messaging.category_in(body.reason or '')))


@app.patch('/households/{hid}/scene/objects/{object_id}')
def move(hid: str, object_id: str, body: MoveBody):
    return core.move_object(hid, object_id, body.position_m, body.rotation_y_rad)


@app.post('/households/{hid}/purchase/authorize')
def purchase(hid: str, body: PurchaseBody):
    return finance.public_op(finance.authorize_purchase(hid, body.member_id, body.proposal_version))


@app.post('/households/{hid}/reimbursements/{liability_id}/authorize')
def reimburse(hid: str, liability_id: str, body: MemberBody):
    return finance.public_op(finance.authorize_reimbursement(hid, liability_id, body.member_id))


@app.post('/households/{hid}/finance/reconcile')
def reconcile(hid: str):
    finance.reconcile(hid)
    return state.snapshot(hid)['finance']


@app.post('/households/{hid}/finance/setup')
def finance_setup(hid: str):
    accts = finance.setup_accounts(hid)
    return {'mode': nessie.client().mode, 'members': [k for k in accts if not k.startswith('_')]}


@app.post('/households/{hid}/scene/objects/{object_id}/texture')
async def put_texture(hid: str, object_id: str, file: UploadFile = File(...), mode: str | None = Form(None),
                      tile_m: float | None = Form(None)):
    core.household(hid)
    if not any(o['object_id'] == object_id for o in core.scene_objects(hid)):
        raise HTTPException(404, f'No object {object_id} in this room')
    if mode is not None and mode not in textures.MODES:
        raise HTTPException(422, f'mode must be one of {", ".join(textures.MODES)}')
    if tile_m is not None and not 0.05 <= tile_m <= 2.0:
        raise HTTPException(422, 'tile_m must be between 0.05 and 2.0')
    _, _, path = await _save_image(file)
    textures.put(hid, object_id, str(path), f'/uploads/{path.name}', mode, tile_m)
    with db.tx() as c:
        db.log(c, hid, f'New texture on {object_id}')
        db.bump(c, hid)
    obj = next(o for o in state.snapshot(hid)['scene']['objects'] if o['object_id'] == object_id)
    return {'object_id': object_id, 'texture': obj.get('texture'), 'asset_url': obj.get('asset_url')}


@app.delete('/households/{hid}/scene/objects/{object_id}/texture')
def delete_texture(hid: str, object_id: str):
    core.household(hid)
    if not textures.delete(hid, object_id):
        raise HTTPException(404, f'No texture on {object_id}')
    with db.tx() as c:
        db.log(c, hid, f'Texture removed from {object_id}')
        db.bump(c, hid)
    return {'ok': True}


@app.post('/households/{hid}/scene/preview')
def scene_preview(hid: str):
    try:
        return blender_mcp_client.render_scene_preview(hid)
    except RuntimeError as e:
        raise HTTPException(503, str(e)) from e


@app.post('/demo/reset')
def demo_reset(clear_handles: bool = False):
    return apartment.reset(clear_handles=clear_handles)


@app.get('/apartments/{aid}')
def get_apartment(aid: str):
    try:
        return apartment.snapshot(aid)
    except KeyError as e:
        raise HTTPException(404, str(e)) from e


@app.post('/apartments/{aid}/floorplan')
async def import_floorplan(aid: str, file: UploadFile = File(...), width_m: float | None = Form(None)):
    if aid != apartment.AID:
        raise HTTPException(404, f'Unknown apartment {aid}')
    if not agent.available():
        raise HTTPException(503, 'Floor-plan import needs Gemini; set up Vertex AI or GEMINI_API_KEY')
    if width_m is not None and not 2.0 <= width_m <= 60.0:
        raise HTTPException(422, 'width_m must be between 2 and 60')
    data, mime, path = await _save_image(file)
    try:
        return await asyncio.to_thread(apartment.import_plan, data, mime, f'/uploads/{path.name}', width_m)
    except floorplan.PlanError as e:
        raise HTTPException(422, str(e)) from e


@app.delete('/apartments/{aid}/floorplan')
def reset_floorplan(aid: str):
    if aid != apartment.AID:
        raise HTTPException(404, f'Unknown apartment {aid}')
    return apartment.restore_built_in()


@app.post('/messages/inbound', status_code=202)
def inbound(body: InboundBody):
    return messaging.handle_inbound(body.model_dump())


@app.post('/messages/outbound/claim')
def outbound_claim(body: ClaimBody):
    return {'jobs': messaging.claim(body.worker_id, body.max)}


@app.post('/messages/outbound/{job_id}/result')
def outbound_result(job_id: int, body: ResultBody):
    if body.status == 'sent' and db.kv_get(f'job-payload:{job_id}'):
        invitations.bind(job_id, body.conversation_id, body.line_phone)
    messaging.result(job_id, body.status, body.provider_message_id, body.error)
    return {'ok': True}


@app.get('/debug/timings')
def timings():
    return db.all_('SELECT stage, ROUND(AVG(ms), 1) AS avg_ms, ROUND(MAX(ms), 1) AS max_ms, COUNT(*) AS n '
                   'FROM timings GROUP BY stage ORDER BY stage')


@app.get('/debug/outbound')
def debug_outbound():
    return db.all_('SELECT job_id, to_handle, text, status, created_at FROM outbound_jobs ORDER BY job_id')
