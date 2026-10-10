"""Frozen SigLIP2 image embeddings (L2-normalized).

    python embed.py catalog [--catalog PATH]   -> artifacts/catalog_embeddings.pt
    python embed.py images DIR                 -> artifacts/room_embeddings.pt (keyed by file sha256)

Both subcommands are incremental: images whose sha256 and model_id are unchanged reuse
their previous embedding, so re-running after the catalog grows is cheap.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import torch
from PIL import Image

from common import (ARTIFACTS_DIR, CATALOG_EMBEDDINGS, CATALOG_PATH, MODEL_ID, ROOM_EMBEDDINGS,
                    STATIC_DIR, atomic_write_bytes, file_sha256, list_images, load_catalog,
                    product_image_path, utc_now)


def pick_device(preferred: str | None = None) -> torch.device:
    if preferred:
        return torch.device(preferred)
    if torch.backends.mps.is_available():
        return torch.device("mps")
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


def load_rgb(path: Path) -> Image.Image:
    image = Image.open(path)
    image.load()
    if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.split()[-1])
        return background
    return image.convert("RGB")


def save_pt(path: Path, obj) -> None:
    atomic_write_bytes(path, lambda handle: torch.save(obj, handle))


class Embedder:
    """Lazily loads the frozen encoder. embed_image() is cached by file content hash."""

    def __init__(self, model_id: str = MODEL_ID, device: str | None = None):
        self.model_id = model_id
        self.device = pick_device(device)
        self._model = None
        self._processor = None
        self._cache: dict[str, torch.Tensor] = {}
        self.embedding_dim: int | None = None

    def _ensure_model(self):
        if self._model is not None:
            return
        from transformers import AutoImageProcessor, AutoModel
        self._processor = AutoImageProcessor.from_pretrained(self.model_id)
        model = AutoModel.from_pretrained(self.model_id, dtype=torch.float32)
        model.eval()
        try:
            model.to(self.device)
        except Exception:
            self.device = torch.device("cpu")
            model.to(self.device)
        self._model = model
        cfg = getattr(model.config, "vision_config", model.config)
        self.embedding_dim = int(getattr(model.config, "projection_dim", None) or cfg.hidden_size)

    def _forward(self, images: list[Image.Image]) -> torch.Tensor:
        inputs = self._processor(images=images, return_tensors="pt")
        inputs = {k: v.to(self.device) for k, v in inputs.items()}
        with torch.inference_mode():
            out = self._model.get_image_features(**inputs)
        if not isinstance(out, torch.Tensor):
            out = out.pooler_output
        return torch.nn.functional.normalize(out.float(), dim=-1).cpu()

    def embed_paths(self, paths: list[Path], batch_size: int = 16) -> torch.Tensor:
        self._ensure_model()
        chunks = []
        for start in range(0, len(paths), batch_size):
            images = [load_rgb(p) for p in paths[start:start + batch_size]]
            try:
                chunks.append(self._forward(images))
            except RuntimeError:
                if self.device.type == "cpu":
                    raise
                self.device = torch.device("cpu")
                self._model.to(self.device)
                chunks.append(self._forward(images))
        if not chunks:
            return torch.empty(0, self.embedding_dim or 0)
        result = torch.cat(chunks)
        self.embedding_dim = result.shape[1]
        return result

    def remember(self, sha: str, embedding: torch.Tensor) -> None:
        self._cache[sha] = embedding

    def embed_image(self, path: Path) -> torch.Tensor:
        sha = file_sha256(Path(path))
        cached = self._cache.get(sha)
        if cached is None:
            cached = self.embed_paths([Path(path)])[0]
            self._cache[sha] = cached
        return cached

    def preload_room_cache(self, artifacts_dir: Path = ARTIFACTS_DIR) -> int:
        data = load_room_embeddings(artifacts_dir)
        if not data or data.get("model_id") != self.model_id:
            return 0
        self._cache.update(data["items"])
        return len(data["items"])


_DEFAULT: Embedder | None = None


def embed_image(path: Path) -> torch.Tensor:
    """Module-level cached embedding of one image file (keyed by sha256 of its bytes)."""
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = Embedder()
        _DEFAULT.preload_room_cache()
    return _DEFAULT.embed_image(path)


def load_catalog_embeddings(artifacts_dir: Path = ARTIFACTS_DIR) -> dict | None:
    path = Path(artifacts_dir) / CATALOG_EMBEDDINGS
    if not path.exists():
        return None
    return torch.load(path, map_location="cpu", weights_only=True)


def load_room_embeddings(artifacts_dir: Path = ARTIFACTS_DIR) -> dict | None:
    path = Path(artifacts_dir) / ROOM_EMBEDDINGS
    if not path.exists():
        return None
    return torch.load(path, map_location="cpu", weights_only=True)


def _timed_embed(embedder: Embedder, paths: list[Path]) -> tuple[torch.Tensor, float]:
    if not paths:
        return torch.empty(0), 0.0
    embedder._ensure_model()
    embedder._forward([Image.new("RGB", (224, 224))])
    start = time.perf_counter()
    result = embedder.embed_paths(paths)
    if embedder.device.type == "mps":
        torch.mps.synchronize()
    return result, time.perf_counter() - start


def cmd_catalog(args) -> int:
    catalog_path = Path(args.catalog)
    try:
        products = load_catalog(catalog_path)
    except FileNotFoundError:
        print(f"Catalog not found at {catalog_path}. Nothing embedded; re-run once it exists.", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"Catalog unreadable: {exc}", file=sys.stderr)
        return 1

    embedder = Embedder(args.model, args.device)
    previous = load_catalog_embeddings(args.artifacts) or {}
    reuse = {}
    if previous.get("model_id") == embedder.model_id:
        for sha, emb in zip(previous.get("image_sha256", []), previous.get("embeddings", [])):
            reuse[sha] = emb

    rows, missing = [], []
    for product in products:
        path = product_image_path(product, Path(args.static))
        if path is None:
            missing.append(product["id"])
            continue
        rows.append((product["id"], product.get("category", "unknown"), path, file_sha256(path)))

    todo = [r for r in rows if r[3] not in reuse]
    fresh, seconds = _timed_embed(embedder, [r[2] for r in todo])
    for row, emb in zip(todo, fresh):
        reuse[row[3]] = emb

    if not rows:
        print(f"{len(products)} products, none with a readable local_image under {args.static}.", file=sys.stderr)
        return 1
    embeddings = torch.stack([reuse[r[3]] for r in rows]).float()
    payload = {
        "product_ids": [r[0] for r in rows],
        "categories": [r[1] for r in rows],
        "image_paths": [str(r[2]) for r in rows],
        "image_sha256": [r[3] for r in rows],
        "embeddings": embeddings,
        "embedding_dim": int(embeddings.shape[1]),
        "model_id": embedder.model_id,
        "created_at": utc_now(),
    }
    out = Path(args.artifacts) / CATALOG_EMBEDDINGS
    save_pt(out, payload)
    rate = f"{len(todo) / seconds:.1f} img/s" if seconds else "n/a (all cached)"
    print(f"Embedded {len(todo)} new, reused {len(rows) - len(todo)}, skipped {len(missing)} without image; "
          f"dim={embeddings.shape[1]} model={embedder.model_id} device={embedder.device} throughput={rate}")
    if missing:
        print("  missing images: " + ", ".join(missing[:20]) + (" ..." if len(missing) > 20 else ""))
    print(f"Wrote {out}")
    return 0


def cmd_images(args) -> int:
    paths = list_images(Path(args.dir))
    if not paths:
        print(f"No images found in {args.dir}", file=sys.stderr)
        return 1
    embedder = Embedder(args.model, args.device)
    previous = load_room_embeddings(args.artifacts) or {}
    same_model = previous.get("model_id") == embedder.model_id
    items = dict(previous.get("items", {})) if same_model else {}
    sources = dict(previous.get("paths", {})) if same_model else {}

    shas = [file_sha256(p) for p in paths]
    todo = [(p, s) for p, s in zip(paths, shas) if s not in items]
    unique_todo = list({s: p for p, s in todo}.items())
    fresh, seconds = _timed_embed(embedder, [p for _, p in unique_todo])
    for (sha, _), emb in zip(unique_todo, fresh):
        items[sha] = emb.float()
    for path, sha in zip(paths, shas):
        sources[sha] = str(path.resolve())
    dim = int(next(iter(items.values())).shape[0])
    payload = {"items": items, "paths": sources, "model_id": embedder.model_id,
               "embedding_dim": dim, "created_at": utc_now()}
    out = Path(args.artifacts) / ROOM_EMBEDDINGS
    save_pt(out, payload)
    rate = f"{len(unique_todo) / seconds:.1f} img/s" if seconds else "n/a (all cached)"
    print(f"Embedded {len(unique_todo)} new, {len(items)} total; dim={dim} model={embedder.model_id} "
          f"device={embedder.device} throughput={rate}")
    print(f"Wrote {out}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", default=MODEL_ID)
    parser.add_argument("--device", default=None, help="mps|cuda|cpu (default: auto)")
    parser.add_argument("--artifacts", default=str(ARTIFACTS_DIR))
    sub = parser.add_subparsers(dest="cmd", required=True)
    cat = sub.add_parser("catalog")
    cat.add_argument("--catalog", default=str(CATALOG_PATH))
    cat.add_argument("--static", default=str(STATIC_DIR))
    img = sub.add_parser("images")
    img.add_argument("dir")
    args = parser.parse_args(argv)
    return cmd_catalog(args) if args.cmd == "catalog" else cmd_images(args)


if __name__ == "__main__":
    sys.exit(main())
