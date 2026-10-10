"""Tiny dependency-free PNG writer and test-image patterns (no PIL/numpy in the backend venv)."""
import math
import struct
import zlib
from pathlib import Path

WHITE = (255, 255, 255)
QUADRANTS = {"top_left": (220, 40, 40), "top_right": (40, 170, 60), "bottom_left": (40, 70, 200),
             "bottom_right": (235, 200, 40)}


def write_png(path: Path, width: int, height: int, pixel) -> Path:
    """pixel(x, y) -> (r, g, b) bytes, y = 0 is the top row."""
    rows = (b"\x00" + bytes(c for x in range(width) for c in pixel(x, y)) for y in range(height))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    Path(path).write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
                           + chunk(b"IDAT", zlib.compress(b"".join(rows), 6)) + chunk(b"IEND", b""))
    return Path(path)


def _noise(x, y):
    return ((x * 73856093) ^ (y * 19349663)) % 7  # deterministic 0..6 jitter, like JPEG noise on a white backdrop


def bordered_quadrants(path: Path, width: int, height: int, border: int) -> Path:
    """Four solid color quadrants inside a near-white border (a product photo of a rug on a white backdrop)."""
    def px(x, y):
        if x < border or y < border or x >= width - border or y >= height - border:
            return tuple(255 - _noise(x, y) for _ in range(3))
        q = ("top_" if y < height / 2 else "bottom_") + ("left" if x < width / 2 else "right")
        return QUADRANTS[q]
    return write_png(path, width, height, px)


def bordered_medallion(path: Path, width: int, height: int, border: int) -> Path:
    """A colorful rug-like pattern (field, frame, medallion, corner motifs) on a near-white backdrop."""
    iw, ih = width - 2 * border, height - 2 * border

    def px(x, y):
        if x < border or y < border or x >= width - border or y >= height - border:
            return tuple(255 - _noise(x, y) for _ in range(3))
        u, v = (x - border) / iw, (y - border) / ih
        edge = min(u, v, 1 - u, 1 - v)
        if edge < 0.04:
            return (120, 30, 40)
        if edge < 0.08:
            return (230, 205, 160) if int((u + v) * 60) % 2 else (40, 70, 110)
        du, dv = (u - 0.5) * iw / ih, v - 0.5
        r = math.hypot(du, dv)
        a = math.atan2(dv, du)
        if r < 0.3 + 0.05 * math.cos(8 * a):
            return (30, 90, 130) if r > 0.18 else (240, 190, 70) if r > 0.08 else (150, 30, 40)
        if v < 0.25 and u < 0.2:
            return (60, 120, 80)  # top-left motif marks "up"
        stripe = int(v * 24) % 2
        return (175, 45, 50) if stripe else (190, 60, 60)
    return write_png(path, width, height, px)


def swatch(path: Path, size: int = 128) -> Path:
    """A tileable weave/plaid swatch."""
    def px(x, y):
        a = (x // 8 + y // 8) % 2
        line = x % 32 < 3 or y % 32 < 3
        return (70, 90, 120) if line else (170, 150, 120) if a else (150, 130, 105)
    return write_png(path, size, size, px)
