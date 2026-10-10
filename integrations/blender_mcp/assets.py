"""Backend-facing asset cache. Importable without Blender (no bpy, no mcp).

    from integrations.blender_mcp.assets import asset_key, ensure_asset
    path = ensure_asset(product, Path("backend/static/assets"))   # -> .../<asset_key>.usdz or None

ensure_asset never raises. It reuses a warm worker if one is published in .run/worker.json
(e.g. by the MCP server), otherwise runs a one-shot Blender subprocess with a timeout.
Env: BLENDER_BIN (Blender executable), R2R_BLENDER_TIMEOUT_S (default 120).
"""
from __future__ import annotations

import contextlib
import fcntl
import functools
import hashlib
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

try:
    from . import specs, worker_client
except ImportError:  # loaded as a top-level module
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from blender_mcp import specs, worker_client

TEMPLATE_VERSION = specs.TEMPLATE_VERSION
BBOX_TOLERANCE_M = 0.001
log = logging.getLogger("rag_to_rooms.blender_assets")


def _dim(v):
    return None if v is None else f"{float(v):.4f}"


@functools.lru_cache(maxsize=256)
def _file_sha256(path: str, mtime_ns: int, size: int) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def texture_sha256(path: str) -> str:
    st = os.stat(path)
    return _file_sha256(path, st.st_mtime_ns, st.st_size)


def asset_key(product: dict, template_version: str = TEMPLATE_VERSION) -> str:
    """Stable 24-hex-char key over the fields that change the geometry or look of an asset
    (style.form enters normalized, so junk keys/values and key order do not change it)."""
    dims = product.get("dimensions_m") or None
    style = product.get("style") or {}
    color = style.get("color_hex")
    mat = style.get("material")
    payload = {
        "id": product.get("id"),
        "variant": product.get("variant"),
        "category": product.get("category"),
        "dimensions_m": None if dims is None else {k: _dim(dims.get(k)) for k in ("width", "depth", "height")},
        "color_hex": color.strip().upper().lstrip("#") if isinstance(color, str) else None,
        "material": mat.strip().lower() if isinstance(mat, str) else None,
        "template_version": str(template_version),
    }
    if specs.product_shape(product) == "round":  # only added when round so rect keys keep their recipe
        payload["shape"] = "round"
    form = specs.product_form(product)
    if form:  # only keys/values valid for the category; absent when there is no usable form
        payload["form"] = form
    tex = specs.product_texture(product)
    if tex is not None:  # keyed on the image bytes, not its path; absent for untextured products
        with contextlib.suppress(OSError):
            payload["texture"] = {"sha256": texture_sha256(tex["path"]), "mode": tex["mode"],
                                  "tile_m": f"{tex['tile_m']:.4f}"}
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]


@contextlib.contextmanager
def _lock(out_dir: Path, key: str):
    lock_dir = out_dir / ".locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    with open(lock_dir / f"{key}.lock", "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def _timeout() -> float:
    try:
        return float(os.environ.get("R2R_BLENDER_TIMEOUT_S", "120"))
    except ValueError:
        return 120.0


def build_one_shot(spec: dict, usdz: Path, glb: Path | None = None, *, room: bool = False,
                   timeout: float | None = None) -> dict:
    """Runs integrations/blender/build_asset.py in a fresh Blender. Raises WorkerError on failure."""
    blender = worker_client.find_blender()
    if blender is None:
        raise worker_client.WorkerError("unavailable", "Blender not found; set BLENDER_BIN")
    cmd = [blender, "--background", "--factory-startup", "--python", str(worker_client.BUILD_SCRIPT), "--",
           "--spec", json.dumps(spec), "--out", str(usdz)]
    if glb is not None:
        cmd += ["--glb", str(glb)]
    if room:
        cmd.append("--room")
    try:
        proc = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                              timeout=timeout or _timeout())
    except subprocess.TimeoutExpired:
        raise worker_client.WorkerError("timeout", f"one-shot Blender build exceeded {timeout or _timeout()}s")
    for line in reversed(proc.stdout.splitlines()):
        if line.startswith("R2R_RESULT "):
            data = json.loads(line[len("R2R_RESULT "):])
            if not data.get("ok"):
                err = data.get("error") or {}
                raise worker_client.WorkerError(err.get("type", "error"), err.get("message", "build failed"))
            return data["result"]
    raise worker_client.WorkerError("crashed", f"Blender exited {proc.returncode} without a result: "
                                               f"{(proc.stderr or proc.stdout)[-400:]}")


def build_asset(product: dict, out_dir: Path, *, glb: bool = False, worker: "worker_client.BlenderWorker | None" = None,
                use_shared_worker: bool = True, force: bool = False) -> dict:
    """Detailed variant of ensure_asset used by the CLI/MCP server. Raises on failure."""
    spec = specs.spec_from_product(product)
    if spec is None:
        raise specs.ValidationError("product has no buildable spec (null/package dimensions or unknown category)")
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    key = asset_key(product)
    usdz = out_dir / f"{key}.usdz"
    glb_path = out_dir / f"{key}.glb" if glb else None
    with _lock(out_dir, key):
        if not force and usdz.is_file() and usdz.stat().st_size > 0 and (glb_path is None or glb_path.is_file()):
            return {"asset_key": key, "usdz_path": str(usdz), "glb_path": str(glb_path) if glb_path else None,
                    "cached": True, "spec": spec}
        t0 = time.perf_counter()
        if worker is None and use_shared_worker:
            worker = worker_client.BlenderWorker.attach()
        params = {"spec": spec, "usdz_path": str(usdz)}
        if glb_path:
            params["glb_path"] = str(glb_path)
        result = None
        if worker is not None:
            try:
                result = worker.request("build_asset", params, timeout=_timeout())
                via = "worker"
            except worker_client.WorkerError as exc:
                if exc.type not in ("unavailable", "crashed", "start_failed"):
                    raise
                log.warning("warm worker failed (%s); falling back to one-shot build", exc)
        if result is None:
            result = build_one_shot(spec, usdz, glb_path)
            via = "one_shot"
        err = result.get("max_abs_error_m")
        if err is None or err > BBOX_TOLERANCE_M:
            usdz.unlink(missing_ok=True)
            raise worker_client.WorkerError("bbox_mismatch", f"exported bbox off by {err} m (> {BBOX_TOLERANCE_M} m)")
        result.update(asset_key=key, cached=False, via=via, spec=spec,
                      wall_seconds=round(time.perf_counter() - t0, 3))
        return result


def ensure_asset(product: dict, out_dir: Path) -> Path | None:
    """Returns <out_dir>/<asset_key>.usdz, building it if missing. None on any failure; never raises."""
    try:
        if not isinstance(product, dict) or not product.get("dimensions_m"):
            return None
        if specs.spec_from_product(product) is None:
            return None
        return Path(build_asset(product, Path(out_dir))["usdz_path"])
    except Exception as exc:  # contract: never raise into the backend
        log.warning("ensure_asset failed for %s: %s", product.get("id") if isinstance(product, dict) else "?", exc)
        return None
