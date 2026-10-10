"""Independent bbox measurement of exported USD/USDZ files (fresh Blender process, pxr only).

  blender --background --factory-startup --python measure_usd.py -- a.usdz b.usdz

Prints `R2R_MEASURE {json}` mapping each path to its measured bbox and stage metadata.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from templates import measure_usd  # noqa: E402

paths = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
out = {}
for p in paths:
    try:
        out[p] = measure_usd(Path(p))
    except Exception as exc:
        out[p] = {"error": str(exc)}
print("R2R_MEASURE " + json.dumps(out))
sys.stdout.flush()
os._exit(0)
