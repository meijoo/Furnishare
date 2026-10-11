"""Parametric furniture and room templates. Runs inside Blender (bpy), not ordinary Python.

Blender space while building: Z up, front faces -Y, meters. The USD export converts to
Y-up / front +Z (Blender (x, y, z) -> USD (x, z, -y)), so assets land in the API's scene space.
Every furniture template fills the box [-w/2, w/2] x [-d/2, d/2] x [0, h] exactly.
"""
from __future__ import annotations

import hashlib
import math
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

import bmesh
import bpy
import numpy as np
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from blender_mcp import specs  # noqa: E402
import surfaces  # noqa: E402

USD_EXPORT_KWARGS = dict(
    selected_objects_only=True,
    export_animation=False,
    export_hair=False,
    export_uvmaps=True,
    export_normals=True,
    export_materials=True,
    generate_preview_surface=True,
    generate_materialx_network=False,
    export_textures_mode="NEW",
    export_subdivision="IGNORE",
    export_armatures=False,
    export_shapekeys=False,
    use_instancing=False,
    evaluation_mode="RENDER",
    convert_orientation=True,
    export_global_forward_selection="NEGATIVE_Z",
    export_global_up_selection="Y",
    convert_scene_units="METERS",
    meters_per_unit=1.0,
    xform_op_mode="TRS",
    root_prim_path="/root",
    export_custom_properties=False,
    author_blender_name=False,
    convert_world_material=False,
    export_lights=False,
    export_cameras=False,
    export_curves=False,
    export_points=False,
    export_volumes=False,
    triangulate_meshes=False,
)

GLB_EXPORT_KWARGS = dict(export_format="GLB", use_selection=True, export_yup=True, export_apply=True,
                         export_cameras=False, export_lights=False, export_materials="EXPORT")

SHARP_ANGLE = math.radians(35)

MATERIAL_PRESETS = {
    "fabric": dict(roughness=0.92, metallic=0.0, sheen=0.4),
    "wool": dict(roughness=1.0, metallic=0.0, sheen=0.6),
    "leather": dict(roughness=0.42, metallic=0.0, coat=0.15),
    "wood": dict(roughness=0.55, metallic=0.0),
    "metal": dict(roughness=0.32, metallic=1.0),
    "paint": dict(roughness=0.85, metallic=0.0),
    "screen": dict(roughness=0.12, metallic=0.0, coat=0.6),
}
WALNUT = "#5B3B26"
BLACK_METAL = "#2A2B2E"
BRASS = "#B39260"
SCREEN = "#0A0C10"
MATTRESS = "#E9E4DA"
SHEET = "#F1EDE4"
PILLOW = "#F7F5F0"
BLANKET_ON_LIGHT = "#6F7F8C"
BLANKET_ON_DARK = "#D8CFC0"
FRINGE = "#E4DCC8"
RECESS = "#1B1916"
ROUND_SEGMENTS = 64
SURFACE_CACHE_DIR = Path(os.environ.get("R2R_SURFACE_CACHE_DIR")
                         or Path(__file__).resolve().parents[1] / "blender_mcp" / ".out" / "surface_cache")
SURFACE_JPEG_QUALITY = 84
SECONDARY_PX = 512        # legs, fronts, borders, buttons: smaller images keep the USDZ light
TOP_ONLY_SURFACES = ("glass", "marble")  # bodies of items whose surface is one of these use the material's finish
TEXTURE_MAX_PX = {"print": 2048, "tile": 1024}  # long side of the image embedded in the USDZ
TEXTURE_SOURCE_MAX_PX = 4096                    # sources are downscaled to this before pixel work
TEXTURE_JPEG_QUALITY = 88
TRIM_TOLERANCE = 0.08     # per-channel distance from the corner color that still counts as background
TRIM_ROW_FRACTION = 0.97  # a row/column is border when this share of its pixels is background
TRIM_MAX_SIDE = 0.35      # a "border" thicker than this share of the image means it is not a border
PRINT_TOP_NORMAL_Z = 0.5  # print materials cover faces facing up at least this much; the rest get the edge color


# ---------------------------------------------------------------- materials

def _srgb_to_linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def hex_to_linear(hex_color: str) -> tuple[float, float, float, float]:
    h = specs.color_hex(hex_color).lstrip("#")
    return tuple(_srgb_to_linear(int(h[i:i + 2], 16) / 255) for i in (0, 2, 4)) + (1.0,)


def shade(hex_color: str, factor: float) -> str:
    """Darken (factor < 1) or lighten (factor > 1) an sRGB hex color."""
    h = specs.color_hex(hex_color).lstrip("#")
    rgb = [int(h[i:i + 2], 16) for i in (0, 2, 4)]
    if factor > 1:
        rgb = [round(c + (255 - c) * (factor - 1)) for c in rgb]
    else:
        rgb = [round(c * factor) for c in rgb]
    return "#" + "".join(f"{max(0, min(255, c)):02X}" for c in rgb)


def get_material(hex_color: str, kind: str) -> bpy.types.Material:
    name = f"r2r_{kind}_{specs.color_hex(hex_color).lstrip('#')}"
    mat = bpy.data.materials.get(name)
    if mat is not None:
        return mat
    preset = MATERIAL_PRESETS[kind]
    color = hex_to_linear(hex_color)
    mat = bpy.data.materials.new(name)
    if mat.node_tree is None:
        mat.use_nodes = True
    bsdf = next(n for n in mat.node_tree.nodes if n.bl_idname == "ShaderNodeBsdfPrincipled")
    bsdf.inputs["Base Color"].default_value = color
    bsdf.inputs["Roughness"].default_value = preset["roughness"]
    bsdf.inputs["Metallic"].default_value = preset["metallic"]
    if "sheen" in preset:
        bsdf.inputs["Sheen Weight"].default_value = preset["sheen"]
    if "coat" in preset:
        bsdf.inputs["Coat Weight"].default_value = preset["coat"]
    mat.diffuse_color = color
    mat.roughness = preset["roughness"]
    mat.metallic = preset["metallic"]
    return mat


# ---------------------------------------------------------------- procedural surfaces (baked to images)

def _write_image(path: Path, px: np.ndarray, png: bool):
    """Writes an (h, w, 4) sRGB float array via Blender's image writer, atomically."""
    h, w = px.shape[:2]
    path.parent.mkdir(parents=True, exist_ok=True)
    img = bpy.data.images.new("r2r_tmp_write", w, h, alpha=png)
    try:
        img.pixels.foreach_set(np.ascontiguousarray(px, np.float32).ravel())
        tmp = path.with_name(f".{path.stem}.{os.getpid()}{path.suffix}")
        img.file_format = "PNG" if png else "JPEG"
        img.save(filepath=str(tmp), quality=SURFACE_JPEG_QUALITY)
        os.replace(tmp, path)
    finally:
        bpy.data.images.remove(img)


def _cached_image(name: str, filename: str, make, png=False, noncolor=False) -> bpy.types.Image:
    """Packed image datablock `name`, generated once into SURFACE_CACHE_DIR/filename and reused."""
    img = bpy.data.images.get(name)
    if img is not None:
        return img
    path = SURFACE_CACHE_DIR / filename
    if not path.is_file() or path.stat().st_size == 0:
        _write_image(path, make(), png)
    img = bpy.data.images.load(str(path), check_existing=False)
    img.name = name
    if noncolor:
        img.colorspace_settings.name = "Non-Color"
    img.pack()  # embedded bytes travel into the USDZ as textures/<name>.<ext>
    return img


def surface_images(hex_color: str, surface: str, px: int | None = None):
    """(color image, normal image or None) for a surface tinted to hex_color (glass: fixed tint + alpha)."""
    preset = surfaces.PRESETS[surface]
    px = min(px or preset["px"], preset["px"])
    hx = specs.color_hex(hex_color).lstrip("#")
    ver = surfaces.VERSION
    if surface == "glass":
        color = _cached_image("r2r_srf_glass", f"glass_{px}_{ver}.png",
                              lambda: surfaces.color_image("glass", hex_color, px), png=True)
    else:
        color = _cached_image(f"r2r_srf_{surface}_{hx}_{px}", f"{surface}_{hx}_{px}_{ver}.jpg",
                              lambda: surfaces.color_image(surface, hex_color, px))
    normal = None
    if preset["normal"]:
        normal = _cached_image(f"r2r_nrm_{surface}_{px}", f"nrm_{surface}_{px}_{ver}.jpg",
                               lambda: surfaces.normal_image(surface, px), noncolor=True)
    return color, normal


def surface_material(hex_color: str, surface: str, kind: str | None = None, px: int | None = None) -> bpy.types.Material:
    """Principled BSDF with a baked surface image in Base Color (+ normal map, + alpha for glass).

    Exported as UsdPreviewSurface + UsdUVTexture. r2r_uv_mode='surface' tells MeshBuilder to lay out
    world-scale box UVs (one repeat = r2r_tile_m) with the grain along each part's longest axis."""
    preset = surfaces.PRESETS[surface]
    kind = kind or preset["kind"]
    px = min(px or preset["px"], preset["px"])
    hx = specs.color_hex(hex_color).lstrip("#")
    name = f"r2r_{kind}_{surface}{'' if px == preset['px'] else f'_{px}'}_{hx}"
    mat = bpy.data.materials.get(name)
    if mat is not None:
        return mat
    color_img, normal_img = surface_images(hex_color, surface, px)
    mat = bpy.data.materials.new(name)
    if mat.node_tree is None:
        mat.use_nodes = True
    nt = mat.node_tree
    bsdf = next(n for n in nt.nodes if n.bl_idname == "ShaderNodeBsdfPrincipled")
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = color_img
    tex.interpolation = "Linear"
    tex.location = (bsdf.location.x - 360, bsdf.location.y)
    nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    if surface == "glass":
        nt.links.new(tex.outputs["Alpha"], bsdf.inputs["Alpha"])  # the USD exporter only writes linked opacity
        if hasattr(mat, "surface_render_method"):
            mat.surface_render_method = "BLENDED"
    if normal_img is not None:
        ntex = nt.nodes.new("ShaderNodeTexImage")
        ntex.image = normal_img
        ntex.interpolation = "Linear"
        ntex.location = (bsdf.location.x - 560, bsdf.location.y - 300)
        nmap = nt.nodes.new("ShaderNodeNormalMap")
        nmap.location = (bsdf.location.x - 260, bsdf.location.y - 300)
        nt.links.new(ntex.outputs["Color"], nmap.inputs["Color"])
        nt.links.new(nmap.outputs["Normal"], bsdf.inputs["Normal"])
    nt.nodes.active = tex  # workbench "TEXTURE" previews show the active image node
    bsdf.inputs["Roughness"].default_value = preset["roughness"]
    bsdf.inputs["Metallic"].default_value = preset["metallic"]
    if "sheen" in preset:
        bsdf.inputs["Sheen Weight"].default_value = preset["sheen"]
    if "coat" in preset:
        bsdf.inputs["Coat Weight"].default_value = preset["coat"]
    base = hex_to_linear(surfaces.GLASS_TINT if surface == "glass" else hex_color)
    mat.diffuse_color = base[:3] + (preset.get("alpha", 1.0),)
    mat.roughness = preset["roughness"]
    mat.metallic = preset["metallic"]
    mat["r2r_uv_mode"] = "surface"
    mat["r2r_tile_m"] = float(preset["tile_m"])
    mat["r2r_surface"] = surface
    return mat


# ---------------------------------------------------------------- image textures

_TEXTURES: dict[tuple, dict] = {}  # (path, mtime, size, mode, aspect) -> info incl. the packed image name


def _rgb_hex(rgb) -> str:
    return "#" + "".join(f"{round(max(0.0, min(1.0, float(c))) * 255):02X}" for c in rgb)


def trim_light_border(a: np.ndarray) -> tuple[int, int, int, int]:
    """(top, bottom, left, right) pixel counts of a near-uniform light background around the subject.

    `a` is (rows top-to-bottom, cols, rgb) in 0..1. Background color = median of the four corner patches;
    returns zeros when the corners are dark or disagree, or when the "border" would eat the image."""
    h, w = a.shape[:2]
    k = max(1, min(h, w) // 100)
    corners = np.stack([a[:k, :k].reshape(-1, 3).mean(0), a[:k, -k:].reshape(-1, 3).mean(0),
                        a[-k:, :k].reshape(-1, 3).mean(0), a[-k:, -k:].reshape(-1, 3).mean(0)])
    bg = np.median(corners, axis=0)
    if bg.mean() < 0.7 or (np.abs(corners - bg).max(axis=1) <= TRIM_TOLERANCE).sum() < 2:
        return 0, 0, 0, 0
    near = np.abs(a - bg).max(axis=2) <= TRIM_TOLERANCE

    def run(flags) -> int:
        bad = np.flatnonzero(~flags)
        return int(bad[0]) if bad.size else len(flags)

    t = b = l = r = 0
    for _ in range(2):  # rows, then columns inside the kept rows, then rows inside the kept columns
        sub = near[:, l:w - r]
        rows = sub.mean(axis=1) >= TRIM_ROW_FRACTION
        t, b = run(rows), run(rows[::-1])
        sub = near[t:h - b]
        cols = sub.mean(axis=0) >= TRIM_ROW_FRACTION if sub.size else np.ones(w, bool)
        l, r = run(cols), run(cols[::-1])
    if max(t, b) > TRIM_MAX_SIDE * h or max(l, r) > TRIM_MAX_SIDE * w:
        return 0, 0, 0, 0
    # Eat the anti-aliased / slightly skewed rug edge too.
    pad_y, pad_x = max(1, round(h * 0.006)), max(1, round(w * 0.006))
    return (t + pad_y if t else 0, b + pad_y if b else 0, l + pad_x if l else 0, r + pad_x if r else 0)


def _load_rgb(path: str) -> np.ndarray:
    """Image file -> float32 (rows top-to-bottom, cols, rgb) in sRGB 0..1, alpha composited over white."""
    img = bpy.data.images.load(path, check_existing=False)
    try:
        w, h = img.size
        if w == 0 or h == 0:
            raise ValueError(f"could not decode texture image {os.path.basename(path)}")
        if max(w, h) > TEXTURE_SOURCE_MAX_PX:
            s = TEXTURE_SOURCE_MAX_PX / max(w, h)
            img.scale(max(1, round(w * s)), max(1, round(h * s)))
            w, h = img.size
        px = np.empty(w * h * 4, np.float32)
        img.pixels.foreach_get(px)
    finally:
        bpy.data.images.remove(img)
    px = px.reshape(h, w, 4)[::-1]
    alpha = px[..., 3:4]
    return px[..., :3] * alpha + (1.0 - alpha)


def _crop_to_aspect(a: np.ndarray, aspect: float) -> tuple[np.ndarray, bool, list[int]]:
    """Cover-fit: center-crop to width/height = aspect. A portrait photo of a landscape rug (or vice versa)
    is turned 90 degrees first so the whole rug survives the crop. Returns (pixels, rotated, [x, y, w, h])."""
    h, w = a.shape[:2]
    r = w / h
    rotated = (r - 1) * (aspect - 1) < 0 and abs(math.log(r)) > 0.05 and abs(math.log(aspect)) > 0.05
    if rotated:
        a = np.rot90(a)  # counter-clockwise: the photo's top edge becomes the rug's left edge
        h, w = w, h
        r = w / h
    if r > aspect:
        cw = max(1, round(h * aspect))
        x0 = (w - cw) // 2
        return a[:, x0:x0 + cw], rotated, [x0, 0, cw, h]
    ch = max(1, round(w / aspect))
    y0 = (h - ch) // 2
    return a[y0:y0 + ch], rotated, [0, y0, w, ch]


def prepare_texture(tex: dict, aspect: float) -> dict:
    """Loads, trims, crops and downsizes a spec texture into a packed JPEG image datablock (cached).

    print: light borders trimmed, cover-fit to `aspect` (footprint width/depth), image top = back (+Y).
    tile:  light borders trimmed, used as a repeating swatch."""
    st = os.stat(tex["path"])
    mode = tex["mode"]
    key = (tex["path"], st.st_mtime_ns, st.st_size, mode, round(aspect, 4) if mode == "print" else None)
    info = _TEXTURES.get(key)
    if info is not None and bpy.data.images.get(info["image_name"]) is not None:
        return info
    a = _load_rgb(tex["path"])
    src_h, src_w = a.shape[:2]
    t, b, l, r = trim_light_border(a)
    a = a[t:src_h - b, l:src_w - r]
    rotated, crop = False, [0, 0, a.shape[1], a.shape[0]]
    if mode == "print":
        a, rotated, crop = _crop_to_aspect(a, aspect)
    a = np.ascontiguousarray(a)
    h, w = a.shape[:2]
    with open(tex["path"], "rb") as fh:
        digest = hashlib.sha256(fh.read() + repr(key[3:]).encode()).hexdigest()[:16]
    name = f"r2r_tex_{digest}"
    s = min(1.0, TEXTURE_MAX_PX[mode] / max(w, h))
    out_w, out_h = max(1, round(w * s)), max(1, round(h * s))

    old = bpy.data.images.get(name)
    if old is not None:
        bpy.data.images.remove(old)
    img = bpy.data.images.new(name + "_raw", w, h, alpha=False)
    rgba = np.concatenate([a[::-1], np.ones((h, w, 1), np.float32)], axis=2)
    img.pixels.foreach_set(rgba.ravel())
    if (out_w, out_h) != (w, h):
        img.scale(out_w, out_h)
    tmpdir = tempfile.mkdtemp(prefix="r2r-tex-")
    try:
        jpg = os.path.join(tmpdir, name + ".jpg")
        img.file_format = "JPEG"
        img.save(filepath=jpg, quality=TEXTURE_JPEG_QUALITY)
        bpy.data.images.remove(img)
        packed = bpy.data.images.load(jpg, check_existing=False)
        packed.name = name
        packed.pack()  # embedded bytes travel into the USDZ as textures/<name>.jpg
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    info = {"mode": mode, "image_name": name, "source_px": [src_w, src_h],
            "trim_px": {"top": t, "bottom": b, "left": l, "right": r}, "rotated": rotated, "crop_px": crop,
            "output_px": [out_w, out_h], "average_hex": _rgb_hex(a.reshape(-1, 3).mean(axis=0))}
    _TEXTURES[key] = info
    return info


def get_texture_material(spec: dict) -> bpy.types.Material:
    """Principled BSDF with the spec texture into Base Color (exported as UsdPreviewSurface + UsdUVTexture).

    Custom props tell MeshBuilder how to lay out UVs: r2r_uv_mode print|tile, r2r_tile_m, and for print
    r2r_edge_material (plain material in the image's average color for faces that do not face up)."""
    tex, dims, kind = spec["texture"], spec["dimensions_m"], spec["material"]
    info = prepare_texture(tex, dims["width"] / dims["depth"])
    name = f"r2r_{kind}_{info['image_name']}" + (f"_t{round(tex['tile_m'] * 1000)}" if info["mode"] == "tile" else "")
    mat = bpy.data.materials.get(name)
    if mat is not None:
        return mat
    preset = MATERIAL_PRESETS[kind]
    avg = info["average_hex"]
    mat = bpy.data.materials.new(name)
    if mat.node_tree is None:
        mat.use_nodes = True
    nt = mat.node_tree
    bsdf = next(n for n in nt.nodes if n.bl_idname == "ShaderNodeBsdfPrincipled")
    node = nt.nodes.new("ShaderNodeTexImage")
    node.image = bpy.data.images[info["image_name"]]
    node.extension = "REPEAT" if info["mode"] == "tile" else "EXTEND"
    node.interpolation = "Linear"
    node.location = (bsdf.location.x - 320, bsdf.location.y)
    nt.links.new(node.outputs["Color"], bsdf.inputs["Base Color"])
    nt.nodes.active = node  # workbench "TEXTURE" previews show the active image node
    bsdf.inputs["Roughness"].default_value = preset["roughness"]
    bsdf.inputs["Metallic"].default_value = preset["metallic"]
    if "sheen" in preset:
        bsdf.inputs["Sheen Weight"].default_value = preset["sheen"]
    if "coat" in preset:
        bsdf.inputs["Coat Weight"].default_value = preset["coat"]
    mat.diffuse_color = hex_to_linear(avg)
    mat.roughness = preset["roughness"]
    mat.metallic = preset["metallic"]
    mat["r2r_uv_mode"] = info["mode"]
    mat["r2r_tile_m"] = float(tex["tile_m"])
    if info["mode"] == "print":
        mat["r2r_edge_material"] = get_material(avg, kind).name
    return mat


def texture_info(spec: dict) -> dict | None:
    if not spec.get("texture"):
        return None
    dims, tex = spec["dimensions_m"], spec["texture"]
    return dict(prepare_texture(tex, dims["width"] / dims["depth"]), tile_m=tex["tile_m"] if tex["mode"] == "tile" else None)


# ---------------------------------------------------------------- mesh building

class MeshBuilder:
    """Accumulates primitive parts into one bmesh with per-face material indices.

    UV map 'st' (only when a textured material is used) is laid out per part as it is merged:
      print   - planar top-down over `footprint` (v=1 at the back, +Y)
      tile    - world-scale box projection, one repeat = r2r_tile_m (photo swatches)
      surface - world-scale box projection with u along the part's longest in-plane axis, so wood grain
                follows each board/leg; each part gets its own offset so neighbours do not repeat.
    `label` names the parts that follow; `parts` collects their bboxes for diagnostics/tests."""

    def __init__(self, footprint: tuple[float, float] | None = None):
        self.bm = bmesh.new()
        self.materials: list[bpy.types.Material] = []
        self.footprint = footprint
        self.label = "body"
        self.parts: dict[str, list] = {}
        self.main_surface: str | None = None  # set by templates that swap the spec's surface (e.g. shag rugs)
        self._uv = None
        self._count = 0

    def _index(self, mat) -> int:
        if mat not in self.materials:
            self.materials.append(mat)
        return self.materials.index(mat)

    def _uv_for(self, mode, tile, co, n, ext, off):
        x, y, z = co
        if mode == "print":
            w, d = self.footprint
            return (x + w / 2) / w, (y + d / 2) / d
        ax = max(range(3), key=lambda i: abs(n[i]))
        if mode == "tile":
            if ax == 2:
                return x / tile, (y if n.z > 0 else -y) / tile
            if ax == 0:
                return (y if n.x > 0 else -y) / tile, z / tile
            return (-x if n.y > 0 else x) / tile, z / tile
        a, b = [i for i in range(3) if i != ax]
        if ext[b] > ext[a]:
            a, b = b, a
        return co[a] / tile + off[0], co[b] / tile + off[1]

    def _merge(self, tmp: bmesh.types.BMesh, mat):
        idx = self._index(mat)
        edge_name = mat.get("r2r_edge_material") if mat is not None else None
        edge_idx = self._index(bpy.data.materials[edge_name]) if edge_name else idx
        tmp.normal_update()
        lo = [min(v.co[i] for v in tmp.verts) for i in range(3)]
        hi = [max(v.co[i] for v in tmp.verts) for i in range(3)]
        self.parts.setdefault(self.label, []).append((lo, hi, len(tmp.verts)))
        mode = mat.get("r2r_uv_mode") if mat is not None else None
        tile = float(mat.get("r2r_tile_m", 1.0)) if mat is not None else 1.0
        if mode and self._uv is None:
            self._uv = self.bm.loops.layers.uv.get("st") or self.bm.loops.layers.uv.new("st")
        self._count += 1
        off = ((self._count * 0.618034) % 1.0, (self._count * 0.414214) % 1.0)
        ext = [hi[i] - lo[i] for i in range(3)]
        vmap = {v: self.bm.verts.new(v.co) for v in tmp.verts}
        for f in tmp.faces:
            nf = self.bm.faces.new([vmap[v] for v in f.verts])
            top = not edge_name or f.normal.z >= PRINT_TOP_NORMAL_Z
            nf.material_index = idx if top else edge_idx
            if mode and top:
                for loop, v in zip(nf.loops, f.verts):
                    loop[self._uv].uv = self._uv_for(mode, tile, v.co, f.normal, ext, off)
        tmp.free()

    def parts_usd(self) -> dict[str, list[dict]]:
        """Part bboxes in USD space (Y-up, front +Z): Blender (x, y, z) -> USD (x, z, -y)."""
        return {name: [{"min": [lo[0], lo[2], -hi[1]], "max": [hi[0], hi[2], -lo[1]], "verts": nv}
                       for lo, hi, nv in boxes] for name, boxes in self.parts.items()}

    def hexa(self, pts, mat, bevel=0.0, segments=3):
        """Convex 8-corner block; pts[i] is the corner with (x, y, z) high-flags i = x + 2*y + 4*z."""
        tmp = bmesh.new()
        bmesh.ops.create_cube(tmp, size=1.0)
        for v in tmp.verts:
            v.co = pts[(v.co.x > 0) + 2 * (v.co.y > 0) + 4 * (v.co.z > 0)]
        tmp.normal_update()
        ext = min(max(p[i] for p in pts) - min(p[i] for p in pts) for i in range(3))
        r = min(bevel, 0.45 * ext)
        if r > 1e-5:
            bmesh.ops.bevel(tmp, geom=list(tmp.edges) + list(tmp.verts), offset=r, offset_type="OFFSET",
                            segments=segments, profile=0.5, affect="EDGES", clamp_overlap=True)
        self._merge(tmp, mat)

    def rod(self, p0, p1, r0, r1, mat, segments=12, bevel=0.0):
        """Cylinder/cone from p0 (radius r0) to p1 (radius r1) along any direction; bevel rounds the cap rims."""
        a, b = Vector(p0), Vector(p1)
        axis = b - a
        if axis.length <= 1e-6 or max(r0, r1) <= 0:
            return
        tmp = bmesh.new()
        bmesh.ops.create_cone(tmp, cap_ends=True, cap_tris=False, segments=segments, radius1=r0, radius2=r1,
                              depth=axis.length)
        r = min(bevel, 0.45 * min(axis.length, max(r0, r1)))
        if r > 1e-5:
            tmp.normal_update()
            rims = [e for e in tmp.edges if sum(abs(f.normal.z) > 0.99 for f in e.link_faces) == 1]
            bmesh.ops.bevel(tmp, geom=rims, offset=r, offset_type="OFFSET", segments=3, profile=0.5,
                            affect="EDGES", clamp_overlap=True)
        rot = Vector((0.0, 0.0, 1.0)).rotation_difference(axis.normalized()).to_matrix()
        mid = (a + b) / 2
        for v in tmp.verts:
            v.co = rot @ v.co + mid
        self._merge(tmp, mat)

    def sphere(self, x, y, z, rx, ry, rz, mat, segments=12, rings=6):
        """Ellipsoid centered at (x, y, z); its poles sit exactly at z +- rz."""
        if min(rx, ry, rz) <= 0:
            return
        tmp = bmesh.new()
        bmesh.ops.create_uvsphere(tmp, u_segments=segments, v_segments=rings, radius=1.0)
        for v in tmp.verts:
            v.co = (x + v.co.x * rx, y + v.co.y * ry, z + v.co.z * rz)
        self._merge(tmp, mat)

    def box(self, x0, x1, y0, y1, z0, z1, mat, bevel=0.0, segments=3):
        sx, sy, sz = x1 - x0, y1 - y0, z1 - z0
        if min(sx, sy, sz) <= 0:
            return
        tmp = bmesh.new()
        bmesh.ops.create_cube(tmp, size=1.0)
        for v in tmp.verts:
            v.co.x = x0 + (v.co.x + 0.5) * sx
            v.co.y = y0 + (v.co.y + 0.5) * sy
            v.co.z = z0 + (v.co.z + 0.5) * sz
        r = min(bevel, 0.45 * min(sx, sy, sz))
        if r > 1e-5:
            bmesh.ops.bevel(tmp, geom=list(tmp.edges) + list(tmp.verts), offset=r, offset_type="OFFSET",
                            segments=segments, profile=0.5, affect="EDGES", clamp_overlap=True)
        self._merge(tmp, mat)

    def cylinder(self, x, y, z0, z1, r_bottom, r_top, mat, segments=20, aspect=1.0, bevel=0.0):
        """Z-axis cylinder/cone; aspect scales the Y radius (ellipse). bevel rounds only the two cap rims."""
        if z1 <= z0 or max(r_bottom, r_top) <= 0:
            return
        tmp = bmesh.new()
        bmesh.ops.create_cone(tmp, cap_ends=True, cap_tris=False, segments=segments,
                              radius1=r_bottom, radius2=r_top, depth=z1 - z0)
        for v in tmp.verts:
            v.co.x += x
            v.co.y = y + v.co.y * aspect
            v.co.z += (z0 + z1) / 2
        r = min(bevel, 0.45 * min(z1 - z0, max(r_bottom, r_top) * min(1.0, aspect)))
        if r > 1e-5:
            tmp.normal_update()
            rims = [e for e in tmp.edges if sum(abs(f.normal.z) > 0.99 for f in e.link_faces) == 1]
            bmesh.ops.bevel(tmp, geom=rims, offset=r, offset_type="OFFSET", segments=3, profile=0.5,
                            affect="EDGES", clamp_overlap=True)
        self._merge(tmp, mat)

    def to_object(self, name: str, target: tuple[float, float, float] | None, collection) -> tuple[bpy.types.Object, float]:
        """Builds the object. If target=(w, d, h), snaps the bbox to [-w/2,w/2]x[-d/2,d/2]x[0,h]."""
        bm = self.bm
        fit_error = 0.0
        if target is not None:
            lo = [min(v.co[i] for v in bm.verts) for i in range(3)]
            hi = [max(v.co[i] for v in bm.verts) for i in range(3)]
            w, d, h = target
            t_lo, t_hi = (-w / 2, -d / 2, 0.0), (w / 2, d / 2, h)
            fit_error = max(max(abs(lo[i] - t_lo[i]), abs(hi[i] - t_hi[i])) for i in range(3))
            scale = [(t_hi[i] - t_lo[i]) / ((hi[i] - lo[i]) or 1.0) for i in range(3)]
            for v in bm.verts:
                v.co = [t_lo[i] + (v.co[i] - lo[i]) * scale[i] for i in range(3)]
        bm.normal_update()
        for f in bm.faces:
            f.smooth = True
        for e in bm.edges:
            e.smooth = not (len(e.link_faces) == 2 and e.calc_face_angle(math.pi) > SHARP_ANGLE)
        mesh = bpy.data.meshes.new(name)
        bm.to_mesh(mesh)
        bm.free()
        for mat in self.materials:
            mesh.materials.append(mat)
        obj = bpy.data.objects.new(name, mesh)
        collection.objects.link(obj)
        return obj, fit_error


# ---------------------------------------------------------------- furniture templates

def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _form(spec) -> dict:
    return spec.get("form") or {}


def _lum(hex_color: str) -> float:
    h = specs.color_hex(hex_color)
    return sum(int(h[i:i + 2], 16) for i in (1, 3, 5)) / 3


def _body_surface(spec) -> str:
    """Surface of the item's body: form.surface (else the material default); glass/marble only cover tops."""
    s = specs.main_surface(spec)
    return specs.material_surface(spec["material"], spec["color_hex"]) if s in TOP_ONLY_SURFACES else s


def _plain_mat(spec, factor: float = 1.0):
    """Body finish without the photo texture (legs, fronts, plinths), optionally shaded darker/lighter."""
    if factor == 1.0:
        return surface_material(spec["color_hex"], _body_surface(spec), spec["material"])
    return surface_material(shade(spec["color_hex"], factor), _body_surface(spec), spec["material"], px=SECONDARY_PX)


def _main_mat(spec):
    """The item's primary surface (upholstery, wood body/top): the photo texture when given, else the body finish."""
    if spec.get("texture"):
        return get_texture_material(spec)
    return _plain_mat(spec)


def _top_mat(spec, top_style=None):
    """Table tops: photo texture, else glass / marble (top_style or form.surface), else the body finish."""
    if spec.get("texture"):
        return get_texture_material(spec)
    s = specs.main_surface(spec)
    if top_style == "glass":
        s = "glass"
    elif top_style == "stone" and s != "marble":
        s = "marble"
    return surface_material(spec["color_hex"], s, None if s in TOP_ONLY_SURFACES else spec["material"])


METAL_SURFACES = ("brushed_metal", "black_metal")
ACCENT_HEX = {"oak": "#B08A5E", "walnut": WALNUT, "white_oak": "#D9C6A5", "pine": "#D9BE92", "painted": "#F2F2EE",
              "lacquer": "#C9C9C9", "brushed_metal": "#B8B8B8", "black_metal": BLACK_METAL, "marble": "#E8E4DE",
              "glass": surfaces.GLASS_TINT}  # accent_surface without accent_hex; soft surfaces take the body color


def _surface_kind(surface: str) -> str | None:
    if surface in METAL_SURFACES:
        return "metal"
    if surface in specs.SOFT_SURFACES:
        return "fabric"
    return None if surface in TOP_ONLY_SURFACES else "wood"


def _has_accent(spec) -> bool:
    f = _form(spec)
    return bool(f.get("accent_surface") or f.get("accent_hex"))


def _metal_accent(spec) -> bool:
    """A metal accent: legs/frames are built slimmer than wooden ones."""
    return _form(spec).get("accent_surface") in METAL_SURFACES


def _secondary_mat(spec, surface: str, hex_color: str):
    """Secondary parts (legs, frames, bases): form.accent_surface/accent_hex when given (either one alone keeps
    the template's own value for the other), else the template's finish `surface` in `hex_color`."""
    f = _form(spec)
    s, hx = f.get("accent_surface"), f.get("accent_hex")
    if s:
        hx = hx or ACCENT_HEX.get(s) or spec["color_hex"]
    s, hx = s or surface, hx or hex_color
    return surface_material(hx, s, _surface_kind(s), px=SECONDARY_PX)


def _metal_mat():
    return surface_material(BLACK_METAL, "black_metal", "metal", px=SECONDARY_PX)


def _metal_leg_mat(spec):
    """Metal legs/frames: the accent when given, else powder-coated black."""
    return _secondary_mat(spec, "black_metal", BLACK_METAL)


def _leg_mat(spec, finish: str):
    if finish == "metal":
        return _metal_leg_mat(spec)
    return _secondary_mat(spec, "walnut", WALNUT)


def _front_mat(spec):
    """Drawer fronts: a slightly shifted tone of the body so the panels read without relying on gaps
    (textured like the body when a swatch is given)."""
    if spec.get("texture"):
        return get_texture_material(spec)
    return _plain_mat(spec, 0.93 if _lum(spec["color_hex"]) > 150 else 1.08)


def _hardware_mat(spec):
    """Handles: a metal accent when given, else brass on dark bodies and black metal on light ones."""
    if _metal_accent(spec):
        return _metal_leg_mat(spec)
    if _lum(spec["color_hex"]) < 115:
        return surface_material(BRASS, "brushed_metal", "metal", px=SECONDARY_PX)
    return _metal_mat()


def _tuft_mat(spec):
    """Tufting buttons, pleats and seams: the body finish in a clearly darker (or, on very dark items, lighter) tone."""
    return _plain_mat(spec, 0.5 if _lum(spec["color_hex"]) > 35 else 1.6)


def _case_leg_mat(spec):
    """Legs of case goods: the accent when given, else matching body when it is solid wood/metal, else the frame
    finish."""
    if _has_accent(spec):
        return _secondary_mat(spec, _body_surface(spec), spec["color_hex"])
    if spec["frame_finish"] == "metal":
        return _metal_mat()
    return _plain_mat(spec) if spec["material"] in ("wood", "metal") else _leg_mat(spec, "wood")


def _base_mat(spec, default):
    """Plinths and bases: the accent when given, else `default`."""
    return _secondary_mat(spec, _body_surface(spec), spec["color_hex"]) if _has_accent(spec) else default


def _recess_mat():
    return get_material(RECESS, "paint")


TURNED_PROFILE = [(0.0, 0.42), (0.1, 0.36), (0.18, 0.62), (0.3, 0.9), (0.42, 0.95), (0.54, 0.55), (0.6, 0.48),
                  (0.66, 0.78), (0.71, 0.5), (0.86, 0.62), (0.9, 0.95), (1.0, 0.95)]  # (height fraction, radius)


def _leg(mb: MeshBuilder, style, x, y, z1, r, mat, taper=0.65, z0=0.0, room=None, along="y"):
    """One leg from z0 up to z1 centered at (x, y); `room` = free distance to the footprint edge.
    tapered: cone | straight: square post | block: chunky square | metal: thin rod | bun: flattened ball |
    hairpin: two thin rods meeting in a V at a small foot (spread along `along`) |
    turned: lathe profile (foot, bulb, rings, neck, collar)."""
    room = 2 * r if room is None else room
    if style in (None, "tapered"):
        mb.cylinder(x, y, z0, z1, r * taper, r, mat)
    elif style == "turned":
        rr = min(r * 1.15, room - 0.001)
        for (fa, ra), (fb, rb) in zip(TURNED_PROFILE, TURNED_PROFILE[1:]):
            mb.cylinder(x, y, z0 + (z1 - z0) * fa, z0 + (z1 - z0) * fb + 0.0005, rr * ra, rr * rb, mat, segments=14)
    elif style in ("straight", "block"):
        s = min(r * (0.85 if style == "straight" else 1.2), room)
        mb.box(x - s, x + s, y - s, y + s, z0, z1, mat, bevel=min(0.004, s * 0.2), segments=2)
    elif style == "metal":
        mb.cylinder(x, y, z0, z1, r * 0.42, r * 0.42, mat, segments=12)
    elif style == "bun":
        rx = min(room - 0.001, max(r * 1.5, (z1 - z0) * 0.6))
        mb.sphere(x, y, (z0 + z1) / 2, rx, rx, (z1 - z0) / 2, mat, segments=16, rings=8)
    elif style == "hairpin":
        rr = _clamp(r * 0.28, 0.0035, 0.006)
        a = max(0.0, min(0.035, room - rr - 0.001))
        foot = min(0.006, (z1 - z0) * 0.2)
        mb.label, label = "leg_foot", mb.label
        mb.cylinder(x, y, z0, z0 + foot, rr * 1.8, rr * 1.8, mat, segments=10)
        mb.label = "leg_rod"
        ends = [(x, y - a), (x, y + a)] if along == "y" else [(x - a, y), (x + a, y)]
        for ex, ey in ends if a > 0.004 else [(x, y)]:
            mb.rod((x, y, z0 + foot * 0.5), (ex, ey, z1), rr, rr, mat, segments=8)
        mb.label = label


def _front_depths(d, handle=None):
    """(handle projection, drawer-front thickness) so handles stay inside the requested depth."""
    proj = {"none": 0.0, "cutout": 0.0008}.get(handle, min(0.018, d * 0.06))
    return proj, min(0.014, d * 0.04)


def _handle(mb: MeshBuilder, style, cx, cz, cw, rh, top_z, yf, proj, hardware):
    """Pull on a drawer front whose face is at y=yf (front is -Y); cz = height for bars/knobs/cups."""
    if style == "cutout":
        sw, sh = _clamp(cw * 0.3, 0.05, 0.14), _clamp(rh * 0.12, 0.012, 0.025)
        zt = top_z - _clamp(rh * 0.06, 0.006, 0.02)
        mb.box(cx - sw / 2, cx + sw / 2, yf - proj, yf + 0.002, zt - sh, zt, _recess_mat(), bevel=sh * 0.45, segments=2)
    elif style == "knob":
        kr = _clamp(min(cw, rh) * 0.07, 0.008, 0.016)
        for kx in ((cx - cw / 4, cx + cw / 4) if cw >= 0.5 else (cx,)):
            mb.rod((kx, yf + 0.001, cz), (kx, yf - proj, cz), kr * 0.55, kr, hardware, segments=14, bevel=kr * 0.35)
    elif style == "cup":
        hw, hh = _clamp(cw * 0.22, 0.06, 0.11), _clamp(rh * 0.2, 0.02, 0.035)
        mb.box(cx - hw / 2, cx + hw / 2, yf - proj, yf + 0.001, cz - hh / 2, cz + hh / 2, hardware,
               bevel=hh * 0.45, segments=3)
    elif style == "bar":
        hw = min(_clamp(cw * 0.35, 0.08, 0.2), cw * 0.7)
        hh = _clamp(rh * 0.06, 0.008, 0.013)
        mb.box(cx - hw / 2, cx + hw / 2, yf - proj, yf + 0.001, cz - hh / 2, cz + hh / 2, hardware,
               bevel=hh * 0.4, segments=2)
    else:  # default look: bar on wide fronts, small square knob on narrow ones
        if cw >= 0.28:
            hw, hh = _clamp(cw * 0.3, 0.06, 0.18), _clamp(rh * 0.07, 0.008, 0.014)
        else:
            hw = hh = _clamp(min(cw, rh) * 0.16, 0.012, 0.028)
        mb.box(cx - hw / 2, cx + hw / 2, yf - proj, yf + 0.001, cz - hh / 2, cz + hh / 2,
               hardware, bevel=hh * 0.4, segments=2)


def _drawer_bank(mb: MeshBuilder, x0, x1, z0, z1, y_face, rows, cols, front, hardware, ft, proj, handle=None):
    """Drawer fronts on the carcass face y=y_face (front is -Y) with pulls in the requested handle style."""
    gap = _clamp(min(x1 - x0, z1 - z0) * 0.015, 0.002, 0.008)
    cw = (x1 - x0 - gap * (cols + 1)) / cols
    rh = (z1 - z0 - gap * (rows + 1)) / rows
    if cw <= 0.01 or rh <= 0.01:
        return
    label = mb.label
    for c in range(cols):
        for r in range(rows):
            dx0 = x0 + gap + c * (cw + gap)
            dz0 = z0 + gap + r * (rh + gap)
            mb.label = "drawer"
            mb.box(dx0, dx0 + cw, y_face - ft, y_face + 0.001, dz0, dz0 + rh, front, bevel=min(0.003, ft * 0.3), segments=2)
            if handle == "none" or (proj <= 0.002 and handle != "cutout"):
                continue
            mb.label = "handle"
            cz = dz0 + rh * (0.5 if rows > 1 or rh < 0.25 else 0.7)
            _handle(mb, handle, dx0 + cw / 2, cz, cw, rh, dz0 + rh, y_face - ft, proj, hardware)
    mb.label = label


def _door(mb: MeshBuilder, x0, x1, z0, z1, y_face, front, hardware, ft, proj):
    """A single cabinet door with a vertical bar pull near its right edge."""
    gap = _clamp(min(x1 - x0, z1 - z0) * 0.015, 0.002, 0.008)
    mb.label = "door"
    mb.box(x0 + gap, x1 - gap, y_face - ft, y_face + 0.001, z0 + gap, z1 - gap, front, bevel=min(0.003, ft * 0.3), segments=2)
    if proj <= 0.002:
        return
    mb.label = "handle"
    hx = x1 - gap - _clamp((x1 - x0) * 0.12, 0.02, 0.05)
    hh, hw, zc = _clamp((z1 - z0) * 0.3, 0.05, 0.16), 0.012, (z0 + z1) / 2
    mb.box(hx - hw / 2, hx + hw / 2, y_face - ft - proj, y_face - ft + 0.001, zc - hh / 2, zc + hh / 2, hardware,
           bevel=hw * 0.4, segments=2)


def _button_grid(mb: MeshBuilder, x0, x1, z0, z1, y, mat, pitch, r=0.011, pleats=False):
    """Tufting buttons in a diamond (staggered) grid on a front-facing (-Y) surface at y; pleats adds the
    diamond fold lines between neighbouring buttons (deep-buttoned / chesterfield look)."""
    if x1 - x0 < pitch * 0.5 or z1 - z0 < 0.03:
        return
    label, mb.label = mb.label, "button"
    cols = max(1, round((x1 - x0) / pitch))
    rows = max(1, round((z1 - z0) / (pitch * 0.75)))
    grid = []
    for j in range(rows + 1):
        z = z0 + (z1 - z0) * j / rows
        odd = j % 2
        grid.append([(x0 + (x1 - x0) * (i + 0.5 * odd) / cols, z) for i in range(cols + (0 if odd else 1))])
        for x, _ in grid[-1]:
            mb.sphere(x, y + r * 0.15, z, r, r * 0.55, r, mat, segments=8, rings=4)
    if pleats:
        mb.label = "pleat"
        pr = r * 0.32
        for row, nxt in zip(grid, grid[1:]):
            for xa, za in row:
                for xb, zb in nxt:
                    if abs(xb - xa) < (x1 - x0) / cols * 0.6:
                        mb.rod((xa, y + pr * 0.4, za), (xb, y + pr * 0.4, zb), pr, pr, mat, segments=6)
    mb.label = label


def _seat_buttons(mb: MeshBuilder, x0, x1, y0, y1, z, mat, pitch=0.2, r=0.011):
    """Tufting buttons on top of a seat (z = top face), staggered."""
    label, mb.label = mb.label, "button"
    cols = max(1, round((x1 - x0) / pitch))
    rows = max(1, round((y1 - y0) / pitch))
    for j in range(rows):
        y = y0 + (y1 - y0) * (j + 0.5) / rows
        for i in range(cols):
            x = x0 + (x1 - x0) * (i + 0.5 + (0.25 if j % 2 else -0.25) * (cols > 1)) / cols
            mb.sphere(x, y, z - r * 0.15, r, r, r * 0.55, mat, segments=8, rings=4)
    mb.label = label


def _block(bottom, top):
    """8 corners for MeshBuilder.hexa from a bottom and a top rectangle, each (x0, x1, y0, y1, z)."""
    pts = []
    for i in range(8):
        x0, x1, y0, y1, z = top if i & 4 else bottom
        pts.append((x1 if i & 1 else x0, y1 if i & 2 else y0, z))
    return pts


def _sofa_arm(mb: MeshBuilder, style, sx, w, arm_w, y0, y1, z0, seat_top, arm_top, round_r, mat, scroll=None):
    x_out, x_in = sx * w / 2, sx * (w / 2 - arm_w)
    lo, hi = min(x_out, x_in), max(x_out, x_in)
    bevel = min(round_r, 0.3 * arm_w)
    if style == "rolled":  # big roll along the arm, flush outside, bulging inward, with a set-back scroll face
        r = min(arm_w * 0.64, (arm_top - z0) * 0.45)
        cx, cz = sx * (w / 2 - r), arm_top - r
        sd = min(0.018, (y1 - y0) * 0.05)
        mb.box(lo, hi, y0, y1, z0, cz, mat, bevel=bevel, segments=4)
        mb.rod((cx, y0 + sd, cz), (cx, y1, cz), r, r, mat, segments=28, bevel=min(0.02, r * 0.3))
        mb.rod((cx, y0, cz), (cx, y0 + sd + 0.002, cz), r * 0.84, r * 0.84, scroll or mat, segments=28,
               bevel=sd * 0.4)
    elif style == "sloped":  # top falls from the back toward a lower, set-back front
        zf = seat_top + (arm_top - seat_top) * 0.3
        yf = y0 + min(0.14, 0.18 * (y1 - y0))
        pts = []
        for i in range(8):
            x = hi if i & 1 else lo
            back, up = bool(i & 2), bool(i & 4)
            y = y1 if back else (yf if up else y0)
            z = (arm_top if back else zf) if up else z0
            pts.append((x, y, z))
        mb.hexa(pts, mat, bevel=bevel, segments=4)
    elif style == "flared":  # narrower at the base, leaning outward to the full width at the top
        inset = arm_w * 0.4
        blo, bhi = (lo + inset, hi) if sx < 0 else (lo, hi - inset)
        mb.hexa(_block((blo, bhi, y0, y1, z0), (lo, hi, y0, y1, arm_top)), mat, bevel=bevel, segments=4)
    else:  # track
        mb.box(lo, hi, y0, y1, z0, arm_top, mat, bevel=round_r, segments=4)


def build_sofa(mb: MeshBuilder, w, d, h, spec):
    """Arms, back panel, seat/back cushions and legs. form: arm_style, back_style, seat_cushions, back_cushions,
    leg_style, skirt, chaise (left = -X; that side's seat runs to the full depth), tufted_seat,
    arm_bulk, seat_rise, arm_rise, back_bulk (silhouette from the listing photo)."""
    f = _form(spec)
    main = _main_mat(spec)
    finish = spec["frame_finish"]
    leg_style = f.get("leg_style")
    legs = _metal_leg_mat(spec) if leg_style == "metal" else _leg_mat(spec, finish)
    base_mat = main if finish == "upholstered" and not _has_accent(spec) else legs
    arm_style = f.get("arm_style", "track")
    back_style = f.get("back_style", "pillow")
    chaise = f.get("chaise") if f.get("chaise") in ("left", "right") else None

    leg_h = _clamp(h * 0.14, 0.01, 0.15)
    if leg_style == "hidden":
        leg_h = _clamp(h * 0.04, 0.005, 0.03)
    elif leg_style == "bun":
        leg_h = _clamp(h * 0.11, 0.01, 0.1)
    arm_frac = {"slim": 0.055, "plump": 0.16}.get(f.get("arm_bulk"), 0.09)
    back_frac = {"thin": 0.12, "thick": 0.32}.get(f.get("back_bulk"), 0.20)
    seat_frac = {"low": 0.42, "high": 0.64}.get(f.get("seat_rise"), 0.55)
    arm_frac_h = {"low": 0.58, "high": 0.88}.get(f.get("arm_rise"), 0.72)
    arm_w = 0.0 if arm_style == "none" else min(_clamp(w * arm_frac, 0.04, 0.28), w * 0.22)
    back_d = min(_clamp(d * back_frac, 0.03, 0.38), d * 0.42)
    base_top = min(leg_h + h * 0.16, h * (seat_frac - 0.12))
    seat_top = _clamp(h * seat_frac, base_top + 0.04, h * 0.78)
    arm_top = _clamp(h * arm_frac_h, seat_top + 0.02, h * 0.96)
    round_r = min(0.05, 0.3 * min(arm_w or _clamp(w * 0.09, 0.05, 0.22), h * 0.3))
    y_back = d / 2 - back_d
    ix0, ix1 = -w / 2 + arm_w, w / 2 - arm_w
    inner = ix1 - ix0
    gap = min(0.008, inner * 0.01)

    main_d = d if chaise is None else min(d, max(0.6 * d, min(0.9, d - 0.25)))
    y_main = d / 2 - main_d  # front edge of the non-chaise seat (front is -Y)
    sections = [(ix0, ix1, -d / 2)]  # seat runs: (x0, x1, front y)
    if chaise:
        cw_ch = min(_clamp(inner * 0.42, 0.5, 0.95), inner * 0.6)
        xb = ix0 + cw_ch if chaise == "left" else ix1 - cw_ch
        sections = [(ix0, xb, -d / 2 if chaise == "left" else y_main), (xb, ix1, y_main if chaise == "left" else -d / 2)]
    side_front = {-1: sections[0][2], 1: sections[-1][2]}

    mb.label = "plinth"
    for x0, x1, yf in sections:
        mb.box(x0, x1, yf + 0.01 * d, y_back, leg_h, base_top, base_mat, bevel=0.006)
    mb.label = "arm"
    if arm_w > 0:
        for sx in (-1, 1):
            _sofa_arm(mb, arm_style, sx, w, arm_w, side_front[sx], d / 2, leg_h, seat_top, arm_top, round_r, main,
                      _plain_mat(spec, 0.78 if _lum(spec["color_hex"]) > 35 else 1.4))
    mb.label = "back"
    mb.box(-w / 2, w / 2, y_back, d / 2, leg_h, h, main, bevel=round_r, segments=4)

    def default_n(width):
        return 1 if width < 0.9 else 2 if width < 1.7 else 3

    n_req, tufted_seat = f.get("seat_cushions"), bool(f.get("tufted_seat"))
    if chaise:
        runs = []
        for x0, x1, yf in sections:
            is_chaise = yf == -d / 2
            n = 1 if is_chaise else (max(1, n_req - 1) if n_req else (1 if tufted_seat else default_n(x1 - x0)))
            runs.append((x0 + (gap / 2 if x0 != ix0 else 0), x1 - (gap / 2 if x1 != ix1 else 0), yf, n))
    else:
        runs = [(ix0, ix1, -d / 2, n_req or (1 if tufted_seat else default_n(inner)))]
    mb.label = "seat"
    seats = []
    for x0, x1, yf, n in runs:
        cw = (x1 - x0 - gap * (n - 1)) / n
        for i in range(n):
            cx0 = x0 + i * (cw + gap)
            mb.box(cx0, cx0 + cw, yf, y_back, base_top, seat_top, main,
                   bevel=min(0.045, 0.35 * (seat_top - base_top), 0.2 * cw), segments=4)
            seats.append((cx0, cx0 + cw, yf))
    if tufted_seat:
        accent = _tuft_mat(spec)
        for x0, x1, yf in seats:
            _seat_buttons(mb, x0 + 0.05, x1 - 0.05, yf + 0.06, y_back - 0.04, seat_top, accent)

    back_cd = min(_clamp(d * 0.16, 0.02, 0.22), (d - back_d) * 0.4)
    nb = f.get("back_cushions")
    style = "tight" if back_style == "pillow" and nb == 0 else back_style
    mb.label = "back_cushion"
    if style == "pillow":
        if nb is None and not chaise:  # default: one back cushion over each seat cushion
            spans = [(x0, x1) for x0, x1, _ in seats]
        else:
            nb = nb or len(seats)
            bw = (inner - gap * (nb - 1)) / nb
            spans = [(ix0 + i * (bw + gap), ix0 + i * (bw + gap) + bw) for i in range(nb)]
        for x0, x1 in spans:
            mb.box(x0, x1, y_back - back_cd, y_back, seat_top, h * 0.95, main,
                   bevel=min(0.05, 0.4 * back_cd, 0.2 * (x1 - x0)), segments=4)
    else:
        tb = back_cd * 0.7
        z0b, z1b = seat_top - 0.03, h * 0.93
        if style == "channel":  # vertical padded channels
            k = max(3, round(inner / 0.15))
            cg = 0.003
            cw = (inner - cg * (k - 1)) / k
            for i in range(k):
                x0 = ix0 + i * (cw + cg)
                mb.box(x0, x0 + cw, y_back - tb, y_back + 0.002, z0b, z1b, main,
                       bevel=min(0.4 * cw, 0.45 * tb, 0.05), segments=4)
        else:  # tight (one padded slab), tufted = tight + buttons
            mb.box(ix0, ix1, y_back - tb, y_back + 0.002, z0b, z1b, main, bevel=min(0.06, 0.45 * tb), segments=4)
            if style == "tufted":
                _button_grid(mb, ix0 + 0.07, ix1 - 0.07, seat_top + 0.07, z1b - 0.06, y_back - tb, _tuft_mat(spec),
                             pitch=0.15, r=0.015, pleats=True)

    if f.get("skirt"):  # fabric skirt around the base, just above the floor, hiding the legs
        mb.label = "skirt"
        t = min(0.006, d * 0.01)
        z0s, z1s = min(0.012, leg_h * 0.35), leg_h
        fronts = [(-w / 2, ix0, side_front[-1])] + sections + [(ix1, w / 2, side_front[1])]
        for x0, x1, yf in fronts:
            mb.box(x0, x1, yf, yf + t, z0s, z1s, main)
        if chaise:
            mb.box(xb - t / 2, xb + t / 2, -d / 2, y_main, z0s, z1s, main)
        mb.box(-w / 2, -w / 2 + t, side_front[-1], d / 2, z0s, z1s, main)
        mb.box(w / 2 - t, w / 2, side_front[1], d / 2, z0s, z1s, main)
        mb.box(-w / 2, w / 2, d / 2 - t, d / 2, z0s, z1s, main)

    mb.label = "leg"
    r = _clamp(min(w, d) * 0.025, 0.004, 0.03)
    inset = max(2 * r, min(0.05, w * 0.1, d * 0.1))
    if _metal_accent(spec):
        r *= 0.6
    if leg_style == "hidden":  # recessed plinth on the floor
        for k, (x0, x1, yf) in enumerate(sections):
            a = -w / 2 + inset if k == 0 else x0
            b = w / 2 - inset if k == len(sections) - 1 else x1
            mb.box(a, b, yf + inset, d / 2 - inset, 0.0, leg_h + 0.002, legs)
        return
    pts = [(-(w / 2 - inset), d / 2 - inset), (w / 2 - inset, d / 2 - inset),
           (-(w / 2 - inset), side_front[-1] + inset), (w / 2 - inset, side_front[1] + inset)]
    if chaise:
        pts += [(xb, -d / 2 + inset), (xb, y_main + inset)]
    for x, y in pts:
        _leg(mb, leg_style, x, y, leg_h + 0.002, r, legs, taper=0.7, room=inset)


def _coffee_supports(mb: MeshBuilder, style, w, d, under, legs, metal, round_=False, accent=False):
    """Leg structure under a coffee table top; returns the (x0, x1, y0, y1) area a shelf/drawer may use."""
    if round_:
        rx, aspect = w / 2, d / w
        r = _clamp(w * (0.018 if metal else 0.035), 0.004, 0.035)
        ring = rx - max(r * 1.5, min(0.08, w * 0.16))
        inset = rx - ring
        diag = [(math.cos(a) * ring, math.sin(a) * ring * aspect) for a in (math.pi / 4 + k * math.pi / 2 for k in range(4))]
        area = (-(ring + r), ring + r, -(ring + r) * aspect, (ring + r) * aspect)  # round: area[1] = shelf radius
    else:
        r = _clamp(min(w, d) * (0.018 if metal else 0.035), 0.004, 0.035)
        inset = max(r * 1.5, min(0.06, w * 0.12, d * 0.12))
        diag = [(sx * (w / 2 - inset), sy * (d / 2 - inset)) for sx in (-1, 1) for sy in (-1, 1)]
        area = (-w / 2 + inset - r, w / 2 - inset + r, -d / 2 + inset - r, d / 2 - inset + r)
        ring = None
    z1 = under + 0.002
    mb.label = "leg"
    if style is None:
        for x, y in diag:
            mb.cylinder(x, y, 0.0, z1, r * (1.0 if metal else 0.65), r, legs)
    elif style in ("tapered", "straight", "hairpin", "turned"):
        lm = legs if style != "hairpin" or metal or accent else _metal_mat()
        room = inset if not round_ else r * 1.5
        for x, y in diag:
            if round_ and style == "straight":
                mb.cylinder(x, y, 0.0, z1, r * 0.85, r * 0.85, lm)
            else:
                _leg(mb, style, x, y, z1, r, lm, room=room, along="x")
    elif style == "pedestal":  # central column on a base plate (tulip on round tables)
        bt = _clamp(under * 0.06, 0.01, 0.03)
        if round_:
            rb, rc = (w / 2) * 0.55, max(0.03, w * 0.08)
            mb.cylinder(0.0, 0.0, 0.0, bt, rb, rb * 0.92, legs, segments=48, aspect=d / w, bevel=bt * 0.3)
            mb.cylinder(0.0, 0.0, bt - 0.001, bt + (under - bt) * 0.25, rb * 0.7, rc, legs, segments=32, aspect=d / w)
            mb.cylinder(0.0, 0.0, bt, z1, rc, rc * 1.1, legs, segments=32, aspect=d / w)
            area = (-w * 0.3, w * 0.3, -d * 0.3, d * 0.3)
        else:
            pw, pd = max(0.05, w * 0.28), max(0.05, d * 0.35)
            mb.box(-w * 0.28, w * 0.28, -d * 0.33, d * 0.33, 0.0, bt, legs, bevel=bt * 0.3)
            mb.box(-pw / 2, pw / 2, -pd / 2, pd / 2, bt - 0.001, z1, legs, bevel=0.004, segments=2)
            area = (-w * 0.32, w * 0.32, -d * 0.36, d * 0.36)
    elif style == "panel":  # solid end panels (waterfall); round tables get two crossing panels
        pt = _clamp(min(w, d) * 0.05, 0.018, 0.05)
        if round_:
            mb.box(-ring, ring, -pt / 2, pt / 2, 0.0, z1, legs, bevel=0.003, segments=2)
            mb.box(-pt / 2, pt / 2, -ring * d / w, ring * d / w, 0.0, z1, legs, bevel=0.003, segments=2)
        else:
            for sx in (-1, 1):
                x0, x1 = sorted((sx * w / 2, sx * (w / 2 - pt)))
                mb.box(x0, x1, -d / 2, d / 2, 0.0, z1, legs, bevel=0.003, segments=2)
            area = (-w / 2 + pt, w / 2 - pt, -d / 2 + 0.02, d / 2 - 0.02)
    elif style == "sled":  # flat-bar U frames at both ends: floor runner, posts, top rail
        t = _clamp(min(w, d) * 0.025, 0.01, 0.022)
        if round_:
            xe = ring * 0.62
            ye = math.sqrt(max(ring ** 2 - xe ** 2, 1e-6)) * d / w
        else:
            xe, ye = w / 2 - inset, d / 2 - inset
        for xc in (-xe, xe):
            mb.box(xc - t / 2, xc + t / 2, -ye - t / 2, ye + t / 2, 0.0, t, legs)
            mb.box(xc - t / 2, xc + t / 2, -ye - t / 2, ye + t / 2, under - t, z1, legs)
            for yy in (-ye, ye):
                mb.box(xc - t / 2, xc + t / 2, yy - t / 2, yy + t / 2, t - 0.001, under - t + 0.001, legs)
        area = (-(xe - t / 2), xe - t / 2, -ye, ye)
        if round_:
            area = (-ring * 0.75, ring * 0.75) + area[2:]
    elif style == "x_base":  # two boards crossing corner to corner in plan
        bt = _clamp(min(w, d) * 0.06, 0.02, 0.05)
        if round_:
            ends = [((-ring * 0.7071, -ring * 0.7071 * d / w), (ring * 0.7071, ring * 0.7071 * d / w)),
                    ((-ring * 0.7071, ring * 0.7071 * d / w), (ring * 0.7071, -ring * 0.7071 * d / w))]
        else:
            i = bt
            ends = [((-w / 2 + i, -d / 2 + i), (w / 2 - i, d / 2 - i)), ((-w / 2 + i, d / 2 - i), (w / 2 - i, -d / 2 + i))]
        for (ax, ay), (bx, by) in ends:
            ln = math.hypot(bx - ax, by - ay)
            nx, ny = -(by - ay) / ln * bt / 2, (bx - ax) / ln * bt / 2
            pts = []
            for k in range(8):
                px, py = (bx, by) if k & 1 else (ax, ay)
                sgn = 1 if k & 2 else -1
                pts.append((px + sgn * nx, py + sgn * ny, z1 if k & 4 else 0.0))
            mb.hexa(pts, legs, bevel=0.003, segments=2)
    return area


def build_coffee_table(mb: MeshBuilder, w, d, h, spec):
    """Top on legs with an optional lower shelf; form: leg_style, shelf, drawer, top_style (glass/stone/lift_top).
    form.surface glass/marble implies the matching top."""
    f = _form(spec)
    top_style = f.get("top_style")
    srf = specs.main_surface(spec)
    if top_style is None and srf in TOP_ONLY_SURFACES:
        top_style = "glass" if srf == "glass" else "stone"
    top = _top_mat(spec, top_style)
    legs = _plain_mat(spec) if spec["material"] in ("wood", "metal") else _leg_mat(spec, "wood")
    legs = _base_mat(spec, legs)
    body = _plain_mat(spec)
    metal = spec["material"] == "metal" or _metal_accent(spec)
    round_ = spec["shape"] == "round"
    top_t = min(_clamp(h * 0.1, 0.012, 0.05), h * 0.5)
    if top_style == "glass":
        top_t = min(_clamp(h * 0.025, 0.006, 0.012), h * 0.5)
    elif top_style == "stone":
        top_t = min(_clamp(h * 0.07, 0.02, 0.04), h * 0.5)
    rx, aspect = w / 2, d / w

    mb.label = "top"
    if top_style == "lift_top":
        lt = top_t * 0.8
        under = h - top_t - lt
        e = min(0.008, w * 0.02, d * 0.02)
        if round_:
            mb.cylinder(0.0, 0.0, under, h - lt + 0.001, rx, rx, top, segments=ROUND_SEGMENTS, aspect=aspect,
                        bevel=min(top_t * 0.3, 0.008))
            mb.cylinder(0.0, 0.0, h - lt, h, rx * 0.86, rx * 0.86, top, segments=ROUND_SEGMENTS, aspect=aspect,
                        bevel=min(lt * 0.3, 0.006))
        else:
            mb.box(-w / 2, w / 2, -d / 2, d / 2, under, h - lt + 0.001, top, bevel=min(top_t * 0.3, 0.008), segments=3)
            ys = -d / 2 + e + (d - 2 * e) * 0.62
            mb.box(-w / 2 + e, w / 2 - e, -d / 2 + e, ys - 0.0025, h - lt, h, top, bevel=min(lt * 0.3, 0.006), segments=3)
            mb.box(-w / 2 + e, w / 2 - e, ys + 0.0025, d / 2 - e, h - lt, h, top, bevel=min(lt * 0.3, 0.006), segments=3)
    else:
        under = h - top_t
        bevel = 0.002 if top_style == "glass" else min(top_t * (0.2 if top_style == "stone" else 0.3), 0.01)
        if round_:
            mb.cylinder(0.0, 0.0, under, h, rx, rx, top, segments=ROUND_SEGMENTS, aspect=aspect, bevel=bevel)
        else:
            mb.box(-w / 2, w / 2, -d / 2, d / 2, under, h, top, bevel=bevel, segments=3 if top_style != "glass" else 1)
    if top_style == "glass" and round_ and under > 0.08:  # thin tube ring under the glass
        mb.label = "apron"
        rt = _clamp(w * 0.012, 0.006, 0.012)
        ring_r, n = rx - rt * 1.5, 40
        pts = [(math.cos(2 * math.pi * k / n) * ring_r, math.sin(2 * math.pi * k / n) * ring_r * aspect,
                under - rt) for k in range(n + 1)]
        for a, b in zip(pts, pts[1:]):
            mb.rod(a, b, rt, rt, legs, segments=8)
    if top_style == "glass" and not round_ and under > 0.08:  # frame rails under the glass
        mb.label = "apron"
        at, rt, e = min(0.035, under * 0.12), _clamp(min(w, d) * 0.03, 0.012, 0.03), min(0.012, w * 0.03, d * 0.03)
        for y0 in (-d / 2 + e, d / 2 - e - rt):
            mb.box(-w / 2 + e, w / 2 - e, y0, y0 + rt, under - at, under + 0.0005, legs)
        for x0 in (-w / 2 + e, w / 2 - e - rt):
            mb.box(x0, x0 + rt, -d / 2 + e + rt, d / 2 - e - rt, under - at, under + 0.0005, legs)

    ls = f.get("leg_style")
    area = _coffee_supports(mb, ls, w, d, under, legs, metal, round_, _has_accent(spec))
    shelf = f.get("shelf")
    if shelf is None:
        shelf = ls != "pedestal" and h > 0.3 and (w if round_ else min(w, d)) > 0.3
    if shelf and h > 0.12:
        mb.label = "shelf"
        shelf_t = max(top_t * 0.7, 0.008)
        z = h * 0.18
        shelf_mat = body if top_style == "stone" else top
        x0, x1, y0, y1 = area
        if round_:
            mb.cylinder(0.0, 0.0, z, z + shelf_t, x1, x1, shelf_mat, segments=ROUND_SEGMENTS, aspect=aspect,
                        bevel=min(shelf_t * 0.3, 0.006))
        else:
            mb.box(x0, x1, y0, y1, z, z + shelf_t, shelf_mat, bevel=min(shelf_t * 0.3, 0.006))
    if f.get("drawer") and under > 0.12:
        mb.label = "drawer"
        x0, x1, y0, y1 = area
        if round_:  # a box inscribed in the shelf circle
            x0, x1, y0, y1 = x0 * 0.68, x1 * 0.68, y0 * 0.68, y1 * 0.68
        dh = min(0.1, under * 0.28)
        ft = 0.012
        mb.box(x0, x1, y0 + ft, y1, under - dh, under + 0.001, body, bevel=0.003, segments=2)
        g = 0.004
        mb.box(x0 + g, x1 - g, y0, y0 + ft + 0.001, under - dh + g, under - g, _front_mat(spec), bevel=0.002, segments=2)
        mb.label = "handle"
        proj = min(0.014, y0 + d / 2 - 0.001)
        _handle(mb, "bar" if x1 - x0 > 0.3 else "knob", (x0 + x1) / 2, under - dh / 2, x1 - x0, dh, under,
                y0, proj, _hardware_mat(spec))


def build_tv(mb: MeshBuilder, w, d, h, spec):
    """Panel with a glossy screen facing -Y. form: bezel thin | frame (wide picture-frame border standing proud),
    stand pedestal (default: center foot + neck) | feet (two splayed feet) | none (wall bracket behind)."""
    f = _form(spec)
    body = _main_mat(spec)
    screen = get_material(SCREEN, "screen")
    stand = f.get("stand", "pedestal")
    framed = f.get("bezel") == "frame"
    panel_t = _clamp(d * 0.25, 0.004, 0.06)
    front_room = max((d - panel_t) / 2, 0.0)
    glass_t = min(0.002, front_room)
    frame_d = min(0.01, front_room * 0.8) if framed else 0.0
    if stand == "none":
        panel_h, panel_z0 = h, 0.0
        y_c = -d / 2 + max(glass_t, frame_d) + panel_t / 2
    else:
        panel_h = h * 0.86
        panel_z0 = h - panel_h
        y_c = 0.0
    yf = y_c - panel_t / 2  # front face of the housing
    mb.label = "panel"
    mb.box(-w / 2, w / 2, yf, y_c + panel_t / 2, panel_z0, h, body, bevel=min(0.004, panel_t * 0.3), segments=2)
    bezel = _clamp(min(w, panel_h) * 0.02, 0.003, 0.03)
    if framed:
        bezel = _clamp(min(w, panel_h) * 0.05, 0.015, 0.07)
        mb.label = "frame"
        for z0, z1 in ((panel_z0, panel_z0 + bezel), (h - bezel, h)):
            mb.box(-w / 2, w / 2, yf - frame_d, yf + 0.001, z0, z1, body, bevel=min(0.003, frame_d * 0.3), segments=2)
        for x0 in (-w / 2, w / 2 - bezel):
            mb.box(x0, x0 + bezel, yf - frame_d, yf + 0.001, panel_z0 + bezel, h - bezel, body,
                   bevel=min(0.003, frame_d * 0.3), segments=2)
    mb.label = "screen"
    mb.box(-w / 2 + bezel, w / 2 - bezel, yf - glass_t, yf + 0.0005, panel_z0 + bezel, h - bezel, screen)
    mb.label = "stand"
    if stand == "none":
        bw = _clamp(w * 0.3, 0.05, 0.4)
        mb.box(-bw / 2, bw / 2, y_c + panel_t / 2 - 0.001, d / 2, h * 0.3, h * 0.62, _metal_mat(), bevel=0.002)
    elif stand == "feet":
        fx = w / 2 - _clamp(w * 0.1, 0.02, 0.2)
        ft = _clamp(w * 0.012, 0.006, 0.02)
        z_top = panel_z0 + min(panel_h * 0.08, 0.06)
        for sx in (-1, 1):
            x = sx * fx
            mb.hexa(_block((x - ft / 2, x + ft / 2, -d / 2, d / 2, 0.0),
                           (x - ft / 2, x + ft / 2, -panel_t * 0.4, panel_t * 0.4, z_top)), body, bevel=0.0015, segments=2)
    else:
        foot_t = min(_clamp(h * 0.025, 0.004, 0.02), panel_z0 * 0.5)
        foot_w = min(w, _clamp(w * 0.38, 0.05, 0.6))
        mb.box(-foot_w / 2, foot_w / 2, -d / 2, d / 2, 0.0, foot_t, body, bevel=min(0.006, foot_t * 0.4))
        neck_w = _clamp(w * 0.06, 0.01, 0.1)
        neck_d = min(panel_t, d * 0.3)
        mb.box(-neck_w / 2, neck_w / 2, 0.0, neck_d, foot_t, panel_z0 + panel_h * 0.3, body, bevel=0.002)


def _rug_tufts(mb: MeshBuilder, ox, oy, band, h, mat, round_, aspect, rng):
    """Shaggy edge: short tufts of varying height around the rug, outer faces on the rug outline."""
    mb.label = "tuft"
    sp = 0.014
    if round_:
        r_out = ox
        n = max(8, int(2 * math.pi * r_out / sp) // 4 * 4)
        da = 2 * math.pi / n
        for k in range(n):
            a = k * da
            hz = h * rng.uniform(0.55, 0.95)
            r_in = r_out - band * rng.uniform(0.9, 1.4)
            pts = []
            for i in range(8):
                ang = a + (da * 0.55 if i & 1 else -da * 0.55)
                rad = r_out if i & 2 else r_in
                pts.append((math.cos(ang) * rad, math.sin(ang) * rad * aspect, hz if i & 4 else 0.0))
            mb.hexa(pts, mat)
        return
    for axis, half_len, half_other in ((0, ox, oy), (1, oy, ox)):
        n = max(2, int(2 * half_len / sp))
        step = 2 * half_len / n
        for side in (-1, 1):
            for k in range(n):
                a0 = -half_len + k * step
                hz = h * rng.uniform(0.55, 0.95)
                depth = band * rng.uniform(0.9, 1.4)
                outer, inner = side * half_other, side * (half_other - depth)
                lo_o, hi_o = min(outer, inner), max(outer, inner)
                a1 = min(a0 + step * 1.05, half_len)
                if axis == 0:
                    mb.box(a0, a1, lo_o, hi_o, 0.0, hz, mat)
                else:
                    mb.box(lo_o, hi_o, a0, a1, 0.0, hz, mat)


def _rug_fringe(mb: MeshBuilder, ox, oy, w, d, h, mat, round_, aspect, rng):
    """Tassels: thin strands lying on the floor past the short ends (all around a round rug)."""
    mb.label = "fringe"
    hf, sw, sp = min(h * 0.5, 0.004), 0.0035, 0.011
    if round_:
        r_in, r_out = ox - 0.004, w / 2
        n = max(8, int(2 * math.pi * r_out / sp) // 4 * 4)
        dw = sw / r_out / 2
        for k in range(n):
            a = 2 * math.pi * k / n
            ro = r_out if k % (n // 4) == 0 else r_in + (r_out - r_in) * rng.uniform(0.85, 1.0)
            pts = []
            for i in range(8):
                ang = a + (dw if i & 1 else -dw)
                rad = ro if i & 2 else r_in
                pts.append((math.cos(ang) * rad, math.sin(ang) * rad * aspect, hf if i & 4 else 0.0))
            mb.hexa(pts, mat)
        return
    long_x = w >= d
    half_end = oy if long_x else ox    # half-length of the end edge carrying the tassels
    inner = (ox if long_x else oy) - 0.004
    outer = (w if long_x else d) / 2
    n = max(2, int(2 * half_end / sp))
    for side in (-1, 1):
        for k in range(n):
            c = -half_end + (k + 0.5) * 2 * half_end / n
            length = (outer - inner) * (1.0 if k == 0 else rng.uniform(0.85, 1.0))
            a, b = sorted((side * inner, side * (inner + length)))
            if long_x:
                mb.box(a, b, c - sw / 2, c + sw / 2, 0.0, hf, mat)
            else:
                mb.box(c - sw / 2, c + sw / 2, a, b, 0.0, hf, mat)


def build_rug(mb: MeshBuilder, w, d, h, spec):
    """Field + contrasting border; with a print texture, one slab whose top carries the whole image.
    form: pile flat (crisp edge, woven surface) | low (default) | high (thick rounded edge + shaggy tufts),
    fringe (tassels past the two short ends, all around when round)."""
    f = _form(spec)
    pile, fringe = f.get("pile"), bool(f.get("fringe"))
    rspec = spec
    if pile == "flat" and specs.main_surface(spec) == "wool":  # flat-woven wool reads as a weave, not pile
        rspec = dict(spec, form=dict(f, surface="weave"))
    elif pile == "high" and specs.main_surface(spec) == "wool":
        rspec = dict(spec, form=dict(f, surface="shag"))
    mb.main_surface = specs.main_surface(rspec)
    round_ = spec["shape"] == "round"
    aspect = d / w
    rng = np.random.default_rng(7)
    ox, oy = w / 2, d / 2  # rug proper, before the fringe
    fl = _clamp(min(w, d) * 0.035, 0.01, 0.07)
    if fringe and (round_ or max(w, d) > 6 * fl):
        if round_:
            ox, oy = ox - fl, oy - fl * aspect
        elif w >= d:
            ox -= fl
        else:
            oy -= fl
    else:
        fringe = False
    band = _clamp(h * 0.9, 0.006, 0.02) if pile == "high" and min(ox, oy) > 0.1 else 0.0
    bx, by = ox - band, oy - band * (aspect if round_ else 1.0)
    mb.footprint = (2 * ox, 2 * oy)
    field = _main_mat(rspec)
    border = _plain_mat(rspec, 0.72 if _lum(spec["color_hex"]) > 70 else 1.6)
    b = min(_clamp(min(bx, by) * 2 * 0.06, 0.005, 0.15), min(bx, by) * 2 * 0.3)
    r = {"flat": min(h * 0.15, 0.001), "high": min(h * 0.45, 0.01)}.get(pile, min(h * 0.4, 0.004))
    mb.label = "field"
    if field.get("r2r_uv_mode") == "print":
        if round_:
            mb.cylinder(0.0, 0.0, 0.0, h, bx, bx, field, segments=ROUND_SEGMENTS, aspect=by / bx, bevel=r)
        else:
            mb.box(-bx, bx, -by, by, 0.0, h, field, bevel=r, segments=2)
        border = bpy.data.materials[field["r2r_edge_material"]]
    elif round_:
        # Field disk stands 3% proud of the border disk so the two tops never z-fight.
        mb.cylinder(0.0, 0.0, 0.0, h * 0.97, bx, bx, border, segments=ROUND_SEGMENTS, aspect=by / bx, bevel=r)
        mb.cylinder(0.0, 0.0, 0.0, h, bx - b, bx - b, field, segments=ROUND_SEGMENTS, aspect=by / bx, bevel=r)
    else:
        mb.box(-bx + b, bx - b, -by + b, by - b, 0.0, h, field, bevel=r, segments=2)
        mb.label = "border"
        mb.box(-bx, bx, -by, -by + b, 0.0, h, border, bevel=r, segments=2)
        mb.box(-bx, bx, by - b, by, 0.0, h, border, bevel=r, segments=2)
        mb.box(-bx, -bx + b, -by + b, by - b, 0.0, h, border, bevel=r, segments=2)
        mb.box(bx - b, bx, -by + b, by - b, 0.0, h, border, bevel=r, segments=2)
    if band:
        _rug_tufts(mb, ox, oy, band, h, border, round_, aspect, rng)
    if fringe:
        _rug_fringe(mb, ox, oy, w, d, h, surface_material(FRINGE, "linen", "fabric", px=SECONDARY_PX),
                    round_, aspect, rng)


def _side_drawers(mb: MeshBuilder, sx, x_face, y0, y1, z0, z1, n, front, hardware, ft, proj):
    """Storage-bed drawers on the long side x = sx * x_face, pulls reaching sx * (x_face + ft + proj)."""
    gap = 0.006
    dw = (y1 - y0 - gap * (n - 1)) / n
    if dw <= 0.05 or z1 - z0 <= 0.03:
        return
    for i in range(n):
        a = y0 + i * (dw + gap)
        mb.label = "drawer"
        xa, xb = sorted((sx * (x_face - 0.001), sx * (x_face + ft)))
        mb.box(xa, xb, a, a + dw, z0, z1, front, bevel=min(0.003, ft * 0.3), segments=2)
        mb.label = "handle"
        hy, hh, zc = _clamp(dw * 0.3, 0.06, 0.18), _clamp((z1 - z0) * 0.08, 0.008, 0.014), (z0 + z1) / 2
        xa, xb = sorted((sx * (x_face + ft - 0.001), sx * (x_face + ft + proj)))
        mb.box(xa, xb, a + dw / 2 - hy / 2, a + dw / 2 + hy / 2, zc - hh / 2, zc + hh / 2, hardware,
               bevel=hh * 0.4, segments=2)


def _bed_board(mb: MeshBuilder, style, w, y0, y1, z0, z1, z_low, mat, post_w):
    """Wooden board between two posts spanning y0..y1 and 0..z1: wood (panel) | slatted | spindle."""
    for sx in (-1, 1):
        x_out, x_in = sx * w / 2, sx * (w / 2 - post_w)
        mb.box(min(x_out, x_in), max(x_out, x_in), y0, y1, 0.0, z1, mat, bevel=0.006, segments=3)
    t = y1 - y0
    if style == "wood":
        mb.box(-w / 2 + post_w, w / 2 - post_w, y0 + t * 0.25, y1 - t * 0.15, z0, z1 * 0.97, mat, bevel=0.004, segments=2)
        return
    rail_h = _clamp(z1 * 0.06, 0.035, 0.08)
    x0, x1 = -w / 2 + post_w, w / 2 - post_w
    top0, low1 = z1 * 0.985 - rail_h, z_low + rail_h * 0.8
    mb.box(x0, x1, y0 + t * 0.15, y1 - t * 0.1, top0, z1 * 0.985, mat, bevel=0.004, segments=2)
    mb.box(x0, x1, y0 + t * 0.2, y1 - t * 0.15, z_low, low1, mat, bevel=0.003, segments=2)
    if top0 - low1 < 0.03:
        return
    mb.label, label = "slat", mb.label
    inner = x1 - x0
    if style == "slatted":
        sw, g = _clamp(w * 0.03, 0.035, 0.06), 0.04
        k = max(3, int((inner + g) / (sw + g)))
        g = (inner - k * sw) / (k + 1)
        for i in range(k):
            a = x0 + g + i * (sw + g)
            mb.box(a, a + sw, y0 + t * 0.3, y1 - t * 0.25, low1 - 0.001, top0 + 0.001, mat, bevel=0.003, segments=2)
    else:
        sr = _clamp(t * 0.18, 0.008, 0.014)
        k = max(3, int(inner / 0.1))
        for i in range(k):
            mb.cylinder(x0 + inner * (i + 0.5) / k, (y0 + y1) / 2, low1 - 0.001, top0 + 0.001, sr, sr, mat, segments=10)
    mb.label = label


def build_bed(mb: MeshBuilder, w, d, h, spec):
    """Frame + mattress, headboard at the back (+Y here, -Z in scene space) setting the full height,
    pillows against the headboard and a blanket with a turned-down sheet over the foot end.
    form: headboard panel|tufted|channel|slatted|spindle|wingback|none, footboard, leg_style, frame
    platform|rails|storage (drawers in the long sides). Without a headboard the pillows set the height."""
    f = _form(spec)
    main = _main_mat(spec)
    finish = spec["frame_finish"]
    soft = finish == "upholstered" or spec["material"] in ("fabric", "leather", "wool")
    hb = f.get("headboard") or ("channel" if soft else "wood")
    if hb == "panel" and not soft:
        hb = "wood"
    frame = f.get("frame", "rails")
    leg_style = f.get("leg_style")
    footboard = bool(f.get("footboard"))
    mattress = surface_material(MATTRESS, "quilted", "fabric")
    sheet = surface_material(SHEET, "linen", "fabric", px=SECONDARY_PX)
    pillow = surface_material(PILLOW, "linen", "fabric", px=SECONDARY_PX)
    blanket = surface_material(BLANKET_ON_LIGHT if _lum(spec["color_hex"]) > 110 else BLANKET_ON_DARK, "weave", "wool")

    hb_t = 0.0 if hb == "none" else min(_clamp(d * 0.045, 0.04, 0.1), d * 0.1)
    y_hb = d / 2 - hb_t                                  # front face of the headboard
    fb_t = min(_clamp(d * 0.035, 0.03, 0.08), d * 0.08) if footboard else 0.0
    y_fb = -d / 2 + fb_t                                 # back face of the footboard
    if hb == "none":
        pillow_t = _clamp(h * 0.22, 0.03, 0.14)
        mattress_top = h - pillow_t
    else:
        mattress_top = min(0.56, h * 0.62)
    if leg_style is None:
        leg_h = 0.0 if finish == "upholstered" or frame == "storage" else _clamp(mattress_top * 0.2, 0.01, 0.12)
    else:
        leg_h = 0.0 if leg_style == "hidden" else _clamp(mattress_top * 0.2, 0.01, 0.12)
    rail_top = leg_h + (mattress_top - leg_h) * {"platform": 0.3, "storage": 0.6}.get(frame, 0.45)
    rail_t = _clamp(w * 0.03, 0.02, 0.06)
    if hb == "wingback":
        rail_t = max(rail_t, _clamp(w * 0.04, 0.04, 0.07))

    side_in = 0.0
    if frame == "storage":
        proj, ft = _front_depths(w)
        side_in = proj + ft
    upholstered_hb = hb in ("channel", "panel", "tufted", "wingback")
    frame_mat = _base_mat(spec, main) if upholstered_hb else main
    mb.label = "frame"
    mb.box(-w / 2 + side_in, w / 2 - side_in, y_fb - (0.002 if footboard else 0.0), min(d / 2, y_hb + 0.002),
           leg_h, rail_top, frame_mat, bevel=min(0.012 if soft else 0.006, 0.3 * (rail_top - leg_h)), segments=3)
    if frame == "platform":
        lip = _clamp(w * 0.03, 0.025, 0.06)
        m_x0, m_x1, m_y0, m_z0 = -w / 2 + lip, w / 2 - lip, y_fb + lip, rail_top - 0.001
    else:
        m_x0, m_x1, m_y0 = -w / 2 + rail_t, w / 2 - rail_t, y_fb + rail_t
        m_z0 = rail_top - min(0.06, 0.5 * (rail_top - leg_h))
    m_y1 = y_hb - 0.004
    mb.label = "mattress"
    mb.box(m_x0, m_x1, m_y0, m_y1, m_z0, mattress_top, mattress,
           bevel=min(0.04, 0.3 * (mattress_top - m_z0)), segments=4)
    if frame == "storage":
        n = 2 if y_hb - y_fb > 1.0 else 1
        for sx in (-1, 1):
            _side_drawers(mb, sx, w / 2 - side_in, y_fb + 0.04, y_hb - 0.04, leg_h + 0.02, rail_top - 0.02, n,
                          _front_mat(spec), _hardware_mat(spec), ft, proj)

    mb.label = "headboard"
    back_t = hb_t * 0.45
    c_z0 = max(rail_top, mattress_top - 0.1)
    post_w = min(_clamp(w * 0.04, 0.04, 0.07), w * 0.1)
    if hb in ("channel", "panel", "tufted", "wingback"):
        mb.box(-w / 2, w / 2, d / 2 - back_t, d / 2, 0.0, h, main, bevel=min(0.012, back_t * 0.3), segments=3)
        wing_t = rail_t - 0.003 if hb == "wingback" else 0.0
        if hb == "channel" and h - c_z0 > 0.05:
            n = max(3, round(w / 0.24))
            gap = 0.006
            cw = (w - gap * (n - 1)) / n
            for i in range(n):
                x0 = -w / 2 + i * (cw + gap)
                mb.box(x0, x0 + cw, y_hb, d / 2 - back_t + 0.002, c_z0, h, main,
                       bevel=min(0.035, 0.4 * cw, 0.45 * (hb_t - back_t), 0.3 * (h - c_z0)), segments=4)
        elif hb != "channel" and h - c_z0 > 0.05:
            mb.box(-w / 2 + wing_t, w / 2 - wing_t, y_hb, d / 2 - back_t + 0.002, c_z0, h, main,
                   bevel=min(0.035, 0.45 * (hb_t - back_t), 0.3 * (h - c_z0)), segments=4)
            if hb in ("tufted", "wingback"):  # classic wingbacks are button-tufted
                _button_grid(mb, -w / 2 + wing_t + 0.09, w / 2 - wing_t - 0.09, c_z0 + 0.09, h - 0.07, y_hb,
                             _tuft_mat(spec), pitch=0.15, r=0.014, pleats=True)
        if hb == "wingback":
            mb.label = "wing"
            wing_d = min(_clamp(d * 0.09, 0.12, 0.24), (y_hb - y_fb) * 0.3)
            for sx in (-1, 1):
                a, b = sorted((sx * w / 2, sx * (w / 2 - wing_t)))
                mb.box(a, b, y_hb - wing_d, d / 2 - back_t + 0.002, rail_top, h, main,
                       bevel=min(0.03, 0.4 * wing_t), segments=4)
    elif hb in ("wood", "slatted", "spindle"):
        _bed_board(mb, hb, w, y_hb, d / 2, 0.0, h, max(rail_top, mattress_top - 0.06), main, post_w)

    if footboard:
        mb.label = "footboard"
        fb_h = min(h, mattress_top + (max(0.06, (h - mattress_top) * 0.4) if hb != "none" else 0.05))
        if hb in ("wood", "slatted", "spindle"):
            _bed_board(mb, hb, w, -d / 2, y_fb, leg_h, fb_h, max(leg_h, rail_top - 0.02), main, post_w)
        else:
            mb.box(-w / 2, w / 2, -d / 2, y_fb, 0.0, fb_h, main, bevel=min(0.03, 0.4 * fb_t), segments=4)

    if leg_h > 0:
        mb.label = "leg"
        legs = _metal_leg_mat(spec) if leg_style == "metal" else _leg_mat(spec, finish)
        r = _clamp(w * 0.016, 0.015, 0.03) * (0.6 if _metal_accent(spec) else 1.0)
        inset = r * 2.2
        xs = (-w / 2 + inset, w / 2 - inset) + ((0.0,) if w > 1.4 else ())
        for x in xs:
            for y in (y_fb + inset, y_hb - inset):
                _leg(mb, leg_style, x, y, leg_h + 0.002, r, legs, taper=0.7, room=inset)

    pillow_t = min(0.14, (h - mattress_top) * 0.7) if hb != "none" else h - mattress_top
    if pillow_t > 0.025:
        mb.label = "pillow"
        n = 1 if m_x1 - m_x0 < 1.15 else 2
        margin, gap = 0.05, 0.04
        pw = (m_x1 - m_x0 - 2 * margin - gap * (n - 1)) / n
        pd = min(0.45, (m_y1 - m_y0) * 0.25)
        py1 = m_y1 - 0.02
        z0p = mattress_top - 0.02
        for i in range(n):
            x0 = m_x0 + margin + i * (pw + gap)
            mb.box(x0, x0 + pw, py1 - pd, py1, z0p, mattress_top + pillow_t, pillow,
                   bevel=min(0.06, 0.45 * pillow_t, 0.3 * pd), segments=5)

    mb.label = "blanket"
    bt = min(0.02, rail_t * 0.8)
    by1 = m_y0 + (m_y1 - m_y0) * 0.62
    drape_z0 = min(rail_top + 0.02, mattress_top - 0.02)
    mb.box(m_x0 - bt, m_x1 + bt, m_y0 - bt, by1, drape_z0, mattress_top + bt, blanket,
           bevel=min(bt * 0.9, 0.3 * (mattress_top + bt - drape_z0)), segments=3)
    cuff_d = min(0.16, (by1 - m_y0) * 0.3)
    mb.box(m_x0 - bt * 0.5, m_x1 + bt * 0.5, by1 - cuff_d, by1 + 0.01, mattress_top, mattress_top + bt * 1.6, sheet,
           bevel=bt * 0.6, segments=3)


def _nightstand_legs(mb: MeshBuilder, style, w, y0, y1, leg_h, legs, spec, round_=False, aspect=1.0, drum=0.0):
    mb.label = "leg"
    slim = 0.65 if _metal_accent(spec) or _body_surface(spec) in METAL_SURFACES else 1.0
    if round_:
        if style == "plinth":
            mb.cylinder(0.0, 0.0, 0.0, leg_h + 0.002, drum * 0.8, drum * 0.8, _base_mat(spec, _plain_mat(spec, 0.6)),
                        segments=ROUND_SEGMENTS, aspect=aspect)
            return
        r = _clamp(w * 0.04, 0.008, 0.02) * slim
        ring = drum - r * 1.6
        for i in range(4):
            a = math.pi / 4 + i * math.pi / 2
            x, y = math.cos(a) * ring, math.sin(a) * ring * aspect
            if style == "straight":
                mb.cylinder(x, y, 0.0, leg_h + 0.002, r * 0.8, r * 0.8, legs)
            else:
                _leg(mb, style, x, y, leg_h + 0.002, r, legs, room=r * 1.6)
        return
    d0 = y1 - y0
    if style == "plinth":
        pi = min(0.02, w * 0.05, d0 * 0.08)
        mb.box(-w / 2 + pi, w / 2 - pi, y0 + pi, y1 - pi, 0.0, leg_h + 0.002, _base_mat(spec, _plain_mat(spec, 0.6)))
        return
    r = _clamp(min(w, d0) * 0.04, 0.008, 0.02) * slim
    inset = r * 1.6
    for x in (-w / 2 + inset, w / 2 - inset):
        for y in (y0 + inset, y1 - inset):
            _leg(mb, style, x, y, leg_h + 0.002, r, legs, room=inset)


def build_nightstand(mb: MeshBuilder, w, d, h, spec):
    """Drawer box on short legs (or on the floor when very low); round variant is a drum with a top disk.
    form: drawers 0-3 (0 without an open shelf = a door), open_shelf (open compartment), door (a door
    compartment), leg_style tapered|straight|hairpin|plinth|none|turned. Compartments stack bottom to top:
    door, open shelf, drawers."""
    f = _form(spec)
    main = _main_mat(spec)
    front, hardware, legs = _front_mat(spec), _hardware_mat(spec), _case_leg_mat(spec)
    ls = f.get("leg_style")
    if ls == "hairpin":
        legs = _metal_leg_mat(spec)
    leg_h = _clamp(h * 0.16, 0.03, 0.14) if h >= 0.3 else 0.0
    if ls == "none":
        leg_h = 0.0
    elif ls in ("straight", "hairpin") and h >= 0.3:  # open-frame stands: tall, clearly visible legs
        leg_h = _clamp(h * 0.27, 0.06, 0.25)
    elif ls == "plinth":
        leg_h = _clamp(h * 0.06, 0.015, 0.06)
    elif ls is not None and leg_h == 0.0:
        leg_h = _clamp(h * 0.12, 0.02, 0.04)
    top_t = _clamp(h * 0.04, 0.012, 0.03)
    drawers, open_shelf = f.get("drawers"), bool(f.get("open_shelf"))
    body_h = h - top_t - leg_h
    interior = _plain_mat(spec, 0.7)
    if spec["shape"] == "round":
        rx, aspect = w / 2, d / w
        drum = rx * 0.93
        mb.label = "top"
        mb.cylinder(0.0, 0.0, h - top_t, h, rx, rx, main, segments=ROUND_SEGMENTS, aspect=aspect,
                    bevel=min(0.006, top_t * 0.35))
        round_door = bool(f.get("door"))
        n = (0 if round_door else 2) if drawers is None else drawers
        zd0, zd1 = leg_h, h - top_t
        mb.label = "carcass"
        if open_shelf:  # open tier: thin bottom disk, recessed core, drawer drum above (if any)
            pt = _clamp(body_h * 0.04, 0.01, 0.02)
            z_b = leg_h + body_h * (0.45 if n else 1.0)
            mb.cylinder(0.0, 0.0, leg_h, leg_h + pt, drum, drum, main, segments=ROUND_SEGMENTS, aspect=aspect)
            mb.cylinder(0.0, 0.0, leg_h + pt - 0.001, z_b + 0.001, drum * 0.72, drum * 0.72, interior,
                        segments=ROUND_SEGMENTS, aspect=aspect)
            zd0 = z_b
        if zd1 - zd0 > 0.01 and (n or not open_shelf or round_door):
            mb.cylinder(0.0, 0.0, zd0, zd1 + 0.001, drum, drum, main, segments=ROUND_SEGMENTS, aspect=aspect)
        seam_t = min(0.004, body_h * 0.02)
        seam = _tuft_mat(spec)
        k = _clamp(w * 0.04, 0.012, 0.025)
        if round_door and zd1 - zd0 > 0.05:  # curved door: two vertical seams on the front and a knob
            dz0, dz1 = zd0, zd0 + (zd1 - zd0) * (0.55 if n else 1.0)
            mb.label = "seam"
            for xs in (-drum * 0.55, drum * 0.55):
                yf = -math.sqrt(drum ** 2 - xs ** 2) * aspect
                mb.box(xs - seam_t / 2, xs + seam_t / 2, yf - 0.0015, yf + 0.004, dz0 + 0.01, dz1 - 0.01, seam)
            if n:
                mb.cylinder(0.0, 0.0, dz1, dz1 + seam_t, drum + 0.0015, drum + 0.0015, seam,
                            segments=ROUND_SEGMENTS, aspect=aspect)
            mb.label = "handle"
            kx, kz = drum * 0.4, (dz0 + dz1) / 2
            yk = -math.sqrt(drum ** 2 - kx ** 2) * aspect
            mb.box(kx - k / 2, kx + k / 2, yk - k * 0.9, yk + 0.003, kz - k / 2, kz + k / 2, hardware,
                   bevel=k * 0.3, segments=2)
            zd0 = dz1
        if n:
            cuts = [zd0 + body_h * 0.45] if drawers is None and not open_shelf else \
                [zd0 + (zd1 - zd0) * i / n for i in range(1, n)]
            for z_seam in cuts:
                mb.label = "seam"
                mb.cylinder(0.0, 0.0, z_seam, z_seam + seam_t, drum + 0.0015, drum + 0.0015, seam,
                            segments=ROUND_SEGMENTS, aspect=aspect)
            edges = [zd0] + cuts + [zd1]
            mb.label = "handle"
            for z_a, z_b in zip(edges, edges[1:]):
                kz = (z_a + z_b) / 2
                mb.box(-k / 2, k / 2, -rx * aspect * 0.995, -drum * aspect + 0.002, kz - k / 2, kz + k / 2, hardware,
                       bevel=k * 0.4, segments=2)
        if leg_h > 0:
            _nightstand_legs(mb, ls, w, 0, 0, leg_h, legs, spec, True, aspect, drum)
        return

    want_door = bool(f.get("door"))
    if drawers is None and want_door:
        drawers = 0
    rows = drawers if drawers is not None else (1 if body_h < 0.22 else 2 if body_h < 0.55 else 3)
    door = want_door or (rows == 0 and not open_shelf)
    proj, ft = _front_depths(d) if rows or door else (0.0, 0.0)
    y_face = -d / 2 + proj + ft
    z_top = h - top_t + 0.001
    mb.label = "top"
    mb.box(-w / 2, w / 2, y_face - ft, d / 2, h - top_t, h, main, bevel=min(0.006, top_t * 0.35), segments=3)
    mb.label = "carcass"
    stack = [k for k, on in (("door", door), ("open", open_shelf), ("drawers", rows > 0)) if on]
    cuts = [leg_h + body_h * i / len(stack) for i in range(len(stack) + 1)]
    for sec, za, zb in zip(stack, cuts, cuts[1:]):
        zt = z_top if sec == stack[-1] else zb + 0.001
        if sec == "open":
            pt = _clamp(min(w, d) * 0.04, 0.012, 0.02)
            mb.box(-w / 2, -w / 2 + pt, y_face, d / 2, za, zt, main)
            mb.box(w / 2 - pt, w / 2, y_face, d / 2, za, zt, main)
            mb.box(-w / 2 + pt, w / 2 - pt, d / 2 - pt, d / 2, za, zt, interior)
            mb.box(-w / 2 + pt, w / 2 - pt, y_face, d / 2 - pt, za, za + pt, main)
            if len(stack) == 1 and zb - za > 0.32:
                zm = (za + zb) / 2
                mb.box(-w / 2 + pt, w / 2 - pt, y_face + 0.01, d / 2 - pt, zm, zm + pt, main)
            continue
        mb.box(-w / 2, w / 2, y_face, d / 2, za, zt, main, bevel=0.004, segments=2)
        if sec == "door":
            _door(mb, -w / 2, w / 2, za, zb, y_face, front, hardware, ft, proj)
        else:
            _drawer_bank(mb, -w / 2, w / 2, za, zb, y_face, rows, 1, front, hardware, ft, proj)
    if leg_h > 0:
        _nightstand_legs(mb, ls, w, y_face, d / 2, leg_h, legs, spec)


def build_dresser(mb: MeshBuilder, w, d, h, spec):
    """Wide carcass with columns x rows of drawers. form: columns 1-3, rows 2-5, leg_style plinth (default) |
    metal (default with frame_finish=metal) | tapered | bun | turned, handle_style knob|bar|cutout|cup|none."""
    f = _form(spec)
    main = _main_mat(spec)
    front, hardware = _front_mat(spec), _hardware_mat(spec)
    handle = f.get("handle_style")
    proj, ft = _front_depths(d, handle)
    y_face = -d / 2 + proj + ft
    top_t = _clamp(h * 0.03, 0.015, 0.03)
    ls = f.get("leg_style") or ("metal" if spec["frame_finish"] == "metal" else "plinth")
    base_h = {"metal": _clamp(h * 0.14, 0.02, 0.15), "tapered": _clamp(h * 0.13, 0.03, 0.16),
              "turned": _clamp(h * 0.13, 0.03, 0.16),
              "bun": _clamp(h * 0.07, 0.02, 0.08)}.get(ls, _clamp(h * 0.06, 0.02, 0.09))
    mb.label = "carcass"
    mb.box(-w / 2, w / 2, y_face, d / 2, base_h, h - top_t + 0.001, main, bevel=0.004, segments=2)
    mb.label = "top"
    mb.box(-w / 2, w / 2, y_face - ft, d / 2, h - top_t, h, main, bevel=min(0.006, top_t * 0.35), segments=3)
    mb.label = "leg"
    if ls == "metal":
        s = _clamp(min(w, d) * 0.04, 0.015, 0.03) * (0.7 if _metal_accent(spec) else 1.0)
        inset = s * 0.5
        for x0 in (-w / 2 + inset, w / 2 - inset - s):
            for y0 in (y_face + inset, d / 2 - inset - s):
                mb.box(x0, x0 + s, y0, y0 + s, 0.0, base_h + 0.002, _metal_leg_mat(spec), bevel=0.002)
    elif ls in ("tapered", "bun", "turned"):
        r = _clamp(min(w, d) * 0.05, 0.012, 0.025)
        inset = r * 1.7
        xs = [-w / 2 + inset, w / 2 - inset] + ([0.0] if w > 1.4 else [])
        for x in xs:
            for y in (y_face + inset, d / 2 - inset):
                _leg(mb, ls, x, y, base_h + 0.002, r, _case_leg_mat(spec), room=inset)
    else:
        inset = min(0.03, w * 0.05, d * 0.08)
        mb.box(-w / 2 + inset, w / 2 - inset, y_face + inset, d / 2 - inset, 0.0, base_h + 0.002,
               _base_mat(spec, _plain_mat(spec, 0.6)))
    body_h = h - top_t - base_h
    cols = f.get("columns") or (1 if w < 0.9 else 2 if w < 1.8 else 3)
    rows = f.get("rows") or (2 if body_h < 0.5 else 3 if body_h < 1.0 else 4)
    _drawer_bank(mb, -w / 2, w / 2, base_h, h - top_t, y_face, rows, cols, front, hardware, ft, proj, handle)


def build_desk(mb: MeshBuilder, w, d, h, spec):
    """Top on supports with aprons and a modesty panel, optional drawer pedestal (default: right, when the desk
    is big enough). form: drawers 0-3 (in the pedestal, else side by side under the top), pedestal
    none|left|right, pedestal_open (open shelved pedestal with mesh sides instead of drawers), leg_style
    straight (default)|tapered|metal_frame|trestle|panel|hairpin, shelf."""
    f = _form(spec)
    main = _main_mat(spec)
    front, hardware, legs = _front_mat(spec), _hardware_mat(spec), _case_leg_mat(spec)
    ls = f.get("leg_style") or "straight"
    metal = spec["frame_finish"] == "metal" or ls == "metal_frame" or _metal_accent(spec)
    if ls in ("metal_frame", "hairpin"):
        legs = _metal_leg_mat(spec)
    top_t = _clamp(h * 0.035, 0.018, 0.035)
    under = h - top_t
    mb.label = "top"
    mb.box(-w / 2, w / 2, -d / 2, d / 2, under, h, main, bevel=min(0.005, top_t * 0.3), segments=3)
    s = 0.03 if metal else _clamp(min(w, d) * 0.06, 0.035, 0.05)
    inset = min(0.03, w * 0.03, d * 0.05)
    lx0, rx1 = -w / 2 + inset, w / 2 - inset
    fy0, by1 = -d / 2 + inset, d / 2 - inset
    ped = f.get("pedestal")
    if ped is None:
        ped = "right" if w >= 1.0 and d >= 0.45 and h >= 0.6 else "none"
    ped_w = min(_clamp(w * 0.3, 0.32, 0.45), w * 0.45)
    ped_x0, ped_x1 = (rx1 - ped_w, rx1) if ped == "right" else (lx0, lx0 + ped_w)
    ends = [e for e in ("left", "right") if e != ped]
    apron_h = min(0.07, h * 0.1)
    apron_t = min(0.02, s * 0.6)
    pt = _clamp(s * 0.6, 0.018, 0.03)
    support_w = pt if ls == "panel" else s
    left_in = ped_x1 if ped == "left" else lx0 + support_w
    right_in = ped_x0 if ped == "right" else rx1 - support_w
    stretch = []
    mb.label = "leg"
    for e in ends:
        x0 = lx0 if e == "left" else rx1 - s
        xc = x0 + s / 2
        if ls == "panel":
            px0 = lx0 if e == "left" else rx1 - pt
            mb.box(px0, px0 + pt, fy0, by1, 0.0, under + 0.001, main, bevel=0.003, segments=2)
            continue
        if ls == "trestle":
            tt, foot_h, ct = max(s, 0.04), _clamp(h * 0.05, 0.03, 0.06), 0.04
            pd = _clamp(d * 0.22, 0.08, 0.2)
            mb.box(xc - tt * 0.6, xc + tt * 0.6, fy0, by1, 0.0, foot_h, legs, bevel=0.006, segments=2)
            mb.box(xc - tt / 2, xc + tt / 2, -pd / 2, pd / 2, foot_h - 0.001, under - ct + 0.001, legs, bevel=0.004, segments=2)
            mb.box(xc - tt * 0.6, xc + tt * 0.6, fy0 + 0.02, by1 - 0.02, under - ct, under + 0.001, legs, bevel=0.004, segments=2)
            stretch.append(xc + (tt / 2 if e == "left" else -tt / 2))
            continue
        for y0 in (fy0, by1 - s):
            if ls == "straight":
                mb.box(x0, x0 + s, y0, y0 + s, 0.0, under + 0.001, legs, bevel=min(0.004, s * 0.15), segments=2)
            elif ls == "metal_frame":
                mb.box(x0, x0 + s, y0, y0 + s, 0.0, under + 0.001, legs, bevel=0.002)
            else:
                _leg(mb, ls, xc, y0 + s / 2, under + 0.001, s / 2, legs, room=inset + s / 2)
        if ls == "metal_frame":  # floor runner and top rail between the two legs (sled frame)
            mb.box(x0 + 0.002, x0 + s - 0.002, fy0 + s, by1 - s, 0.0, s * 0.8, legs)
            mb.box(x0 + 0.002, x0 + s - 0.002, fy0 + s, by1 - s, under - s * 0.8, under + 0.001, legs)
        elif ls != "hairpin":
            mb.label = "apron"
            mb.box(xc - apron_t / 2, xc + apron_t / 2, fy0 + s, by1 - s, under - apron_h, under + 0.001,
                   legs if metal else main)
            mb.label = "leg"
    if ls == "trestle":
        mb.label = "stretcher"
        a = stretch[0] if "left" in ends else ped_x1
        b = stretch[-1] if "right" in ends else ped_x0
        z = under * 0.3
        mb.box(min(a, b), max(a, b), -0.02, 0.02, z, z + _clamp(h * 0.07, 0.04, 0.07), legs, bevel=0.004, segments=2)

    drawers = f.get("drawers")
    apron_drawers = ped == "none" and bool(drawers)
    if ls != "hairpin":
        mb.label = "apron"
        if not apron_drawers:
            mb.box(left_in, right_in, fy0 + s * 0.3, fy0 + s * 0.3 + apron_t, under - apron_h, under + 0.001,
                   legs if metal else main)
        mb.box(left_in, right_in, by1 - s * 0.5 - apron_t, by1 - s * 0.5, under * 0.45, under + 0.001, main)
    if apron_drawers:
        mb.label = "drawer_box"
        dh = min(0.12, under * 0.16)
        proj, ft = _front_depths(d)
        y_face = fy0 + s * 0.3
        mb.box(left_in, right_in, y_face, by1 - s * 0.5, under - dh, under + 0.001, main)
        _drawer_bank(mb, left_in, right_in, under - dh, under, y_face, 1, drawers, front, hardware, ft, proj)
    if ped != "none":
        mb.label = "pedestal"
        proj, ft = _front_depths(d)
        y_face = fy0 + proj + ft
        base_h = min(0.05, h * 0.06)
        frame = legs if metal or _has_accent(spec) else main
        rows = drawers if drawers is not None else (3 if under - base_h > 0.55 else 2)
        if f.get("pedestal_open"):
            _open_pedestal(mb, ped_x0, ped_x1, fy0, by1, under, ped, frame, main, metal)
        else:
            mb.box(ped_x0, ped_x1, y_face, by1, 0.0, under + 0.001, _base_mat(spec, main), bevel=0.004, segments=2)
            if rows:
                _drawer_bank(mb, ped_x0, ped_x1, base_h, under, y_face, rows, 1, front, hardware, ft, proj)
            else:
                _door(mb, ped_x0, ped_x1, base_h, under, y_face, front, hardware, ft, proj)
    if f.get("shelf"):
        mb.label = "shelf"
        zs = _clamp(under * 0.15, 0.05, 0.16)
        mb.box(left_in, right_in, fy0 + s, by1 - s, zs, zs + 0.02, main, bevel=0.003, segments=2)


def _open_pedestal(mb: MeshBuilder, x0, x1, y0, y1, under, side, frame, shelf_mat, metal):
    """Open shelf pedestal: corner posts, shelves and a wire-mesh panel on the outer side and the back."""
    p = 0.02 if metal else 0.03
    for px in (x0, x1 - p):
        for py in (y0, y1 - p):
            mb.box(px, px + p, py, py + p, 0.0, under + 0.001, frame, bevel=0.002)
    n = 3 if under > 0.55 else 2
    st = 0.018
    mb.label = "shelf"
    for i in range(n):
        z = 0.03 + (under - 0.03) * i / n
        mb.box(x0 + p, x1 - p, y0 + 0.002, y1 - p, z, z + st, shelf_mat, bevel=0.002)
    mb.label = "mesh"
    r, pitch = 0.0022, 0.05
    xo = x0 + p / 2 if side == "left" else x1 - p / 2
    yb = y1 - p / 2
    ny = max(2, round((y1 - y0 - 2 * p) / pitch))
    nx = max(2, round((x1 - x0 - 2 * p) / pitch))
    nz = max(2, round(under / pitch))
    for i in range(1, ny):
        y = y0 + p + (y1 - y0 - 2 * p) * i / ny
        mb.rod((xo, y, 0.0), (xo, y, under), r, r, frame, segments=4)
    for i in range(1, nx):
        x = x0 + p + (x1 - x0 - 2 * p) * i / nx
        mb.rod((x, yb, 0.0), (x, yb, under), r, r, frame, segments=4)
    for k in range(1, nz):
        z = under * k / nz
        mb.rod((xo, y0 + p, z), (xo, y1 - p, z), r, r, frame, segments=4)
        mb.rod((x0 + p, yb, z), (x1 - p, yb, z), r, r, frame, segments=4)


def _lamp_kind(w, d, h, form):
    kind = form.get("kind")
    if kind in ("table", "floor", "desk", "accent", "arc", "torchiere"):
        return kind
    if h >= 1.15:
        return "floor"
    if h <= 0.38 and max(w, d) <= 0.22:
        return "accent"
    if h <= 0.5 and max(w, d) <= 0.32:
        return "desk"
    return "table"


def build_lamp(mb: MeshBuilder, w, d, h, spec):
    """Distinct lamp silhouettes that scale with the listing box (14\" table vs 70\" floor vs arc)."""
    form = _form(spec)
    kind = _lamp_kind(w, d, h, form)
    shade = form.get("shade") or "drum"
    base = form.get("base") or ("gourd" if kind == "accent" else "tripod" if kind == "floor" else "round")
    shade_mat, metal = _main_mat(spec), _metal_leg_mat(spec)
    r = min(w, d) / 2
    stem_k = {"thin": 0.045, "thick": 0.13}.get(form.get("stem"), 0.075)
    shade_k = {"small": 0.22, "large": 0.50}.get(form.get("shade_scale"), 0.36)
    if kind in ("floor", "torchiere", "arc"):
        shade_k = {"small": 0.10, "large": 0.24}.get(form.get("shade_scale"), 0.16)
    shade_h = max(h * shade_k, 0.04)
    shade_r = max(r * (0.95 if form.get("shade_scale") == "large" else 0.82), 0.03)
    stem_r = max(r * stem_k, 0.004)
    if kind == "arc":
        _lamp_arc(mb, w, d, h, metal, shade_mat, shade, shade_h, shade_r, stem_r)
        return
    if kind == "torchiere":
        _lamp_base(mb, base, r, h, metal, shade_mat)
        pole_r = max(stem_r, 0.008)
        bowl_h, bowl_r = max(h * 0.12, 0.08), max(r * 0.72, 0.07)
        mb.cylinder(0, 0, h * 0.06, h - bowl_h * 0.35, pole_r, pole_r * 0.9, metal, segments=12)
        if shade in ("mushroom", "square", "bell", "empire"):
            _lamp_shade(mb, 0, 0, h - shade_h, shade_h, bowl_r, shade, shade_mat)
        else:
            mb.cylinder(0, 0, h - bowl_h, h, bowl_r * 0.32, bowl_r, shade_mat, segments=22, bevel=0.004)
        return
    if kind == "desk":
        base_h, s = max(h * 0.08, 0.01), max(r * 0.5, 0.03)
        arm_z = h * 0.58
        mb.box(-s, s, -s * 0.75, s * 0.75, 0.0, base_h, metal, bevel=0.003, segments=2)
        mb.cylinder(0, 0, base_h, arm_z * 0.5, stem_r, stem_r, metal, segments=10)
        mb.rod((0.0, 0.0, arm_z * 0.48), (r * 0.4, 0.0, arm_z), stem_r * 0.9, stem_r * 0.9, metal, segments=8)
        _lamp_shade(mb, r * 0.4, 0.0, arm_z, max(h * 0.2, 0.04), max(r * 0.42, 0.03),
                    shade if shade != "none" else "cone", shade_mat)
        return
    if kind == "accent" or (kind == "table" and base == "gourd"):
        body_h = h * (0.62 if base == "gourd" else 0.48)
        br = r * (0.78 if base == "gourd" else 0.55)
        mb.sphere(0, 0, body_h * 0.48, br, br, body_h * 0.48, shade_mat if base == "gourd" else metal,
                  segments=18, rings=10)
        neck = body_h + h * 0.04
        mb.cylinder(0, 0, body_h * 0.88, neck, r * 0.1, r * 0.08, metal, segments=12)
        if shade != "none":
            _lamp_shade(mb, 0, 0, neck, h - neck, shade_r, shade, shade_mat)
        return
    # table / floor
    _lamp_base(mb, base, r, h, metal, shade_mat)
    base_h = h * (0.04 if kind == "floor" else 0.12)
    stem_top = h - (0 if shade == "none" else shade_h * 0.7)
    mb.cylinder(0, 0, base_h, max(stem_top, base_h + 0.02), stem_r, stem_r * 0.88, metal, segments=12)
    if shade != "none":
        _lamp_shade(mb, 0, 0, h - shade_h, shade_h, shade_r, shade, shade_mat)


def _lamp_base(mb: MeshBuilder, style, r, h, metal, body):
    base_h = max(h * 0.035, 0.008)
    br = r * 0.48
    if style == "tripod":
        foot, join = max(h * 0.01, 0.006), max(h * 0.18, 0.08)
        pr = max(r * 0.06, 0.005)
        for ang in (0.0, 2.094, 4.189):
            fx, fy = math.cos(ang) * br, math.sin(ang) * br
            mb.cylinder(fx, fy, 0.0, foot, pr * 1.5, pr * 1.5, metal, segments=10)
            mb.rod((fx, fy, foot), (0.0, 0.0, join), pr, pr, metal, segments=8)
    elif style == "square":
        s = br * 0.85
        mb.box(-s, s, -s, s, 0.0, base_h, metal, bevel=0.004, segments=2)
    elif style == "sculpted":
        mb.sphere(0, 0, base_h * 0.9, br, br, base_h * 0.9, metal, segments=16, rings=8)
    elif style == "disc":
        mb.cylinder(0, 0, 0.0, max(base_h * 0.45, 0.004), br * 1.15, br * 1.05, metal, segments=22)
    elif style == "gourd":
        mb.sphere(0, 0, h * 0.22, r * 0.7, r * 0.7, h * 0.22, body, segments=18, rings=10)
    else:
        mb.cylinder(0, 0, 0.0, base_h, br, br * 0.72, metal, segments=20, bevel=0.003)


def _lamp_arc(mb: MeshBuilder, w, d, h, metal, shade_mat, shade, shade_h, shade_r, stem_r):
    br = min(w, d) * 0.16
    x0, x1 = -w / 2 + br, w / 2 - shade_r * 0.6
    mb.cylinder(x0, 0, 0.0, br * 0.7, br, br * 0.65, metal, segments=16)
    pts = []
    for i in range(6):
        t = i / 5
        pts.append((x0 + t * (x1 - x0), 0.0, br * 0.6 + (h - shade_h * 0.45 - br * 0.6) * math.sin(t * math.pi * 0.92)))
    for a, b in zip(pts, pts[1:]):
        mb.rod(a, b, stem_r, stem_r, metal, segments=8)
    _lamp_shade(mb, pts[-1][0], 0.0, h - shade_h, shade_h, shade_r, shade if shade != "none" else "drum", shade_mat)


def _lamp_shade(mb: MeshBuilder, x, y, z0, hh, r, style, mat):
    if hh <= 0 or r <= 0:
        return
    if style == "none":
        return
    if style == "empire":
        mb.cylinder(x, y, z0, z0 + hh, r * 0.58, r, mat, segments=22, bevel=0.004)
    elif style == "cone":
        mb.cylinder(x, y, z0, z0 + hh, r, r * 0.35, mat, segments=20, bevel=0.003)
    elif style == "mushroom":
        mb.sphere(x, y, z0 + hh * 0.35, r, r, hh * 0.55, mat, segments=20, rings=10)
    elif style == "square":
        s = r * 0.82
        mb.box(x - s, x + s, y - s, y + s, z0, z0 + hh, mat, bevel=min(0.01, hh * 0.12), segments=2)
    elif style == "bell":
        mb.cylinder(x, y, z0, z0 + hh * 0.55, r, r * 0.72, mat, segments=22, bevel=0.004)
        mb.cylinder(x, y, z0 + hh * 0.52, z0 + hh, r * 0.72, r * 0.38, mat, segments=20, bevel=0.003)
    else:
        mb.cylinder(x, y, z0, z0 + hh, r * 0.9, r, mat, segments=22, bevel=0.004)


BUILDERS = {"sofa": build_sofa, "coffee_table": build_coffee_table, "tv": build_tv, "rug": build_rug,
            "bed": build_bed, "nightstand": build_nightstand, "dresser": build_dresser, "desk": build_desk,
            "lamp": build_lamp}


def build_furniture(spec: dict, name: str | None = None, collection=None,
                    report: dict | None = None) -> tuple[bpy.types.Object, float]:
    """spec must already be validated by specs.furniture_spec. Returns (object, pre-snap fit error in m).
    `report`, when given, receives the part bboxes (USD space) and the surfaces used."""
    dims = spec["dimensions_m"]
    w, d, h = dims["width"], dims["depth"], dims["height"]
    if _form(spec).get("primary_hex"):
        spec = dict(spec, color_hex=specs.primary_hex(spec))
    mb = MeshBuilder(footprint=(w, d))
    BUILDERS[spec["category"]](mb, w, d, h, spec)
    if report is not None:
        report["parts"] = mb.parts_usd()
        report["surfaces"] = sorted({m["r2r_surface"] for m in mb.materials if m.get("r2r_surface")})
        report["main_surface"] = None if spec.get("texture") else (mb.main_surface or specs.main_surface(spec))
    return mb.to_object(name or spec["category"], (w, d, h), collection or bpy.context.scene.collection)


# ---------------------------------------------------------------- room shell

def build_room(room: dict, collection=None) -> list[bpy.types.Object]:
    """Floor (plane at y=0 spanning the outer footprint) + walls outside the interior rectangle."""
    collection = collection or bpy.context.scene.collection
    w, d, h, t = room["width_m"], room["depth_m"], room["height_m"], room["wall_thickness_m"]
    wall_mat = get_material(room["wall_color_hex"], "paint")
    floor_mat = get_material(room["floor_color_hex"], "wood")
    objects = []

    floor_mesh = bpy.data.meshes.new("room_floor")
    bm = bmesh.new()
    vs = [bm.verts.new(co) for co in ((-w / 2 - t, -d / 2 - t, 0), (w / 2 + t, -d / 2 - t, 0),
                                      (w / 2 + t, d / 2 + t, 0), (-w / 2 - t, d / 2 + t, 0))]
    bm.faces.new(vs)
    bm.to_mesh(floor_mesh)
    bm.free()
    floor_mesh.materials.append(floor_mat)
    floor = bpy.data.objects.new("room_floor", floor_mesh)
    collection.objects.link(floor)
    objects.append(floor)

    for wall in room["walls"]:
        along_x = wall in ("front", "back")
        length = w + 2 * t if along_x else d
        openings = sorted((o for o in room["openings"] if o["wall"] == wall), key=lambda o: o["offset_m"])
        # u runs along the wall in scene coordinates (x for front/back, z for left/right).
        segments = []  # (u0, u1, z0, z1)
        cursor = -length / 2
        for o in openings:
            u0, u1 = o["offset_m"] - o["width_m"] / 2, o["offset_m"] + o["width_m"] / 2
            segments.append((cursor, u0, 0.0, h))
            if o["sill_m"] > 0:
                segments.append((u0, u1, 0.0, o["sill_m"]))
            segments.append((u0, u1, o["sill_m"] + o["height_m"], h))
            cursor = u1
        segments.append((cursor, length / 2, 0.0, h))

        mb = MeshBuilder()
        for u0, u1, z0, z1 in segments:
            if u1 - u0 < 1e-6 or z1 - z0 < 1e-6:
                continue
            if along_x:
                y0, y1 = (d / 2, d / 2 + t) if wall == "back" else (-d / 2 - t, -d / 2)
                mb.box(u0, u1, y0, y1, z0, z1, wall_mat)
            else:
                x0, x1 = (-w / 2 - t, -w / 2) if wall == "left" else (w / 2, w / 2 + t)
                mb.box(x0, x1, -u1, -u0, z0, z1, wall_mat)  # scene z = -blender y
        obj, _ = mb.to_object(f"room_wall_{wall}", None, collection)
        objects.append(obj)
    return objects


def room_expected_bbox(room: dict) -> tuple[list[float], list[float]]:
    """Expected USD-space bbox (Y-up) of an exported room."""
    w, d, h, t = room["width_m"], room["depth_m"], room["height_m"], room["wall_thickness_m"]
    top = h if room["walls"] else 0.0
    return [-w / 2 - t, 0.0, -d / 2 - t], [w / 2 + t, top, d / 2 + t]


def furniture_expected_bbox(spec: dict) -> tuple[list[float], list[float]]:
    dims = spec["dimensions_m"]
    w, d, h = dims["width"], dims["depth"], dims["height"]
    return [-w / 2, 0.0, -d / 2], [w / 2, h, d / 2]


# ---------------------------------------------------------------- export + measure

def _select_only(objects):
    bpy.context.view_layer.update()  # bases of freshly linked objects are stale until the view layer syncs
    for o in bpy.context.scene.objects:
        if o is not None and o not in objects:
            o.select_set(False)
    for o in objects:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]


def _atomic_export(path: Path, write):
    """Exports into a temp dir next to `path` using the final file name, then renames into place."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmpdir = Path(tempfile.mkdtemp(prefix=".r2r-", dir=path.parent))
    try:
        tmp = tmpdir / path.name
        write(str(tmp))
        if not tmp.exists() or tmp.stat().st_size == 0:
            raise RuntimeError(f"exporter produced no file for {path.name}")
        os.replace(tmp, path)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def export_usdz(objects, path: Path):
    _select_only(objects)
    _atomic_export(path, lambda p: bpy.ops.wm.usd_export(filepath=p, **USD_EXPORT_KWARGS))


def export_glb(objects, path: Path):
    _select_only(objects)
    _atomic_export(path, lambda p: bpy.ops.export_scene.gltf(filepath=p, **GLB_EXPORT_KWARGS))


def measure_usd(path: Path) -> dict:
    """Re-opens an exported USD/USDZ with pxr and measures the world-space bbox from mesh points."""
    from pxr import Gf, Usd, UsdGeom, UsdShade

    stage = Usd.Stage.Open(str(path))
    lo, hi = [math.inf] * 3, [-math.inf] * 3
    max_radius_xz = 0.0
    meshes = 0
    preview_surfaces = 0
    textures: list[dict] = []
    uv_top_corners, st_extent = None, None
    per_material: dict[str, list[list[float]]] = {}
    st_by_material: dict[str, list[list[float]]] = {}
    surface_inputs: dict[str, dict] = {}
    triangles = 0
    t = Usd.TimeCode.Default()
    xcache = UsdGeom.XformCache(t)

    def grow(name, q, table=per_material, n=3):
        b = table.setdefault(name, [[math.inf] * n, [-math.inf] * n])
        for i in range(n):
            b[0][i] = min(b[0][i], q[i])
            b[1][i] = max(b[1][i], q[i])

    def texture_file(shader, name):
        inp = shader.GetInput(name)
        if not inp or not inp.HasConnectedSource():
            return None
        src = UsdShade.Shader(inp.GetConnectedSource()[0].GetPrim())
        f = src.GetInput("file")
        return {"file": f.Get().path if f and f.Get() else None,
                "color_space": src.GetInput("sourceColorSpace").Get() if src.GetInput("sourceColorSpace") else None}

    for prim in stage.Traverse():
        if prim.IsA(UsdGeom.Mesh):
            if UsdGeom.Imageable(prim).ComputeVisibility(t) == UsdGeom.Tokens.invisible:
                continue
            meshes += 1
            mesh = UsdGeom.Mesh(prim)
            xf = xcache.GetLocalToWorldTransform(prim)
            world = [xf.Transform(Gf.Vec3d(p[0], p[1], p[2])) for p in mesh.GetPointsAttr().Get(t) or []]
            for q in world:
                for i in range(3):
                    lo[i] = min(lo[i], q[i])
                    hi[i] = max(hi[i], q[i])
                max_radius_xz = max(max_radius_xz, math.hypot(q[0], q[2]))
            counts = list(mesh.GetFaceVertexCountsAttr().Get(t) or [])
            triangles += sum(c - 2 for c in counts)
            indices = list(mesh.GetFaceVertexIndicesAttr().Get(t) or [])
            starts = [0]
            for c in counts:
                starts.append(starts[-1] + c)
            st = UsdGeom.PrimvarsAPI(prim).GetPrimvar("st")
            uvs, face_varying = [], False
            if st and st.HasValue() and world:
                uvs = list(st.ComputeFlattened(t) or [])
                face_varying = st.GetInterpolation() == UsdGeom.Tokens.faceVarying
                ids = indices if st.GetInterpolation() == UsdGeom.Tokens.faceVarying else range(len(world))
                pairs = [(world[p], uv) for p, uv in zip(ids, uvs)]
                if pairs:
                    top = max(q[1] for q, _ in pairs)
                    up = [(q, uv) for q, uv in pairs if q[1] >= top - 1e-4]
                    uv_top_corners = {f"{zn}_{xn}": list(max(up, key=lambda e: sx * e[0][0] + sz * e[0][2])[1])
                                      for zn, sz in (("back", -1), ("front", 1)) for xn, sx in (("left", -1), ("right", 1))}
                    st_extent = [[min(uv[i] for _, uv in pairs) for i in (0, 1)],
                                 [max(uv[i] for _, uv in pairs) for i in (0, 1)]]
            subsets = UsdGeom.Subset.GetAllGeomSubsets(mesh)
            if not subsets:
                mat = UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial()[0]
                for q in world:
                    grow(mat.GetPrim().GetName() if mat else "", q)
            for sub in subsets:
                mat = UsdShade.MaterialBindingAPI(sub.GetPrim()).ComputeBoundMaterial()[0]
                name = mat.GetPrim().GetName() if mat else ""
                for f in sub.GetIndicesAttr().Get(t) or []:
                    for k in range(starts[f], starts[f + 1]):
                        grow(name, world[indices[k]])
                        if uvs:
                            grow(name, uvs[k if face_varying else indices[k]], st_by_material, 2)
        elif prim.IsA(UsdShade.Shader) and UsdShade.Shader(prim).GetIdAttr().Get() == "UsdPreviewSurface":
            preview_surfaces += 1
            sh = UsdShade.Shader(prim)
            surface_inputs[prim.GetParent().GetName()] = {
                k: texture_file(sh, k) for k in ("diffuseColor", "normal", "opacity", "roughness", "metallic")}
        elif prim.IsA(UsdShade.Shader) and UsdShade.Shader(prim).GetIdAttr().Get() == "UsdUVTexture":
            sh = UsdShade.Shader(prim)
            f, wrap = sh.GetInput("file"), sh.GetInput("wrapS")
            textures.append({"file": f.Get().path if f and f.Get() else None,
                             "wrap": wrap.Get() if wrap and wrap.Get() else None})
    default_prim = stage.GetDefaultPrim()
    return {
        "min": lo, "max": hi, "size": [hi[i] - lo[i] for i in range(3)],
        "max_radius_xz": max_radius_xz,  # farthest point from the vertical axis; ~w/2 when round, ~w/2*sqrt(2) when square
        "up_axis": str(UsdGeom.GetStageUpAxis(stage)),
        "meters_per_unit": UsdGeom.GetStageMetersPerUnit(stage),
        "default_prim": str(default_prim.GetPath()) if default_prim else None,
        "mesh_count": meshes,
        "preview_surface_count": preview_surfaces,
        "textures": textures,  # authored UsdUVTexture file paths (relative inside a USDZ package)
        "uv_top_corners": uv_top_corners,  # 'st' at the topmost footprint corners (back = -Z), None without UVs
        "st_extent": st_extent,
        "st_extent_by_material": {k: [list(v[0]), list(v[1])] for k, v in st_by_material.items()},
        "material_bboxes": {k: {"min": v[0], "max": v[1]} for k, v in per_material.items()},
        "surface_inputs": surface_inputs,  # material -> {diffuseColor/normal/opacity/...: texture or None}
        "triangles": triangles,
    }


def bbox_error(measured: dict, expected: tuple[list[float], list[float]]) -> float:
    lo, hi = expected
    return max(max(abs(measured["min"][i] - lo[i]), abs(measured["max"][i] - hi[i])) for i in range(3))


def remove_objects(objects):
    for obj in objects:
        mesh = obj.data if obj.type == "MESH" else None
        bpy.data.objects.remove(obj, do_unlink=True)
        if mesh is not None and mesh.users == 0:
            bpy.data.meshes.remove(mesh)


def build_and_export(spec: dict, usdz_path: Path | None, glb_path: Path | None = None, *, kind="furniture",
                     report_parts: bool = False) -> dict:
    """Builds a validated furniture spec (or room spec when kind='room') at the origin, exports, measures, cleans up.
    report_parts adds per-part bboxes (USD space) for diagnostics."""
    t0 = time.perf_counter()
    report: dict = {}
    if kind == "room":
        objects = build_room(spec)
        expected = room_expected_bbox(spec)
        fit_error = 0.0
    else:
        obj, fit_error = build_furniture(spec, name=spec["category"], report=report)
        objects = [obj]
        expected = furniture_expected_bbox(spec)
    t_build = time.perf_counter()
    result = {"expected_bbox_m": {"min": expected[0], "max": expected[1]}, "template_fit_error_m": fit_error,
              "triangles": sum(len(p.vertices) - 2 for o in objects for p in o.data.polygons)}
    if kind != "room":
        result["surfaces"] = report["surfaces"]
        result["main_surface"] = report["main_surface"]
        if report_parts:
            result["parts"] = report["parts"]
    if kind != "room" and spec.get("texture"):
        result["texture"] = texture_info(spec)
    try:
        if usdz_path is not None:
            export_usdz(objects, Path(usdz_path))
            result["usdz_path"] = str(usdz_path)
        t_export = time.perf_counter()
        if glb_path is not None:
            export_glb(objects, Path(glb_path))
            result["glb_path"] = str(glb_path)
        if usdz_path is not None:
            measured = measure_usd(Path(usdz_path))
            result["measured_bbox_m"] = measured
            result["max_abs_error_m"] = bbox_error(measured, expected)
    finally:
        remove_objects(objects)
    result["timings_ms"] = {"build": round((t_build - t0) * 1000, 1),
                            "export_usdz": round((t_export - t_build) * 1000, 1),
                            "total": round((time.perf_counter() - t0) * 1000, 1)}
    return result


def reset_blend():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0
