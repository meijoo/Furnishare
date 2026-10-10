"""Prebuild USDZ assets for every catalog product and write backend/static/assets/manifest.json.

  .venv/bin/python integrations/blender_mcp/build_catalog_assets.py [--catalog PATH] [--glb] [--one-shot] [--force]

Catalog: backend/data/catalog_verified.json, else backend/catalog.json. Accepts a JSON list of
products or {"products": [...]}.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    from . import assets, specs, worker_client
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from blender_mcp import assets, specs, worker_client

REPO = worker_client.REPO
CATALOG_CANDIDATES = [REPO / "backend" / "data" / "catalog_verified.json", REPO / "backend" / "catalog.json"]
DEFAULT_OUT = REPO / "backend" / "static" / "assets"
DEMO_ROOM = {"width_m": 4.5, "depth_m": 4.0, "height_m": 2.5,
             "openings": [{"kind": "door", "wall": "front", "offset_m": 1.0, "width_m": 0.9},
                          {"kind": "window", "wall": "left", "offset_m": -0.4, "width_m": 1.4}]}


def load_catalog(path: Path | None) -> tuple[Path, list[dict]]:
    candidates = [path] if path else CATALOG_CANDIDATES
    for c in candidates:
        if c and c.is_file():
            data = json.loads(c.read_text())
            products = data.get("products", []) if isinstance(data, dict) else data
            return c, [p for p in products if isinstance(p, dict)]
    raise SystemExit(f"no catalog found at {[str(c) for c in candidates]}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--catalog", type=Path, default=None)
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--glb", action="store_true", help="also write <asset_key>.glb previews")
    ap.add_argument("--one-shot", action="store_true", help="one Blender process per asset instead of a warm worker")
    ap.add_argument("--force", action="store_true", help="rebuild even if the .usdz exists")
    ap.add_argument("--room", action="store_true", help="also build the demo room shell (room-<hash>.usdz)")
    args = ap.parse_args(argv)

    catalog_path, products = load_catalog(args.catalog)
    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"catalog: {catalog_path} ({len(products)} products) -> {out_dir}", flush=True)

    worker = None
    if not args.one_shot:
        worker = worker_client.BlenderWorker(allowed_roots=[out_dir], state_file=None)
        t0 = time.perf_counter()
        worker.request("ping")
        print(f"warm worker started in {time.perf_counter() - t0:.2f}s", flush=True)

    manifest = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "template_version": specs.TEMPLATE_VERSION, "catalog": str(catalog_path),
                "assets": {}, "skipped": {}, "failed": {}}
    try:
        for p in products:
            pid = str(p.get("id"))
            if specs.spec_from_product(p) is None:
                manifest["skipped"][pid] = "no assembled dimensions_m or unsupported category/style"
                print(f"  skip  {pid}: not buildable", flush=True)
                continue
            t0 = time.perf_counter()
            try:
                r = assets.build_asset(p, out_dir, glb=args.glb, worker=worker, use_shared_worker=False,
                                       force=args.force)
            except Exception as exc:
                manifest["failed"][pid] = str(exc)
                print(f"  FAIL  {pid}: {exc}", flush=True)
                continue
            usdz = Path(r["usdz_path"])
            measured = r.get("measured_bbox_m")
            if measured is None and worker is not None:  # cached file: measure what is on disk
                measured = worker.request("measure_asset", {"path": str(usdz)})
                r["max_abs_error_m"] = bbox_error(measured, r["spec"]["dimensions_m"])
            entry = {
                "asset_key": r["asset_key"], "asset_file": usdz.name, "asset_url": f"/assets/{usdz.name}",
                "glb_file": Path(r["glb_path"]).name if r.get("glb_path") else None,
                "category": p["category"], "dimensions_m": r["spec"]["dimensions_m"],
                "color_hex": r["spec"]["color_hex"], "material": r["spec"]["material"],
                "cached": r["cached"], "build_seconds": round(time.perf_counter() - t0, 3),
            }
            if measured:
                entry["measured_bbox_m"] = {k: [round(v, 6) for v in measured[k]] for k in ("min", "max", "size")}
                entry["max_abs_error_m"] = r["max_abs_error_m"]
            elif r["cached"]:
                prev = _previous_entry(out_dir, pid, r["asset_key"])
                if prev:
                    entry.update({k: prev[k] for k in ("measured_bbox_m", "max_abs_error_m") if k in prev})
            manifest["assets"][pid] = entry
            err = entry.get("max_abs_error_m")
            print(f"  ok    {pid}: {usdz.name} {'(cached)' if r['cached'] else ''} "
                  f"bbox err={err if err is None else f'{err * 1000:.4f} mm'} {entry['build_seconds']}s", flush=True)

        if args.room:
            room = specs.room_spec(DEMO_ROOM)
            key = "room-" + assets.asset_key({"id": "demo-room", "category": "room",
                                              "dimensions_m": {"width": room["width_m"], "depth": room["depth_m"],
                                                               "height": room["height_m"]},
                                              "variant": json.dumps(room["openings"], sort_keys=True)})[:16]
            usdz = out_dir / f"{key}.usdz"
            t0 = time.perf_counter()
            params = {"room": room, "usdz_path": str(usdz)}
            r = (worker.request("build_asset", params) if worker else assets.build_one_shot(room, usdz, room=True))
            manifest["rooms"] = {"demo": {"asset_file": usdz.name, "asset_url": f"/assets/{usdz.name}", "room": room,
                                          "measured_bbox_m": {k: r["measured_bbox_m"][k] for k in ("min", "max", "size")},
                                          "max_abs_error_m": r["max_abs_error_m"],
                                          "build_seconds": round(time.perf_counter() - t0, 3)}}
            print(f"  ok    room: {usdz.name} bbox err={r['max_abs_error_m'] * 1000:.4f} mm", flush=True)
    finally:
        if worker is not None:
            worker.stop()

    tmp = out_dir / "manifest.json.tmp"
    tmp.write_text(json.dumps(manifest, indent=2))
    os.replace(tmp, out_dir / "manifest.json")
    print(json.dumps({"built": len(manifest["assets"]), "skipped": len(manifest["skipped"]),
                      "failed": len(manifest["failed"]), "manifest": str(out_dir / "manifest.json")}))
    return 1 if manifest["failed"] else 0


def bbox_error(measured: dict, dims: dict) -> float:
    """Max deviation of a Y-up measured bbox from [-w/2, 0, -d/2]..[w/2, h, d/2]."""
    w, d, h = dims["width"], dims["depth"], dims["height"]
    lo, hi = (-w / 2, 0.0, -d / 2), (w / 2, h, d / 2)
    return max(max(abs(measured["min"][i] - lo[i]), abs(measured["max"][i] - hi[i])) for i in range(3))


def _previous_entry(out_dir: Path, pid: str, key: str) -> dict | None:
    try:
        prev = json.loads((out_dir / "manifest.json").read_text())["assets"].get(pid)
        return prev if prev and prev.get("asset_key") == key else None
    except Exception:
        return None


if __name__ == "__main__":
    sys.exit(main())
