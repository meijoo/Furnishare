"""Floor-plan import: Gemini reads room labels, size text and boxes from an image; this module turns them into metres.

Gemini is only trusted for what it reads (labels, "13'x12'" text, rough boxes). Scale comes from the labelled sizes,
every number is validated here, and the result is a plan in the same shape as the built-in apartment.
"""
import re
import logging
import time
import statistics
import struct

from . import config

KINDS = ('bedroom', 'bathroom', 'living', 'kitchen', 'dining', 'hall', 'closet', 'patio', 'laundry', 'other')
FT = 0.3048
MIN_BEDROOM_M = 2.4

PROMPT = """This is a residential floor-plan drawing. Return every enclosed space that has its own walls
or a clear partition: bedrooms, bathrooms, living/family/great rooms, kitchen, dining, halls, closets,
laundry, patio/deck/porch, pantry, foyer.

Do not return furniture, fixtures, doors, windows, stairs, north arrows, scale bars, legends, title
blocks, addresses, sheet notes, or overall building dimensions that sit outside a room. Do not list
the same space twice.

For each space:
- label: the printed room name only. No sizes, no sq ft, no owner names. If unlabelled, use a short
  kind name (Closet, Hall, Bath).
- kind: bedroom, bathroom, living, kitchen, dining, hall, closet, patio, laundry, or other.
  master / primary / guest bedroom → bedroom.
  washroom, W.C., powder, toilet, half bath, en-suite bath → bathroom.
  family / great / sitting / lounge / living → living.
  dining / dinette / breakfast → dining.
  washer/dryer, W/D, laundry → laundry.
  deck / balcony / porch / patio → patio.
  foyer / entry / corridor / hallway → hall.
- dimension_text: copy the size printed inside THAT room, exactly (10'-10"X14'-5", 12'6" x 10',
  9' x 12', 137 sq ft). Null if that room has no size. Never copy a neighbor's size or a title-block
  overall width.
- box_2d: [ymin, xmin, ymax, xmax] in 0-1000 image coordinates, tight to the inside of that room's
  walls. Do not swallow an adjoining closet, bath, or hall. For an L-shape or bay, box the main
  rectangle only.

List rooms left-to-right, top-to-bottom."""

RESPONSE_SCHEMA = {
    'type': 'object',
    'properties': {'rooms': {'type': 'array', 'items': {
        'type': 'object',
        'properties': {
            'label': {'type': 'string'},
            'kind': {'type': 'string', 'enum': list(KINDS)},
            'dimension_text': {'type': 'string', 'nullable': True},
            'box_2d': {'type': 'array', 'items': {'type': 'integer'}},
        },
        'required': ['label', 'kind', 'box_2d'],
    }}},
    'required': ['rooms'],
}


class PlanError(ValueError):
    pass


def image_size(data: bytes) -> tuple[int, int]:
    """(width, height) of a PNG or JPEG without an imaging library."""
    if data[:8] == b'\x89PNG\r\n\x1a\n' and len(data) >= 24:
        return struct.unpack('>II', data[16:24])
    if data[:2] == b'\xff\xd8':
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                i += 2
                continue
            length = struct.unpack('>H', data[i + 2:i + 4])[0]
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                h, w = struct.unpack('>HH', data[i + 5:i + 9])
                return w, h
            i += 2 + length
    raise PlanError('Upload a PNG or JPEG floor plan')


# 10'-10", 12'6", 13', 8'-8½", 6'-½"
_FT_MARK = r"(?:'|ft|’|′)"
_IN_MARK = r"(?:\"|in|”|''|″)"
_INCHES = r"((?:\d+(?:\.\d+)?)?\s*(?:½|1/2)|\d+(?:\.\d+)?)"
_FT_IN = rf"(\d+(?:\.\d+)?)\s*{_FT_MARK}\s*-?\s*(?:{_INCHES}\s*{_IN_MARK}?)?"
_SQFT = re.compile(r'(\d+(?:\.\d+)?)\s*(?:sq\.?\s*ft|sqft|sf|square\s*feet)\b')
_SQM = re.compile(r'(\d+(?:\.\d+)?)\s*(?:m2|m\^2|sq\.?\s*m|square\s*metres?)\b')
SQFT = 0.09290304


def _inches(raw: str | None) -> float:
    if not raw:
        return 0.0
    s = raw.strip()
    if '½' in s or '1/2' in s:
        whole = s.replace('½', '').replace('1/2', '').strip()
        return (float(whole) if whole else 0.0) + 0.5
    return float(s)


def _normalize_size_text(text: str) -> str:
    return (text.strip().lower().replace('×', 'x').replace('–', '-').replace('—', '-')
            .replace('′', "'").replace('″', '"'))


def parse_dimensions(text: str | None) -> tuple[float, float] | None:
    """Metres (a, b) from size text like 13'x12', 10'-10"X14'-5", 12'6" x 10', 4.2 x 3.6 m."""
    if not text:
        return None
    t = _normalize_size_text(text)
    m = re.search(_FT_IN + r'\s*x\s*' + _FT_IN, t)
    if m:
        a = float(m.group(1)) + _inches(m.group(2)) / 12
        b = float(m.group(3)) + _inches(m.group(4)) / 12
        return a * FT, b * FT
    m = re.search(r'(\d+(?:\.\d+)?)\s*m?\s*x\s*(\d+(?:\.\d+)?)\s*m\b', t)
    if m:
        return float(m.group(1)), float(m.group(2))
    return None


def parse_area_m2(text: str | None) -> float | None:
    """Square metres from '137 sq ft', '78sqft', or '12.5 m2'."""
    if not text:
        return None
    t = _normalize_size_text(text)
    if m := _SQFT.search(t):
        return float(m.group(1)) * SQFT
    if m := _SQM.search(t):
        return float(m.group(1))
    return None


def dims_from_area(area_m2: float, width_px: float, height_px: float) -> tuple[float, float] | None:
    """Width and depth in metres from printed area and the drawn box's aspect ratio."""
    if area_m2 <= 0 or width_px < 1 or height_px < 1:
        return None
    width_m = (area_m2 * (width_px / height_px)) ** 0.5
    return width_m, area_m2 / width_m


def size_from_read(read: dict) -> tuple[float, float] | None:
    """WxD metres from dimension_text or the room label (area is turned into WxD later)."""
    blob = ' '.join(str(read.get(k) or '') for k in ('dimension_text', 'label'))
    if dims := parse_dimensions(blob):
        return dims
    return None


def area_from_read(read: dict) -> float | None:
    blob = ' '.join(str(read.get(k) or '') for k in ('dimension_text', 'label'))
    return parse_area_m2(blob)


def kind_from_label(label: str | None, kind: str) -> str:
    """Correct obvious Gemini kind mistakes from the printed name."""
    t = re.sub(r'[^a-z0-9]+', ' ', (label or '').lower()).strip()
    words = set(t.split())
    if (words & {'washroom', 'wc', 'powder', 'toilet'} or t.startswith('w c')
            or 'bath' in t or 'half bath' in t):
        return 'bathroom'
    if 'laundry' in words or re.search(r'\bw\s*d\b', t):
        return 'laundry'
    if 'bedroom' in t or (words & {'master', 'primary'} and not (words & {'bath', 'bathroom'})):
        return 'bedroom'
    if words & {'family', 'great', 'sitting', 'lounge'} or 'living' in t:
        return 'living'
    if words & {'dining', 'dinette', 'breakfast'}:
        return 'dining'
    if words & {'deck', 'balcony', 'porch', 'patio'}:
        return 'patio'
    if words & {'foyer', 'hallway', 'corridor', 'entry', 'entryway'}:
        return 'hall'
    return kind if kind in KINDS else 'other'


_SIZE_IN_LABEL = re.compile(
    rf'(?:{_FT_IN}\s*x\s*{_FT_IN}'
    r'|\d+(?:\.\d+)?\s*m?\s*x\s*\d+(?:\.\d+)?\s*m\b'
    r'|\d+(?:\.\d+)?\s*(?:sq\.?\s*ft|sqft|sf|square\s*feet)\b'
    r'|\d+(?:\.\d+)?\s*(?:m2|m\^2|sq\.?\s*m|square\s*metres?)\b)',
    re.I,
)


def clean_label(label: str | None) -> str:
    """Drop printed sizes Gemini sometimes glues onto the room name."""
    raw = (label or '').strip() or 'Room'
    t = _SIZE_IN_LABEL.sub('', raw)
    t = re.sub(r'[\s,;:/–—-]+$', '', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return (t or raw)[:40]


def extract(data: bytes, mime: str) -> list[dict]:
    """Raw room reads from Gemini. Separate so tests can replace it."""
    from google.genai import types

    from . import agent
    # Short JSON extract: no thinking, medium image tokens, one try.
    thinking = types.ThinkingConfig(thinking_budget=0, thinking_level=types.ThinkingLevel.MINIMAL)
    started = time.perf_counter()
    resp = agent._gemini().models.generate_content(
        model=config.GEMINI_FLOORPLAN_MODEL,
        contents=[types.Part.from_bytes(data=data, mime_type=mime), PROMPT],
        config=types.GenerateContentConfig(response_mime_type='application/json', response_schema=RESPONSE_SCHEMA,
                                           temperature=0, thinking_config=thinking,
                                           max_output_tokens=4096,
                                           media_resolution=types.MediaResolution.MEDIA_RESOLUTION_MEDIUM,
                                           http_options=types.HttpOptions(
                                               timeout=40_000,
                                               retry_options=types.HttpRetryOptions(attempts=1))),
    )
    import json
    rooms = json.loads(resp.text)['rooms']
    logging.getLogger('uvicorn.error').info('Floor-plan image read: %.1f s (%d rooms)',
                                           time.perf_counter() - started, len(rooms))
    return rooms


def _r(v: float) -> float:
    return round(round(v / 0.05) * 0.05, 2)


def _overlap(a: tuple, b: tuple) -> tuple[float, float]:
    return min(a[2], b[2]) - max(a[0], b[0]), min(a[3], b[3]) - max(a[1], b[1])


def _trim_overlaps(spaces: list[dict], rounds: int = 20) -> None:
    """Boxes often swallow an adjoining closet or bath. Cut the larger box back to the smaller one's edge, along
    the axis where they overlap least; never cut a box to under half its size."""
    skip: set[tuple[int, int]] = set()
    for _ in range(rounds):
        worst = None
        for i, a in enumerate(spaces):
            for b in spaces[i + 1:]:
                if (id(a), id(b)) in skip:
                    continue
                ox, oy = _overlap(a['px'], b['px'])
                if ox > 2 and oy > 2 and (worst is None or ox * oy > worst[0]):
                    worst = (ox * oy, a, b, ox, oy)
        if worst is None:
            return
        _, a, b, ox, oy = worst
        area = lambda s: (s['px'][2] - s['px'][0]) * (s['px'][3] - s['px'][1])  # noqa: E731
        big, small = (a, b) if area(a) >= area(b) else (b, a)
        x0, y0, x1, y1 = big['px']
        sx0, sy0, sx1, sy1 = small['px']
        if oy <= ox:
            cut = (x0, y0, x1, sy0) if (sy0 + sy1) / 2 > (y0 + y1) / 2 else (x0, sy1, x1, y1)
            ok = cut[3] - cut[1] >= (y1 - y0) / 2
        else:
            cut = (x0, y0, sx0, y1) if (sx0 + sx1) / 2 > (x0 + x1) / 2 else (sx1, y0, x1, y1)
            ok = cut[2] - cut[0] >= (x1 - x0) / 2
        if ok:
            big['px'] = cut
        else:
            skip.add((id(a), id(b)))


def build_plan(reads: list[dict], width_px: int, height_px: int, members: list[str],
               plan_width_m: float | None = None) -> dict:
    """Plan dict (rooms in metres, owners assigned) from Gemini reads. Raises PlanError when it can't be scaled."""
    spaces = []
    for r in reads:
        box = r.get('box_2d') or []
        if len(box) != 4 or not all(isinstance(v, (int, float)) for v in box):
            continue
        y0, x0, y1, x1 = (max(0.0, min(1000.0, float(v))) for v in box)
        x0, x1 = sorted((x0 / 1000 * width_px, x1 / 1000 * width_px))
        y0, y1 = sorted((y0 / 1000 * height_px, y1 / 1000 * height_px))
        if x1 - x0 < 4 or y1 - y0 < 4:
            continue
        kind = kind_from_label(r.get('label'), r.get('kind') if r.get('kind') in KINDS else 'other')
        w_px, h_px = x1 - x0, y1 - y0
        dims = size_from_read(r)
        if not dims and (area := area_from_read(r)):
            dims = dims_from_area(area, w_px, h_px)
        spaces.append({'label': clean_label(r.get('label') or kind.title()), 'kind': kind,
                       'dims': dims, 'dimension_text': r.get('dimension_text') or r.get('label'),
                       'px': (x0, y0, x1, y1)})
    if not spaces:
        raise PlanError('No rooms found on the floor plan')

    _trim_overlaps(spaces)
    min_x = min(s['px'][0] for s in spaces)
    min_y = min(s['px'][1] for s in spaces)
    max_x = max(s['px'][2] for s in spaces)
    ratios = []
    for s in spaces:
        if s['dims']:
            w, h = s['px'][2] - s['px'][0], s['px'][3] - s['px'][1]
            long_m, short_m = max(s['dims']), min(s['dims'])
            ratios += [long_m / max(w, h), short_m / min(w, h)]
        elif area := parse_area_m2(s.get('dimension_text')):
            w, h = s['px'][2] - s['px'][0], s['px'][3] - s['px'][1]
            if w * h > 0:
                ratios.append((area ** 0.5) / ((w * h) ** 0.5))
    if ratios:
        scale = statistics.median(ratios)
    elif plan_width_m:
        scale = plan_width_m / (max_x - min_x)
    else:
        raise PlanError('No room sizes are printed on the plan; send width_m (the overall plan width in metres)')

    warnings = []
    rooms = []
    for s in spaces:
        x0, y0, x1, y1 = s['px']
        room = {'name': s['label'], 'kind': s['kind'], 'x_m': _r((x0 - min_x) * scale), 'z_m': _r((y0 - min_y) * scale),
                'width_m': max(0.3, _r((x1 - x0) * scale)), 'depth_m': max(0.3, _r((y1 - y0) * scale))}
        if s['dims']:
            long_m, short_m = max(s['dims']), min(s['dims'])
            interior = (long_m, short_m) if room['width_m'] >= room['depth_m'] else (short_m, long_m)
            room['interior_m'] = {'width_m': _r(interior[0]), 'depth_m': _r(interior[1])}
            off = max(abs(interior[0] - room['width_m']) / interior[0], abs(interior[1] - room['depth_m']) / interior[1])
            if off > 0.2:
                warnings.append(f"{s['label']}: drawn size differs from the printed {s['dimension_text']} by {off:.0%}")
        if s['kind'] in ('living', 'kitchen', 'dining'):
            room['shared'] = True
        rooms.append(room)

    rooms.sort(key=lambda r: (round(r['z_m'] / 0.5), r['x_m']))
    counts: dict[str, int] = {}
    owners = iter(members)
    living_taken = False
    for room in rooms:
        counts[room['kind']] = counts.get(room['kind'], 0) + 1
        room['id'] = f"{room['kind']}-{counts[room['kind']]}"
        if room['kind'] == 'bedroom':
            size = room.get('interior_m') or room
            if min(size['width_m'], size['depth_m']) < MIN_BEDROOM_M:
                warnings.append(f"{room['name']} is too small to furnish ({size['width_m']} x {size['depth_m']} m)")
                continue
            owner = next(owners, None)
            if owner:
                room.update(id=f'bed-{owner}', owner_id=owner, household_id=f'demo-bed-{owner}')
            else:
                warnings.append(f"{room['name']} has no roommate left to own it")
        elif room['kind'] == 'living' and not living_taken:
            living_taken = True
            room.update(id='living', household_id='demo')
    if not living_taken:
        warnings.append('No living room found; the live demo room is not on this plan')

    for i, a in enumerate(rooms):
        for b in rooms[i + 1:]:
            ox = min(a['x_m'] + a['width_m'], b['x_m'] + b['width_m']) - max(a['x_m'], b['x_m'])
            oz = min(a['z_m'] + a['depth_m'], b['z_m'] + b['depth_m']) - max(a['z_m'], b['z_m'])
            if ox > 0.15 and oz > 0.15:
                warnings.append(f"{a['name']} and {b['name']} overlap by {ox:.2f} x {oz:.2f} m")

    width_m = _r(max(r['x_m'] + r['width_m'] for r in rooms))
    depth_m = _r(max(r['z_m'] + r['depth_m'] for r in rooms))
    return {'width_m': width_m, 'depth_m': depth_m, 'rooms': rooms, 'warnings': warnings,
            'scale_m_per_px': round(scale, 5),
            'image_frame_m': {'x_m': round(-min_x * scale, 3), 'z_m': round(-min_y * scale, 3),
                              'width_m': round(width_px * scale, 3), 'depth_m': round(height_px * scale, 3)}}
