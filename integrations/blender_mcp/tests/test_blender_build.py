"""End-to-end Blender tests: build every category at several sizes, then re-open the exported USDZ in a
separate, fresh Blender process (pxr) and check the measured bbox against the requested dimensions."""
import json
import math
import os
import signal
import subprocess
import time
import zipfile
from pathlib import Path

import pytest

from blender_mcp import assets, specs, worker_client
import pngutil

pytestmark = pytest.mark.blender
TOL_M = 0.001

CASES = [
    ("sofa", {"width": 2.28, "depth": 0.95, "height": 0.83}, {"material": "fabric"}),
    ("sofa", {"width": 0.6, "depth": 0.5, "height": 0.4}, {"material": "leather", "frame_finish": "metal"}),
    ("sofa", {"width": 5.0, "depth": 2.0, "height": 1.1}, {"frame_finish": "upholstered", "material": "wool"}),
    ("coffee_table", {"width": 1.0, "depth": 0.55, "height": 0.42}, {"material": "wood"}),
    ("coffee_table", {"width": 0.45, "depth": 0.45, "height": 0.25}, {"material": "metal", "color_hex": "#202020"}),
    ("tv", {"width": 1.12, "depth": 0.22, "height": 0.7}, {}),
    ("tv", {"width": 1.95, "depth": 0.35, "height": 1.2}, {"color_hex": "#E0E0E0"}),
    ("rug", {"width": 2.3, "depth": 1.6, "height": 0.015}, {"material": "wool"}),
    ("rug", {"width": 1.2, "depth": 0.8, "height": 0.01}, {"color_hex": "#1A1A1A"}),
    ("rug", {"width": 0.01, "depth": 0.01, "height": 0.01}, {}),  # minimum allowed size still exact
    ("bed", {"width": 1.65, "depth": 2.12, "height": 1.1}, {}),
    ("bed", {"width": 1.45, "depth": 2.05, "height": 0.95}, {"material": "wood", "color_hex": "#8A6748"}),
    ("bed", {"width": 0.6, "depth": 1.2, "height": 0.2}, {"frame_finish": "upholstered"}),
    ("bed", {"width": 2.2, "depth": 2.4, "height": 1.4}, {"frame_finish": "metal"}),
    ("nightstand", {"width": 0.45, "depth": 0.4, "height": 0.55}, {}),
    ("nightstand", {"width": 0.2, "depth": 0.2, "height": 0.2}, {}),
    ("nightstand", {"width": 0.45, "depth": 0.45, "height": 0.55}, {"shape": "round"}),
    ("nightstand", {"width": 0.2, "depth": 0.2, "height": 0.2}, {"shape": "round"}),
    ("dresser", {"width": 1.6, "depth": 0.48, "height": 0.78}, {}),
    ("dresser", {"width": 0.4, "depth": 0.25, "height": 0.3}, {"frame_finish": "metal"}),
    ("dresser", {"width": 2.6, "depth": 0.9, "height": 1.8}, {"color_hex": "#F2EFEA"}),
    ("desk", {"width": 1.4, "depth": 0.65, "height": 0.75}, {}),
    ("desk", {"width": 0.5, "depth": 0.3, "height": 0.4}, {"frame_finish": "metal"}),
    ("desk", {"width": 2.6, "depth": 1.4, "height": 1.3}, {}),
    ("coffee_table", {"width": 0.7, "depth": 0.7, "height": 0.42}, {"shape": "round"}),
    ("coffee_table", {"width": 0.05, "depth": 0.05, "height": 0.05}, {"shape": "round", "material": "metal"}),
    ("rug", {"width": 1.6, "depth": 1.6, "height": 0.015}, {"shape": "round"}),
    ("lamp", {"width": 0.35, "depth": 0.35, "height": 0.58}, {"color_hex": "#3F7A45"}),
    ("lamp", {"width": 0.28, "depth": 0.28, "height": 1.55}, {"form": {"kind": "floor"}}),
    ("lamp", {"width": 0.18, "depth": 0.18, "height": 0.42}, {"form": {"kind": "desk"}}),
    ("lamp", {"width": 0.14, "depth": 0.14, "height": 0.28}, {"form": {"kind": "accent"}}),
    ("lamp", {"width": 0.42, "depth": 0.78, "height": 1.80}, {"form": {"kind": "arc"}}),
    ("lamp", {"width": 0.32, "depth": 0.32, "height": 1.82}, {"form": {"kind": "torchiere"}}),
    ("lamp", {"width": 0.35, "depth": 0.35, "height": 0.58},
     {"form": {"kind": "table", "shade": "mushroom", "base": "gourd"}}),
]
NEW_TOL_M = 0.0005
BEDROOM_CATEGORIES = {"bed", "nightstand", "dresser", "desk"}
NEW_CASES = [i for i, (c, _, x) in enumerate(CASES)
             if c in BEDROOM_CATEGORIES or c == "lamp" or x.get("shape") == "round"]
ROOM = {"width_m": 4.5, "depth_m": 4.0, "height_m": 2.5, "wall_thickness_m": 0.12,
        "openings": [{"kind": "door", "wall": "front", "offset_m": 1.0, "width_m": 0.9},
                     {"kind": "window", "wall": "left", "offset_m": -0.4, "width_m": 1.4},
                     {"kind": "window", "wall": "back", "offset_m": 0.0, "width_m": 1.8, "sill_m": 0.6, "height_m": 1.5}]}


def measure_fresh(blender_bin, paths):
    """Independent measurement in a new Blender process (not the one that exported)."""
    out = subprocess.run([blender_bin, "--background", "--factory-startup", "--python",
                          str(worker_client.BLENDER_DIR / "measure_usd.py"), "--", *map(str, paths)],
                         capture_output=True, text=True, timeout=120)
    line = next(l for l in out.stdout.splitlines() if l.startswith("R2R_MEASURE "))
    return json.loads(line[len("R2R_MEASURE "):])


@pytest.fixture(scope="module")
def worker(blender_bin, tmp_path_factory):
    root = tmp_path_factory.mktemp("assets")
    w = worker_client.BlenderWorker(allowed_roots=[root], state_file=None)
    w.request("ping")
    w.root = root
    yield w
    w.stop()


@pytest.fixture(scope="module")
def built(worker, blender_bin):
    results = []
    for i, (cat, dims, extra) in enumerate(CASES):
        spec = dict({"category": cat, "dimensions_m": dims}, **extra)
        path = worker.root / f"{cat}_{i}.usdz"
        r = worker.request("build_asset", {"spec": spec, "usdz_path": str(path)})
        results.append((cat, dims, path, r))
    room_path = worker.root / "room.usdz"
    room_r = worker.request("build_asset", {"room": ROOM, "usdz_path": str(room_path)})
    measured = measure_fresh(blender_bin, [p for *_, p, _ in results] + [room_path])
    return results, (room_path, room_r), measured


def _case_id(c, d, x):
    return f"{c}{'-round' if x.get('shape') == 'round' else ''}-{d['width']}x{d['depth']}x{d['height']}"


@pytest.mark.parametrize("i", range(len(CASES)), ids=[_case_id(*c) for c in CASES])
def test_exported_bbox_matches_dimensions(built, i):
    results, _, measured = built
    cat, dims, path, r = results[i]
    m = measured[str(path)]
    w, d, h = dims["width"], dims["depth"], dims["height"]
    assert m["up_axis"] == "Y" and m["meters_per_unit"] == 1.0 and m["default_prim"] == "/root"
    assert m["preview_surface_count"] >= 1 and m["mesh_count"] >= 1
    for got, want in zip(m["min"] + m["max"], [-w / 2, 0.0, -d / 2, w / 2, h, d / 2]):
        assert abs(got - want) <= TOL_M, (cat, dims, m["min"], m["max"])
    assert r["max_abs_error_m"] <= TOL_M


@pytest.mark.parametrize("i", NEW_CASES, ids=[_case_id(*CASES[i]) for i in NEW_CASES])
def test_bedroom_and_round_fit_natively_within_half_mm(built, i):
    """Measured in a fresh process within 0.5 mm, and the template itself fills the box (no snap distortion)."""
    results, _, measured = built
    cat, dims, path, r = results[i]
    m = measured[str(path)]
    w, d, h = dims["width"], dims["depth"], dims["height"]
    for got, want in zip(m["min"] + m["max"], [-w / 2, 0.0, -d / 2, w / 2, h, d / 2]):
        assert abs(got - want) <= NEW_TOL_M, (cat, dims, m["min"], m["max"])
    assert r["template_fit_error_m"] <= NEW_TOL_M, (cat, dims, r["template_fit_error_m"])


def _boxes(built, i):
    results, _, measured = built
    return results[i][1], measured[str(results[i][2])]["material_bboxes"]


def test_bed_headboard_at_back_and_tallest(built):
    for i, (cat, _, extra) in enumerate(CASES):
        if cat != "bed":
            continue
        dims, boxes = _boxes(built, i)
        frame = next(v for k, v in boxes.items() if k.lower().endswith(
            specs.furniture_spec(dict({"category": "bed", "dimensions_m": dims}, **extra))["color_hex"][1:].lower()))
        pillows = next(v for k, v in boxes.items() if "f7f5f0" in k.lower())
        blanket = next(v for k, v in boxes.items() if "wool" in k.lower())
        assert abs(frame["max"][1] - dims["height"]) <= TOL_M, "headboard sets the height"
        assert pillows["max"][1] < dims["height"] and blanket["max"][1] < dims["height"]
        assert pillows["min"][2] < 0 and (pillows["min"][2] + pillows["max"][2]) / 2 < -dims["depth"] * 0.25, \
            "pillows sit against the headboard at -Z"
        assert (blanket["min"][2] + blanket["max"][2]) / 2 > 0, "blanket covers the foot end at +Z"


@pytest.mark.parametrize("cat", ["nightstand", "dresser", "desk"])
def test_drawer_handles_face_plus_z(built, cat):
    i = next(i for i, (c, _, x) in enumerate(CASES) if c == cat and not x)
    dims, boxes = _boxes(built, i)
    handles = next(v for k, v in boxes.items() if "metal" in k.lower())
    overhang = 0.03 if cat == "desk" else 0.0  # the desk top overhangs its drawer pedestal
    assert abs(handles["max"][2] - (dims["depth"] / 2 - overhang)) <= TOL_M, "handles sit on the front (+Z) face"
    assert handles["min"][2] > dims["depth"] / 2 - overhang - 0.05


def test_round_shapes_have_no_corners(built):
    results, _, measured = built
    for (cat, dims, path, _), (_, _, extra) in zip(results, CASES):
        radius = measured[str(path)]["max_radius_xz"]
        if extra.get("shape") == "round":
            assert abs(radius - dims["width"] / 2) <= TOL_M, (cat, dims, radius)
        elif cat in specs.ROUND_CATEGORIES and min(dims["width"], dims["depth"]) >= 0.1:  # bevels round tiny boxes
            assert radius > math.hypot(dims["width"], dims["depth"]) / 2 * 0.95, (cat, dims, radius)


def test_tv_screen_faces_plus_z(built):
    results, _, measured = built
    for cat, dims, path, _ in results:
        if cat != "tv":
            continue
        boxes = measured[str(path)]["material_bboxes"]
        screen = next(v for k, v in boxes.items() if "screen" in k)
        center_z = (screen["min"][2] + screen["max"][2]) / 2
        assert center_z > 0, "screen should be on the +Z (front) side"
        assert screen["max"][2] <= dims["depth"] / 2 + TOL_M


def test_sofa_legs_on_floor_and_back_at_minus_z(built):
    results, _, measured = built
    cat, dims, path, _ = results[0]
    boxes = measured[str(path)]["material_bboxes"]
    legs = next(v for k, v in boxes.items() if "wood" in k)
    assert abs(legs["min"][1]) <= TOL_M and legs["max"][1] < dims["height"] * 0.5


def test_room_bbox(built):
    _, (room_path, r), measured = built
    m = measured[str(room_path)]
    t = ROOM["wall_thickness_m"]
    want = [-ROOM["width_m"] / 2 - t, 0.0, -ROOM["depth_m"] / 2 - t,
            ROOM["width_m"] / 2 + t, ROOM["height_m"], ROOM["depth_m"] / 2 + t]
    for got, exp in zip(m["min"] + m["max"], want):
        assert abs(got - exp) <= TOL_M
    assert m["mesh_count"] == 5 and r["max_abs_error_m"] <= TOL_M


def test_scene_commands_and_preview(worker):
    worker.request("reset_scene")
    worker.request("create_room", ROOM)
    worker.request("instantiate_furniture", {"object_id": "sofa", "position_m": [0, 0, -1.4],
                                             "spec": {"category": "sofa", "dimensions_m": CASES[0][1]}})
    worker.request("instantiate_furniture", {"object_id": "table", "position_m": [0, 0, -0.4],
                                             "spec": {"category": "coffee_table", "dimensions_m": CASES[3][1]}})
    assert worker.request("validate_scene") == {"ok": True, "issues": []}
    worker.request("set_transform", {"object_id": "table", "position_m": [0, 0, -1.2]})
    v = worker.request("validate_scene")
    assert not v["ok"] and v["issues"][0]["code"] == "overlap"
    r = worker.request("set_dimensions_and_material", {"object_id": "sofa", "material": "leather",
                                                       "dimensions_m": {"width": 1.8, "depth": 0.9, "height": 0.8}})
    assert r["dimensions_m"]["width"] == 1.8 and r["position_m"] == [0, 0, -1.4]
    e = worker.request("export_asset", {"target": "sofa", "path": str(worker.root / "scene_sofa.usdz")})
    assert e["max_abs_error_m"] <= TOL_M  # exported in canonical pose despite its scene transform
    png = worker.root / "preview.png"
    worker.request("render_preview", {"path": str(png), "width_px": 160, "height_px": 120})
    assert png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    glb = worker.root / "scene.glb"
    worker.request("export_asset", {"target": "scene", "path": str(glb), "format": "glb"})
    assert glb.read_bytes()[:4] == b"glTF"


@pytest.mark.parametrize("cmd,params,err", [
    ("exec", {"code": "import os"}, "unknown_command"),
    ("instantiate_furniture", {"object_id": "x", "spec": {"category": "sofa",
                               "dimensions_m": {"width": 6, "depth": 1, "height": 1}}}, "validation"),
    ("instantiate_furniture", {"object_id": "x", "spec": {"category": "sofa",
                               "dimensions_m": {"width": 1, "depth": 1, "height": 1}}, "extra": 1}, "validation"),
    ("export_asset", {"target": "scene", "path": "/etc/x.usdz"}, "forbidden"),
    ("export_asset", {"target": "scene", "path": "relative.usdz"}, "validation"),
    ("render_preview", {"path": "/tmp/x.png", "width_px": 5000}, None),
    ("set_transform", {"object_id": "missing", "position_m": [0, 0, 0]}, "not_found"),
    ("set_transform", {"object_id": "sofa", "position_m": [0, 0, 1e9]}, "validation"),
])
def test_worker_rejects_bad_requests(worker, cmd, params, err):
    with pytest.raises(worker_client.WorkerError) as exc:
        worker.request(cmd, params)
    if err:
        assert exc.value.type == err


def test_plain_exports_embed_procedural_surface_textures(built):
    """No photo texture: every build still carries baked procedural images (wood grain, weave...) in the package."""
    results, _, measured = built
    for cat, dims, path, r in results:
        m = measured[str(path)]
        names = zipfile.ZipFile(path).namelist()
        images = {n for n in names if n.lower().endswith((".jpg", ".png"))}
        assert "texture" not in r and images and all(n.startswith("textures/") for n in images), (cat, dims, names)
        assert {t["file"] for t in m["textures"]} == {"./" + n for n in images}, (cat, dims)
        assert all(t["wrap"] == "repeat" for t in m["textures"])
        assert not any("r2r_tex_" in n for n in images)
        main = r["main_surface"]
        assert main in specs.SURFACES and main in r["surfaces"], (cat, r["surfaces"])
        assert path.stat().st_size < 1.5 * 1024 * 1024 and m["triangles"] < 60000, (cat, dims)


# ---------------------------------------------------------------- image textures

TEX_BORDER_PX = 40
SAMPLE_SCRIPT = r"""
import bpy, json, os, sys
import numpy as np
out = {}
for p in sys.argv[sys.argv.index("--") + 1:]:
    img = bpy.data.images.load(p)
    w, h = img.size
    a = np.empty(w * h * 4, np.float32)
    img.pixels.foreach_get(a)
    a = (a.reshape(h, w, 4)[::-1, :, :3] * 255).round()   # rows top-to-bottom
    def at(u, v):
        return a[min(h - 1, int(v * h)), min(w - 1, int(u * w))].tolist()
    ring = np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]])
    out[p] = {"size": [w, h], "top_left": at(0.08, 0.08), "top_right": at(0.92, 0.08),
              "bottom_left": at(0.08, 0.92), "bottom_right": at(0.92, 0.92),
              "ring_white_fraction": float((ring.min(axis=1) > 225).mean())}
print("R2R_SAMPLE " + json.dumps(out))
sys.stdout.flush()
os._exit(0)
"""


def sample_images(blender_bin, paths):
    out = subprocess.run([blender_bin, "--background", "--factory-startup", "--python-expr", SAMPLE_SCRIPT, "--",
                          *map(str, paths)], capture_output=True, text=True, timeout=120)
    line = next(l for l in out.stdout.splitlines() if l.startswith("R2R_SAMPLE "))
    return json.loads(line[len("R2R_SAMPLE "):])


def _wide_stripes(path):
    return pngutil.write_png(path, 2600, 416, lambda x, y: (200, 60, 50) if (x // 100) % 2 else (40, 60, 120))


@pytest.fixture(scope="module")
def textured(worker, blender_bin, tmp_path_factory):
    src = tmp_path_factory.mktemp("texture_src")
    quad = pngutil.bordered_quadrants(src / "quad.png", 400, 300, TEX_BORDER_PX)
    medallion = pngutil.bordered_medallion(src / "medallion.png", 300, 300, 30)
    swatch = pngutil.swatch(src / "swatch.png")
    cases = {
        "rug_print": {"category": "rug", "dimensions_m": {"width": 1.6, "depth": 1.1, "height": 0.015},
                      "texture": {"path": str(quad)}},
        "rug_round": {"category": "rug", "shape": "round", "dimensions_m": {"width": 1.6, "depth": 1.6, "height": 0.015},
                      "texture": {"path": str(medallion)}},
        "rug_wide": {"category": "rug", "dimensions_m": {"width": 5.0, "depth": 0.8, "height": 0.01},
                     "texture": {"path": str(_wide_stripes(src / "wide.png"))}},
        "sofa_tile": {"category": "sofa", "dimensions_m": CASES[0][1], "texture": {"path": str(swatch)}},
        "table_tile": {"category": "coffee_table", "dimensions_m": CASES[3][1], "material": "wood",
                       "texture": {"path": str(swatch), "tile_m": 0.2}},
    }
    results = {}
    for name, spec in cases.items():
        path = worker.root / f"tex_{name}.usdz"
        results[name] = (spec, path, worker.request("build_asset", {"spec": spec, "usdz_path": str(path)}))
    measured = measure_fresh(blender_bin, [p for _, p, _ in results.values()])
    extracted = {}
    for name, (_, path, _) in results.items():
        with zipfile.ZipFile(path) as z:
            images = [n for n in z.namelist() if "r2r_tex_" in n]
            if images:
                extracted[name] = Path(z.extract(images[0], worker.root / f"x_{name}"))
    samples = sample_images(blender_bin, list(extracted.values()))
    return results, measured, {k: samples[str(p)] for k, p in extracted.items()}


@pytest.mark.parametrize("name", ["rug_print", "rug_round", "rug_wide", "sofa_tile", "table_tile"])
def test_textured_usdz_embeds_image_and_keeps_bbox(textured, name):
    results, measured, _ = textured
    spec, path, r = results[name]
    m = measured[str(path)]
    w, d, h = (spec["dimensions_m"][k] for k in ("width", "depth", "height"))
    for got, want in zip(m["min"] + m["max"], [-w / 2, 0.0, -d / 2, w / 2, h, d / 2]):
        assert abs(got - want) <= NEW_TOL_M, (name, m["min"], m["max"])
    assert r["max_abs_error_m"] <= NEW_TOL_M and m["preview_surface_count"] >= 1
    names = zipfile.ZipFile(path).namelist()
    photo = [n for n in names if "r2r_tex_" in n]
    assert len(photo) == 1 and names[0].endswith(".usdc"), names  # USDZ: the layer comes first
    files = {t["file"]: t["wrap"] for t in m["textures"]}
    assert set(files) == {"./" + n for n in names if n.lower().endswith((".jpg", ".jpeg", ".png"))}, files
    assert files["./" + photo[0]] == ("clamp" if spec["category"] == "rug" else "repeat")  # relative path inside
    assert all(v == "repeat" for k, v in files.items() if "r2r_tex_" not in k), "procedural images repeat"
    assert path.stat().st_size < 3 * 1024 * 1024
    assert r["texture"]["mode"] == ("print" if spec["category"] == "rug" else "tile")


def test_print_rug_trims_white_border_and_stays_upright(textured):
    results, measured, samples = textured
    _, path, r = results["rug_print"]
    tex = r["texture"]
    assert tex["source_px"] == [400, 300] and not tex["rotated"]
    assert all(TEX_BORDER_PX <= v <= TEX_BORDER_PX + 4 for v in tex["trim_px"].values()), tex["trim_px"]
    s = samples["rug_print"]
    assert s["ring_white_fraction"] < 0.02, "the white backdrop must be cropped out of the embedded texture"
    for corner, rgb in pngutil.QUADRANTS.items():
        assert max(abs(a - b) for a, b in zip(s[corner], rgb)) <= 40, (corner, s[corner], rgb)
    # Image top edge maps to the rug's back edge (-Z): v=1 at the back, u=0 on the left.
    uv = measured[str(path)]["uv_top_corners"]
    for corner, want in {"back_left": (0, 1), "back_right": (1, 1), "front_left": (0, 0), "front_right": (1, 0)}.items():
        assert max(abs(a - b) for a, b in zip(uv[corner], want)) <= 0.01, (corner, uv[corner])
    edge = next(k for k in measured[str(path)]["material_bboxes"] if tex["average_hex"][1:].lower() in k.lower())
    assert edge, "rug sides use a plain material in the image's average color"


def test_round_print_rug_maps_inscribed_disk(textured):
    results, measured, samples = textured
    spec, path, r = results["rug_round"]
    m = measured[str(path)]
    assert abs(m["max_radius_xz"] - spec["dimensions_m"]["width"] / 2) <= TOL_M
    assert r["texture"]["output_px"][0] == r["texture"]["output_px"][1], "square crop for a round rug"
    assert samples["rug_round"]["ring_white_fraction"] < 0.02
    (u0, v0), (u1, v1) = m["st_extent"]
    assert -0.01 <= u0 and u1 <= 1.01 and -0.01 <= v0 and v1 <= 1.01 and u1 - u0 > 0.98 and v1 - v0 > 0.98


def test_large_print_texture_is_downscaled(textured):
    results, _, samples = textured
    tex = results["rug_wide"][2]["texture"]
    assert tex["source_px"] == [2600, 416] and max(tex["output_px"]) <= 2048
    assert samples["rug_wide"]["size"] == tex["output_px"]
    assert abs(tex["output_px"][0] / tex["output_px"][1] - 5.0 / 0.8) < 0.05  # cover-fit to the footprint


@pytest.mark.parametrize("name,tile_m", [("sofa_tile", 0.3), ("table_tile", 0.2)])
def test_tile_texture_is_world_scale_on_primary_surfaces_only(textured, name, tile_m):
    results, measured, _ = textured
    spec, path, r = results[name]
    m = measured[str(path)]
    dims = spec["dimensions_m"]
    tex_mat = next(k for k in m["st_extent_by_material"] if r["texture"]["image_name"].lower() in k.lower())
    (u0, _), (u1, _) = m["st_extent_by_material"][tex_mat]
    span_m = (u1 - u0) * tile_m  # one UV unit is one tile, so the span in meters is the widest projected face
    assert max(dims["width"], dims["depth"]) - 0.05 <= span_m <= max(dims["width"], dims["depth"]) + TOL_M, span_m
    assert r["texture"]["tile_m"] == tile_m
    boxes = m["material_bboxes"]
    tex_box = boxes[tex_mat]
    plain = [v for k, v in boxes.items() if r["texture"]["image_name"].lower() not in k.lower()]
    assert abs(tex_box["max"][1] - dims["height"]) <= TOL_M, "top/upholstery is textured"
    assert tex_box["min"][1] > 0.01, "legs are not textured"
    assert any(abs(v["min"][1]) <= TOL_M for v in plain), "legs keep a plain material on the floor"


def test_worker_texture_commands(worker, tmp_path):
    png = pngutil.swatch(tmp_path / "s.png", 32)
    worker.request("reset_scene")
    o = worker.request("instantiate_furniture", {"object_id": "tsofa", "spec": {
        "category": "sofa", "dimensions_m": CASES[0][1], "texture": {"path": str(png)}}})
    assert o["texture"] == {"path": str(png), "mode": "tile", "tile_m": 0.3}
    o = worker.request("set_dimensions_and_material", {"object_id": "tsofa", "texture": {"tile_m": 0.5}})
    assert o["texture"] == {"path": str(png), "mode": "tile", "tile_m": 0.5}
    out = worker.root / "tex_preview.png"
    worker.request("render_preview", {"path": str(out), "width_px": 96, "height_px": 64, "target": "tsofa"})
    assert out.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    e = worker.request("export_asset", {"target": "tsofa", "path": str(worker.root / "tex_scene_sofa.usdz")})
    photo = [t for t in e["measured_bbox_m"]["textures"] if "r2r_tex_" in t["file"]]
    assert e["max_abs_error_m"] <= TOL_M and len(photo) == 1
    o = worker.request("set_dimensions_and_material", {"object_id": "tsofa", "form": {"arm_style": "rolled"}})
    assert o["form"] == {"arm_style": "rolled"} and o["texture"]["tile_m"] == 0.5
    assert worker.request("set_dimensions_and_material", {"object_id": "tsofa", "form": {}})["form"] == {}
    assert worker.request("set_dimensions_and_material", {"object_id": "tsofa", "clear_texture": True})["texture"] is None
    for params in ({"texture": {"path": str(tmp_path / "missing.png")}},
                   {"texture": {"path": str(png)}, "clear_texture": True}, {"texture": "x"},
                   {"form": {"arm_style": "spaceship"}}, {"form": {"headboard": "tufted"}}, {"form": "rolled"}):
        with pytest.raises(worker_client.WorkerError) as exc:
            worker.request("set_dimensions_and_material", dict(params, object_id="tsofa"))
        assert exc.value.type == "validation"
    worker.request("reset_scene")


def test_ensure_asset_textured_rug(blender_bin, tmp_path, monkeypatch):
    monkeypatch.setattr(worker_client.BlenderWorker, "attach", classmethod(lambda cls, *a, **k: None))
    img = pngutil.bordered_quadrants(tmp_path / "rug.png", 200, 150, 20)
    product = {"id": "rug-x", "category": "rug", "dimensions_m": {"width": 1.6, "depth": 1.2, "height": 0.01},
               "style": {"color_hex": "#B7AE9C", "texture_path": str(img)}}
    p = assets.ensure_asset(product, tmp_path / "out")
    assert p is not None and p.name == f"{assets.asset_key(product)}.usdz"
    assert p.name != f"{assets.asset_key(dict(product, style={'color_hex': '#B7AE9C'}))}.usdz"
    assert any(n.startswith("textures/") for n in zipfile.ZipFile(p).namelist())


def test_worker_rejects_bad_token(worker):
    resp = worker_client._send(worker.port, {"id": 1, "token": "wrong", "cmd": "ping", "params": {}}, 5)
    assert resp["ok"] is False and resp["error"]["type"] == "auth"


def test_worker_restarts_after_crash(blender_bin, tmp_path):
    w = worker_client.BlenderWorker(allowed_roots=[tmp_path], state_file=None)
    try:
        pid = w.request("ping")["pid"]
        os.kill(pid, signal.SIGKILL)
        w.proc.wait(10)
        r = w.request("ping")
        assert r["pid"] != pid and w.restarts == 1
    finally:
        w.stop()


def test_ensure_asset_one_shot_then_cached(blender_bin, tmp_path, monkeypatch):
    monkeypatch.setattr(worker_client.BlenderWorker, "attach", classmethod(lambda cls, *a, **k: None))
    product = {"id": "ikea-kivik", "variant": "beige", "category": "sofa",
               "dimensions_m": {"width": 2.28, "depth": 0.95, "height": 0.83},
               "style": {"color_hex": "#C9BFAE", "material": "fabric"}}
    t0 = time.perf_counter()
    p = assets.ensure_asset(product, tmp_path)
    cold = time.perf_counter() - t0
    assert p == tmp_path.resolve() / f"{assets.asset_key(product)}.usdz" and p.is_file()
    t0 = time.perf_counter()
    assert assets.ensure_asset(product, tmp_path) == p
    assert time.perf_counter() - t0 < 0.5 < cold
    m = measure_fresh(blender_bin, [p])[str(p)]
    assert abs(m["size"][0] - 2.28) <= TOL_M and abs(m["size"][1] - 0.83) <= TOL_M and abs(m["size"][2] - 0.95) <= TOL_M
    assert assets.ensure_asset(dict(product, dimensions_m=None), tmp_path) is None
    assert not list(tmp_path.glob(".r2r-*")), "temp export dirs must be cleaned up"


# ---------------------------------------------------------------- form parameters + procedural surfaces

def _f(cat, dims, material=None, color=None, shape=None, **form):
    spec = {"category": cat, "dimensions_m": dict(zip(("width", "depth", "height"), dims))}
    for k, v in (("material", material), ("color_hex", color), ("shape", shape)):
        if v is not None:
            spec[k] = v
    if form:
        spec["form"] = form
    return spec


FORM_CASES = {
    "sofa_track_pillow_linen": _f("sofa", (2.2, 0.95, 0.85), "fabric", "#C9C0AE", arm_style="track",
                                  back_style="pillow", leg_style="tapered", surface="linen"),
    "sofa_rolled_tufted_velvet": _f("sofa", (2.1, 0.92, 0.82), "fabric", "#2F4A3A", arm_style="rolled",
                                    back_style="tufted", leg_style="bun", surface="velvet"),
    "sofa_chaise_left": _f("sofa", (2.6, 1.6, 0.8), "leather", "#8A5A3A", arm_style="sloped", back_style="channel",
                           leg_style="metal", chaise="left", surface="leather"),
    "sofa_chaise_right_min": _f("sofa", (0.6, 0.5, 0.4), "fabric", "#7A6A5A", arm_style="flared", chaise="right",
                                skirt=True, tufted_seat=True, seat_cushions=4, back_cushions=0, leg_style="hidden",
                                surface="chenille"),
    "sofa_none_max": _f("sofa", (5.0, 2.0, 1.1), "fabric", "#EDE6DA", arm_style="none", back_style="pillow",
                        back_cushions=4, seat_cushions=1, leg_style="block", surface="boucle"),
    "sofa_faux": _f("sofa", (1.9, 0.9, 0.8), "leather", "#202020", surface="faux_leather", skirt=True),
    "coffee_hairpin_glass": _f("coffee_table", (1.2, 0.6, 0.42), "wood", "#5C3D28", leg_style="hairpin",
                               top_style="glass", surface="walnut"),
    "coffee_round_pedestal_marble": _f("coffee_table", (0.9, 0.9, 0.42), "wood", "#E8E4DE", "round",
                                       leg_style="pedestal", top_style="stone", surface="marble"),
    "coffee_sled_small": _f("coffee_table", (0.45, 0.45, 0.25), "metal", "#C8C8C8", leg_style="sled", shelf=True,
                            drawer=True, surface="brushed_metal"),
    "coffee_round_x_lift": _f("coffee_table", (0.7, 0.7, 0.42), "wood", "#9A7B5A", "round", leg_style="x_base",
                              top_style="lift_top", surface="pine"),
    "coffee_round_tiny": _f("coffee_table", (0.05, 0.05, 0.05), "wood", None, "round", leg_style="hairpin",
                            shelf=True, drawer=True),
    "coffee_panel_lacquer": _f("coffee_table", (1.0, 0.55, 0.42), "wood", "#B03030", leg_style="panel",
                               shelf=False, surface="lacquer"),
    "tv_frame_feet": _f("tv", (1.45, 0.06, 0.88), "metal", "#1A1A1A", bezel="frame", stand="feet"),
    "tv_pedestal": _f("tv", (1.12, 0.22, 0.7), bezel="thin", stand="pedestal"),
    "tv_wall_max": _f("tv", (1.95, 0.35, 1.2), "metal", "#E0E0E0", stand="none", bezel="frame"),
    "rug_fringe_high": _f("rug", (2.4, 1.7, 0.03), "wool", "#B8A890", fringe=True, pile="high", surface="wool"),
    "rug_flat": _f("rug", (1.2, 0.8, 0.01), "wool", "#506070", pile="flat"),
    "rug_round_fringe": _f("rug", (1.6, 1.6, 0.015), "wool", "#8A4A3A", "round", fringe=True, pile="high"),
    "rug_tiny": _f("rug", (0.01, 0.01, 0.01), fringe=True, pile="high"),
    "bed_wingback": _f("bed", (1.65, 2.15, 1.25), "fabric", "#8C8C94", headboard="wingback"),
    "bed_slatted_platform": _f("bed", (1.6, 2.1, 0.95), "wood", "#B08A5E", headboard="slatted", frame="platform",
                               surface="oak"),
    "bed_spindle_storage": _f("bed", (1.4, 2.0, 1.0), "wood", "#6B4A32", headboard="spindle", frame="storage",
                              footboard=True, leg_style="metal", surface="walnut"),
    "bed_none_min": _f("bed", (0.6, 1.2, 0.2), "fabric", "#A0A8B0", headboard="none", footboard=True,
                       leg_style="hidden"),
    "bed_channel_max": _f("bed", (2.2, 2.4, 1.4), "leather", "#3A2A20", headboard="channel", frame="rails",
                          leg_style="block"),
    "bed_tufted_footboard": _f("bed", (1.5, 2.1, 1.1), "fabric", "#C4B8A8", headboard="tufted", footboard=True),
    "nightstand_shelf_hairpin": _f("nightstand", (0.5, 0.4, 0.55), "wood", "#7A5236", open_shelf=True,
                                   leg_style="hairpin"),
    "nightstand_round_plinth": _f("nightstand", (0.45, 0.45, 0.55), "wood", "#E8E0D0", "round", drawers=3,
                                  leg_style="plinth", surface="painted"),
    "nightstand_round_tiny": _f("nightstand", (0.2, 0.2, 0.2), "wood", None, "round", open_shelf=True,
                                leg_style="hairpin"),
    "nightstand_door": _f("nightstand", (0.45, 0.4, 0.6), "wood", "#5A4A3A", drawers=0, leg_style="none"),
    "dresser_3x3_bar": _f("dresser", (1.5, 0.48, 0.85), "wood", "#D9C6A5", columns=3, rows=3, handle_style="bar",
                          leg_style="tapered", surface="white_oak"),
    "dresser_1x5_min": _f("dresser", (0.4, 0.25, 0.3), "wood", None, columns=1, rows=5, handle_style="knob",
                          leg_style="plinth"),
    "dresser_cup_bun": _f("dresser", (1.2, 0.5, 0.8), "metal", "#303030", columns=2, rows=2, handle_style="cup",
                          leg_style="bun", surface="black_metal"),
    "dresser_cutout_max": _f("dresser", (2.6, 0.9, 1.8), "wood", "#F2EFEA", handle_style="cutout",
                             leg_style="metal"),
    "dresser_none": _f("dresser", (1.0, 0.45, 0.9), "wood", "#8A6748", handle_style="none"),
    "desk_right_trestle": _f("desk", (1.4, 0.7, 0.76), "wood", "#6B4A32", pedestal="right", leg_style="trestle"),
    "desk_left_panel_shelf": _f("desk", (1.6, 0.7, 0.75), "wood", "#C8B090", pedestal="left", leg_style="panel",
                                shelf=True),
    "desk_metal_frame": _f("desk", (1.2, 0.6, 0.75), "wood", "#9A7B5A", leg_style="metal_frame", drawers=3),
    "desk_hairpin_min": _f("desk", (0.5, 0.3, 0.4), "wood", None, leg_style="hairpin", drawers=0),
    "desk_straight_max": _f("desk", (2.6, 1.4, 1.3), "wood", "#4A3A2A", pedestal="left", leg_style="straight"),
}
# The same item with the explicit default values left out must build identically (absent keys = today's look).
DEFAULT_TWINS = {"sofa_track_pillow_linen": {"surface": "linen"}}

COLOR_SCRIPT = r"""
import bpy, json, os, sys
import numpy as np
out = {}
for p in sys.argv[sys.argv.index("--") + 1:]:
    img = bpy.data.images.load(p)
    a = np.empty(img.size[0] * img.size[1] * 4, np.float32)
    img.pixels.foreach_get(a)
    s = a.reshape(-1, 4)[:, :3]                   # byte images: sRGB-encoded floats
    lin = np.where(s <= 0.04045, s / 12.92, ((s + 0.055) / 1.055) ** 2.4)
    out[p] = lin.mean(axis=0).tolist()
print("R2R_COLOR " + json.dumps(out))
sys.stdout.flush()
os._exit(0)
"""


def _linear(hex_color):
    c = [int(hex_color.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return [x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c]


@pytest.fixture(scope="module")
def formed(worker, blender_bin):
    results = {}
    for name, spec in FORM_CASES.items():
        path = worker.root / f"form_{name}.usdz"
        t0 = time.perf_counter()
        r = worker.request("build_asset", {"spec": spec, "usdz_path": str(path), "report_parts": True})
        results[name] = (spec, path, r, time.perf_counter() - t0)
    for name, form in DEFAULT_TWINS.items():
        spec = dict(FORM_CASES[name], form=form)
        path = worker.root / f"twin_{name}.usdz"
        results["twin_" + name] = (spec, path, worker.request("build_asset", {"spec": spec, "usdz_path": str(path),
                                                                              "report_parts": True}), 0.0)
    measured = measure_fresh(blender_bin, [p for _, p, _, _ in results.values()])
    extracted = {}
    for name, (spec, path, r, _) in results.items():
        main, hx = r["main_surface"], r["spec"]["color_hex"].lstrip("#").upper()
        with zipfile.ZipFile(path) as z:
            hit = [n for n in z.namelist() if n.startswith(f"textures/{main}_{hx}_")]
            if hit:
                extracted[name] = Path(z.extract(hit[0], worker.root / f"fx_{name}"))
    out = subprocess.run([blender_bin, "--background", "--factory-startup", "--python-expr", COLOR_SCRIPT, "--",
                          *map(str, extracted.values())], capture_output=True, text=True, timeout=120)
    colors = json.loads(next(l for l in out.stdout.splitlines() if l.startswith("R2R_COLOR "))[len("R2R_COLOR "):])
    return results, measured, {k: colors[str(p)] for k, p in extracted.items()}


@pytest.mark.parametrize("name", sorted(FORM_CASES))
def test_form_matrix_exact_bbox_budget_and_textures(formed, name):
    results, measured, colors = formed
    spec, path, r, _ = results[name]
    m = measured[str(path)]
    w, d, h = (spec["dimensions_m"][k] for k in ("width", "depth", "height"))
    for got, want in zip(m["min"] + m["max"], [-w / 2, 0.0, -d / 2, w / 2, h, d / 2]):
        assert abs(got - want) <= NEW_TOL_M, (name, m["min"], m["max"])
    assert r["template_fit_error_m"] <= NEW_TOL_M, (name, r["template_fit_error_m"])
    assert m["triangles"] < 60000 and r["triangles"] == m["triangles"], (name, m["triangles"])
    assert path.stat().st_size < 1.5 * 1024 * 1024, (name, path.stat().st_size)
    names = zipfile.ZipFile(path).namelist()
    images = {n for n in names if n.lower().endswith((".jpg", ".png"))}
    assert images and {t["file"] for t in m["textures"]} == {"./" + n for n in images}, name
    assert r["spec"].get("form", {}) == spec.get("form", {})
    if spec.get("form", {}).get("surface"):
        high_wool = spec["form"]["surface"] == "wool" and spec["form"].get("pile") == "high"
        assert r["main_surface"] == ("shag" if high_wool else spec["form"]["surface"])  # shag = long wool pile
    if r["main_surface"] != "glass":
        assert name in colors, (name, r["main_surface"], images)
        want, got = _linear(r["spec"]["color_hex"]), colors[name]
        assert max(abs(a - b) for a, b in zip(got, want)) <= 0.06 * max(max(want), 0.05), (name, got, want)


def test_form_normal_maps_reach_usdz(formed):
    results, measured, _ = formed
    m = measured[str(results["coffee_hairpin_glass"][1])]
    normals = [v["normal"] for v in m["surface_inputs"].values() if v["normal"]]
    assert normals and all(n["color_space"] == "raw" for n in normals), m["surface_inputs"]
    glass = [v for k, v in m["surface_inputs"].items() if "glass" in k]
    assert glass and glass[0]["opacity"] is not None, "glass carries an alpha-linked opacity texture"
    assert all(v["diffuseColor"] for k, v in m["surface_inputs"].items() if "screen" not in k)


def test_absent_form_keeps_default_look(formed):
    results, _, _ = formed
    for name in DEFAULT_TWINS:
        explicit, twin = results[name][2], results["twin_" + name][2]
        assert explicit["parts"] == twin["parts"] and explicit["triangles"] == twin["triangles"], name


def test_form_build_time_warm(formed):
    results, _, _ = formed
    times = sorted(t for *_, t in results.values() if t)
    assert times[len(times) // 2] < 1.0, times  # warm worker, textures cached on disk


def _parts(formed, name):
    return formed[0][name][2]["parts"]


def test_rolled_arms_are_curved(formed):
    rolled = _parts(formed, "sofa_rolled_tufted_velvet")["arm"]
    track = _parts(formed, "sofa_track_pillow_linen")["arm"]
    assert len(rolled) == 6 and len(track) == 2  # each rolled arm = base + cylindrical roll + scroll face
    assert sum(p["verts"] for p in rolled) > 2 * sum(p["verts"] for p in track)
    base_w = min(p["max"][0] - p["min"][0] for p in rolled)
    assert max(p["max"][0] - p["min"][0] for p in rolled) > base_w * 1.05, "the roll bulges past the arm base"


def test_chaise_extends_depth_on_requested_side(formed):
    for name, side in (("sofa_chaise_left", -1), ("sofa_chaise_right_min", 1)):
        d = FORM_CASES[name]["dimensions_m"]["depth"]
        seats = _parts(formed, name)["seat"]
        chaise = [s for s in seats if (s["min"][0] + s["max"][0]) / 2 * side > 0]
        other = [s for s in seats if (s["min"][0] + s["max"][0]) / 2 * side < 0]
        assert chaise and other, name
        assert max(s["max"][2] for s in chaise) >= d / 2 - 0.005, "chaise seat runs to the front (+Z)"
        assert max(s["max"][2] for s in other) < d / 2 - 0.1, "the other seats keep a normal depth"


def test_slatted_headboard_has_gaps(formed):
    slats = sorted(_parts(formed, "bed_slatted_platform")["slat"], key=lambda p: p["min"][0])
    assert len(slats) >= 5
    gaps = [b["min"][0] - a["max"][0] for a, b in zip(slats, slats[1:])]
    assert min(gaps) > 0.01, gaps


def test_hairpin_legs_are_thin(formed):
    for name in ("coffee_hairpin_glass", "nightstand_shelf_hairpin", "desk_hairpin_min"):
        rods = _parts(formed, name)["leg_rod"]
        assert len(rods) >= 4, name
        for p in rods:
            ext = sorted(p["max"][i] - p["min"][i] for i in (0, 2))
            assert ext[0] <= 0.013, (name, ext)


def test_footboard_only_when_requested(formed):
    for name in FORM_CASES:
        if FORM_CASES[name]["category"] == "bed":
            has = "footboard" in _parts(formed, name)
            assert has == bool(FORM_CASES[name]["form"].get("footboard")), name


def test_form_keys_change_geometry(formed):
    """Distinct forms of one category never produce identical part sets + triangle counts (items too small to
    carry the details, like a 1 cm rug, fall back to the plain build and are skipped)."""
    seen = {}
    for name, (spec, _, r, _) in formed[0].items():
        if name.startswith("twin_") or spec["dimensions_m"]["width"] < 0.3:
            continue
        sig = (spec["category"], tuple(sorted((k, len(v)) for k, v in r["parts"].items())), r["triangles"])
        assert sig not in seen, (name, seen.get(sig))
        seen[sig] = name
