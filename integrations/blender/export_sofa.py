"""Deprecated shim: the parametric templates now live in templates.py (see integrations/blender_mcp/README.md).

  blender --background --factory-startup --python export_sofa.py -- --width 1.65 --depth .85 --height .8 --output /tmp/sofa.usdz

Kept for old invocations; it delegates to templates.build_and_export. Output may be .usdz or .glb.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import templates  # noqa: E402
from templates import specs  # noqa: E402

parser = argparse.ArgumentParser()
for key, default in [("width", 1.65), ("height", 0.8), ("depth", 0.85)]:
    parser.add_argument("--" + key, type=float, default=default)
parser.add_argument("--color-hex", default=None)
parser.add_argument("--material", default=None)
parser.add_argument("--output", required=True)
args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])

spec = specs.furniture_spec({k: v for k, v in {
    "category": "sofa", "dimensions_m": {"width": args.width, "depth": args.depth, "height": args.height},
    "color_hex": args.color_hex, "material": args.material}.items() if v is not None})
output = Path(args.output).resolve()
if output.suffix.lower() not in (".usdz", ".glb"):
    raise ValueError("Output must be .usdz or .glb")
templates.reset_blend()
if output.suffix.lower() == ".usdz":
    result = templates.build_and_export(spec, output)
else:
    result = templates.build_and_export(spec, None, output)
print(json.dumps({k: v for k, v in result.items() if k != "measured_bbox_m"}))
