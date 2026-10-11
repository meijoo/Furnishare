"""2D footprint checks in room space (meters, X width, Z depth, origin at floor center)."""
import math

FLOOR_LAYER = {'rug'}


def footprint(obj: dict) -> list[tuple[float, float]]:
    d = obj['dimensions_m']
    x, _, z = obj['position_m']
    hw, hd = d['width'] / 2, d['depth'] / 2
    c, s = math.cos(obj.get('rotation_y_rad', 0.0)), math.sin(obj.get('rotation_y_rad', 0.0))
    corners = [(-hw, -hd), (hw, -hd), (hw, hd), (-hw, hd)]
    # Rotation about +Y maps (x, z) -> (x cos + z sin, -x sin + z cos).
    return [(x + px * c + pz * s, z - px * s + pz * c) for px, pz in corners]


def rect(x: float, z: float, width: float, depth: float) -> list[tuple[float, float]]:
    hw, hd = width / 2, depth / 2
    return [(x - hw, z - hd), (x + hw, z - hd), (x + hw, z + hd), (x - hw, z + hd)]


def _axes(poly):
    for i in range(len(poly)):
        (x1, z1), (x2, z2) = poly[i], poly[(i + 1) % len(poly)]
        yield (z1 - z2, x2 - x1)


def overlaps(a, b, tolerance=1e-3) -> bool:
    for axis in list(_axes(a)) + list(_axes(b)):
        pa = [p[0] * axis[0] + p[1] * axis[1] for p in a]
        pb = [p[0] * axis[0] + p[1] * axis[1] for p in b]
        norm = math.hypot(*axis) or 1
        if (min(pa) - max(pb)) / norm >= -tolerance or (min(pb) - max(pa)) / norm >= -tolerance:
            return False
    return True


def validate_scene(room: dict, objects: list[dict]) -> dict:
    issues = []
    hw, hd = room['width_m'] / 2, room['depth_m'] / 2
    polys = {o['object_id']: footprint(o) for o in objects}
    for o in objects:
        if any(abs(x) > hw + 1e-3 or abs(z) > hd + 1e-3 for x, z in polys[o['object_id']]):
            issues.append({'kind': 'out_of_bounds', 'objects': [o['object_id']],
                           'message': f"{o['category'].replace('_', ' ')} extends past the room walls"})
    for i, a in enumerate(objects):
        for b in objects[i + 1:]:
            if a['category'] in FLOOR_LAYER or b['category'] in FLOOR_LAYER:
                continue
            if overlaps(polys[a['object_id']], polys[b['object_id']]):
                issues.append({'kind': 'overlap', 'objects': [a['object_id'], b['object_id']],
                               'message': f"{a['category'].replace('_', ' ')} overlaps {b['category'].replace('_', ' ')}"})
    for zone in room.get('clearances', []):
        zp = rect(zone['x_m'], zone['z_m'], zone['width_m'], zone['depth_m'])
        for o in objects:
            if o['category'] not in FLOOR_LAYER and overlaps(polys[o['object_id']], zp):
                issues.append({'kind': 'clearance', 'objects': [o['object_id']],
                               'message': f"{o['category'].replace('_', ' ')} blocks {zone.get('label', 'a clearance zone')}"})
    return {'ok': not issues, 'issues': issues}


def fits_room(dims: dict | None, room: dict, margin=0.05) -> bool:
    if not dims:
        return False
    w, d = dims['width'], dims['depth']
    rw, rd = room['width_m'] - margin, room['depth_m'] - margin
    return (w <= rw and d <= rd) or (d <= rw and w <= rd)


WALL_PIECES = {'sofa', 'tv', 'bed', 'nightstand', 'dresser', 'desk'}
# Rotations that turn a piece's front (+Z) to face into the room from the left (-X) or right (+X) wall.
FACE_FROM_LEFT_WALL, FACE_FROM_RIGHT_WALL = math.pi / 2, -math.pi / 2


def door_side(room: dict) -> float:
    """+1 if the room's door is on the right half (or right wall), -1 if on the left; +1 when unknown."""
    for o in room.get('openings', []):
        if o.get('kind') != 'door':
            continue
        if o.get('wall') == 'left':
            return -1.0
        if o.get('wall') == 'right':
            return 1.0
        return -1.0 if o.get('offset_m', 0.0) < 0 else 1.0
    return 1.0


def _bedroom_position(category: str, dims: dict, room: dict, others: list[dict]) -> tuple[list[float], float]:
    hw, hd = room['width_m'] / 2, room['depth_m'] / 2
    gap = 0.03
    away = -door_side(room)
    if category == 'bed':
        return [0.0, 0.0, -hd + dims['depth'] / 2 + gap], 0.0
    if category == 'nightstand':
        bed = next((o for o in others if o['category'] == 'bed'), None)
        bed_edge = bed['dimensions_m']['width'] / 2 if bed else 0.8
        return [away * (bed_edge + 0.05 + dims['width'] / 2), 0.0, -hd + dims['depth'] / 2 + gap], 0.0
    # Dresser on the wall away from the door, desk on the door-side wall; both face into the room.
    on_away_wall = category == 'dresser'
    side = away if on_away_wall else -away
    x = side * (hw - dims['depth'] / 2 - gap)
    rot = FACE_FROM_LEFT_WALL if side < 0 else FACE_FROM_RIGHT_WALL
    z = (hd - dims['width'] / 2 - 0.35) if on_away_wall else (-hd + dims['width'] / 2 + 0.6)
    return [x, 0.0, z], rot


def default_position(category: str, dims: dict, room: dict, others: list[dict]) -> tuple[list[float], float]:
    """Living room: sofa on the back wall, TV on the front wall facing it. Bedroom: bed headboard on the back wall."""
    if category in ('bed', 'nightstand', 'dresser', 'desk'):
        return _bedroom_position(category, dims, room, others)
    hd = room['depth_m'] / 2
    wall_gap = 0.08
    if category == 'sofa':
        return [0.0, 0.0, -hd + dims['depth'] / 2 + wall_gap], 0.0
    if category == 'tv':
        return [0.0, 0.0, hd - dims['depth'] / 2 - wall_gap], math.pi
    sofa = next((o for o in others if o['category'] == 'sofa'), None)
    sofa_front = (sofa['position_m'][2] + sofa['dimensions_m']['depth'] / 2) if sofa else -hd + 1.0
    if category == 'coffee_table':
        return [0.0, 0.0, sofa_front + 0.45 + dims['depth'] / 2], 0.0
    if category == 'chair':
        sofa_half = (sofa['dimensions_m']['width'] / 2) if sofa else 1.0
        return [sofa_half + 0.25 + dims['width'] / 2, 0.0, sofa_front - dims['depth'] / 2], -0.4
    if category == 'lamp':
        sofa_half = (sofa['dimensions_m']['width'] / 2) if sofa else 1.0
        return [sofa_half + 0.12 + dims['width'] / 2, 0.0, sofa_front - 0.15], 0.0
    if category == 'rug':
        return [0.0, 0.0, min(sofa_front - 0.25 + dims['depth'] / 2, hd - dims['depth'] / 2 - 0.05)], 0.0
    return [0.0, 0.0, 0.0], 0.0


def place_without_conflicts(obj: dict, room: dict, others: list[dict]) -> dict:
    """Nudge an object along X (then Z) until it passes validation against the others, if possible."""
    base = list(obj['position_m'])
    for dz in (0.0, 0.15, -0.15, 0.3, -0.3):
        for dx in (0.0, 0.25, -0.25, 0.5, -0.5, 0.75, -0.75, 1.0, -1.0):
            candidate = {**obj, 'position_m': [base[0] + dx, 0.0, base[2] + dz]}
            if validate_scene(room, others + [candidate])['ok']:
                return candidate
    return obj
