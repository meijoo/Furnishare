"""RankerService: the contract in docs/API.md ("Ranker interface").

    service = RankerService.load(Path("ml/artifacts"))
    service.mode                      # "learned" | "cosine" | "neutral"
    service.score(room_image, ids)    # {product_id: float}; higher = more compatible

Importing this module needs only the stdlib, so the backend (root .venv, no torch) can import it.

Backends:
- local  (torch importable): embeds the room image in-process with SigLIP2.
- remote (no torch, or RAG_RANKER_URL set): forwards to the sidecar (ml/serve.py,
  default http://127.0.0.1:8100). If the sidecar is unreachable, mode is "neutral" and it is
  re-probed at most every 10 s, so starting the sidecar later upgrades the mode automatically.

Score semantics:
- Scores are only comparable among products of the same category for the same room image.
- learned: MLP logit. cosine: cosine similarity of SigLIP2 embeddings. neutral: 0.0.
- room_image None (or unreadable/unembeddable): every requested id gets 0.0.
- Unknown product ids (no catalog embedding) are OMITTED in learned/cosine mode; use
  scores.get(pid, default). In neutral mode every requested id gets 0.0.
- load() and score() never raise.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

_ML_DIR = Path(__file__).resolve().parent
if str(_ML_DIR) not in sys.path:
    sys.path.insert(0, str(_ML_DIR))

log = logging.getLogger("rag_to_rooms.ranker")

DEFAULT_SIDECAR_URL = "http://127.0.0.1:8100"
MODES = ("learned", "cosine", "neutral")


def _torch_available() -> bool:
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
        return True
    except Exception:
        return False


class RankerService:
    mode: str

    def __init__(self):
        self.mode = "neutral"
        self.reason = "not loaded"

    @classmethod
    def load(cls, artifacts_dir: Path, *, backend: str | None = None, embedder=None,
             sidecar_url: str | None = None) -> "RankerService":
        """Never raises. backend: "local" | "remote" | None (auto)."""
        try:
            url = sidecar_url or os.environ.get("RAG_RANKER_URL")
            backend = backend or os.environ.get("RAG_RANKER_BACKEND")
            if backend is None:
                backend = "remote" if (url or not (embedder or _torch_available())) else "local"
            if backend == "remote":
                return _RemoteRanker(url or DEFAULT_SIDECAR_URL)
            return _LocalRanker(Path(artifacts_dir), embedder=embedder)
        except Exception as exc:
            log.exception("RankerService.load failed; using neutral scores")
            service = cls()
            service.reason = f"load failed: {exc!r}"
            return service

    def score(self, room_image: Path | None, product_ids: list[str]) -> dict[str, float]:
        return {pid: 0.0 for pid in product_ids}

    def info(self) -> dict:
        return {"mode": self.mode, "reason": self.reason}


class _LocalRanker(RankerService):
    def __init__(self, artifacts_dir: Path, embedder=None):
        super().__init__()
        import torch
        from embed import Embedder, load_catalog_embeddings
        from common import RANKER_CHECKPOINT

        self._torch = torch
        self._lock = threading.Lock()
        self.artifacts_dir = artifacts_dir
        self.model = None
        self.product_index: dict[str, int] = {}
        self.product_embeddings = None
        self.model_id = None
        self.embedding_dim = None

        try:
            catalog = load_catalog_embeddings(artifacts_dir)
        except Exception as exc:
            self.reason = f"catalog embeddings unreadable: {exc!r}"
            return
        if not catalog or len(catalog.get("product_ids", [])) == 0:
            self.reason = "no catalog embeddings; run `python embed.py catalog`"
            return

        self.model_id = catalog["model_id"]
        self.product_embeddings = torch.nn.functional.normalize(catalog["embeddings"].float(), dim=-1)
        self.embedding_dim = int(self.product_embeddings.shape[1])
        self.product_index = {pid: i for i, pid in enumerate(catalog["product_ids"])}

        try:
            self.embedder = embedder or Embedder(self.model_id)
            if embedder is None:
                self.embedder.preload_room_cache(artifacts_dir)
                self.embedder._ensure_model()
        except Exception as exc:
            self.reason = f"image encoder unavailable ({exc!r}); cannot embed room images"
            self.product_index = {}
            return
        if getattr(self.embedder, "model_id", self.model_id) != self.model_id:
            self.reason = "embedder model_id differs from catalog embeddings"
            self.product_index = {}
            return

        self.mode, self.reason = "cosine", "catalog embeddings loaded; no compatible ranker.pt"
        checkpoint_path = artifacts_dir / RANKER_CHECKPOINT
        if checkpoint_path.exists():
            try:
                self._load_checkpoint(checkpoint_path)
            except Exception as exc:
                self.reason = f"ranker.pt unusable ({exc!r}); using cosine"

    def _load_checkpoint(self, path: Path) -> None:
        from ranker import CompatibilityRanker
        ckpt = self._torch.load(path, map_location="cpu", weights_only=True)
        if ckpt.get("model_id") != self.model_id:
            self.reason = f"ranker.pt model_id {ckpt.get('model_id')!r} != catalog {self.model_id!r}; using cosine"
            return
        if int(ckpt.get("embedding_dim", -1)) != self.embedding_dim:
            self.reason = f"ranker.pt embedding_dim {ckpt.get('embedding_dim')} != {self.embedding_dim}; using cosine"
            return
        model = CompatibilityRanker(self.embedding_dim, int(ckpt.get("hidden_dim", 128)))
        model.load_state_dict(ckpt["state_dict"])
        model.eval()
        self.model = model
        self.mode, self.reason = "learned", "ranker.pt loaded"

    def score(self, room_image: Path | None, product_ids: list[str]) -> dict[str, float]:
        neutral = {pid: 0.0 for pid in product_ids}
        if self.mode == "neutral" or room_image is None:
            return neutral
        try:
            known = [pid for pid in product_ids if pid in self.product_index]
            if not known:
                return {}
            torch = self._torch
            with self._lock:
                room = self.embedder.embed_image(Path(room_image)).float().reshape(1, -1)
                room = torch.nn.functional.normalize(room, dim=-1)
                products = self.product_embeddings[[self.product_index[p] for p in known]]
                with torch.no_grad():
                    if self.mode == "learned":
                        values = self.model(room.expand(len(known), -1), products)
                    else:
                        values = products @ room[0]
            return {pid: float(v) for pid, v in zip(known, values.tolist())}
        except Exception:
            log.exception("ranker score failed; returning neutral scores")
            return neutral

    def info(self) -> dict:
        return {"mode": self.mode, "reason": self.reason, "backend": "local", "model_id": self.model_id,
                "embedding_dim": self.embedding_dim, "catalog_size": len(self.product_index),
                "device": str(getattr(getattr(self, "embedder", None), "device", None))}


class _RemoteRanker(RankerService):
    PROBE_INTERVAL_S = 10.0

    def __init__(self, url: str, timeout_s: float = 5.0):
        super().__init__()
        self.url = url.rstrip("/")
        self.timeout_s = timeout_s
        self._last_probe = 0.0
        self._probe()

    def _request(self, path: str, body: dict | None = None, timeout: float | None = None) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.url + path, data=data, method="POST" if body is not None else "GET",
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout or self.timeout_s) as resp:
            return json.loads(resp.read())

    def _probe(self) -> None:
        self._last_probe = time.monotonic()
        try:
            health = self._request("/health", timeout=1.5)
            mode = health.get("mode")
            self.mode = mode if mode in MODES else "neutral"
            self.reason = f"sidecar {self.url}: {health.get('reason', '')}"
        except Exception as exc:
            self.mode, self.reason = "neutral", f"sidecar {self.url} unreachable ({exc.__class__.__name__})"

    def score(self, room_image: Path | None, product_ids: list[str]) -> dict[str, float]:
        neutral = {pid: 0.0 for pid in product_ids}
        if self.mode == "neutral" and time.monotonic() - self._last_probe > self.PROBE_INTERVAL_S:
            self._probe()
        if self.mode == "neutral" or room_image is None:
            return neutral
        try:
            result = self._request("/score", {"room_image_path": str(Path(room_image).resolve()),
                                              "product_ids": list(product_ids)})
            self.mode = result.get("mode", self.mode) if result.get("mode") in MODES else self.mode
            scores = result.get("scores") or {}
            return {str(k): float(v) for k, v in scores.items() if v is not None}
        except Exception as exc:
            log.warning("sidecar score failed (%s); returning neutral scores", exc)
            self.mode, self.reason = "neutral", f"sidecar error ({exc.__class__.__name__})"
            return neutral

    def info(self) -> dict:
        return {"mode": self.mode, "reason": self.reason, "backend": "remote", "url": self.url}
