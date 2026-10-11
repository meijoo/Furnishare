"""Parameter validation shared by the MCP server, the asset cache and the Blender worker.

Pure Python (no bpy, no mcp) so it runs in the backend venv and inside Blender's bundled Python.
Every validator returns a normalized copy and raises ValidationError on bad input.
"""
from __future__ import annotations

import math
import os
import re
from typing import Any

TEMPLATE_VERSION = "2026.10.14"
# Capabilities a warm worker must report in `ping` before clients reuse it (older workers lack these).
WORKER_FEATURES = ("texture", "form", "surfaces")

CATEGORIES = ("sofa", "coffee_table", "tv", "rug", "bed", "nightstand", "dresser", "desk", "lamp")
MATERIALS = ("fabric", "wood", "metal", "leather", "wool")
FRAME_FINISHES = ("wood", "metal", "upholstered")
SHAPES = ("rect", "round")
ROUND_CATEGORIES = ("coffee_table", "nightstand", "rug", "lamp")
ROUND_TOLERANCE_M = 0.005  # round pieces need width == depth (the diameter) within this
_SHAPE_ALIASES = {"rect": "rect", "rectangular": "rect", "square": "rect",
                  "round": "round", "circular": "round", "circle": "round"}
WALLS = ("back", "front", "left", "right")
OPENING_KINDS = ("door", "window")
EXPORT_FORMATS = ("usdz", "glb")
RENDER_ENGINES = ("workbench", "eevee")
RENDER_VIEWS = ("iso", "front", "top")

DIM_MIN_M, DIM_MAX_M = 0.003, 5.0
# Tighter (min, max) per axis for categories whose templates need realistic proportions.
CATEGORY_DIM_RANGES_M = {
    "bed": {"width": (0.6, 2.2), "depth": (1.2, 2.4), "height": (0.2, 1.4)},
    "nightstand": {"width": (0.2, 1.0), "depth": (0.2, 0.8), "height": (0.2, 1.0)},
    "dresser": {"width": (0.4, 2.6), "depth": (0.25, 0.9), "height": (0.3, 1.8)},
    "desk": {"width": (0.5, 2.6), "depth": (0.3, 1.4), "height": (0.4, 1.3)},
    "lamp": {"width": (0.08, 0.8), "depth": (0.08, 0.8), "height": (0.2, 2.2)},
}
ROOM_WIDTH_RANGE_M = (1.0, 20.0)
ROOM_HEIGHT_RANGE_M = (1.8, 5.0)
WALL_THICKNESS_RANGE_M = (0.02, 0.5)
POSITION_LIMIT_M = 50.0
ROTATION_LIMIT_RAD = 4 * math.pi
MAX_OPENINGS = 16
MAX_CLEARANCES = 32
PREVIEW_PX_RANGE = (64, 1024)
TEXTURE_MODES = ("print", "tile")  # print: one image across the top face; tile: repeating swatch
TEXTURE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp")
TEXTURE_MAX_BYTES = 15 * 1024 * 1024
TEXTURE_TILE_RANGE_M = (0.05, 2.0)
DEFAULT_TEXTURE_TILE_M = 0.3
_IMAGE_MAGIC = {".jpg": (b"\xff\xd8\xff",), ".jpeg": (b"\xff\xd8\xff",), ".png": (b"\x89PNG\r\n\x1a\n",),
                ".webp": (b"RIFF",)}

DEFAULT_MATERIAL = {"sofa": "fabric", "coffee_table": "wood", "tv": "metal", "rug": "wool",
                    "bed": "fabric", "nightstand": "wood", "dresser": "wood", "desk": "wood", "lamp": "metal"}
DEFAULT_COLOR = {"sofa": "#C9BFAE", "coffee_table": "#9C7A55", "tv": "#24262B", "rug": "#B7AE9C",
                 "bed": "#B5AA99", "nightstand": "#A27E58", "dresser": "#8A6748", "desk": "#B89A74",
                 "lamp": "#E8D9B8"}
DEFAULT_WALL_COLOR = "#ECE8E1"
DEFAULT_FLOOR_COLOR = "#B48E66"

# Visible main surface finish; every build renders it as an image texture (see integrations/blender/surfaces.py).
SURFACES = ("oak", "walnut", "white_oak", "pine", "painted", "lacquer", "linen", "weave", "boucle", "velvet",
            "chenille", "leather", "faux_leather", "brushed_metal", "black_metal", "glass", "marble", "wool",
            "suede", "cotton", "ceramic", "enamel", "rattan")
SOFT_SURFACES = ("linen", "weave", "boucle", "velvet", "chenille", "leather", "faux_leather", "wool",
                 "suede", "cotton")
MATERIAL_SURFACE = {"fabric": "weave", "wood": "oak", "leather": "leather", "wool": "wool"}  # metal: by luminance
METAL_DARK_LUMA = 100  # sRGB luma below this -> black_metal, else brushed_metal

# Product-faithful form parameters (product.style.form / spec.form). Values: tuple of str = enum,
# (lo, hi) ints = inclusive int range, bool = boolean, HEX = '#RRGGBB' color. Absent keys keep the template's
# default look. Sides (chaise, pedestal) are as seen from the front: left = -X.
# primary_hex overrides style.color_hex for the main surface; accent_surface/accent_hex finish the secondary
# parts (legs, frames, bases, plinths, metal frames, metal handles, bed frame under an upholstered headboard).
HEX = "hex"
_COMMON_FORM = {"surface": SURFACES, "primary_hex": HEX, "accent_surface": SURFACES, "accent_hex": HEX}
FORM_SCHEMA: dict[str, dict[str, Any]] = {
    "sofa": {"arm_style": ("track", "rolled", "sloped", "flared", "none"),
             "back_style": ("tight", "pillow", "tufted", "channel"),
             "seat_cushions": (1, 4), "back_cushions": (0, 4),
             "leg_style": ("tapered", "block", "metal", "hidden", "bun", "turned"),
             "skirt": bool, "chaise": ("none", "left", "right"), "tufted_seat": bool,
             "arm_bulk": ("slim", "regular", "plump"),
             "seat_rise": ("low", "mid", "high"),
             "arm_rise": ("low", "mid", "high"),
             "back_bulk": ("thin", "regular", "thick"),
             **_COMMON_FORM},
    "coffee_table": {"leg_style": ("tapered", "straight", "hairpin", "pedestal", "panel", "sled", "x_base", "turned"),
                     "shelf": bool, "drawer": bool, "top_style": ("slab", "glass", "stone", "lift_top"),
                     **_COMMON_FORM},
    "tv": {"bezel": ("thin", "frame"), "stand": ("feet", "pedestal", "none"), **_COMMON_FORM},
    "rug": {"fringe": bool, "pile": ("flat", "low", "high"), **_COMMON_FORM},
    "bed": {"headboard": ("panel", "tufted", "channel", "slatted", "spindle", "wingback", "none"),
            "footboard": bool, "leg_style": ("tapered", "block", "metal", "hidden"),
            "frame": ("platform", "rails", "storage"), **_COMMON_FORM},
    "nightstand": {"drawers": (0, 3), "open_shelf": bool, "door": bool,
                   "leg_style": ("tapered", "straight", "hairpin", "plinth", "none", "turned"), **_COMMON_FORM},
    "dresser": {"columns": (1, 3), "rows": (2, 5), "leg_style": ("tapered", "plinth", "metal", "bun", "turned"),
                "handle_style": ("knob", "bar", "cutout", "cup", "none"), **_COMMON_FORM},
    "desk": {"drawers": (0, 3), "pedestal": ("none", "left", "right"), "pedestal_open": bool,
             "leg_style": ("tapered", "straight", "metal_frame", "trestle", "panel", "hairpin"),
             "shelf": bool, **_COMMON_FORM},
    "lamp": {"kind": ("table", "floor", "desk", "accent", "arc", "torchiere"),
             "shade": ("drum", "empire", "cone", "none", "mushroom", "square", "bell"),
             "base": ("round", "square", "tripod", "sculpted", "disc", "gourd"),
             "shade_scale": ("small", "regular", "large"), "stem": ("thin", "regular", "thick"),
             **_COMMON_FORM},
}
_BOOL_WORDS = {"true": True, "yes": True, "1": True, "false": False, "no": False, "0": False}
# (regex, surface) hints read from free-text style.material when form.surface is absent; earliest match wins.
_SURFACE_HINTS = [(re.compile(p), s) for p, s in (
    (r"\bfaux[ -]?leather\b|\bleather[ -]?look\b|\bvegan leather\b|\bbonded leather\b|\bcoated\b|\bpu\b", "faux_leather"),
    (r"\bleather\b", "leather"), (r"\bvelvet\b", "velvet"), (r"\bchenille\b", "chenille"),
    (r"\bboucl[eé]\b", "boucle"), (r"\blinen\b", "linen"), (r"\bjute\b|\bflat[ -]?wov|\bflatweave\b|\bsisal\b", "weave"),
    (r"\bwool\b", "wool"),
    (r"\bwalnut\b", "walnut"), (r"\bwhite oak\b|\bbirch\b|\bmaple\b", "white_oak"), (r"\boak\b|\bash\b", "oak"),
    (r"\bpine\b", "pine"), (r"\blacquer", "lacquer"), (r"\bpainted\b", "painted"), (r"\bglass\b", "glass"),
    (r"\bmarble\b|\bstone\b|\bterrazzo\b", "marble"),
    (r"\bsuede\b", "suede"), (r"\bcotton\b", "cotton"), (r"\bceramic\b", "ceramic"),
    (r"\benamel\b", "enamel"), (r"\brattan\b|\bwicker\b", "rattan"))]
_GENERIC_FABRIC_HINT = re.compile(r"\bfabric\b|\bcotton\b|\bpolyester\b|\bupholster")  # only when nothing specific
_HINT_SURFACES = {"sofa": SOFT_SURFACES, "bed": SOFT_SURFACES, "rug": ("wool", "weave", "linen"),
                  "tv": ("oak", "walnut", "white_oak", "brushed_metal", "black_metal"),
                  "lamp": ("linen", "cotton", "ceramic", "enamel", "brushed_metal", "black_metal")}
_PILE_HINTS = [(re.compile(r"\bhigh[ -]?pile\b|\bshag"), "high"), (re.compile(r"\blow[ -]?pile\b"), "low"),
               (re.compile(r"\bflat[ -]?wov|\bflatweave\b"), "flat")]

_HEX_RE = re.compile(r"^#?([0-9A-Fa-f]{6})$")
_OBJECT_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
_FILENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class ValidationError(ValueError):
    pass


def _check_keys(name: str, value: Any, allowed: set[str], required: set[str] = frozenset()) -> dict:
    if not isinstance(value, dict):
        raise ValidationError(f"{name} must be an object")
    unknown = set(value) - allowed
    if unknown:
        raise ValidationError(f"{name} has unknown keys: {sorted(unknown)}")
    missing = required - set(value)
    if missing:
        raise ValidationError(f"{name} is missing keys: {sorted(missing)}")
    return value


def number(name: str, value: Any, lo: float, hi: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"{name} must be a number")
    v = float(value)
    if not math.isfinite(v):
        raise ValidationError(f"{name} must be finite")
    if not lo <= v <= hi:
        raise ValidationError(f"{name}={v} is outside [{lo}, {hi}]")
    return v


def color_hex(value: Any, name: str = "color_hex") -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{name} must be a string like #A1B2C3")
    m = _HEX_RE.match(value.strip())
    if not m:
        raise ValidationError(f"{name}={value!r} is not a 6-digit hex color")
    return "#" + m.group(1).upper()


def material(value: Any) -> str:
    if not isinstance(value, str) or value.strip().lower() not in MATERIALS:
        raise ValidationError(f"material must be one of {MATERIALS}")
    return value.strip().lower()


def category(value: Any) -> str:
    if value not in CATEGORIES:
        raise ValidationError(f"category must be one of {CATEGORIES}")
    return value


def dimensions(value: Any, name: str = "dimensions_m", cat: str | None = None) -> dict[str, float]:
    _check_keys(name, value, {"width", "depth", "height"}, {"width", "depth", "height"})
    dims = {k: number(f"{name}.{k}", value[k], DIM_MIN_M, DIM_MAX_M) for k in ("width", "depth", "height")}
    for k, (lo, hi) in CATEGORY_DIM_RANGES_M.get(cat, {}).items():
        if not lo <= dims[k] <= hi:
            raise ValidationError(f"{name}.{k}={dims[k]} is outside [{lo}, {hi}] for a {cat}")
    return dims


def shape(value: Any, cat: str, dims: dict[str, float]) -> str:
    s = _SHAPE_ALIASES.get(value.strip().lower()) if isinstance(value, str) else None
    if s is None:
        raise ValidationError(f"shape must be one of {SHAPES}")
    if s == "round":
        if cat not in ROUND_CATEGORIES:
            raise ValidationError(f"shape 'round' is only supported for {ROUND_CATEGORIES}")
        if abs(dims["width"] - dims["depth"]) > ROUND_TOLERANCE_M:
            raise ValidationError("shape 'round' needs width == depth (the diameter)")
    return s


def product_shape(product: dict) -> str | None:
    """'round' when style.shape (or, failing that, a 'round' style tag) asks for it; else None (rect)."""
    style = product.get("style") or {}
    if not isinstance(style, dict):
        return None
    s = style.get("shape")
    if isinstance(s, str):
        return "round" if _SHAPE_ALIASES.get(s.strip().lower()) == "round" else None
    tags = [t.strip().lower() for t in style.get("tags") or [] if isinstance(t, str)]
    return "round" if "round" in tags else None


def default_texture_mode(cat: str) -> str:
    return "print" if cat == "rug" else "tile"


def texture_path(value: Any) -> str:
    """Absolute path to an existing JPEG/PNG/WebP file under TEXTURE_MAX_BYTES (checked by magic bytes too)."""
    if not isinstance(value, str) or not value or "\x00" in value or not os.path.isabs(value):
        raise ValidationError("texture.path must be an absolute file path")
    suffix = os.path.splitext(value)[1].lower()
    if suffix not in TEXTURE_SUFFIXES:
        raise ValidationError(f"texture.path must end with one of {TEXTURE_SUFFIXES}")
    if not os.path.isfile(value):
        raise ValidationError("texture.path does not exist or is not a file")
    size = os.path.getsize(value)
    if not 0 < size < TEXTURE_MAX_BYTES:
        raise ValidationError(f"texture file must be non-empty and smaller than {TEXTURE_MAX_BYTES} bytes")
    with open(value, "rb") as fh:
        head = fh.read(12)
    if not head.startswith(_IMAGE_MAGIC[suffix]) or (suffix == ".webp" and head[8:12] != b"WEBP"):
        raise ValidationError(f"texture file is not a valid {suffix[1:]} image")
    return os.path.normpath(value)


def texture(value: Any, cat: str) -> dict:
    """{path, mode?, tile_m?} -> {path, mode, tile_m}; mode defaults per category, tile_m is clamped."""
    _check_keys("texture", value, {"path", "mode", "tile_m"}, {"path"})
    mode = value.get("mode") or default_texture_mode(cat)
    if mode not in TEXTURE_MODES:
        raise ValidationError(f"texture.mode must be one of {TEXTURE_MODES}")
    tile = value.get("tile_m")
    tile = DEFAULT_TEXTURE_TILE_M if tile is None else number("texture.tile_m", tile, -math.inf, math.inf)
    lo, hi = TEXTURE_TILE_RANGE_M
    return {"path": texture_path(value["path"]), "mode": mode, "tile_m": min(hi, max(lo, tile))}


def product_texture(product: dict) -> dict | None:
    """Normalized texture from style.texture_path/texture_mode/texture_tile_m, or None when absent or unusable.
    A bad mode or tile size falls back to the default; a missing/unsupported file means no texture."""
    style = product.get("style") if isinstance(product, dict) else None
    if not isinstance(style, dict) or not style.get("texture_path"):
        return None
    cat = product.get("category")
    if cat != "rug":
        return None
    mode = style.get("texture_mode")
    tile = style.get("texture_tile_m")
    raw = {"path": style["texture_path"],
           "mode": mode if mode in TEXTURE_MODES else None,
           "tile_m": tile if isinstance(tile, (int, float)) and not isinstance(tile, bool) and math.isfinite(tile)
           else None}
    try:
        return texture(raw, cat)
    except (ValidationError, OSError):
        return None


def _form_value(cat: str, key: str, value: Any, strict: bool) -> Any:
    """Normalized value for FORM_SCHEMA[cat][key]; raises ValidationError when it does not fit."""
    allowed = FORM_SCHEMA[cat][key]
    name = f"form.{key}"
    if allowed == HEX:
        if isinstance(value, str) and re.fullmatch(r"#[0-9A-Fa-f]{6}", value.strip()):
            return value.strip().upper()
        raise ValidationError(f"{name} must be a '#RRGGBB' hex color")
    if allowed is bool:
        if isinstance(value, bool):
            return value
        if not strict and isinstance(value, str) and value.strip().lower() in _BOOL_WORDS:
            return _BOOL_WORDS[value.strip().lower()]
        raise ValidationError(f"{name} must be a boolean")
    if isinstance(allowed[0], int):
        lo, hi = allowed
        if not strict and isinstance(value, str) and value.strip().isdigit():
            value = int(value.strip())
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) \
                or value != int(value) or not lo <= value <= hi:
            raise ValidationError(f"{name} must be an integer in [{lo}, {hi}]")
        return int(value)
    v = value.strip().lower().replace("-", "_").replace(" ", "_") if isinstance(value, str) else None
    if v not in allowed:
        raise ValidationError(f"{name} must be one of {allowed}")
    return v


def form(value: Any, cat: str) -> dict:
    """Strict form validation (MCP tools / explicit specs): unknown keys and bad values raise."""
    if not isinstance(value, dict):
        raise ValidationError("form must be an object")
    unknown = set(value) - set(FORM_SCHEMA[cat])
    if unknown:
        raise ValidationError(f"form has unknown keys for a {cat}: {sorted(map(str, unknown))}; "
                              f"allowed: {sorted(FORM_SCHEMA[cat])}")
    return {k: _form_value(cat, k, value[k], True) for k in sorted(value) if value[k] is not None}


def product_form(product: Any) -> dict:
    """Lenient form from product.style.form: keeps only keys/values valid for the category (sorted), drops junk."""
    style = product.get("style") if isinstance(product, dict) else None
    raw = style.get("form") if isinstance(style, dict) else None
    cat = product.get("category") if isinstance(product, dict) else None
    if not isinstance(raw, dict) or cat not in FORM_SCHEMA:
        return {}
    out = {}
    for k in sorted(k for k in raw if isinstance(k, str) and k in FORM_SCHEMA[cat]):
        try:
            out[k] = _form_value(cat, k, raw[k], False)
        except ValidationError:
            pass
    return out


def material_hints(product: dict) -> dict:
    """Form defaults implied by free-text style.material ("velvet, turned wood legs" -> surface velvet,
    "high pile" -> pile high). The raw material string is part of asset_key, so these stay keyed."""
    style = product.get("style") if isinstance(product.get("style"), dict) else {}
    text = style.get("material")
    cat = product.get("category")
    if not isinstance(text, str) or cat not in FORM_SCHEMA:
        return {}
    text = text.lower()
    out = {}
    hits = [(m.start(), -len(m.group(0)), s) for rx, s in _SURFACE_HINTS for m in [rx.search(text)] if m]
    allowed = _HINT_SURFACES.get(cat, tuple(s for s in SURFACES if s not in SOFT_SURFACES))
    hits = sorted(h for h in hits if h[2] in allowed)
    if hits:
        out["surface"] = hits[0][2]
    elif "weave" in allowed and _GENERIC_FABRIC_HINT.search(text):
        out["surface"] = "weave"
    if cat == "rug":
        pile = next((p for rx, p in _PILE_HINTS if rx.search(text)), None)
        if pile:
            out["pile"] = pile
    return out


def _luma(hex_color: str) -> float:
    h = color_hex(hex_color).lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def material_surface(mat: str, hex_color: str) -> str:
    """Default surface for a material kind (metal: dark colors are powder-coated black, light ones brushed)."""
    if mat == "metal":
        return "black_metal" if _luma(hex_color) < METAL_DARK_LUMA else "brushed_metal"
    return MATERIAL_SURFACE[mat]


def primary_hex(spec: dict) -> str:
    """Main-surface color of a validated spec: form.primary_hex (photo-read) over the catalog color_hex."""
    return (spec.get("form") or {}).get("primary_hex") or spec["color_hex"]


def main_surface(spec: dict) -> str:
    """The visible main surface of a validated spec: form.surface, else derived from material + color."""
    return (spec.get("form") or {}).get("surface") or material_surface(spec["material"], primary_hex(spec))


def object_id(value: Any) -> str:
    if not isinstance(value, str) or not _OBJECT_ID_RE.match(value):
        raise ValidationError("object_id must match [A-Za-z0-9_.:-]{1,64}")
    return value


def filename(value: Any, suffixes: tuple[str, ...]) -> str:
    if not isinstance(value, str) or not _FILENAME_RE.match(value) or ".." in value:
        raise ValidationError("filename must be a plain file name ([A-Za-z0-9._-], no directories)")
    if not value.lower().endswith(suffixes):
        raise ValidationError(f"filename must end with one of {suffixes}")
    return value


def position(value: Any) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValidationError("position_m must be [x, y, z]")
    return [number(f"position_m[{i}]", v, -POSITION_LIMIT_M, POSITION_LIMIT_M) for i, v in enumerate(value)]


def rotation(value: Any) -> float:
    return number("rotation_y_rad", value, -ROTATION_LIMIT_RAD, ROTATION_LIMIT_RAD)


def furniture_spec(value: Any) -> dict:
    """{category, dimensions_m, color_hex?, material?, frame_finish?, shape?, texture?, form?} -> normalized spec.
    `texture` ({path, mode?, tile_m?}) and `form` (FORM_SCHEMA[category]) are only present when given/non-empty."""
    _check_keys("spec", value, {"category", "dimensions_m", "color_hex", "material", "frame_finish", "shape",
                                "texture", "form"},
                {"category", "dimensions_m"})
    cat = category(value["category"])
    dims = dimensions(value["dimensions_m"], cat=cat)
    spec = {
        "category": cat,
        "dimensions_m": dims,
        "color_hex": color_hex(value.get("color_hex") or DEFAULT_COLOR[cat]),
        "material": material(value.get("material") or DEFAULT_MATERIAL[cat]),
        "shape": shape(value.get("shape") or "rect", cat, dims),
    }
    finish = value.get("frame_finish")
    if finish is None:
        finish = "metal" if spec["material"] == "metal" else "wood"
    if finish not in FRAME_FINISHES:
        raise ValidationError(f"frame_finish must be one of {FRAME_FINISHES}")
    spec["frame_finish"] = finish
    if value.get("texture") is not None:
        spec["texture"] = texture(value["texture"], cat)
    if value.get("form") is not None:
        f = form(value["form"], cat)
        if f:
            spec["form"] = f
    return spec


def _opening(value: Any, i: int, room: dict) -> dict:
    name = f"openings[{i}]"
    _check_keys(name, value, {"kind", "wall", "offset_m", "width_m", "height_m", "sill_m"},
                {"kind", "wall", "offset_m", "width_m"})
    kind, wall = value["kind"], value["wall"]
    if kind not in OPENING_KINDS:
        raise ValidationError(f"{name}.kind must be one of {OPENING_KINDS}")
    if wall not in WALLS:
        raise ValidationError(f"{name}.wall must be one of {WALLS}")
    wall_len = room["width_m"] if wall in ("front", "back") else room["depth_m"]
    h = room["height_m"]
    width = number(f"{name}.width_m", value["width_m"], 0.2, wall_len)
    offset = number(f"{name}.offset_m", value["offset_m"], -wall_len / 2, wall_len / 2)
    if offset - width / 2 < -wall_len / 2 - 1e-9 or offset + width / 2 > wall_len / 2 + 1e-9:
        raise ValidationError(f"{name} does not fit inside the {wall} wall (length {wall_len} m)")
    if kind == "door":
        sill = number(f"{name}.sill_m", value.get("sill_m", 0.0), 0.0, 0.0)
        height = number(f"{name}.height_m", value.get("height_m", min(2.05, h)), 0.5, h)
    else:
        sill = number(f"{name}.sill_m", value.get("sill_m", min(0.9, h - 0.6)), 0.0, h - 0.2)
        height = number(f"{name}.height_m", value.get("height_m", min(1.2, h - sill - 0.1)), 0.2, h - sill)
    return {"kind": kind, "wall": wall, "offset_m": offset, "width_m": width, "height_m": height, "sill_m": sill}


def _clearance(value: Any, i: int) -> dict:
    name = f"clearances[{i}]"
    _check_keys(name, value, {"label", "x_m", "z_m", "width_m", "depth_m"}, {"x_m", "z_m", "width_m", "depth_m"})
    label = value.get("label", f"clearance {i}")
    if not isinstance(label, str) or len(label) > 80:
        raise ValidationError(f"{name}.label must be a string of at most 80 chars")
    return {"label": label,
            "x_m": number(f"{name}.x_m", value["x_m"], -POSITION_LIMIT_M, POSITION_LIMIT_M),
            "z_m": number(f"{name}.z_m", value["z_m"], -POSITION_LIMIT_M, POSITION_LIMIT_M),
            "width_m": number(f"{name}.width_m", value["width_m"], 0.01, 20.0),
            "depth_m": number(f"{name}.depth_m", value["depth_m"], 0.01, 20.0)}


def room_spec(value: Any) -> dict:
    """Accepts the API room object (width_m/depth_m/height_m/openings/clearances) plus build options.

    Openings: offset_m is the opening's center along the wall in scene coordinates
    (x for front/back walls, z for left/right walls), matching how clearances use x_m/z_m.
    """
    _check_keys("room", value,
                {"width_m", "depth_m", "height_m", "openings", "clearances", "inspiration_image_url",
                 "wall_thickness_m", "walls", "wall_color_hex", "floor_color_hex"},
                {"width_m", "depth_m", "height_m"})
    room = {
        "width_m": number("width_m", value["width_m"], *ROOM_WIDTH_RANGE_M),
        "depth_m": number("depth_m", value["depth_m"], *ROOM_WIDTH_RANGE_M),
        "height_m": number("height_m", value["height_m"], *ROOM_HEIGHT_RANGE_M),
        "wall_thickness_m": number("wall_thickness_m", value.get("wall_thickness_m", 0.1), *WALL_THICKNESS_RANGE_M),
        "wall_color_hex": color_hex(value.get("wall_color_hex") or DEFAULT_WALL_COLOR, "wall_color_hex"),
        "floor_color_hex": color_hex(value.get("floor_color_hex") or DEFAULT_FLOOR_COLOR, "floor_color_hex"),
    }
    walls = value.get("walls", list(WALLS))
    if not isinstance(walls, (list, tuple)) or any(w not in WALLS for w in walls) or len(set(walls)) != len(walls):
        raise ValidationError(f"walls must be a list of distinct values from {WALLS}")
    room["walls"] = [w for w in WALLS if w in walls]
    openings = value.get("openings") or []
    if not isinstance(openings, list) or len(openings) > MAX_OPENINGS:
        raise ValidationError(f"openings must be a list of at most {MAX_OPENINGS}")
    room["openings"] = [_opening(o, i, room) for i, o in enumerate(openings)]
    for wall in WALLS:
        spans = sorted((o["offset_m"] - o["width_m"] / 2, o["offset_m"] + o["width_m"] / 2)
                       for o in room["openings"] if o["wall"] == wall)
        for (_, a_hi), (b_lo, _) in zip(spans, spans[1:]):
            if b_lo < a_hi + 0.05:
                raise ValidationError(f"openings on the {wall} wall overlap or are closer than 5 cm")
    clearances = value.get("clearances") or []
    if not isinstance(clearances, list) or len(clearances) > MAX_CLEARANCES:
        raise ValidationError(f"clearances must be a list of at most {MAX_CLEARANCES}")
    room["clearances"] = [_clearance(c, i) for i, c in enumerate(clearances)]
    return room


def render_params(value: Any) -> dict:
    _check_keys("render", value, {"width_px", "height_px", "engine", "view", "cutaway", "target"})
    out = {
        "width_px": int(number("width_px", value.get("width_px", 480), *PREVIEW_PX_RANGE)),
        "height_px": int(number("height_px", value.get("height_px", 360), *PREVIEW_PX_RANGE)),
        "engine": value.get("engine", "workbench"),
        "view": value.get("view", "iso"),
        "cutaway": value.get("cutaway", True),
        "target": value.get("target", "scene"),
    }
    if out["engine"] not in RENDER_ENGINES:
        raise ValidationError(f"engine must be one of {RENDER_ENGINES}")
    if out["view"] not in RENDER_VIEWS:
        raise ValidationError(f"view must be one of {RENDER_VIEWS}")
    if not isinstance(out["cutaway"], bool):
        raise ValidationError("cutaway must be a boolean")
    if out["target"] not in ("scene", "room"):
        object_id(out["target"])
    return out


def spec_from_product(product: Any) -> dict | None:
    """Product (API schema) -> furniture spec, or None when it cannot be built to scale."""
    if not isinstance(product, dict):
        return None
    dims = product.get("dimensions_m")
    if not dims or product.get("dimension_kind") == "package":
        return None
    if product.get("category") not in CATEGORIES:
        return None
    style = product.get("style") or {}
    mat = style.get("material")
    spec = {
        "category": product["category"],
        "dimensions_m": {k: dims.get(k) for k in ("width", "depth", "height")} if isinstance(dims, dict) else dims,
        "color_hex": style.get("color_hex") or None,
        "material": mat.lower() if isinstance(mat, str) and mat.lower() in MATERIALS else None,
    }
    tags = [t.lower() for t in style.get("tags") or [] if isinstance(t, str)]
    if spec["category"] in ("sofa", "bed", "desk") and "metal" in tags:
        spec["frame_finish"] = "metal"
    if spec["category"] == "bed" and "upholstered" in tags:
        spec["frame_finish"] = "upholstered"
    spec["shape"] = product_shape(product)
    spec["texture"] = product_texture(product)
    spec["form"] = dict(material_hints(product), **product_form(product)) or None
    try:
        return furniture_spec({k: v for k, v in spec.items() if v is not None})
    except ValidationError:
        if spec["shape"] is None:
            return None
    try:  # a round request the template cannot honor (category or width != depth) still builds to scale
        return furniture_spec({k: v for k, v in spec.items() if v is not None and k != "shape"})
    except ValidationError:
        return None
