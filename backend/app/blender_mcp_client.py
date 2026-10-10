"""Persistent MCP stdio client for integrations/blender_mcp/server.py, used by the agent and the preview endpoint."""
import asyncio
import json
import shutil
import sys
import threading
import time

from . import catalog, config, core, db, textures

SERVER = config.REPO_DIR / 'integrations' / 'blender_mcp' / 'server.py'
PREVIEW_DIR = config.UPLOADS_DIR / 'previews'


class BlenderMCP:
    def __init__(self):
        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._session = None
        self._error = None
        self._lock = threading.Lock()
        threading.Thread(target=self._run, name='blender-mcp', daemon=True).start()

    def _run(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._main())

    async def _main(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        params = StdioServerParameters(command=sys.executable, args=[str(SERVER)])
        try:
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    self._session = session
                    self._ready.set()
                    await asyncio.Event().wait()
        except Exception as e:  # noqa: BLE001
            self._error = e
            self._ready.set()

    def call(self, tool: str, args: dict | None = None, timeout: float = 180) -> dict:
        if not self._ready.wait(timeout=30) or self._session is None:
            raise RuntimeError(f'Blender MCP server unavailable: {self._error!r}')
        with self._lock:
            fut = asyncio.run_coroutine_threadsafe(self._session.call_tool(tool, args or {}), self._loop)
            result = fut.result(timeout=timeout)
        texts = [c.text for c in result.content if getattr(c, 'type', '') == 'text']
        if getattr(result, 'is_error', None) or getattr(result, 'isError', None):
            raise RuntimeError(f"{tool} failed: {' '.join(texts)[:300]}")
        data = getattr(result, 'structured_content', None) or getattr(result, 'structuredContent', None)
        if data:
            return data.get('result', data) if isinstance(data, dict) else {'result': data}
        for t in texts:
            try:
                return json.loads(t)
            except ValueError:
                continue
        return {'text': ' '.join(texts)}


_client = None
_client_lock = threading.Lock()


def client() -> BlenderMCP:
    global _client
    with _client_lock:
        if _client is None:
            _client = BlenderMCP()
        return _client


def render_scene_preview(hid: str) -> dict:
    """Rebuild the current layout in Blender through MCP tools, validate it there, and render a PNG preview."""
    started = time.perf_counter()
    h = core.household(hid)
    room = h['room']
    objects = core.scene_objects(hid)
    b = client()
    b.call('reset_scene')
    b.call('create_room', {'width_m': room['width_m'], 'depth_m': room['depth_m'], 'height_m': room.get('height_m', 2.5),
                           'openings': [{k: o[k] for k in ('kind', 'wall', 'offset_m', 'width_m')} for o in room.get('openings', [])],
                           'clearances': room.get('clearances', [])})
    for o in objects:
        style = (catalog.get(o['product_id']) or {}).get('style') or {}
        override = textures.get(hid, o['object_id'])
        texture = ({'texture_path': override['image_path'], 'texture_mode': override.get('mode'),
                    'texture_tile_m': override.get('tile_m')} if override else
                   {k: style.get(k) for k in ('texture_path', 'texture_mode', 'texture_tile_m')})
        b.call('instantiate_furniture', {
            'object_id': o['object_id'], 'category': o['category'], 'dimensions_m': o['dimensions_m'],
            'color_hex': o['color_hex'] if o['color_hex'] and len(o['color_hex'].lstrip('#')) == 6 else None,
            'position_m': o['position_m'], 'rotation_y_rad': o['rotation_y_rad'], 'product_id': o['product_id'],
            **{k: v for k, v in texture.items() if v is not None}})
    validation = b.call('validate_scene')
    version = (core.current_proposal(hid) or {}).get('version', 0)
    name = f'{hid}-v{version}-{int(time.time())}.png'
    rendered = b.call('render_preview', {'filename': name, 'width_px': 640, 'height_px': 480, 'view': 'iso'})
    src = rendered.get('path') if isinstance(rendered, dict) else None
    if not src:
        src = str(config.REPO_DIR / 'integrations' / 'blender_mcp' / '.out' / 'previews' / name)
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy(src, PREVIEW_DIR / name)
    url = f'/uploads/previews/{name}'
    db.kv_set(f'preview:{hid}', {'url': url, 'proposal_version': version, 'validation': validation})
    with db.tx() as c:
        db.log(c, hid, 'Blender rendered a layout preview')
        db.bump(c, hid)
    db.record_timing('blender_preview', (time.perf_counter() - started) * 1000, f'objects={len(objects)}')
    return {'preview_url': url, 'blender_validation': validation}
