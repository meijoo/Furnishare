"""Client for the warm Blender worker (integrations/blender/worker.py). No bpy required.

BlenderWorker starts Blender lazily, restarts it if it died, and publishes its port/token to a
state file (mode 0600) so other processes on this machine (e.g. the backend's ensure_asset) can reuse it.
"""
from __future__ import annotations

import json
import os
import secrets
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
BLENDER_DIR = REPO / "integrations" / "blender"
WORKER_SCRIPT = BLENDER_DIR / "worker.py"
BUILD_SCRIPT = BLENDER_DIR / "build_asset.py"
RUN_DIR = HERE / ".run"
DEFAULT_STATE_FILE = RUN_DIR / "worker.json"
DEFAULT_ALLOWED_ROOTS = [REPO / "backend" / "static" / "assets", HERE / ".out", Path(tempfile.gettempdir())]
MAC_BLENDER = "/Applications/Blender.app/Contents/MacOS/Blender"


class WorkerError(RuntimeError):
    def __init__(self, type_: str, message: str):
        super().__init__(f"{type_}: {message}")
        self.type = type_
        self.message = message


def find_blender() -> str | None:
    for candidate in (os.environ.get("BLENDER_BIN"), MAC_BLENDER, shutil.which("blender")):
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def _send(port: int, payload: dict, timeout: float) -> dict:
    with socket.create_connection(("127.0.0.1", port), timeout=min(timeout, 5.0)) as s:
        s.settimeout(timeout)
        s.sendall(json.dumps(payload).encode("utf-8") + b"\n")
        buf = bytearray()
        while b"\n" not in buf:
            chunk = s.recv(65536)
            if not chunk:
                raise ConnectionResetError("worker closed the connection without replying")
            buf += chunk
    return json.loads(bytes(buf).split(b"\n", 1)[0])


class BlenderWorker:
    def __init__(self, blender_bin: str | None = None, allowed_roots: list[Path] | None = None,
                 state_file: Path | None = DEFAULT_STATE_FILE, start_timeout: float = 90.0,
                 log_path: Path | None = None):
        self.blender_bin = blender_bin or find_blender()
        self.allowed_roots = [Path(r) for r in (allowed_roots or DEFAULT_ALLOWED_ROOTS)]
        self.state_file = Path(state_file) if state_file else None
        self.start_timeout = start_timeout
        self.log_path = Path(log_path) if log_path else RUN_DIR / "worker.log"
        self.proc: subprocess.Popen | None = None
        self.port: int | None = None
        self.token: str | None = None
        self.restarts = 0
        self.last_restart_reason: str | None = None
        self._ids = 0
        self._lock = threading.RLock()

    # ------------------------------------------------------------ lifecycle

    @classmethod
    def attach(cls, state_file: Path = DEFAULT_STATE_FILE) -> "BlenderWorker | None":
        """Connects to a worker another process published, or returns None if none is alive or it runs
        older templates (or lacks WORKER_FEATURES) compared to this checkout."""
        from . import specs
        try:
            info = json.loads(Path(state_file).read_text())
            w = cls(state_file=None)
            w.port, w.token = int(info["port"]), str(info["token"])
            pong = w.request("ping", timeout=3.0, _allow_restart=False)
            if pong.get("template_version") != specs.TEMPLATE_VERSION:
                return None
            if not set(specs.WORKER_FEATURES) <= set(pong.get("features") or ()):
                return None
            return w
        except Exception:
            return None

    def running(self) -> bool:
        if self.proc is not None:
            return self.proc.poll() is None
        return self.port is not None  # attached to someone else's worker

    def start(self):
        with self._lock:
            if self.blender_bin is None:
                raise WorkerError("unavailable", "Blender not found; set BLENDER_BIN")
            RUN_DIR.mkdir(parents=True, exist_ok=True)
            for r in self.allowed_roots:
                r.mkdir(parents=True, exist_ok=True)
            self.token = secrets.token_hex(16)
            ready = Path(tempfile.mkdtemp(prefix="r2r-worker-")) / "ready.json"
            cmd = [self.blender_bin, "--background", "--factory-startup", "--python", str(WORKER_SCRIPT), "--",
                   "--port", "0", "--ready-file", str(ready), "--parent-pid", str(os.getpid())]
            for r in self.allowed_roots:
                cmd += ["--allowed-root", str(r)]
            env = dict(os.environ, R2R_WORKER_TOKEN=self.token)
            log = open(self.log_path, "ab")
            self.proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                         env=env, start_new_session=True)
            log.close()
            deadline = time.monotonic() + self.start_timeout
            while time.monotonic() < deadline:
                if self.proc.poll() is not None:
                    raise WorkerError("start_failed", f"Blender exited with {self.proc.returncode}; see {self.log_path}")
                if ready.exists():
                    info = json.loads(ready.read_text())
                    self.port = int(info["port"])
                    shutil.rmtree(ready.parent, ignore_errors=True)
                    self._publish(info)
                    return
                time.sleep(0.05)
            self.stop()
            raise WorkerError("start_timeout", f"worker not ready after {self.start_timeout}s; see {self.log_path}")

    def _publish(self, info: dict):
        if not self.state_file:
            return
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_file.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(dict(info, token=self.token), f)
        os.replace(tmp, self.state_file)

    def stop(self):
        with self._lock:
            if self.proc is not None and self.proc.poll() is None:
                try:
                    _send(self.port, {"id": 0, "token": self.token, "cmd": "shutdown"}, 3.0)
                    self.proc.wait(5)
                except Exception:
                    self.proc.kill()
                    self.proc.wait(5)
            if self.proc is not None and self.state_file and self.state_file.exists():
                try:
                    if json.loads(self.state_file.read_text()).get("port") == self.port:
                        self.state_file.unlink()
                except Exception:
                    pass
            self.proc, self.port = None, None

    def restart(self, reason: str):
        self.restarts += 1
        self.last_restart_reason = reason
        self.stop()
        self.start()

    # ------------------------------------------------------------ requests

    def request(self, cmd: str, params: dict | None = None, timeout: float = 120.0, _allow_restart: bool = True) -> dict:
        """Sends one command. Starts the worker if needed; restarts it once if it is dead."""
        with self._lock:
            owned = self.proc is not None or self.port is None
            if owned and not self.running():
                if self.proc is not None:
                    self.restart(f"worker exited with code {self.proc.returncode}")
                else:
                    self.start()
            self._ids += 1
            payload = {"id": self._ids, "token": self.token, "cmd": cmd, "params": params or {}}
            try:
                resp = _send(self.port, payload, timeout)
            except ConnectionRefusedError:
                if not (_allow_restart and owned):
                    raise WorkerError("unavailable", "worker is not accepting connections")
                self.restart("connection refused")
                resp = _send(self.port, payload, timeout)
            except socket.timeout:
                if owned:
                    self.restart(f"{cmd} timed out after {timeout}s")
                raise WorkerError("timeout", f"{cmd} timed out after {timeout}s; worker restarted, scene state was lost")
            except (ConnectionResetError, BrokenPipeError, json.JSONDecodeError) as exc:
                if owned:
                    self.restart(f"worker crashed during {cmd}: {exc}")
                raise WorkerError("crashed", f"worker crashed during {cmd}; restarted with an empty scene")
            if not resp.get("ok"):
                err = resp.get("error") or {}
                raise WorkerError(err.get("type", "error"), err.get("message", "unknown error"))
            return resp["result"]
