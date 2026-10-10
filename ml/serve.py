"""HTTP sidecar exposing RankerService to processes without torch (e.g. the backend).

    ml/.venv/bin/python ml/serve.py [--host 127.0.0.1] [--port 8100]

GET  /health  -> {"mode", "reason", "model_id", "embedding_dim", "catalog_size", "device"}
POST /score   {"room_image_path": str|null, "product_ids": [str]} -> {"mode", "scores": {id: float}}
POST /reload  re-read artifacts (after re-embedding the catalog or retraining) -> /health body

The backend does not call this directly: `from ml.infer import RankerService` in the root .venv
(no torch) automatically proxies to this sidecar. room_image_path must be readable by this process.
"""
from __future__ import annotations

import argparse
import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from common import ARTIFACTS_DIR
from infer import RankerService

MAX_BODY = 1 << 20


class SidecarState:
    def __init__(self, artifacts_dir: Path):
        self.artifacts_dir = artifacts_dir
        self.lock = threading.Lock()
        self.service = RankerService.load(artifacts_dir, backend="local")

    def reload(self):
        service = RankerService.load(self.artifacts_dir, backend="local")
        with self.lock:
            self.service = service


def make_handler(state: SidecarState):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, body: dict):
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _body(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                raise ValueError("body too large")
            raw = self.rfile.read(length) if length else b"{}"
            body = json.loads(raw or b"{}")
            if not isinstance(body, dict):
                raise ValueError("expected a JSON object")
            return body

        def do_GET(self):
            if self.path.split("?")[0] == "/health":
                return self._send(200, state.service.info())
            self._send(404, {"error": "not found"})

        def do_POST(self):
            path = self.path.split("?")[0]
            try:
                body = self._body()
            except (ValueError, json.JSONDecodeError) as exc:
                return self._send(400, {"error": str(exc)})
            if path == "/reload":
                state.reload()
                return self._send(200, state.service.info())
            if path != "/score":
                return self._send(404, {"error": "not found"})
            ids = body.get("product_ids")
            if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
                return self._send(400, {"error": "product_ids must be a list of strings"})
            room = body.get("room_image_path")
            if room is not None and not isinstance(room, str):
                return self._send(400, {"error": "room_image_path must be a string or null"})
            room_path = Path(room) if room else None
            if room_path is not None and not room_path.is_file():
                return self._send(400, {"error": f"room image not found: {room}"})
            service = state.service
            scores = service.score(room_path, ids)
            self._send(200, {"mode": service.mode, "scores": scores})

        def log_message(self, fmt, *args):
            logging.getLogger("sidecar").info("%s " + fmt, self.address_string(), *args)

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8100)
    parser.add_argument("--artifacts", default=str(ARTIFACTS_DIR))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    state = SidecarState(Path(args.artifacts))
    info = state.service.info()
    logging.info("ranker mode=%s (%s)", info["mode"], info["reason"])
    server = ThreadingHTTPServer((args.host, args.port), make_handler(state))
    logging.info("listening on http://%s:%d", args.host, args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
