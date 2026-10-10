"""Read each catalog photo with Gemini and save its visible design features to data/catalog_forms.json.

Usage (from backend/): ../.venv/bin/python scripts/extract_forms.py [--force] [product_id ...]
Needs Gemini (Vertex or GEMINI_API_KEY). Existing entries are kept unless --force. Safe to rerun.
"""
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import agent, catalog, config, forms  # noqa: E402


def main(argv: list[str]) -> int:
    if not agent.available():
        print('Gemini is not configured (see README keys).')
        return 1
    force = '--force' in argv
    only = {a for a in argv if not a.startswith('--')}
    existing = forms.load()
    todo = [p for p in catalog.products()
            if p.get('local_image') and (config.STATIC_DIR / p['local_image']).is_file()
            and (not only or p['id'] in only) and (force or p['id'] not in existing)]
    print(f'Reading {len(todo)} photos with {config.GEMINI_MODEL} ({config.GEMINI_BACKEND})')

    agent._gemini()  # create the shared client once, before the worker threads use it

    def one(p):
        last = None
        for _ in range(3):
            try:
                return p['id'], forms.read_photo(p), None
            except Exception as e:  # noqa: BLE001 - transient Vertex/client errors; retry
                last = str(e)[:120]
        return p['id'], None, last

    with ThreadPoolExecutor(max_workers=4) as pool:
        for pid, form, err in pool.map(one, todo):
            if form is None:
                print(f'  fail {pid}: {err}')
                continue
            existing[pid] = form
            print(f'  ok   {pid}: {json.dumps(form, sort_keys=True)}')
    forms.FORMS_PATH.write_text(json.dumps(dict(sorted(existing.items())), indent=2) + '\n')
    print(f'Wrote {len(existing)} entries to {forms.FORMS_PATH}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
