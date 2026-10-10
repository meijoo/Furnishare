"""Footprint validation in canonical scene space (Y-up, floor at y=0, room centered at the origin).

Objects are oriented rectangles in the X/Z plane: width along local X, depth along local Z,
rotated by rotation_y_rad about +Y. Pure Python so it can be unit tested without Blender.
"""
from __future__ import annotations

import math

TOLERANCE_M = 0.001
FLAT_CATEGORIES = {"rug"}

Point = tuple[float, float]


def footprint(obj: dict) -> list[Point]:
    """Corners (x, z) of an object's footprint, counter-clockwise when viewed from above."""
    x0, _, z0 = obj["position_m"]
    hw, hd = obj["dimensions_m"]["width"] / 2, obj["dimensions_m"]["depth"] / 2
    c, s = math.cos(obj.get("rotation_y_rad", 0.0)), math.sin(obj.get("rotation_y_rad", 0.0))
    # Rotation about +Y: (x, z) -> (x cos + z sin, -x sin + z cos)
    return [(x0 + lx * c + lz * s, z0 - lx * s + lz * c) for lx, lz in ((-hw, -hd), (hw, -hd), (hw, hd), (-hw, hd))]


def rect(cx: float, cz: float, width: float, depth: float) -> list[Point]:
    return footprint({"position_m": [cx, 0.0, cz], "dimensions_m": {"width": width, "depth": depth}})


def _axes(poly: list[Point]) -> list[Point]:
    out = []
    for (ax, az), (bx, bz) in zip(poly, poly[1:] + poly[:1]):
        ex, ez = bx - ax, bz - az
        n = math.hypot(ex, ez) or 1.0
        out.append((-ez / n, ex / n))
    return out


def penetration(a: list[Point], b: list[Point]) -> float:
    """Separating-axis test for convex polygons; returns overlap depth in meters (0 if disjoint)."""
    depth = math.inf
    for ax, az in _axes(a) + _axes(b):
        pa = [x * ax + z * az for x, z in a]
        pb = [x * ax + z * az for x, z in b]
        overlap = min(max(pa), max(pb)) - max(min(pa), min(pb))
        if overlap <= 0:
            return 0.0
        depth = min(depth, overlap)
    return depth


def door_swing_zones(room: dict) -> list[dict]:
    """Default clearance in front of each door (square of the door width) when none are given."""
    w, d = room["width_m"], room["depth_m"]
    zones = []
    for o in room["openings"]:
        if o["kind"] != "door":
            continue
        s = o["width_m"]
        cx, cz, zw, zd = {
            "back": (o["offset_m"], -d / 2 + s / 2, s, s),
            "front": (o["offset_m"], d / 2 - s / 2, s, s),
            "left": (-w / 2 + s / 2, o["offset_m"], s, s),
            "right": (w / 2 - s / 2, o["offset_m"], s, s),
        }[o["wall"]]
        zones.append({"label": f"{o['wall']} door swing", "x_m": cx, "z_m": cz, "width_m": zw, "depth_m": zd})
    return zones


def validate_scene(room: dict | None, objects: list[dict]) -> dict:
    """Returns {"ok", "issues": [{"severity", "code", "message", "objects"}]} in the API's validation shape."""
    issues: list[dict] = []

    def add(severity, code, message, ids):
        issues.append({"severity": severity, "code": code, "message": message, "objects": ids})

    polys = {o["object_id"]: footprint(o) for o in objects}

    if room is None:
        add("warning", "no_room", "No room has been created; only overlaps were checked.", [])
    else:
        hw, hd = room["width_m"] / 2, room["depth_m"] / 2
        for o in objects:
            oid = o["object_id"]
            xs = [p[0] for p in polys[oid]]
            zs = [p[1] for p in polys[oid]]
            out = max(min(xs) * -1 - hw, max(xs) - hw, min(zs) * -1 - hd, max(zs) - hd)
            if out > TOLERANCE_M:
                add("error", "outside_room", f"{oid} extends {out:.3f} m beyond the room walls.", [oid])
            if o["dimensions_m"]["height"] + o["position_m"][1] > room["height_m"] + TOLERANCE_M:
                add("error", "too_tall", f"{oid} is taller than the room ({room['height_m']} m).", [oid])
        zones = room.get("clearances") or door_swing_zones(room)
        for zone in zones:
            zpoly = rect(zone["x_m"], zone["z_m"], zone["width_m"], zone["depth_m"])
            for o in objects:
                if o["category"] in FLAT_CATEGORIES:
                    continue
                pen = penetration(polys[o["object_id"]], zpoly)
                if pen > TOLERANCE_M:
                    add("error", "clearance_blocked",
                        f"{o['object_id']} intrudes {pen:.3f} m into '{zone['label']}'.", [o["object_id"]])

    for o in objects:
        if abs(o["position_m"][1]) > TOLERANCE_M:
            add("warning", "not_on_floor", f"{o['object_id']} is not on the floor (y={o['position_m'][1]:.3f}).",
                [o["object_id"]])

    for i, a in enumerate(objects):
        for b in objects[i + 1:]:
            flat = (a["category"] in FLAT_CATEGORIES) + (b["category"] in FLAT_CATEGORIES)
            if flat == 1:
                continue  # furniture standing on a rug is expected
            pen = penetration(polys[a["object_id"]], polys[b["object_id"]])
            if pen > TOLERANCE_M:
                severity = "warning" if flat == 2 else "error"
                add(severity, "overlap", f"{a['object_id']} and {b['object_id']} overlap by {pen:.3f} m.",
                    [a["object_id"], b["object_id"]])

    return {"ok": not any(i["severity"] == "error" for i in issues), "issues": issues}
