#!/bin/sh
# Public HTTPS URL for the backend on :8000, for networks that block device-to-device traffic (campus,
# guest Wi-Fi). Prints the https://….trycloudflare.com URL and shows a QR code: scan it with the iPad
# Camera app to connect the app. The URL changes every run. Quick tunnels buffer event streams, so the
# app falls back to polling every 2 s.
cd "$(dirname "$0")/.." || exit 1
log=$(mktemp)
cloudflared tunnel --no-autoupdate --url http://localhost:8000 >"$log" 2>&1 &
pid=$!
trap 'kill $pid 2>/dev/null; rm -f "$log"' EXIT INT TERM
url=""
for _ in $(seq 1 30); do
  url=$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' "$log" | head -1)
  [ -n "$url" ] && break
  sleep 1
done
if [ -z "$url" ]; then
  cat "$log"
  echo "cloudflared did not print a URL" >&2
  exit 1
fi
sleep 3
../.venv/bin/python scripts/connect_qr.py "$url"
echo "\nTunnel running. Ctrl+C to stop."
wait $pid
