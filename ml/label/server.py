"""Local pairwise labeling tool.

    ml/.venv/bin/python ml/label/server.py [--port 8200]
    open http://127.0.0.1:8200

Shows a room image and two same-category catalog products; appends judgments to
ml/data/labels.jsonl (skips go to ml/data/skips.jsonl). Room, product A and product B are always
drawn from the same identity pool (train/validation/test, see splits.py) so no label is wasted
when build_pairs.py enforces identity-disjoint splits. Pairs with close cosine scores are favored
(hard pairs), with some uniform exploration; an annotator never sees the same room+pair twice.
"""
from __future__ import annotations

import argparse
import itertools
import json
import math
import mimetypes
import random
import re
import sys
import threading
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

ML_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ML_DIR))

import torch  # noqa: E402

from common import (ARTIFACTS_DIR, CATALOG_PATH, DATA_DIR, ROOMS_DIR, STATIC_DIR,  # noqa: E402
                    atomic_write_json, load_catalog, product_image_path, read_jsonl, utc_now)
from dataset import load_rooms  # noqa: E402
from embed import load_catalog_embeddings  # noqa: E402
from splits import compute_pools, load_manifest  # noqa: E402

INDEX_HTML = Path(__file__).resolve().parent / "index.html"
ANNOTATOR_RE = re.compile(r"^[A-Za-z0-9_.@-]{1,64}$")


def pair_key(room_id: str, a: str, b: str) -> tuple[str, str, str]:
    return (room_id, *sorted((a, b)))


class LabelStore:
    def __init__(self, args):
        self.args = args
        self.lock = threading.Lock()
        self.rng = random.Random(args.seed)
        data_dir = Path(args.data_dir)
        self.labels_path = data_dir / "labels.jsonl"
        self.skips_path = data_dir / "skips.jsonl"
        self.manifest_path = data_dir / "split_manifest.json"
        self.reload()

    def reload(self):
        args = self.args
        try:
            catalog = load_catalog(Path(args.catalog))
        except FileNotFoundError:
            catalog = []
            print(f"WARNING: catalog not found at {args.catalog}")
        self.products = {}
        for p in catalog:
            path = product_image_path(p, Path(args.static))
            if path:
                self.products[p["id"]] = {"id": p["id"], "title": p.get("title") or p.get("name") or p["id"],
                                          "variant": p.get("variant") or "", "retailer": p.get("retailer") or "",
                                          "category": p.get("category", "unknown"), "path": path,
                                          "price_cents": p.get("price_cents")}
        emb = load_catalog_embeddings(Path(args.artifacts))
        self.product_emb = {}
        model_id = None
        if emb:
            model_id = emb["model_id"]
            for pid, vec in zip(emb["product_ids"], emb["embeddings"]):
                if pid in self.products:
                    self.product_emb[pid] = torch.nn.functional.normalize(vec.float(), dim=0)
        self.rooms = load_rooms(Path(args.rooms), Path(args.artifacts), model_id, embed_missing=bool(emb))
        self.room_paths = dict(zip(self.rooms.ids, self.rooms.paths))
        self.room_sha = dict(zip(self.rooms.ids, self.rooms.shas))

        self.pools_enabled = bool(self.product_emb) and self.rooms.embeddings is not None and \
            len(self.product_emb) == len(self.products)
        self.room_pool, self.product_pool = {}, {}
        if self.pools_enabled:
            manifest = load_manifest(self.manifest_path)
            pids = list(self.product_emb)
            pools = compute_pools(self.rooms.ids, self.rooms.embeddings, pids,
                                  torch.stack([self.product_emb[p] for p in pids]),
                                  [self.products[p]["category"] for p in pids], manifest)
            self.room_pool, self.product_pool = pools["rooms"], pools["products"]
            manifest["rooms"] = {**manifest.get("rooms", {}), **self.room_pool}
            manifest["products"] = {**manifest.get("products", {}), **self.product_pool}
            atomic_write_json(self.manifest_path, manifest)
        else:
            print("WARNING: embeddings incomplete; pairs are sampled uniformly WITHOUT pool constraints. "
                  "Run `embed.py catalog` and `embed.py images data/rooms`, then restart, so labels respect splits.")

    def _labels(self):
        return read_jsonl(self.labels_path), read_jsonl(self.skips_path)

    def stats(self, annotator: str | None = None) -> dict:
        labels, skips = self._labels()
        by_pool = Counter(self.room_pool.get(r.get("room_id"), "unassigned") for r in labels)
        return {"labels": len(labels), "skips": len(skips), "rooms": len(self.rooms.ids),
                "products": len(self.products), "mine": sum(r.get("annotator_id") == annotator for r in labels),
                "ties": sum(r.get("preferred_product") == "tie" for r in labels),
                "by_pool": dict(by_pool), "pools_enabled": self.pools_enabled}

    def next_pair(self, annotator: str) -> dict:
        labels, skips = self._labels()
        seen = {pair_key(r["room_id"], r["product_a_id"], r["product_b_id"])
                for r in labels + skips if r.get("annotator_id") == annotator and "room_id" in r}
        labeled_any = Counter(pair_key(r["room_id"], r["product_a_id"], r["product_b_id"]) for r in labels if "room_id" in r)
        per_room = Counter(r.get("room_id") for r in labels)
        per_room_cat = Counter((r.get("room_id"), r.get("furniture_category")) for r in labels)

        if not self.rooms.ids:
            return {"done": True, "reason": f"No room images in {self.args.rooms}. Add photos and restart."}
        if len(self.products) < 2:
            return {"done": True, "reason": "Fewer than two catalog products with local images."}

        rooms = list(self.rooms.ids)
        self.rng.shuffle(rooms)
        rooms.sort(key=lambda r: per_room[r])
        for room_id in rooms:
            pool = self.room_pool.get(room_id)
            by_cat: dict[str, list[str]] = {}
            for pid, p in self.products.items():
                if not self.pools_enabled or self.product_pool.get(pid) == pool:
                    by_cat.setdefault(p["category"], []).append(pid)
            cats = [c for c, ids in by_cat.items() if len(ids) >= 2]
            self.rng.shuffle(cats)
            cats.sort(key=lambda c: per_room_cat[(room_id, c)])
            for cat in cats:
                pair = self._sample_pair(room_id, sorted(by_cat[cat]), seen, labeled_any)
                if pair:
                    a, b = pair if self.rng.random() < 0.5 else pair[::-1]
                    return {"done": False, "room_id": room_id, "pool": pool, "category": cat,
                            "room_url": f"/img/room/{room_id}",
                            "a": self._public(a), "b": self._public(b)}
        return {"done": True, "reason": "No unseen same-pool pairs left for this annotator."}

    def _public(self, pid: str) -> dict:
        p = self.products[pid]
        return {k: p[k] for k in ("id", "title", "variant", "retailer", "price_cents")} | {"image_url": f"/img/product/{pid}"}

    def _sample_pair(self, room_id, ids, seen, labeled_any):
        candidates = [(a, b) for a, b in itertools.combinations(ids, 2) if pair_key(room_id, a, b) not in seen]
        if not candidates:
            return None
        room_vec = self.rooms.by_sha.get(self.room_sha[room_id])
        use_hard = room_vec is not None and all(p in self.product_emb for p in ids) and \
            self.rng.random() >= self.args.explore
        if not use_hard:
            return self.rng.choice(candidates)
        room_vec = torch.nn.functional.normalize(room_vec.float(), dim=0)
        cos = {p: float(self.product_emb[p] @ room_vec) for p in ids}
        weights = [math.exp(-abs(cos[a] - cos[b]) / self.args.tau) *
                   (self.args.overlap_weight if labeled_any[pair_key(room_id, a, b)] else 1.0)
                   for a, b in candidates]
        return self.rng.choices(candidates, weights=weights, k=1)[0]

    def append(self, body: dict) -> dict:
        annotator = str(body.get("annotator_id", "")).strip()
        if not ANNOTATOR_RE.match(annotator):
            raise ValueError("annotator_id required (letters, digits, _ . @ -)")
        room_id, a, b = body.get("room_id"), body.get("product_a_id"), body.get("product_b_id")
        if room_id not in self.room_paths:
            raise ValueError("unknown room_id")
        if a not in self.products or b not in self.products or a == b:
            raise ValueError("unknown or identical products")
        category = self.products[a]["category"]
        if self.products[b]["category"] != category:
            raise ValueError("products must share a category")
        action = body.get("action")
        row = {"room_id": room_id, "room_sha256": self.room_sha[room_id], "product_a_id": a, "product_b_id": b,
               "furniture_category": category, "annotator_id": annotator, "timestamp": utc_now(),
               "pool": self.room_pool.get(room_id)}
        if action == "skip":
            target = self.skips_path
        else:
            preferred = body.get("preferred_product")
            if preferred not in (a, b, "tie"):
                raise ValueError("preferred_product must be product_a_id, product_b_id or 'tie'")
            uncertainty = body.get("uncertainty", "sure")
            if uncertainty not in ("sure", "unsure"):
                raise ValueError("uncertainty must be 'sure' or 'unsure'")
            row |= {"preferred_product": preferred, "uncertainty": uncertainty}
            target = self.labels_path
        with self.lock:
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, "a") as handle:
                handle.write(json.dumps(row) + "\n")
        return row


def make_handler(store: LabelStore):
    class Handler(BaseHTTPRequestHandler):
        def _json(self, status, body):
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _file(self, path: Path):
            data = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            url = urlparse(self.path)
            query = parse_qs(url.query)
            annotator = (query.get("annotator") or [""])[0]
            if url.path in ("/", "/index.html"):
                return self._file(INDEX_HTML)
            if url.path == "/api/next":
                if not ANNOTATOR_RE.match(annotator):
                    return self._json(400, {"error": "annotator required"})
                return self._json(200, store.next_pair(annotator))
            if url.path == "/api/stats":
                return self._json(200, store.stats(annotator))
            if url.path.startswith("/img/room/"):
                path = store.room_paths.get(unquote(url.path[len("/img/room/"):]))
                return self._file(path) if path else self._json(404, {"error": "unknown room"})
            if url.path.startswith("/img/product/"):
                product = store.products.get(unquote(url.path[len("/img/product/"):]))
                return self._file(product["path"]) if product else self._json(404, {"error": "unknown product"})
            self._json(404, {"error": "not found"})

        def do_POST(self):
            if urlparse(self.path).path == "/api/reload":
                store.reload()
                return self._json(200, store.stats())
            if urlparse(self.path).path != "/api/label":
                return self._json(404, {"error": "not found"})
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                self._json(200, {"ok": True, "row": store.append(body)})
            except (ValueError, json.JSONDecodeError) as exc:
                self._json(400, {"error": str(exc)})

        def log_message(self, fmt, *args):
            pass

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8200)
    parser.add_argument("--catalog", default=str(CATALOG_PATH))
    parser.add_argument("--static", default=str(STATIC_DIR))
    parser.add_argument("--rooms", default=str(ROOMS_DIR))
    parser.add_argument("--artifacts", default=str(ARTIFACTS_DIR))
    parser.add_argument("--data-dir", default=str(DATA_DIR), help="where labels.jsonl, skips.jsonl, split_manifest.json live")
    parser.add_argument("--tau", type=float, default=0.03, help="hard-pair temperature on |cos_a - cos_b|")
    parser.add_argument("--explore", type=float, default=0.2, help="probability of a uniform (non-hard) pair")
    parser.add_argument("--overlap-weight", type=float, default=0.3,
                        help="relative weight for pairs another annotator already judged (enables disagreement stats)")
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()
    store = LabelStore(args)
    print(json.dumps(store.stats(), indent=2))
    server = ThreadingHTTPServer((args.host, args.port), make_handler(store))
    print(f"Labeling tool at http://{args.host}:{args.port}  (labels -> {store.labels_path})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
