"""One-shot asset build. Runs inside Blender:

  blender --background --factory-startup --python build_asset.py -- \
      --spec '{"category":"sofa","dimensions_m":{"width":2.28,"depth":0.95,"height":0.83}}' \
      --out /path/<asset_key>.usdz [--glb /path/<asset_key>.glb] [--room]

Prints one line `R2R_RESULT {json}` on stdout; exit code 0 on success, 2 on validation error, 1 otherwise.
"""
import argparse
import json
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import templates  # noqa: E402
from templates import specs  # noqa: E402


def main() -> int:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(prog="build_asset.py")
    parser.add_argument("--spec", required=True, help="JSON furniture spec (or room object with --room)")
    parser.add_argument("--out", required=True, help="output .usdz path")
    parser.add_argument("--glb", default=None, help="optional .glb preview path")
    parser.add_argument("--room", action="store_true", help="build a room shell instead of furniture")
    args = parser.parse_args(argv)
    try:
        raw = json.loads(args.spec)
        spec = specs.room_spec(raw) if args.room else specs.furniture_spec(raw)
        out = Path(args.out).resolve()
        if out.suffix.lower() != ".usdz":
            raise specs.ValidationError("--out must end with .usdz")
        glb = Path(args.glb).resolve() if args.glb else None
        if glb is not None and glb.suffix.lower() != ".glb":
            raise specs.ValidationError("--glb must end with .glb")
    except (ValueError, specs.ValidationError) as exc:
        print("R2R_RESULT " + json.dumps({"ok": False, "error": {"type": "validation", "message": str(exc)}}))
        return 2
    try:
        templates.reset_blend()
        result = templates.build_and_export(spec, out, glb, kind="room" if args.room else "furniture")
        print("R2R_RESULT " + json.dumps({"ok": True, "result": result, "spec": spec}))
        return 0
    except Exception as exc:  # report, never hang
        traceback.print_exc()
        print("R2R_RESULT " + json.dumps({"ok": False, "error": {"type": "internal", "message": str(exc)}}))
        return 1


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    import os
    os._exit(code)
