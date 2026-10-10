"""Show a QR code that points the iPad app at a backend: scan it with the iPad Camera app.

Usage: ../.venv/bin/python scripts/connect_qr.py [backend-url]   (default: http://<this Mac's Wi-Fi IP>:8000)
"""
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote

import segno


def lan_url() -> str:
    ip = subprocess.run(['ipconfig', 'getifaddr', 'en0'], capture_output=True, text=True).stdout.strip()
    if not ip:
        sys.exit('No Wi-Fi IP found; pass the backend URL explicitly.')
    return f'http://{ip}:8000'


def main() -> None:
    backend = sys.argv[1] if len(sys.argv) > 1 else lan_url()
    link = f'ragtorooms://connect?url={quote(backend, safe="")}'
    qr = segno.make(link, error='m')
    png = Path(tempfile.gettempdir()) / 'ragtorooms-connect.png'
    qr.save(png, scale=12, border=3)
    print(f'Backend: {backend}\nScan with the iPad Camera app, then tap "Open in RagToRooms".\n')
    qr.terminal(compact=True)
    subprocess.run(['open', str(png)], check=False)


if __name__ == '__main__':
    main()
