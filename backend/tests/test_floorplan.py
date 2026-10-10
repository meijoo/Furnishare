"""Floor-plan import and object textures. Gemini is replaced by a recorded read of a real 3-bedroom plan image."""
import json
import struct
import zlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import agent, apartment, assets, config, floorplan, textures
from app.main import app

READS = json.loads((Path(__file__).parent / 'fixtures' / 'floorplan_3bed_reads.json').read_text())
MEMBERS = ['emily', 'maya', 'alex']


def png(width: int = 909, height: int = 790) -> bytes:
    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body))
    rows = b''.join(b'\x00' + b'\xff\xff\xff' * width for _ in range(height))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b''))


def jpeg_header(width: int, height: int) -> bytes:
    sof = b'\xff\xc0' + struct.pack('>HBHH', 17, 8, height, width) + b'\x03' + b'\x00' * 9
    return b'\xff\xd8' + b'\xff\xe0' + struct.pack('>H', 16) + b'JFIF\x00' + b'\x00' * 9 + sof + b'\xff\xd9'


@pytest.mark.parametrize('text,expect', [
    ("13'x 12'", (13 * 0.3048, 12 * 0.3048)),
    ('12\'6" x 10\'', (12.5 * 0.3048, 10 * 0.3048)),
    ("14' x 10'", (14 * 0.3048, 10 * 0.3048)),
    ('4.2 x 3.6 m', (4.2, 3.6)),
    ('Closet', None),
    (None, None),
])
def test_parse_dimensions(text, expect):
    got = floorplan.parse_dimensions(text)
    assert got == expect if expect is None else got == pytest.approx(expect)


def test_image_size_png_and_jpeg():
    assert floorplan.image_size(png(40, 30)) == (40, 30)
    assert floorplan.image_size(jpeg_header(1200, 900)) == (1200, 900)
    with pytest.raises(floorplan.PlanError):
        floorplan.image_size(b'GIF89a....')


def test_build_plan_from_real_read():
    plan = floorplan.build_plan(READS, 909, 790, MEMBERS)
    rooms = {r['id']: r for r in plan['rooms']}
    assert plan['warnings'] == []
    assert 12 < plan['width_m'] < 14 and 9 < plan['depth_m'] < 10.5
    assert [rooms[f'bed-{m}']['household_id'] for m in MEMBERS] == [f'demo-bed-{m}' for m in MEMBERS]
    assert rooms['living']['household_id'] == 'demo' and rooms['living']['shared']
    assert rooms['kitchen-1']['shared'] and 'household_id' not in rooms['kitchen-1']
    for m in MEMBERS:
        r = rooms[f'bed-{m}']
        assert abs(r['width_m'] - r['interior_m']['width_m']) < 0.3
        assert abs(r['depth_m'] - r['interior_m']['depth_m']) < 0.3
    plan_rooms = plan['rooms']
    for i, a in enumerate(plan_rooms):
        for b in plan_rooms[i + 1:]:
            ox = min(a['x_m'] + a['width_m'], b['x_m'] + b['width_m']) - max(a['x_m'], b['x_m'])
            oz = min(a['z_m'] + a['depth_m'], b['z_m'] + b['depth_m']) - max(a['z_m'], b['z_m'])
            assert ox <= 0.15 or oz <= 0.15, (a['name'], b['name'])


def test_build_plan_needs_a_scale():
    unlabelled = [{**r, 'dimension_text': None} for r in READS]
    with pytest.raises(floorplan.PlanError):
        floorplan.build_plan(unlabelled, 909, 790, MEMBERS)
    plan = floorplan.build_plan(unlabelled, 909, 790, MEMBERS, plan_width_m=13.0)
    assert plan['width_m'] == pytest.approx(13.0, abs=0.1)


def test_extra_and_tiny_bedrooms_are_flagged():
    extra = READS + [{'label': 'Den', 'kind': 'bedroom', 'dimension_text': "11'x 10'", 'box_2d': [910, 110, 990, 300]}]
    plan = floorplan.build_plan(extra, 909, 790, MEMBERS)
    assert sum(1 for r in plan['rooms'] if r.get('household_id', '').startswith('demo-bed-')) == 3
    assert any('Den' in w for w in plan['warnings'])


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(floorplan, 'extract', lambda data, mime: READS)
    monkeypatch.setattr(agent, 'available', lambda: True)
    with TestClient(app) as c:
        c.delete('/apartments/demo/floorplan')
        c.post('/demo/reset')
        yield c
        c.delete('/apartments/demo/floorplan')


def test_import_reseeds_bedrooms_at_plan_size(client):
    r = client.post('/apartments/demo/floorplan', files={'file': ('plan.png', png(), 'image/png')})
    assert r.status_code == 200, r.text
    body = r.json()
    a = body['apartment']
    assert a['source'] == 'imported' and a['image_url'].startswith('/uploads/')
    assert a['image_frame_m']['width_m'] > a['width_m'] - 0.5
    for m in MEMBERS:
        assert body['seeded'][f'bed-{m}']['ok'], body['seeded']
        state = client.get(f'/households/demo-bed-{m}/state').json()
        room = next(x for x in a['rooms'] if x['id'] == f'bed-{m}')
        assert state['room']['width_m'] == room['interior_m']['width_m']
        assert state['room']['depth_m'] == room['interior_m']['depth_m']
        assert state['scene']['validation']['ok'], state['scene']['validation']
    assert client.get('/apartments/demo').json()['source'] == 'imported'

    restored = client.delete('/apartments/demo/floorplan').json()
    assert restored['source'] == 'built_in' and restored['width_m'] == apartment.WIDTH_M
    assert client.get('/households/demo-bed-emily/state').json()['room']['width_m'] == apartment.BEDROOM_SIZE


def test_import_rejects_bad_uploads(client, monkeypatch):
    assert client.post('/apartments/demo/floorplan', files={'file': ('x.gif', b'GIF89a', 'image/gif')}).status_code == 415
    assert client.post('/apartments/nope/floorplan', files={'file': ('p.png', png(), 'image/png')}).status_code == 404
    monkeypatch.setattr(agent, 'available', lambda: False)
    assert client.post('/apartments/demo/floorplan', files={'file': ('p.png', png(), 'image/png')}).status_code == 503


def test_texture_upload_and_delete(client):
    objects = client.get('/households/demo/state').json()['scene']['objects']
    oid = objects[0]['object_id']
    assert client.post('/households/demo/scene/objects/nope/texture',
                       files={'file': ('t.png', png(8, 8), 'image/png')}).status_code == 404
    assert client.post(f'/households/demo/scene/objects/{oid}/texture', data={'mode': 'shiny'},
                       files={'file': ('t.png', png(8, 8), 'image/png')}).status_code == 422
    r = client.post(f'/households/demo/scene/objects/{oid}/texture', data={'mode': 'print'},
                    files={'file': ('t.png', png(8, 8), 'image/png')})
    assert r.status_code == 200, r.text
    assert r.json()['texture']['image_url'].startswith('/uploads/')
    obj = next(o for o in client.get('/households/demo/state').json()['scene']['objects'] if o['object_id'] == oid)
    assert obj['texture']['status'] == 'unavailable'
    assert client.delete(f'/households/demo/scene/objects/{oid}/texture').status_code == 200
    obj = next(o for o in client.get('/households/demo/state').json()['scene']['objects'] if o['object_id'] == oid)
    assert 'texture' not in obj
    assert client.delete(f'/households/demo/scene/objects/{oid}/texture').status_code == 404


def test_textured_asset_swaps_in_when_built(client, tmp_path, monkeypatch):
    objects = client.get('/households/demo/state').json()['scene']['objects']
    oid = objects[0]['object_id']
    client.post(f'/households/demo/scene/objects/{oid}/texture', files={'file': ('t.png', png(8, 8), 'image/png')})
    requested = []
    monkeypatch.setattr(assets, 'available', lambda: True)
    monkeypatch.setattr(textures, '_key', lambda product: 'f' * 24)
    monkeypatch.setattr(assets, 'request_variant', lambda product, hid: requested.append(product['id']))
    monkeypatch.setattr(config, 'ASSETS_DIR', tmp_path)
    obj = next(o for o in client.get('/households/demo/state').json()['scene']['objects'] if o['object_id'] == oid)
    assert obj['texture']['status'] == 'building' and requested
    (tmp_path / f"{'f' * 24}.usdz").write_bytes(b'usdz')
    obj = next(o for o in client.get('/households/demo/state').json()['scene']['objects'] if o['object_id'] == oid)
    assert obj['texture']['status'] == 'ready' and obj['asset_url'] == f"/assets/{'f' * 24}.usdz"
    textures.delete('demo', oid)
