"""Visible design features ("form") read from product photos by Gemini, so Blender builds look like the listing.

Mirrors FORM_SCHEMA in integrations/blender_mcp/specs.py. Gemini only picks from these enums; anything not
clearly visible is left out and the template keeps its default.
"""
import json
import re
from pathlib import Path

from . import config

SURFACES = ('oak', 'walnut', 'white_oak', 'pine', 'painted', 'lacquer', 'linen', 'weave', 'boucle', 'velvet',
            'chenille', 'leather', 'faux_leather', 'brushed_metal', 'black_metal', 'glass', 'marble', 'wool',
            'suede', 'cotton', 'ceramic', 'enamel', 'rattan')
BOOL = 'bool'
HEX = 'hex'
_HEX_RE = re.compile(r'^#?([0-9A-Fa-f]{6})$')
_COMMON = {'primary_hex': HEX, 'accent_surface': SURFACES, 'accent_hex': HEX}
SCHEMA = {
    'sofa': {'arm_style': ('track', 'rolled', 'sloped', 'flared', 'none'),
             'back_style': ('tight', 'pillow', 'tufted', 'channel'), 'seat_cushions': (1, 4), 'back_cushions': (0, 4),
             'leg_style': ('tapered', 'block', 'metal', 'hidden', 'bun', 'turned'), 'skirt': BOOL,
             'chaise': ('none', 'left', 'right'), 'tufted_seat': BOOL,
             'arm_bulk': ('slim', 'regular', 'plump'), 'seat_rise': ('low', 'mid', 'high'),
             'arm_rise': ('low', 'mid', 'high'), 'back_bulk': ('thin', 'regular', 'thick'), **_COMMON},
    'coffee_table': {'leg_style': ('tapered', 'straight', 'hairpin', 'pedestal', 'panel', 'sled', 'x_base', 'turned'),
                     'shelf': BOOL, 'drawer': BOOL, 'top_style': ('slab', 'glass', 'stone', 'lift_top'), **_COMMON},
    'tv': {'bezel': ('thin', 'frame'), 'stand': ('feet', 'pedestal', 'none'), **_COMMON},
    'rug': {'fringe': BOOL, 'pile': ('flat', 'low', 'high'), **_COMMON},
    'bed': {'headboard': ('panel', 'tufted', 'channel', 'slatted', 'spindle', 'wingback', 'none'), 'footboard': BOOL,
            'leg_style': ('tapered', 'block', 'metal', 'hidden'), 'frame': ('platform', 'rails', 'storage'), **_COMMON},
    'nightstand': {'drawers': (0, 3), 'open_shelf': BOOL, 'door': BOOL,
                   'leg_style': ('tapered', 'straight', 'hairpin', 'plinth', 'none', 'turned'), **_COMMON},
    'dresser': {'columns': (1, 3), 'rows': (2, 5), 'leg_style': ('tapered', 'plinth', 'metal', 'bun', 'turned'),
                'handle_style': ('knob', 'bar', 'cutout', 'cup', 'none'), **_COMMON},
    'desk': {'drawers': (0, 3), 'pedestal': ('none', 'left', 'right'), 'pedestal_open': BOOL,
             'leg_style': ('tapered', 'straight', 'metal_frame', 'trestle', 'panel', 'hairpin'), 'shelf': BOOL,
             **_COMMON},
    'lamp': {'kind': ('table', 'floor', 'desk', 'accent', 'arc', 'torchiere'),
             'shade': ('drum', 'empire', 'cone', 'none', 'mushroom', 'square', 'bell'),
             'base': ('round', 'square', 'tripod', 'sculpted', 'disc', 'gourd'),
             'shade_scale': ('small', 'regular', 'large'), 'stem': ('thin', 'regular', 'thick'), **_COMMON},
}
FORMS_PATH = Path(config.DATA_DIR / 'catalog_forms.json')

PROMPT = """You are describing a {category} product photo so a 3D modeller can match its SHAPE. Title: {title}.
Fill a field only when the photo clearly shows it; omit anything you cannot see. Silhouette matters more than
colour. For a sofa: arm_bulk is how thick the arms are (slim mid-century vs plump overstuffed); seat_rise is
how high the seat is on the piece; arm_rise is how high the arms sit versus the back; back_bulk is how deep
the backrest is front-to-back. For a lamp: kind is table/floor/desk/accent/arc/torchiere; shade is the shade
silhouette (drum, empire, cone, mushroom, square, bell, or none); base is the foot or body (gourd = ceramic
body with little stem); shade_scale is how tall the shade is versus the whole lamp; stem is pole thickness.
"surface" is the main visible finish. "primary_hex" is that finish as #RRGGBB.
"accent_surface" and "accent_hex" are legs/frame when they differ. Counts are visible seat and back cushions."""


def response_schema(category: str) -> dict:
    props = {'surface': {'type': 'string', 'enum': list(SURFACES)}}
    for key, rule in SCHEMA[category].items():
        if rule == BOOL:
            props[key] = {'type': 'boolean'}
        elif rule == HEX:
            props[key] = {'type': 'string', 'pattern': '^#[0-9A-Fa-f]{6}$'}
        elif isinstance(rule[0], int):
            props[key] = {'type': 'integer', 'minimum': rule[0], 'maximum': rule[1]}
        else:
            props[key] = {'type': 'string', 'enum': list(rule)}
    return {'type': 'object', 'properties': props}


def clean(category: str, raw: dict) -> dict:
    """Keep only schema-valid values, so a bad read can never break a build."""
    out = {}
    if raw.get('surface') in SURFACES:
        out['surface'] = raw['surface']
    for key, rule in SCHEMA.get(category, {}).items():
        v = raw.get(key)
        if rule == BOOL:
            ok = isinstance(v, bool)
        elif rule == HEX:
            m = _HEX_RE.match(v.strip()) if isinstance(v, str) else None
            if m:
                out[key] = '#' + m.group(1).upper()
            continue
        elif isinstance(rule[0], int):
            ok = type(v) is int and rule[0] <= v <= rule[1]
        else:
            ok = v in rule
        if ok:
            out[key] = v
    return out


DIM_PROMPT = """Read the assembled furniture size from the title and photo if it is printed.
Use inches. Omit a field when you cannot see it. Do not guess a typical size and do not use package size.
Title: {title}."""


def read_dimensions(product: dict) -> dict | None:
    """Gemini W×D×H in metres from a listing title and local photo, or None."""
    from google.genai import types

    from . import agent
    photo = config.STATIC_DIR / product['local_image']
    mime = 'image/png' if photo.suffix.lower() == '.png' else 'image/jpeg'
    resp = agent._gemini().models.generate_content(
        model=config.GEMINI_MODEL,
        contents=[types.Part.from_bytes(data=photo.read_bytes(), mime_type=mime),
                  DIM_PROMPT.format(title=product.get('title', ''))],
        config=types.GenerateContentConfig(
            response_mime_type='application/json',
            response_schema={'type': 'object', 'properties': {
                'width_in': {'type': 'number'}, 'depth_in': {'type': 'number'}, 'height_in': {'type': 'number'}}},
            temperature=0),
    )
    raw = json.loads(resp.text or '{}')
    try:
        w, d, h = float(raw['width_in']), float(raw['depth_in']), float(raw['height_in'])
    except (KeyError, TypeError, ValueError):
        return None
    if min(w, d, h) <= 0 or max(w, d, h) > 240:
        return None
    return {'width': round(w * 0.0254, 3), 'depth': round(d * 0.0254, 3), 'height': round(h * 0.0254, 3)}


def read_photo(product: dict) -> dict:
    """Gemini's form read for one product with a local photo."""
    from google.genai import types

    from . import agent
    photo = config.STATIC_DIR / product['local_image']
    mime = 'image/png' if photo.suffix.lower() == '.png' else 'image/jpeg'
    resp = agent._gemini().models.generate_content(
        model=config.GEMINI_MODEL,
        contents=[types.Part.from_bytes(data=photo.read_bytes(), mime_type=mime),
                  PROMPT.format(category=product['category'].replace('_', ' '), title=product.get('title', ''))],
        config=types.GenerateContentConfig(response_mime_type='application/json',
                                           response_schema=response_schema(product['category']), temperature=0),
    )
    return clean(product['category'], json.loads(resp.text))


def load() -> dict:
    try:
        return json.loads(FORMS_PATH.read_text())
    except (OSError, ValueError):
        return {}
