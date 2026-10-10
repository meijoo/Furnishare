import math

import pytest

from blender_mcp import specs

from pngutil import swatch

DIMS = {"width": 2.0, "depth": 0.9, "height": 0.8}
RUG_DIMS = {"width": 2.3, "depth": 1.6, "height": 0.015}


def test_furniture_spec_defaults_and_normalization():
    s = specs.furniture_spec({"category": "sofa", "dimensions_m": DIMS, "color_hex": "c9bfae", "material": "Leather"})
    assert s == {"category": "sofa", "dimensions_m": DIMS, "color_hex": "#C9BFAE", "material": "leather",
                 "frame_finish": "wood", "shape": "rect"}
    t = specs.furniture_spec({"category": "tv", "dimensions_m": DIMS})
    assert t["material"] == "metal" and t["frame_finish"] == "metal" and t["color_hex"].startswith("#")


@pytest.mark.parametrize("dims", [
    {"width": 0.0, "depth": 1, "height": 1},
    {"width": 5.01, "depth": 1, "height": 1},
    {"width": -1, "depth": 1, "height": 1},
    {"width": math.nan, "depth": 1, "height": 1},
    {"width": math.inf, "depth": 1, "height": 1},
    {"width": True, "depth": 1, "height": 1},
    {"width": "1", "depth": 1, "height": 1},
    {"width": 1, "depth": 1},
    {"width": 1, "depth": 1, "height": 1, "length": 2},
])
def test_dimension_bounds(dims):
    with pytest.raises(specs.ValidationError):
        specs.furniture_spec({"category": "sofa", "dimensions_m": dims})


def test_dimension_limits_inclusive():
    s = specs.furniture_spec({"category": "rug", "dimensions_m": {"width": 5.0, "depth": 0.01, "height": 0.01}})
    assert s["dimensions_m"]["width"] == 5.0


@pytest.mark.parametrize("bad", [
    {"category": "lamp", "dimensions_m": DIMS},
    {"category": "sofa", "dimensions_m": DIMS, "material": "glass"},
    {"category": "sofa", "dimensions_m": DIMS, "color_hex": "#12345"},
    {"category": "sofa", "dimensions_m": DIMS, "color_hex": "red"},
    {"category": "sofa", "dimensions_m": DIMS, "frame_finish": "gold"},
    {"category": "sofa", "dimensions_m": DIMS, "python": "import os"},
    "sofa",
])
def test_furniture_spec_rejects(bad):
    with pytest.raises(specs.ValidationError):
        specs.furniture_spec(bad)


BEDROOM = {
    "bed": ({"width": 1.65, "depth": 2.12, "height": 1.1}, "fabric"),
    "nightstand": ({"width": 0.45, "depth": 0.4, "height": 0.55}, "wood"),
    "dresser": ({"width": 1.6, "depth": 0.48, "height": 0.78}, "wood"),
    "desk": ({"width": 1.4, "depth": 0.65, "height": 0.75}, "wood"),
}


@pytest.mark.parametrize("cat", sorted(BEDROOM))
def test_bedroom_categories_defaults(cat):
    dims, mat = BEDROOM[cat]
    s = specs.furniture_spec({"category": cat, "dimensions_m": dims})
    assert cat in specs.CATEGORIES
    assert s["material"] == mat == specs.DEFAULT_MATERIAL[cat]
    assert s["color_hex"] == specs.DEFAULT_COLOR[cat] and s["shape"] == "rect" and s["frame_finish"] == "wood"
    lo = {k: r[0] for k, r in specs.CATEGORY_DIM_RANGES_M[cat].items()}
    hi = {k: r[1] for k, r in specs.CATEGORY_DIM_RANGES_M[cat].items()}
    assert specs.furniture_spec({"category": cat, "dimensions_m": lo})["dimensions_m"] == lo  # inclusive
    assert specs.furniture_spec({"category": cat, "dimensions_m": hi})["dimensions_m"] == hi


@pytest.mark.parametrize("cat,dims", [
    ("bed", {"width": 2.3, "depth": 2.1, "height": 1.0}),
    ("bed", {"width": 1.6, "depth": 2.5, "height": 1.0}),
    ("bed", {"width": 1.6, "depth": 2.1, "height": 1.5}),
    ("bed", {"width": 1.6, "depth": 0.8, "height": 1.0}),
    ("nightstand", {"width": 0.45, "depth": 0.4, "height": 1.1}),
    ("nightstand", {"width": 0.1, "depth": 0.4, "height": 0.5}),
    ("dresser", {"width": 0.3, "depth": 0.45, "height": 0.8}),
    ("dresser", {"width": 1.6, "depth": 1.0, "height": 0.8}),
    ("desk", {"width": 1.4, "depth": 1.5, "height": 0.75}),
    ("desk", {"width": 1.4, "depth": 0.6, "height": 0.3}),
])
def test_bedroom_category_bounds(cat, dims):
    with pytest.raises(specs.ValidationError, match=cat):
        specs.furniture_spec({"category": cat, "dimensions_m": dims})


def test_shape_validation():
    round_dims = {"width": 0.7, "depth": 0.7, "height": 0.42}
    for cat in ("coffee_table", "nightstand", "rug"):
        assert specs.furniture_spec({"category": cat, "dimensions_m": round_dims, "shape": "round"})["shape"] == "round"
    assert specs.furniture_spec({"category": "coffee_table", "dimensions_m": round_dims, "shape": "Circular"})["shape"] == "round"
    assert specs.furniture_spec({"category": "coffee_table", "dimensions_m": round_dims, "shape": "rect"})["shape"] == "rect"
    near = {"width": 0.7, "depth": 0.704, "height": 0.42}  # within ROUND_TOLERANCE_M
    assert specs.furniture_spec({"category": "coffee_table", "dimensions_m": near, "shape": "round"})["shape"] == "round"


@pytest.mark.parametrize("bad", [
    {"category": "coffee_table", "dimensions_m": {"width": 1.0, "depth": 0.55, "height": 0.42}, "shape": "round"},
    {"category": "dresser", "dimensions_m": {"width": 0.8, "depth": 0.8, "height": 0.8}, "shape": "round"},
    {"category": "bed", "dimensions_m": {"width": 2.0, "depth": 2.0, "height": 1.0}, "shape": "round"},
    {"category": "coffee_table", "dimensions_m": {"width": 0.7, "depth": 0.7, "height": 0.4}, "shape": "oval"},
    {"category": "coffee_table", "dimensions_m": {"width": 0.7, "depth": 0.7, "height": 0.4}, "shape": 1},
])
def test_shape_rejects(bad):
    with pytest.raises(specs.ValidationError, match="shape"):
        specs.furniture_spec(bad)


def test_spec_from_product_bedroom_and_shape():
    def product(cat, dims, **style):
        return {"id": f"x-{cat}", "category": cat, "dimensions_m": dims, "style": style}
    for cat, (dims, mat) in BEDROOM.items():
        s = specs.spec_from_product(product(cat, dims, color_hex="#808080"))
        assert s["category"] == cat and s["material"] == mat and s["color_hex"] == "#808080" and s["shape"] == "rect"
    round_dims = {"width": 0.699, "depth": 0.699, "height": 0.419}
    assert specs.spec_from_product(product("coffee_table", round_dims, shape="round"))["shape"] == "round"
    assert specs.spec_from_product(product("coffee_table", round_dims, tags=["birch", "Round"]))["shape"] == "round"
    assert specs.spec_from_product(product("coffee_table", round_dims, shape="rect", tags=["round"]))["shape"] == "rect"
    assert specs.spec_from_product(product("nightstand", {"width": 0.4, "depth": 0.4, "height": 0.5},
                                           shape="round"))["shape"] == "round"
    # Round requests the template cannot honor still build to scale as rect.
    assert specs.spec_from_product(product("coffee_table", {"width": 1.0, "depth": 0.5, "height": 0.4},
                                           shape="round"))["shape"] == "rect"
    assert specs.spec_from_product(product("dresser", {"width": 0.8, "depth": 0.8, "height": 0.8},
                                           shape="round"))["shape"] == "rect"
    assert specs.spec_from_product(product("bed", {"width": 3.0, "depth": 2.1, "height": 1.0}, shape="round")) is None
    bed = BEDROOM["bed"][0]
    assert specs.spec_from_product(product("bed", bed, tags=["upholstered"]))["frame_finish"] == "upholstered"
    assert specs.spec_from_product(product("desk", BEDROOM["desk"][0], tags=["metal"]))["frame_finish"] == "metal"


def test_room_spec_accepts_api_room_object():
    room = specs.room_spec({"width_m": 4.5, "depth_m": 4.0, "height_m": 2.5,
                            "openings": [{"kind": "door", "wall": "front", "offset_m": 1.0, "width_m": 0.9}],
                            "clearances": [{"label": "door swing", "x_m": 1.0, "z_m": 1.6, "width_m": 0.9, "depth_m": 0.9}],
                            "inspiration_image_url": "/uploads/x.jpg"})
    door = room["openings"][0]
    assert door["height_m"] == 2.05 and door["sill_m"] == 0.0
    assert room["walls"] == ["back", "front", "left", "right"]


@pytest.mark.parametrize("opening", [
    {"kind": "door", "wall": "front", "offset_m": 2.0, "width_m": 0.9},      # sticks out of the wall
    {"kind": "door", "wall": "ceiling", "offset_m": 0.0, "width_m": 0.9},
    {"kind": "window", "wall": "left", "offset_m": 0.0, "width_m": 1.0, "sill_m": 2.0, "height_m": 1.0},
    {"kind": "door", "wall": "back", "offset_m": 0.0, "width_m": 0.9, "sill_m": 0.3},
])
def test_room_spec_rejects_bad_openings(opening):
    with pytest.raises(specs.ValidationError):
        specs.room_spec({"width_m": 4.5, "depth_m": 4.0, "height_m": 2.5, "openings": [opening]})


def test_room_spec_rejects_overlapping_openings():
    with pytest.raises(specs.ValidationError):
        specs.room_spec({"width_m": 4.5, "depth_m": 4.0, "height_m": 2.5, "openings": [
            {"kind": "door", "wall": "front", "offset_m": 0.0, "width_m": 0.9},
            {"kind": "window", "wall": "front", "offset_m": 0.5, "width_m": 0.9}]})


@pytest.mark.parametrize("room", [
    {"width_m": 0.5, "depth_m": 4, "height_m": 2.5},
    {"width_m": 4, "depth_m": 4, "height_m": 9},
    {"width_m": 4, "depth_m": 4, "height_m": 2.5, "wall_thickness_m": 2},
])
def test_room_spec_bounds(room):
    with pytest.raises(specs.ValidationError):
        specs.room_spec(room)


def test_filenames_and_ids():
    assert specs.filename("abc_1.usdz", (".usdz",)) == "abc_1.usdz"
    for bad in ("../x.usdz", "a/b.usdz", ".hidden.usdz", "x.py", ""):
        with pytest.raises(specs.ValidationError):
            specs.filename(bad, (".usdz",))
    with pytest.raises(specs.ValidationError):
        specs.object_id("a b")
    with pytest.raises(specs.ValidationError):
        specs.position([0, 0])
    with pytest.raises(specs.ValidationError):
        specs.rotation(100.0)


@pytest.fixture
def png(tmp_path):
    return swatch(tmp_path / "swatch.png", 16)


def test_texture_spec_defaults_per_category(png):
    rug = specs.furniture_spec({"category": "rug", "dimensions_m": RUG_DIMS, "texture": {"path": str(png)}})
    assert rug["texture"] == {"path": str(png), "mode": "print", "tile_m": specs.DEFAULT_TEXTURE_TILE_M}
    for cat in ("sofa", "coffee_table", "tv", "bed", "nightstand", "dresser", "desk"):
        dims = BEDROOM[cat][0] if cat in BEDROOM else DIMS
        s = specs.furniture_spec({"category": cat, "dimensions_m": dims, "texture": {"path": str(png)}})
        assert s["texture"]["mode"] == "tile", cat
    s = specs.furniture_spec({"category": "rug", "dimensions_m": RUG_DIMS,
                              "texture": {"path": str(png), "mode": "tile", "tile_m": 0.5}})
    assert s["texture"] == {"path": str(png), "mode": "tile", "tile_m": 0.5}
    assert "texture" not in specs.furniture_spec({"category": "rug", "dimensions_m": RUG_DIMS})
    assert "texture" not in specs.furniture_spec({"category": "rug", "dimensions_m": RUG_DIMS, "texture": None})


@pytest.mark.parametrize("tile,want", [(0.01, 0.05), (0.05, 0.05), (0.3, 0.3), (2.0, 2.0), (9.0, 2.0), (-1, 0.05)])
def test_texture_tile_is_clamped(png, tile, want):
    s = specs.furniture_spec({"category": "sofa", "dimensions_m": DIMS, "texture": {"path": str(png), "tile_m": tile}})
    assert s["texture"]["tile_m"] == want


def test_texture_extensions_accepted(tmp_path, png):
    data = png.read_bytes()
    for name, blob in (("a.PNG", data), ("b.jpg", b"\xff\xd8\xff\xe0" + b"\0" * 32), ("c.jpeg", b"\xff\xd8\xff\xdb" + b"\0" * 32),
                       ("d.webp", b"RIFF\x10\0\0\0WEBPVP8 " + b"\0" * 32)):
        p = tmp_path / name
        p.write_bytes(blob)
        assert specs.texture({"path": str(p)}, "sofa")["path"] == str(p)


@pytest.mark.parametrize("make,match", [
    (lambda d, png: "relative/swatch.png", "absolute"),
    (lambda d, png: str(d / "missing.png"), "does not exist"),
    (lambda d, png: str(d), "end with"),
    (lambda d, png: (d / "x.gif").write_bytes(b"GIF89a") and str(d / "x.gif"), "end with"),
    (lambda d, png: (d / "x.png").write_bytes(b"not a png at all") and str(d / "x.png"), "not a valid png"),
    (lambda d, png: (d / "x.webp").write_bytes(b"RIFF\0\0\0\0WAVEfmt ") and str(d / "x.webp"), "not a valid webp"),
    (lambda d, png: (d / "e.png").write_bytes(b"") or str(d / "e.png"), "non-empty"),
    (lambda d, png: 42, "absolute"),
])
def test_texture_path_rejects(tmp_path, png, make, match):
    with pytest.raises(specs.ValidationError, match=match):
        specs.furniture_spec({"category": "rug", "dimensions_m": RUG_DIMS, "texture": {"path": make(tmp_path, png)}})


def test_texture_rejects_big_files_bad_modes_and_keys(tmp_path, png):
    big = tmp_path / "big.png"
    with open(big, "wb") as fh:
        fh.write(png.read_bytes())
        fh.truncate(specs.TEXTURE_MAX_BYTES)  # sparse: exactly the limit is already too big
    for tex, match in (({"path": str(big)}, "smaller than"), ({"path": str(png), "mode": "stretch"}, "mode"),
                       ({"path": str(png), "tile_m": "big"}, "tile_m"), ({"path": str(png), "tile_m": math.nan}, "tile_m"),
                       ({"path": str(png), "url": "http://x"}, "unknown keys"), ({"mode": "print"}, "missing"),
                       ("/abs/path.png", "object")):
        with pytest.raises(specs.ValidationError, match=match):
            specs.furniture_spec({"category": "rug", "dimensions_m": RUG_DIMS, "texture": tex})


def test_spec_from_product_texture(tmp_path, png):
    def product(cat="rug", dims=RUG_DIMS, **style):
        return {"id": "x", "category": cat, "dimensions_m": dims, "style": dict({"color_hex": "#808080"}, **style)}
    s = specs.spec_from_product(product(texture_path=str(png)))
    assert s["texture"] == {"path": str(png), "mode": "print", "tile_m": 0.3}
    s = specs.spec_from_product(product("sofa", DIMS, texture_path=str(png), texture_tile_m=0.01))
    assert s["texture"] == {"path": str(png), "mode": "tile", "tile_m": 0.05}
    s = specs.spec_from_product(product(texture_path=str(png), texture_mode="tile", texture_tile_m=0.6))
    assert s["texture"] == {"path": str(png), "mode": "tile", "tile_m": 0.6}
    # Bad mode / tile size fall back to defaults; unusable files are ignored silently (still buildable).
    s = specs.spec_from_product(product(texture_path=str(png), texture_mode="stretch", texture_tile_m="x"))
    assert s["texture"] == {"path": str(png), "mode": "print", "tile_m": 0.3}
    gif = tmp_path / "x.gif"
    gif.write_bytes(b"GIF89a")
    for bad in (str(tmp_path / "missing.png"), "relative.png", str(gif), 7, ""):
        s = specs.spec_from_product(product(texture_path=bad))
        assert s is not None and "texture" not in s, bad
    assert "texture" not in specs.spec_from_product(product())
    round_rug = specs.spec_from_product(product(dims={"width": 1.6, "depth": 1.6, "height": 0.01}, shape="round",
                                                texture_path=str(png)))
    assert round_rug["shape"] == "round" and round_rug["texture"]["mode"] == "print"
    fallback = specs.spec_from_product(product("coffee_table", {"width": 1.0, "depth": 0.5, "height": 0.4},
                                               shape="round", texture_path=str(png)))
    assert fallback["shape"] == "rect" and fallback["texture"]["mode"] == "tile"


CAT_DIMS = {"sofa": DIMS, "coffee_table": {"width": 1.0, "depth": 0.55, "height": 0.42},
            "tv": {"width": 1.2, "depth": 0.06, "height": 0.75}, "rug": RUG_DIMS, **{c: d for c, (d, _) in BEDROOM.items()}}


def _good_values(allowed):
    if allowed == specs.HEX:
        return ["#A1B2C3"]
    if allowed is bool:
        return [True, False]
    if isinstance(allowed[0], int):
        return list(range(allowed[0], allowed[1] + 1))
    return list(allowed)


def test_form_schema_shape():
    assert set(specs.FORM_SCHEMA) == set(specs.CATEGORIES)
    for cat, keys in specs.FORM_SCHEMA.items():
        assert keys["surface"] == specs.SURFACES
        for k, allowed in keys.items():
            assert allowed is bool or allowed == specs.HEX or (isinstance(allowed, tuple) and allowed), (cat, k)
            if isinstance(allowed, tuple) and isinstance(allowed[0], int):
                assert len(allowed) == 2 and allowed[0] <= allowed[1], (cat, k)


@pytest.mark.parametrize("cat", sorted(specs.FORM_SCHEMA))
def test_form_accepts_every_schema_value(cat):
    for key, allowed in specs.FORM_SCHEMA[cat].items():
        for v in _good_values(allowed):
            s = specs.furniture_spec({"category": cat, "dimensions_m": CAT_DIMS[cat], "form": {key: v}})
            assert s["form"] == {key: v}, (cat, key, v)
    assert "form" not in specs.furniture_spec({"category": cat, "dimensions_m": CAT_DIMS[cat]})
    assert "form" not in specs.furniture_spec({"category": cat, "dimensions_m": CAT_DIMS[cat], "form": {}})


def test_form_normalizes_enum_spelling_and_sorts_keys():
    s = specs.furniture_spec({"category": "sofa", "dimensions_m": DIMS,
                              "form": {"leg_style": "Metal", "arm_style": " ROLLED ", "chaise": None}})
    assert s["form"] == {"arm_style": "rolled", "leg_style": "metal"} and list(s["form"]) == ["arm_style", "leg_style"]
    d = specs.furniture_spec({"category": "desk", "dimensions_m": BEDROOM["desk"][0], "form": {"leg_style": "metal-frame"}})
    assert d["form"] == {"leg_style": "metal_frame"}


@pytest.mark.parametrize("cat,form,match", [
    ("sofa", {"arm_style": "spaceship"}, "arm_style"),
    ("sofa", {"seat_cushions": 5}, "seat_cushions"),
    ("sofa", {"seat_cushions": 0}, "seat_cushions"),
    ("sofa", {"seat_cushions": 2.5}, "seat_cushions"),
    ("sofa", {"seat_cushions": "2"}, "seat_cushions"),        # strict: no string coercion for explicit forms
    ("sofa", {"seat_cushions": True}, "seat_cushions"),
    ("sofa", {"skirt": "yes"}, "skirt"),
    ("sofa", {"skirt": 1}, "skirt"),
    ("sofa", {"headboard": "panel"}, "unknown keys"),          # a bed key on a sofa
    ("sofa", {"surface": "granite"}, "surface"),
    ("sofa", {"surface": "quilted"}, "surface"),               # internal surface, not public
    ("bed", {"headboard": ["tufted"]}, "headboard"),
    ("dresser", {"rows": 1}, "rows"),
    ("dresser", {"columns": 4}, "columns"),
    ("rug", {"pile": "deep"}, "pile"),
    ("tv", {"stand": "wall"}, "stand"),
    ("desk", {"pedestal": "both"}, "pedestal"),
    ("coffee_table", {"leg_style": 3}, "leg_style"),
    ("nightstand", {"drawers": -1}, "drawers"),
    ("sofa", "rolled", "object"),
    ("sofa", ["arm_style"], "object"),
])
def test_form_rejects_bad_values(cat, form, match):
    with pytest.raises(specs.ValidationError, match=match):
        specs.furniture_spec({"category": cat, "dimensions_m": CAT_DIMS[cat], "form": form})


def test_spec_from_product_form_lenient():
    def product(cat="sofa", **style):
        return {"id": "x", "category": cat, "dimensions_m": CAT_DIMS[cat], "style": style}
    s = specs.spec_from_product(product(form={"arm_style": "Rolled", "seat_cushions": "2", "skirt": "yes",
                                              "back_style": "spaceship", "leg_style": 7, "headboard": "tufted",
                                              "chaise": None, "bogus": {"x": 1}, 3: "x"}))
    assert s["form"] == {"arm_style": "rolled", "seat_cushions": 2, "skirt": True}
    for junk in ("rolled", ["x"], 5, None, {}, {"nope": 1}):
        s = specs.spec_from_product(product(form=junk))
        assert s is not None and "form" not in s, junk
    b = specs.spec_from_product(product("bed", form={"headboard": "wingback", "footboard": "false"}))
    assert b["form"] == {"footboard": False, "headboard": "wingback"}
    # The validated spec round-trips through the strict validator unchanged.
    assert specs.furniture_spec(b) == b


@pytest.mark.parametrize("cat,material,want", [
    ("sofa", "Velvet, solid oak legs", {"surface": "velvet"}),
    ("sofa", "faux leather", {"surface": "faux_leather"}),
    ("sofa", "100% linen blend", {"surface": "linen"}),
    ("sofa", "boucle", {"surface": "boucle"}),
    ("bed", "upholstered chenille, pine frame", {"surface": "chenille"}),
    ("coffee_table", "walnut veneer, steel legs", {"surface": "walnut"}),
    ("coffee_table", "tempered glass top", {"surface": "glass"}),
    ("coffee_table", "Marble", {"surface": "marble"}),
    ("dresser", "white oak", {"surface": "white_oak"}),
    ("dresser", "Lacquered MDF", {"surface": "lacquer"}),
    ("nightstand", "velvet", {}),                     # soft surfaces are not offered for case goods
    ("rug", "wool, high pile", {"surface": "wool", "pile": "high"}),
    ("rug", "jute flatweave", {"surface": "weave", "pile": "flat"}),
    ("rug", "polyester shag", {"surface": "weave", "pile": "high"}),
    ("tv", "metal", {}),
])
def test_spec_from_product_material_hints(cat, material, want):
    p = {"id": "x", "category": cat, "dimensions_m": CAT_DIMS[cat], "style": {"material": material}}
    s = specs.spec_from_product(p)
    assert (s.get("form") or {}) == want, s.get("form")
    explicit = specs.spec_from_product(dict(p, style={"material": material, "form": {"surface": "pine"}}))
    if cat not in ("sofa", "bed", "rug"):
        assert explicit["form"]["surface"] == "pine", "an explicit form.surface wins over material hints"


def test_material_surface_defaults():
    assert specs.material_surface("fabric", "#808080") == "weave"
    assert specs.material_surface("wood", "#808080") == "oak"
    assert specs.material_surface("leather", "#808080") == "leather"
    assert specs.material_surface("wool", "#808080") == "wool"
    assert specs.material_surface("metal", "#202020") == "black_metal"
    assert specs.material_surface("metal", "#D0D0D0") == "brushed_metal"
    s = specs.furniture_spec({"category": "sofa", "dimensions_m": DIMS, "material": "leather"})
    assert specs.main_surface(s) == "leather"
    assert specs.main_surface(dict(s, form={"surface": "velvet"})) == "velvet"


def test_spec_from_product():
    p = {"id": "x", "category": "sofa", "dimensions_m": {"width": 2.28, "depth": 0.95, "height": 0.83},
         "style": {"color_hex": "#C9BFAE", "material": "fabric", "tags": ["light"]}}
    assert specs.spec_from_product(p)["dimensions_m"]["width"] == 2.28
    assert specs.spec_from_product(dict(p, dimensions_m=None)) is None
    assert specs.spec_from_product(dict(p, dimension_kind="package")) is None
    assert specs.spec_from_product(dict(p, category="lamp")) is None
    assert specs.spec_from_product(dict(p, dimensions_m={"width": 9, "depth": 1, "height": 1})) is None
    assert specs.spec_from_product(dict(p, style={"material": "velvet"}))["material"] == "fabric"
    legacy = {"id": "sofa-blue", "name": "Cloud sofa", "category": "sofa", "price_cents": 60000,
              "dimensions_m": {"width": 2.1, "height": 0.85, "depth": 0.9}}
    assert specs.spec_from_product(legacy)["color_hex"] == specs.DEFAULT_COLOR["sofa"]


def test_form_hex_keys_normalize_and_reject():
    base = {"category": "desk", "dimensions_m": {"width": 1.2, "depth": 0.6, "height": 0.75},
            "material": "wood", "color_hex": "#5A3E2A"}
    spec = specs.furniture_spec(dict(base, form={"primary_hex": " #b8865a", "accent_surface": "black_metal",
                                                 "accent_hex": "#222222"}))
    assert spec["form"] == {"primary_hex": "#B8865A", "accent_surface": "black_metal", "accent_hex": "#222222"}
    assert specs.primary_hex(spec) == "#B8865A"
    for bad in ("B8865A", "#B8865", "#GGGGGG", 123):
        with pytest.raises(specs.ValidationError):
            specs.furniture_spec(dict(base, form={"accent_hex": bad}))
    with pytest.raises(specs.ValidationError):
        specs.furniture_spec(dict(base, form={"accent_surface": "chrome"}))


def test_product_form_drops_bad_hex():
    form = specs.product_form({"category": "desk", "style": {"form": {
        "primary_hex": "pine", "accent_hex": "#22222", "accent_surface": "black_metal"}}})
    assert form == {"accent_surface": "black_metal"}
