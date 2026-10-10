"""Prebuild USDZ assets for every product the backend serves (photo-read forms and photo textures included).

Usage: ../.venv/bin/python scripts/build_assets.py [--prune]
--prune deletes cached .usdz files that no current product resolves to; photo-texture variants rebuild on demand.
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import assets, catalog, config  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--prune', action='store_true')
    args = parser.parse_args()
    if assets.blender_assets is None:
        sys.exit('integrations/blender_mcp is not importable')

    products = {p['id']: p for p in catalog._demo_products() + catalog.products() if p.get('dimensions_m')}
    keep: set[str] = set()
    failed = []
    started = time.perf_counter()
    start_wall = time.time()
    for i, p in enumerate(products.values(), 1):
        t = time.perf_counter()
        path = assets.blender_assets.ensure_asset(p, config.ASSETS_DIR)
        if path:
            keep.add(path.name)
        else:
            failed.append(p['id'])
        print(f'[{i}/{len(products)}] {p["id"]}: {"ok" if path else "FAILED"} {time.perf_counter() - t:.1f}s', flush=True)

    print(f'{len(keep)} assets in {time.perf_counter() - started:.0f}s, {len(failed)} failed {failed}')
    if args.prune:
        stale = [f for f in config.ASSETS_DIR.glob('*.usdz') if f.name not in keep and f.stat().st_mtime < start_wall]
        for f in stale:
            f.unlink()
        print(f'pruned {len(stale)} stale assets')


if __name__ == '__main__':
    main()
