#!/bin/zsh
# Restart the backend on 0.0.0.0:8000 (reachable from the iPad on the same Wi-Fi).
# Only the process listening on :8000 is stopped; clients such as the tunnel (scripts/tunnel.sh) keep running.
cd "$(dirname "$0")/.."
for pid in $(lsof -ti tcp:8000 -sTCP:LISTEN); do kill "$pid"; done
for _ in {1..50}; do lsof -ti tcp:8000 -sTCP:LISTEN >/dev/null || break; sleep 0.2; done
exec ../.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
