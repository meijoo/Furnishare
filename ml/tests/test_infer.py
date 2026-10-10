"""RankerService fallback modes, using a fake embedder and SYNTHETIC artifacts (no model download)."""
import hashlib
import json
import subprocess
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
import torch

from infer import RankerService
from ranker import CompatibilityRanker

DIM = 8
MODEL = "fake/test-encoder"


class FakeEmbedder:
    model_id = MODEL
    embedding_dim = DIM
    device = "cpu"

    def __init__(self):
        self.calls = 0

    def embed_image(self, path):
        self.calls += 1
        seed = int(hashlib.sha256(Path(path).read_bytes()).hexdigest()[:8], 16)
        return torch.nn.functional.normalize(torch.randn(DIM, generator=torch.Generator().manual_seed(seed)), dim=0)


def write_catalog(artifacts: Path, model_id=MODEL, dim=DIM):
    emb = torch.nn.functional.normalize(torch.randn(3, dim, generator=torch.Generator().manual_seed(0)), dim=1)
    torch.save({"product_ids": ["p1", "p2", "p3"], "categories": ["sofa"] * 3, "embeddings": emb,
                "model_id": model_id, "embedding_dim": dim, "created_at": "now"}, artifacts / "catalog_embeddings.pt")
    return emb


def write_ranker(artifacts: Path, model_id=MODEL, dim=DIM):
    model = CompatibilityRanker(dim, 4)
    torch.save({"state_dict": model.state_dict(), "embedding_dim": dim, "hidden_dim": 4, "model_id": model_id},
               artifacts / "ranker.pt")


@pytest.fixture
def room(tmp_path):
    path = tmp_path / "room.jpg"
    path.write_bytes(b"not really a jpeg, the fake embedder only hashes bytes")
    return path


def test_neutral_when_no_artifacts(tmp_path, room):
    service = RankerService.load(tmp_path, backend="local", embedder=FakeEmbedder())
    assert service.mode == "neutral"
    assert service.score(room, ["p1", "zzz"]) == {"p1": 0.0, "zzz": 0.0}


def test_neutral_without_embedder_does_not_download(tmp_path, room):
    service = RankerService.load(tmp_path / "missing", backend="local")
    assert service.mode == "neutral"
    assert service.score(room, ["p1"]) == {"p1": 0.0}


def test_cosine_mode(tmp_path, room):
    emb = write_catalog(tmp_path)
    fake = FakeEmbedder()
    service = RankerService.load(tmp_path, backend="local", embedder=fake)
    assert service.mode == "cosine"
    scores = service.score(room, ["p1", "p3", "unknown"])
    assert set(scores) == {"p1", "p3"}, "unknown ids are omitted"
    expected = emb[[0, 2]] @ fake.embed_image(room)
    assert scores["p1"] == pytest.approx(float(expected[0]), abs=1e-5)
    assert service.score(None, ["p1", "p2"]) == {"p1": 0.0, "p2": 0.0}


def test_learned_mode(tmp_path, room):
    write_catalog(tmp_path)
    write_ranker(tmp_path)
    service = RankerService.load(tmp_path, backend="local", embedder=FakeEmbedder())
    assert service.mode == "learned"
    scores = service.score(room, ["p1", "p2", "p3"])
    assert set(scores) == {"p1", "p2", "p3"} and all(isinstance(v, float) for v in scores.values())


@pytest.mark.parametrize("kwargs", [{"model_id": "other/model"}, {"dim": DIM * 2}])
def test_mismatched_ranker_falls_back_to_cosine(tmp_path, room, kwargs):
    write_catalog(tmp_path)
    write_ranker(tmp_path, **kwargs)
    service = RankerService.load(tmp_path, backend="local", embedder=FakeEmbedder())
    assert service.mode == "cosine"


def test_corrupt_artifacts_never_raise(tmp_path, room):
    (tmp_path / "catalog_embeddings.pt").write_bytes(b"garbage")
    service = RankerService.load(tmp_path, backend="local", embedder=FakeEmbedder())
    assert service.mode == "neutral"
    write_catalog(tmp_path)
    (tmp_path / "ranker.pt").write_bytes(b"garbage")
    service = RankerService.load(tmp_path, backend="local", embedder=FakeEmbedder())
    assert service.mode == "cosine"


def test_unreadable_room_image_returns_neutral(tmp_path):
    write_catalog(tmp_path)
    service = RankerService.load(tmp_path, backend="local", embedder=FakeEmbedder())
    assert service.score(tmp_path / "missing.jpg", ["p1"]) == {"p1": 0.0}


def test_remote_unreachable_is_neutral(room):
    service = RankerService.load(Path("."), backend="remote", sidecar_url="http://127.0.0.1:9")
    assert service.mode == "neutral"
    assert service.score(room, ["p1"]) == {"p1": 0.0}


def test_remote_proxies_to_sidecar(tmp_path, room):
    import serve
    write_catalog(tmp_path)

    class State(serve.SidecarState):
        def __init__(self):
            self.artifacts_dir = tmp_path
            self.lock = threading.Lock()
            self.service = RankerService.load(tmp_path, backend="local", embedder=FakeEmbedder())

    server = ThreadingHTTPServer(("127.0.0.1", 0), serve.make_handler(State()))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}"
        remote = RankerService.load(Path("."), backend="remote", sidecar_url=url)
        assert remote.mode == "cosine"
        scores = remote.score(room, ["p1", "p2", "nope"])
        assert set(scores) == {"p1", "p2"}
        assert remote.score(None, ["p1"]) == {"p1": 0.0}
    finally:
        server.shutdown()


def test_infer_importable_without_torch():
    """The backend imports infer.py from a Python without torch; module import must be stdlib-only."""
    code = ("import sys, builtins; real = builtins.__import__\n"
            "def guard(name, *a, **k):\n"
            "    if name.split('.')[0] in ('torch', 'transformers'): raise ImportError(name)\n"
            "    return real(name, *a, **k)\n"
            "builtins.__import__ = guard\n"
            f"sys.path.insert(0, {str(Path(__file__).resolve().parent.parent)!r})\n"
            "from infer import RankerService\n"
            "s = RankerService.load('.', sidecar_url='http://127.0.0.1:9')\n"
            "print(s.mode, s.score(None, ['a']))\n")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert out.stdout.split()[0] == "neutral"
