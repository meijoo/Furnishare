"""asset_key / ensure_asset behaviour that needs no Blender."""
import copy
import subprocess
import sys
from pathlib import Path

from blender_mcp import assets, specs, worker_client
from pngutil import swatch

PRODUCT = {
    "id": "ikea-kivik-3seat-tibbleby-beige-gray", "variant": "Tibbleby beige/gray", "category": "sofa",
    "title": "KIVIK Sofa", "price_cents": 59900,
    "dimensions_m": {"width": 2.28, "depth": 0.95, "height": 0.83},
    "style": {"color_hex": "#C9BFAE", "material": "fabric", "tags": ["light", "neutral"]},
}


def test_asset_key_is_stable_and_hex():
    k = assets.asset_key(PRODUCT)
    assert k == assets.asset_key(copy.deepcopy(PRODUCT))
    assert len(k) == 24 and all(c in "0123456789abcdef" for c in k)


def test_asset_key_pinned_value():
    # Pins the hash recipe; changing it invalidates every cached asset, so bump TEMPLATE_VERSION instead.
    assert assets.asset_key(PRODUCT, template_version="pinned") == assets.asset_key(
        dict(PRODUCT, title="other", price_cents=1), template_version="pinned")
    import hashlib
    import json
    blob = json.dumps({"id": PRODUCT["id"], "variant": PRODUCT["variant"], "category": "sofa",
                       "dimensions_m": {"width": "2.2800", "depth": "0.9500", "height": "0.8300"},
                       "color_hex": "C9BFAE", "material": "fabric", "template_version": "pinned"},
                      sort_keys=True, separators=(",", ":"))
    assert assets.asset_key(PRODUCT, template_version="pinned") == hashlib.sha256(blob.encode()).hexdigest()[:24]


def test_asset_key_pinned_value_with_form():
    import hashlib
    import json
    product = dict(PRODUCT, style=dict(PRODUCT["style"], form={"Leg_Style": "Metal", "arm_style": "rolled",
                                                               "seat_cushions": "2", "bogus": 1}))
    blob = json.dumps({"id": PRODUCT["id"], "variant": PRODUCT["variant"], "category": "sofa",
                       "dimensions_m": {"width": "2.2800", "depth": "0.9500", "height": "0.8300"},
                       "color_hex": "C9BFAE", "material": "fabric", "template_version": "pinned",
                       "form": {"arm_style": "rolled", "seat_cushions": 2}},
                      sort_keys=True, separators=(",", ":"))
    # "Leg_Style" is not a schema key (keys are case-sensitive) and "bogus" is junk: both ignored.
    assert assets.asset_key(product, template_version="pinned") == hashlib.sha256(blob.encode()).hexdigest()[:24]


def test_asset_key_form_and_surface():
    def key(form):
        return assets.asset_key(dict(PRODUCT, style=dict(PRODUCT["style"], form=form)))
    base = assets.asset_key(PRODUCT)
    assert key({}) == key({"junk": True}) == key({"arm_style": "spaceship"}) == key(None) == base
    variants = [{"arm_style": "rolled"}, {"arm_style": "sloped"}, {"leg_style": "metal"}, {"chaise": "left"},
                {"surface": "velvet"}, {"surface": "boucle"}, {"surface": "velvet", "arm_style": "rolled"}]
    keys = {key(f) for f in variants}
    assert base not in keys and len(keys) == len(variants)
    assert key({"arm_style": "rolled", "surface": "velvet"}) == key({"surface": "Velvet", "arm_style": "ROLLED"})


def test_asset_key_ignores_irrelevant_fields_and_noise():
    base = assets.asset_key(PRODUCT)
    noisy = copy.deepcopy(PRODUCT)
    noisy.update(title="Renamed", price_cents=1, description="x", retrieved_at="now", asset_url="/assets/y.usdz")
    noisy["dimensions_m"] = {"height": 0.83000000001, "width": 2.28, "depth": 0.95}  # key order + float noise
    noisy["style"] = {"color_hex": "#c9bfae", "material": "Fabric", "tags": ["different"]}
    assert assets.asset_key(noisy) == base


def test_asset_key_changes_with_relevant_fields():
    base = assets.asset_key(PRODUCT)
    variants = [
        dict(PRODUCT, id="other"),
        dict(PRODUCT, variant="Hillared anthracite"),
        dict(PRODUCT, category="rug"),
        dict(PRODUCT, dimensions_m={"width": 2.281, "depth": 0.95, "height": 0.83}),
        dict(PRODUCT, style={"color_hex": "#C9BFAF", "material": "fabric"}),
        dict(PRODUCT, style={"color_hex": "#C9BFAE", "material": "leather"}),
    ]
    keys = {assets.asset_key(v) for v in variants}
    assert base not in keys and len(keys) == len(variants)
    assert assets.asset_key(PRODUCT, template_version="999") != base


def test_asset_key_changes_with_shape():
    table = {"id": "ikea-borgeby", "variant": "birch", "category": "coffee_table",
             "dimensions_m": {"width": 0.699, "depth": 0.699, "height": 0.419},
             "style": {"color_hex": "#C8A97E", "material": "wood"}}
    rect = assets.asset_key(table)
    round_ = assets.asset_key(dict(table, style=dict(table["style"], shape="round")))
    assert round_ != rect
    assert assets.asset_key(dict(table, style=dict(table["style"], shape="rect"))) == rect
    assert assets.asset_key(dict(table, style=dict(table["style"], tags=["round"]))) == round_
    assert assets.asset_key(dict(table, style=dict(table["style"], shape="Circular"))) == round_
    assert round_ != assets.asset_key(dict(table, style=dict(table["style"], shape="round")), template_version="old")


RUG = {"id": "ikea-jarnvag", "variant": "pink", "category": "rug",
       "dimensions_m": {"width": 2.311, "depth": 1.6, "height": 0.013},
       "style": {"color_hex": "#C8B39E", "material": "low pile"}}


def _with_texture(product, **tex):
    return dict(product, style=dict(product["style"], **tex))


def test_asset_key_texture_uses_image_bytes_not_path(tmp_path):
    a = swatch(tmp_path / "a.png", 16)
    b = swatch(tmp_path / "b.png", 24)
    moved = tmp_path / "sub" / "renamed.png"
    moved.parent.mkdir()
    moved.write_bytes(a.read_bytes())
    base = assets.asset_key(RUG)
    ka = assets.asset_key(_with_texture(RUG, texture_path=str(a)))
    assert ka != base
    assert assets.asset_key(_with_texture(RUG, texture_path=str(moved))) == ka  # same bytes, other path
    assert assets.asset_key(_with_texture(RUG, texture_path=str(b))) not in (ka, base)
    assert assets.asset_key(_with_texture(RUG, texture_path=str(a), texture_mode="print")) == ka  # rug default
    keys = {ka, assets.asset_key(_with_texture(RUG, texture_path=str(a), texture_mode="tile")),
            assets.asset_key(_with_texture(RUG, texture_path=str(a), texture_mode="tile", texture_tile_m=0.5)),
            assets.asset_key(_with_texture(RUG, texture_path=str(a), texture_mode="tile", texture_tile_m=0.6))}
    assert len(keys) == 4
    # tile_m is clamped before hashing, like the build does.
    assert assets.asset_key(_with_texture(RUG, texture_path=str(a), texture_tile_m=9)) == \
        assets.asset_key(_with_texture(RUG, texture_path=str(a), texture_tile_m=2.0))
    a.write_bytes(b.read_bytes())  # edited in place: new content -> new key (hash cache is keyed on mtime/size)
    assert assets.asset_key(_with_texture(RUG, texture_path=str(a))) == assets.asset_key(
        _with_texture(RUG, texture_path=str(b)))


def test_asset_key_unchanged_without_usable_texture(tmp_path):
    gif = tmp_path / "x.gif"
    gif.write_bytes(b"GIF89a")
    for product in (PRODUCT, RUG):
        base = assets.asset_key(product)
        for bad in (str(tmp_path / "missing.jpg"), "relative.png", str(gif), None, ""):
            assert assets.asset_key(_with_texture(product, texture_path=bad, texture_mode="tile")) == base, bad
        assert assets.asset_key(_with_texture(product, texture_mode="tile", texture_tile_m=1.0)) == base


def test_attach_requires_worker_features(tmp_path, monkeypatch):
    state = tmp_path / "worker.json"
    state.write_text('{"port": 1, "token": "t"}')
    pong = {"template_version": specs.TEMPLATE_VERSION}
    monkeypatch.setattr(worker_client.BlenderWorker, "request", lambda self, *a, **k: pong)
    assert worker_client.BlenderWorker.attach(state) is None  # pre-texture worker with the same template version
    pong["features"] = list(specs.WORKER_FEATURES)
    assert worker_client.BlenderWorker.attach(state) is not None
    pong["template_version"] = "old"
    assert worker_client.BlenderWorker.attach(state) is None


def test_asset_key_handles_missing_fields():
    assert len(assets.asset_key({"id": "x"})) == 24
    assert assets.asset_key({"id": "x", "dimensions_m": None}) == assets.asset_key({"id": "x"})


def test_ensure_asset_null_dimensions_returns_none(tmp_path, monkeypatch):
    monkeypatch.setenv("BLENDER_BIN", "/nonexistent")
    assert assets.ensure_asset(dict(PRODUCT, dimensions_m=None), tmp_path) is None
    assert assets.ensure_asset(dict(PRODUCT, dimension_kind="package"), tmp_path) is None
    assert assets.ensure_asset(dict(PRODUCT, category="spaceship"), tmp_path) is None


def test_ensure_asset_returns_cached_file_without_blender(tmp_path, monkeypatch):
    monkeypatch.setattr(assets.worker_client, "find_blender", lambda: None)
    cached = tmp_path / f"{assets.asset_key(PRODUCT)}.usdz"
    cached.write_bytes(b"PK fake usdz")
    assert assets.ensure_asset(PRODUCT, tmp_path) == cached


def test_ensure_asset_never_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(assets.worker_client, "find_blender", lambda: None)
    monkeypatch.setattr(assets.worker_client.BlenderWorker, "attach", classmethod(lambda cls, *a, **k: None))
    assert assets.ensure_asset(PRODUCT, tmp_path) is None              # no Blender
    assert assets.ensure_asset("not a product", tmp_path) is None       # type: ignore[arg-type]
    assert assets.ensure_asset(PRODUCT, Path("/dev/null/nope")) is None  # unwritable dir


def test_assets_module_does_not_import_bpy_or_mcp():
    code = ("import sys; sys.path.insert(0, 'integrations'); import blender_mcp.assets; "
            "assert 'bpy' not in sys.modules and 'mcp' not in sys.modules; print('ok')")
    repo = Path(__file__).resolve().parents[3]
    out = subprocess.run([sys.executable, "-c", code], cwd=repo, capture_output=True, text=True)
    assert out.stdout.strip() == "ok", out.stderr
    # Also importable the way the backend would (repo root on sys.path, namespace package `integrations`).
    code2 = "from integrations.blender_mcp.assets import asset_key, ensure_asset, TEMPLATE_VERSION; print('ok')"
    out2 = subprocess.run([sys.executable, "-c", code2], cwd=repo, capture_output=True, text=True)
    assert out2.stdout.strip() == "ok", out2.stderr
