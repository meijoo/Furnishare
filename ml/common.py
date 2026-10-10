"""Shared paths and helpers for the ml/ pipeline. Stdlib-only at import time."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ML_DIR = Path(__file__).resolve().parent
REPO_DIR = ML_DIR.parent
ARTIFACTS_DIR = ML_DIR / "artifacts"
DATA_DIR = ML_DIR / "data"
ROOMS_DIR = DATA_DIR / "rooms"
LABELS_PATH = DATA_DIR / "labels.jsonl"
SKIPS_PATH = DATA_DIR / "skips.jsonl"
SPLIT_MANIFEST_PATH = DATA_DIR / "split_manifest.json"
CATALOG_PATH = REPO_DIR / "backend" / "data" / "catalog_verified.json"
STATIC_DIR = REPO_DIR / "backend" / "static"

CATALOG_EMBEDDINGS = "catalog_embeddings.pt"
ROOM_EMBEDDINGS = "room_embeddings.pt"
RANKER_CHECKPOINT = "ranker.pt"

MODEL_ID = os.environ.get("RAG_EMBED_MODEL", "google/siglip2-base-patch16-224")
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_catalog(path: Path = CATALOG_PATH) -> list[dict]:
    """Return product dicts. Accepts a bare list or {"products": [...]}. Raises FileNotFoundError."""
    with open(path) as handle:
        data = json.load(handle)
    if isinstance(data, dict):
        data = data.get("products", [])
    if not isinstance(data, list):
        raise ValueError(f"{path}: expected a list of products")
    return [p for p in data if isinstance(p, dict) and p.get("id")]


def product_image_path(product: dict, static_dir: Path = STATIC_DIR) -> Path | None:
    local = product.get("local_image")
    if not local:
        return None
    path = (static_dir / local).resolve()
    if static_dir.resolve() not in path.parents:
        return None
    return path if path.is_file() else None


def list_images(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(p for p in directory.rglob("*") if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES)


def atomic_write_bytes(path: Path, write) -> None:
    """Call write(file_obj) into a temp file, then atomically replace path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "wb") as handle:
            write(handle)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def atomic_write_json(path: Path, obj) -> None:
    atomic_write_bytes(path, lambda h: h.write(json.dumps(obj, indent=2, sort_keys=True).encode()))


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    with open(path) as handle:
        for line in handle:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return rows
