import math

from blender_mcp import layout, specs

ROOM = specs.room_spec({"width_m": 4.5, "depth_m": 4.0, "height_m": 2.5,
                        "openings": [{"kind": "door", "wall": "front", "offset_m": 1.0, "width_m": 0.9}]})


def obj(oid, cat, pos, w, d, h=0.8, rot=0.0):
    return {"object_id": oid, "category": cat, "position_m": pos, "rotation_y_rad": rot,
            "dimensions_m": {"width": w, "depth": d, "height": h}}


def codes(result):
    return sorted(i["code"] for i in result["issues"])


def test_valid_layout():
    r = layout.validate_scene(ROOM, [obj("sofa", "sofa", [0, 0, -1.5], 2.28, 0.95),
                                     obj("rug", "rug", [0, 0, -0.8], 2.3, 1.6, 0.015),
                                     obj("table", "coffee_table", [0, 0, -0.5], 1.0, 0.55, 0.42)])
    assert r == {"ok": True, "issues": []}


def test_overlap_and_touching():
    a = obj("a", "sofa", [0, 0, 0], 2.0, 1.0)
    assert codes(layout.validate_scene(ROOM, [a, obj("b", "coffee_table", [1.4, 0, 0], 1.0, 0.5)])) == ["overlap"]
    assert layout.validate_scene(ROOM, [a, obj("b", "coffee_table", [1.498, 0, 0], 1.0, 0.5)])["ok"] is False
    assert layout.validate_scene(ROOM, [a, obj("b", "coffee_table", [1.5, 0, 0], 1.0, 0.5)])["ok"] is True
    assert layout.validate_scene(ROOM, [a, obj("b", "coffee_table", [1.4995, 0, 0], 1.0, 0.5)])["ok"] is True


def test_rotation_changes_footprint():
    assert codes(layout.validate_scene(ROOM, [obj("s", "sofa", [-1.2, 0, 0], 2.0, 0.9)])) == []
    against_wall = obj("s", "sofa", [-1.7, 0, 0], 2.0, 0.9)
    assert codes(layout.validate_scene(ROOM, [against_wall])) == ["outside_room"]
    turned = dict(against_wall, rotation_y_rad=math.pi / 2)
    assert codes(layout.validate_scene(ROOM, [turned])) == []


def test_rotated_corners():
    c = layout.footprint(obj("x", "sofa", [1, 0, 2], 2.0, 1.0, rot=math.pi / 2))
    xs, zs = sorted(p[0] for p in c), sorted(p[1] for p in c)
    assert math.isclose(xs[0], 0.5) and math.isclose(xs[-1], 1.5)
    assert math.isclose(zs[0], 1.0) and math.isclose(zs[-1], 3.0)


def test_rug_overlap_allowed_but_door_swing_enforced():
    r = layout.validate_scene(ROOM, [obj("rug", "rug", [1.0, 0, 1.4], 1.5, 1.0, 0.01),
                                     obj("chair", "sofa", [1.0, 0, 1.6], 0.8, 0.8)])
    assert codes(r) == ["clearance_blocked"]


def test_explicit_clearances_and_heights():
    room = dict(ROOM, clearances=[{"label": "walkway", "x_m": -1.5, "z_m": 0.0, "width_m": 1.0, "depth_m": 1.0}])
    r = layout.validate_scene(room, [obj("tv", "tv", [-1.5, 0, 0.3], 1.0, 0.2, 2.6)])
    assert codes(r) == ["clearance_blocked", "too_tall"]


def test_no_room_and_floating():
    r = layout.validate_scene(None, [obj("a", "sofa", [0, 0.2, 0], 1, 1)])
    assert r["ok"] is True and codes(r) == ["no_room", "not_on_floor"]
