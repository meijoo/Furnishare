"""MCP server (stdio) exposing the warm Blender worker as typed tools.

  .venv/bin/python integrations/blender_mcp/server.py

The worker starts lazily on the first tool call and is restarted if it crashes. Output files are
confined to backend/static/assets (assets) and integrations/blender_mcp/.out/previews (previews).
"""
from __future__ import annotations

import atexit
import sys
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

try:
    from mcp.server.mcpserver import Image, MCPServer
    from mcp.server.mcpserver.exceptions import ToolError
except ImportError:  # mcp < 2
    from mcp.server.fastmcp import FastMCP as MCPServer, Image
    from mcp.server.fastmcp.exceptions import ToolError

try:
    from . import assets, specs, worker_client
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from blender_mcp import assets, specs, worker_client

ASSETS_DIR = worker_client.REPO / "backend" / "static" / "assets"
PREVIEWS_DIR = worker_client.HERE / ".out" / "previews"
EXPORTS_DIR = worker_client.HERE / ".out" / "exports"

Meters = Annotated[float, Field(ge=specs.DIM_MIN_M, le=specs.DIM_MAX_M)]
Coord = Annotated[float, Field(ge=-specs.POSITION_LIMIT_M, le=specs.POSITION_LIMIT_M)]
Rotation = Annotated[float, Field(ge=-specs.ROTATION_LIMIT_RAD, le=specs.ROTATION_LIMIT_RAD,
                                  description="Rotation about +Y in radians")]
ObjectId = Annotated[str, Field(pattern=r"^[A-Za-z0-9_.:-]{1,64}$")]
ColorHex = Annotated[str, Field(pattern=r"^#?[0-9A-Fa-f]{6}$", description="sRGB hex color, e.g. #C9BFAE")]
FileName = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$",
                                description="Plain file name without directories")]
Category = Annotated[Literal["sofa", "coffee_table", "tv", "rug", "bed", "nightstand", "dresser", "desk"],
                     Field(description="bed: headboard at the back (-Z) sets the height; nightstand/dresser/desk: "
                                       "drawer fronts face +Z. Per-category size limits (m, width/depth/height): "
                                       + "; ".join(f"{c} {r['width'][1]}/{r['depth'][1]}/{r['height'][1]} max"
                                                   for c, r in specs.CATEGORY_DIM_RANGES_M.items()))]
MaterialKind = Literal["fabric", "wood", "metal", "leather", "wool"]
FrameFinish = Annotated[Literal["wood", "metal", "upholstered"],
                        Field(description="Legs/frame finish (sofa, bed, desk); 'upholstered' beds have no legs")]
Shape = Annotated[Literal["rect", "round"],
                  Field(description="'round' (coffee_table, nightstand, rug only) needs width == depth = diameter")]
Wall = Literal["back", "front", "left", "right"]
TexturePath = Annotated[str, Field(min_length=2, max_length=4096,
                                   description="Absolute path to a .jpg/.jpeg/.png/.webp image (< 15 MB)")]
TextureMode = Annotated[Literal["print", "tile"],
                        Field(description="'print': the whole image once across the top (default for rugs; light "
                                          "photo borders are trimmed); 'tile': repeating swatch on the main "
                                          "surfaces (default otherwise)")]
TileMeters = Annotated[float, Field(description="Tile size in meters for 'tile' mode (default 0.3, clamped to "
                                                f"{specs.TEXTURE_TILE_RANGE_M[0]}..{specs.TEXTURE_TILE_RANGE_M[1]})")]


def _schema_doc(allowed) -> str:
    if allowed is bool:
        return "bool"
    if allowed == specs.HEX:
        return "'#RRGGBB'"
    if isinstance(allowed[0], int):
        return f"{allowed[0]}..{allowed[1]}"
    return "|".join(allowed)


_COMMON_KEYS = ("surface", "primary_hex", "accent_surface", "accent_hex")
FormParam = Annotated[dict[str, Any], Field(description=(
    "Shape/finish details per category (all optional; unknown keys or values are rejected; sides are as seen from "
    "the front, left = -X). Every category: surface " + "|".join(specs.SURFACES) + " (else derived from material "
    "+ color); primary_hex '#RRGGBB' (main surface color, overrides color_hex); accent_surface (same values) and "
    "accent_hex '#RRGGBB' for legs, frames, bases, plinths and metal handles. "
    + "; ".join(f"{cat}: " + ", ".join(f"{k} {_schema_doc(v)}" for k, v in keys.items() if k not in _COMMON_KEYS)
                for cat, keys in specs.FORM_SCHEMA.items())))]


class Dimensions(BaseModel):
    """Exact outer bounding box in meters: width along X, depth along Z, height along Y."""
    width: Meters
    depth: Meters
    height: Meters


class Opening(BaseModel):
    kind: Literal["door", "window"]
    wall: Wall
    offset_m: Annotated[float, Field(description="Center of the opening along the wall, in scene coordinates "
                                                 "(x for front/back walls, z for left/right walls)")]
    width_m: Annotated[float, Field(ge=0.2, le=20.0)]
    height_m: Annotated[float | None, Field(ge=0.2, le=5.0)] = None
    sill_m: Annotated[float | None, Field(ge=0.0, le=5.0, description="Windows only")] = None


class Clearance(BaseModel):
    label: Annotated[str, Field(max_length=80)] = "clearance"
    x_m: Coord
    z_m: Coord
    width_m: Annotated[float, Field(gt=0, le=20.0)]
    depth_m: Annotated[float, Field(gt=0, le=20.0)]


mcp = MCPServer(
    "rag-to-rooms-blender",
    instructions=("Builds dimensionally exact furniture and room shells in Blender for RAG to Rooms. "
                  "Scene space is meters, Y-up, room centered at the origin, back wall at z=-depth/2, "
                  "objects face +Z. position_m is the footprint center on the floor."),
)

_worker: worker_client.BlenderWorker | None = None


def worker() -> worker_client.BlenderWorker:
    global _worker
    if _worker is None:
        _worker = worker_client.BlenderWorker(allowed_roots=[ASSETS_DIR, PREVIEWS_DIR, EXPORTS_DIR])
        atexit.register(_worker.stop)
    return _worker


def call(cmd: str, params: dict | None = None, timeout: float = 120.0) -> dict:
    w = worker()
    restarts = w.restarts
    try:
        result = w.request(cmd, params, timeout=timeout)
    except worker_client.WorkerError as exc:
        raise ToolError(str(exc)) from None
    if w.restarts != restarts:
        result = dict(result, warning=f"Blender worker was restarted ({w.last_restart_reason}); "
                                      "previous scene state was lost.")
    return result


def _drop_none(d: dict) -> dict:
    return {k: v for k, v in d.items() if v is not None}


def _texture(path: str | None, mode: str | None, tile_m: float | None) -> dict | None:
    t = _drop_none({"path": path, "mode": mode, "tile_m": tile_m})
    return t or None


def _form(form: dict | None, category: str) -> dict | None:
    if form is None:
        return None
    try:
        return specs.form(form, category)
    except specs.ValidationError as exc:
        raise ToolError(str(exc)) from None


@mcp.tool()
def create_room(width_m: Annotated[float, Field(ge=1.0, le=20.0)],
                depth_m: Annotated[float, Field(ge=1.0, le=20.0)],
                height_m: Annotated[float, Field(ge=1.8, le=5.0)] = 2.5,
                openings: list[Opening] | None = None,
                clearances: list[Clearance] | None = None,
                wall_thickness_m: Annotated[float, Field(ge=0.02, le=0.5)] = 0.1,
                walls: list[Wall] | None = None,
                wall_color_hex: ColorHex | None = None,
                floor_color_hex: ColorHex | None = None) -> dict[str, Any]:
    """Create (or replace) the room shell: floor plus walls outside the interior rectangle, with door/window openings."""
    room = _drop_none({
        "width_m": width_m, "depth_m": depth_m, "height_m": height_m, "wall_thickness_m": wall_thickness_m,
        "openings": [_drop_none(o.model_dump()) for o in openings or []],
        "clearances": [c.model_dump() for c in clearances or []],
        "walls": walls, "wall_color_hex": wall_color_hex, "floor_color_hex": floor_color_hex,
    })
    return call("create_room", room)


@mcp.tool()
def instantiate_furniture(object_id: ObjectId, category: Category, dimensions_m: Dimensions,
                          color_hex: ColorHex | None = None, material: MaterialKind | None = None,
                          frame_finish: FrameFinish | None = None,
                          shape: Shape | None = None,
                          position_m: tuple[Coord, Coord, Coord] = (0.0, 0.0, 0.0),
                          rotation_y_rad: Rotation = 0.0,
                          product_id: Annotated[str | None, Field(max_length=200)] = None,
                          texture_path: TexturePath | None = None,
                          texture_mode: TextureMode | None = None,
                          texture_tile_m: TileMeters | None = None,
                          form: FormParam | None = None) -> dict[str, Any]:
    """Add a parametric furniture object (sofa, coffee_table, tv, rug, bed, nightstand, dresser, desk) whose
    bounding box exactly matches dimensions_m. shape='round' builds a round top/base (width == depth).
    form picks arm/back/leg/handle styles etc. and the procedural surface (wood grain, weave, leather...).
    texture_path applies an image (rug photo printed on top, or a material swatch tiled on the main surfaces)."""
    if texture_path is None and (texture_mode is not None or texture_tile_m is not None):
        raise ToolError("texture_mode/texture_tile_m need texture_path")
    spec = _drop_none({"category": category, "dimensions_m": dimensions_m.model_dump(), "color_hex": color_hex,
                       "material": material, "frame_finish": frame_finish, "shape": shape,
                       "texture": _texture(texture_path, texture_mode, texture_tile_m),
                       "form": _form(form, category)})
    return call("instantiate_furniture", _drop_none({"object_id": object_id, "spec": spec,
                                                     "position_m": list(position_m),
                                                     "rotation_y_rad": rotation_y_rad, "product_id": product_id}))


@mcp.tool()
def set_dimensions_and_material(object_id: ObjectId, dimensions_m: Dimensions | None = None,
                                color_hex: ColorHex | None = None, material: MaterialKind | None = None,
                                frame_finish: FrameFinish | None = None,
                                shape: Shape | None = None,
                                texture_path: TexturePath | None = None,
                                texture_mode: TextureMode | None = None,
                                texture_tile_m: TileMeters | None = None,
                                clear_texture: bool = False,
                                form: FormParam | None = None) -> dict[str, Any]:
    """Rebuild an existing object with new outer dimensions, material, shape, form and/or texture; its transform
    is kept. form replaces the current form ({} clears it). texture_mode/texture_tile_m alone adjust the current
    texture; clear_texture removes it."""
    texture = _texture(texture_path, texture_mode, texture_tile_m)
    if clear_texture and texture:
        raise ToolError("pass either texture_* or clear_texture, not both")
    if form is not None and not isinstance(form, dict):
        raise ToolError("form must be an object")
    return call("set_dimensions_and_material", _drop_none({
        "object_id": object_id, "dimensions_m": dimensions_m.model_dump() if dimensions_m else None,
        "color_hex": color_hex, "material": material, "frame_finish": frame_finish, "shape": shape,
        "texture": texture, "clear_texture": clear_texture or None, "form": form}))


@mcp.tool()
def set_transform(object_id: ObjectId, position_m: tuple[Coord, Coord, Coord] | None = None,
                  rotation_y_rad: Rotation | None = None) -> dict[str, Any]:
    """Move/rotate an object. position_m is the footprint center on the floor (y=0 means on the floor)."""
    return call("set_transform", _drop_none({"object_id": object_id,
                                             "position_m": list(position_m) if position_m else None,
                                             "rotation_y_rad": rotation_y_rad}))


@mcp.tool()
def remove_object(object_id: ObjectId) -> dict[str, Any]:
    """Delete a furniture object from the scene."""
    return call("remove_object", {"object_id": object_id})


@mcp.tool()
def list_objects() -> dict[str, Any]:
    """Return the room and all furniture objects in scene space."""
    return call("list_objects")


@mcp.tool()
def reset_scene() -> dict[str, Any]:
    """Remove the room and all furniture."""
    return call("reset_scene")


@mcp.tool()
def validate_scene() -> dict[str, Any]:
    """Check footprints: inside the room, not taller than the room, no overlaps (rugs excepted), clearances free."""
    return call("validate_scene")


@mcp.tool()
def render_preview(filename: FileName = "preview.png",
                   width_px: Annotated[int, Field(ge=64, le=1024)] = 480,
                   height_px: Annotated[int, Field(ge=64, le=1024)] = 360,
                   engine: Literal["workbench", "eevee"] = "workbench",
                   view: Literal["iso", "front", "top"] = "iso",
                   cutaway: bool = True,
                   target: Annotated[str, Field(pattern=r"^[A-Za-z0-9_.:-]{1,64}$",
                                                description="'scene', 'room' or an object_id")] = "scene") -> list:
    """Render a small PNG preview into integrations/blender_mcp/.out/previews and return it as an image."""
    if not filename.lower().endswith(".png"):
        raise ToolError("filename must end with .png")
    result = call("render_preview", {"path": str(PREVIEWS_DIR / filename), "width_px": width_px,
                                     "height_px": height_px, "engine": engine, "view": view,
                                     "cutaway": cutaway, "target": target}, timeout=180.0)
    return [Image(path=result["path"]), result]


@mcp.tool()
def export_asset(target: Annotated[str, Field(pattern=r"^[A-Za-z0-9_.:-]{1,64}$",
                                              description="'scene', 'room' or an object_id")],
                 filename: FileName, format: Literal["usdz", "glb"] = "usdz",
                 directory: Literal["assets", "exports"] = "exports") -> dict[str, Any]:
    """Export an object (canonical pose at the origin), the room, or the whole scene. Returns the measured bbox."""
    if not filename.lower().endswith("." + format):
        raise ToolError(f"filename must end with .{format}")
    base = ASSETS_DIR if directory == "assets" else EXPORTS_DIR
    return call("export_asset", {"target": target, "path": str(base / filename), "format": format})


@mcp.tool()
def build_product_asset(product: Annotated[dict[str, Any], Field(
                            description="Catalog Product: id, variant?, category (sofa, coffee_table, tv, rug, bed, "
                                        "nightstand, dresser, desk), dimensions_m {width, depth, height}, style? "
                                        "{color_hex, material, shape: 'rect'|'round', tags, texture_path, "
                                        "texture_mode: 'print'|'tile', texture_tile_m}. A 'round' tag also "
                                        "requests a round build when style.shape is absent. texture_path is an "
                                        "absolute .jpg/.jpeg/.png/.webp path (< 15 MB); unusable files are ignored.")],
                        glb_preview: bool = False, force: bool = False,
                        texture_path: TexturePath | None = None,
                        texture_mode: TextureMode | None = None,
                        texture_tile_m: TileMeters | None = None,
                        form: FormParam | None = None) -> dict[str, Any]:
    """Build (or reuse) backend/static/assets/<asset_key>.usdz for a catalog Product (API schema).
    Round requests fall back to rect when the category or width != depth cannot be built round.
    texture_* arguments override product.style.texture_*; form keys override product.style.form (validated
    strictly here, whereas junk in product.style.form is ignored); the result's spec shows what was applied."""
    if form is not None:
        if product.get("category") not in specs.FORM_SCHEMA:
            raise ToolError("form needs a product with a known category")
        form = _form(form, product["category"])
    style = dict(product.get("style") or {}) if isinstance(product.get("style"), dict) else {}
    if texture_path is not None or texture_mode is not None or texture_tile_m is not None:
        style.update(_drop_none({"texture_path": texture_path, "texture_mode": texture_mode,
                                 "texture_tile_m": texture_tile_m}))
        product = dict(product, style=style)
    if form:
        base = style.get("form") if isinstance(style.get("form"), dict) else {}
        product = dict(product, style=dict(style, form=dict(base, **form)))
    if texture_path is not None and specs.product_texture(product) is None:
        raise ToolError("texture_path must be an existing absolute .jpg/.jpeg/.png/.webp file under 15 MB")
    if specs.spec_from_product(product) is None:
        raise ToolError("product has null/package dimensions, an unknown category, or invalid style values")
    try:
        result = assets.build_asset(product, ASSETS_DIR, glb=glb_preview, worker=worker(), force=force)
    except (worker_client.WorkerError, specs.ValidationError) as exc:
        raise ToolError(str(exc)) from None
    result["asset_url"] = f"/assets/{result['asset_key']}.usdz"
    return result


@mcp.tool()
def worker_status() -> dict[str, Any]:
    """Report whether the Blender worker is running (does not start it)."""
    w = _worker
    return {"running": bool(w and w.running()), "pid": w.proc.pid if w and w.proc else None,
            "restarts": w.restarts if w else 0, "last_restart_reason": w.last_restart_reason if w else None,
            "blender_bin": worker_client.find_blender(), "template_version": specs.TEMPLATE_VERSION}


if __name__ == "__main__":
    mcp.run(transport="stdio")
