"""Procedural surface textures as images (numpy only, deterministic, seamless).

Blender's procedural shader nodes do not survive the USD export, so every surface is rendered to a
tileable image here and embedded in the USDZ as a UsdUVTexture. Each generator returns
(modulation, height): modulation is a per-pixel brightness factor (mean ~1) that `tint` turns into
linear RGB around the requested color, height feeds an optional tangent-space normal map.

Arrays are (rows, cols) = (v, u) with row 0 at v=0 (Blender pixel order). Grain/brushing runs along u.
Everything is periodic (FFT-filtered noise, integer-period waves), so tiles repeat without seams.
"""
from __future__ import annotations

import hashlib
import math
from pathlib import Path

import numpy as np

# Content hash of this file: cached images are keyed on it, so editing a generator invalidates the cache.
VERSION = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:10]

# kind: material family (used in material names), tile_m: one repeat in meters, px: image size,
# normal: baked normal-map strength (0 = none). roughness/metallic/sheen/coat feed the Principled BSDF.
PRESETS = {
    "oak":           dict(kind="wood", tile_m=0.6, px=1024, roughness=0.55, metallic=0.0, normal=1.6),
    "walnut":        dict(kind="wood", tile_m=0.6, px=1024, roughness=0.5, metallic=0.0, normal=1.4),
    "white_oak":     dict(kind="wood", tile_m=0.6, px=1024, roughness=0.55, metallic=0.0, normal=1.6),
    "pine":          dict(kind="wood", tile_m=0.6, px=1024, roughness=0.6, metallic=0.0, normal=1.2),
    "painted":       dict(kind="paint", tile_m=0.5, px=512, roughness=0.6, metallic=0.0, normal=0.0),
    "lacquer":       dict(kind="paint", tile_m=0.5, px=512, roughness=0.22, metallic=0.0, normal=0.0, coat=0.5),
    "linen":         dict(kind="fabric", tile_m=0.15, px=512, roughness=0.92, metallic=0.0, normal=2.2, sheen=0.3),
    "weave":         dict(kind="fabric", tile_m=0.15, px=512, roughness=0.9, metallic=0.0, normal=2.5, sheen=0.3),
    "boucle":        dict(kind="fabric", tile_m=0.2, px=512, roughness=0.95, metallic=0.0, normal=3.0, sheen=0.4),
    "velvet":        dict(kind="fabric", tile_m=0.4, px=512, roughness=0.78, metallic=0.0, normal=0.0, sheen=1.0),
    "chenille":      dict(kind="fabric", tile_m=0.25, px=512, roughness=0.88, metallic=0.0, normal=1.5, sheen=0.6),
    "leather":       dict(kind="leather", tile_m=0.3, px=512, roughness=0.45, metallic=0.0, normal=1.6, coat=0.15),
    "faux_leather":  dict(kind="leather", tile_m=0.25, px=512, roughness=0.36, metallic=0.0, normal=1.2, coat=0.25),
    "brushed_metal": dict(kind="metal", tile_m=0.3, px=512, roughness=0.32, metallic=1.0, normal=0.0),
    "black_metal":   dict(kind="metal", tile_m=0.3, px=512, roughness=0.48, metallic=0.6, normal=0.0),
    "glass":         dict(kind="glass", tile_m=0.5, px=64, roughness=0.04, metallic=0.0, normal=0.0, alpha=0.32),
    "marble":        dict(kind="stone", tile_m=0.8, px=1024, roughness=0.2, metallic=0.0, normal=0.0, coat=0.3),
    "wool":          dict(kind="wool", tile_m=0.25, px=512, roughness=1.0, metallic=0.0, normal=1.8, sheen=0.6),
    "quilted":       dict(kind="fabric", tile_m=0.32, px=512, roughness=0.95, metallic=0.0, normal=3.0, sheen=0.3),
    "shag":          dict(kind="wool", tile_m=0.3, px=512, roughness=1.0, metallic=0.0, normal=3.0, sheen=0.8),
    "suede":         dict(kind="fabric", tile_m=0.28, px=512, roughness=0.88, metallic=0.0, normal=1.4, sheen=0.7),
    "cotton":        dict(kind="fabric", tile_m=0.14, px=512, roughness=0.9, metallic=0.0, normal=1.8, sheen=0.2),
    "ceramic":       dict(kind="paint", tile_m=0.4, px=512, roughness=0.28, metallic=0.0, normal=0.0, coat=0.35),
    "enamel":        dict(kind="paint", tile_m=0.4, px=512, roughness=0.18, metallic=0.0, normal=0.0, coat=0.7),
    "rattan":        dict(kind="wood", tile_m=0.18, px=512, roughness=0.72, metallic=0.0, normal=2.4),
}
GLASS_TINT = "#A9BDB8"  # glass is a fixed cool tint; its frame/legs carry the product color


def _rng(name: str, salt: str = "") -> np.random.Generator:
    return np.random.default_rng(int(hashlib.sha256(f"{name}:{salt}".encode()).hexdigest()[:12], 16))


def _freqs(n):
    fv = np.fft.fftfreq(n).astype(np.float32)[:, None]
    fu = np.fft.rfftfreq(n).astype(np.float32)[None, :]
    return fu, fv


def _norm(a):
    a = a - a.mean()
    return (a / (a.std() + 1e-8)).astype(np.float32)


def noise(n, rng, su, sv=None, angle=0.0):
    """Periodic Gaussian-filtered noise (zero mean, unit std); su/sv = correlation lengths in px along the
    (rotated) u / v axes, so su >> sv gives long streaks along u."""
    sv = su if sv is None else sv
    fu, fv = _freqs(n)
    c, s = math.cos(angle), math.sin(angle)
    a, b = fu * c + fv * s, -fu * s + fv * c
    filt = np.exp(-2 * math.pi ** 2 * ((a * su) ** 2 + (b * sv) ** 2))
    return _norm(np.fft.irfft2(np.fft.rfft2(rng.standard_normal((n, n)).astype(np.float32)) * filt, s=(n, n)))


def bandpass(n, rng, cycles, width=0.25):
    """Periodic noise concentrated around `cycles` waves per tile (blobs/loops of that size)."""
    fu, fv = _freqs(n)
    r = np.sqrt(fu ** 2 + fv ** 2) * n
    filt = np.exp(-((r - cycles) / (cycles * width)) ** 2)
    return _norm(np.fft.irfft2(np.fft.rfft2(rng.standard_normal((n, n)).astype(np.float32)) * filt, s=(n, n)))


def _grid(n):
    i = (np.arange(n, dtype=np.float32) + 0.5) / n
    return i[None, :].repeat(n, 0), i[:, None].repeat(n, 1)  # u (cols), v (rows) in 0..1


def _smooth(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def _fbm(n, rng, base, octaves=4):
    out = np.zeros((n, n), np.float32)
    amp = 1.0
    for k in range(octaves):
        out += amp * noise(n, rng, base / 2 ** k)
        amp *= 0.5
    return _norm(out)


# ---------------------------------------------------------------- generators

def _wood(n, rng, rings, wobble, ring_contrast, fiber, pores, knots=0, figure=0.05):
    """Plain-sawn board: growth rings as stripes along u, bent by stretched noise into cathedrals,
    fine fibre streaks, optional pore dashes (oak) and knots (pine)."""
    u, v = _grid(n)
    warp = noise(n, rng, n / 3.0, n / 9.0) * wobble + noise(n, rng, n / 8.0, n / 30.0) * wobble * 0.25
    r = v * rings + warp
    for _ in range(knots):
        cu, cv = rng.random(2)
        du = (u - cu + 0.5) % 1.0 - 0.5
        dv = (v - cv + 0.5) % 1.0 - 0.5
        d2 = (du * 3.0) ** 2 + dv ** 2
        r = r + 2.2 * np.exp(-d2 / 0.0012)
    t = r - np.floor(r)
    late = _smooth(0.55, 0.92, t) * (1 - _smooth(0.94, 1.0, t))       # dark latewood band, sharp on one side
    fibers = noise(n, rng, n / 5.0, 0.7)
    fine = noise(n, rng, n / 24.0, 0.5)
    cloud = noise(n, rng, n / 2.5, n / 6.0)
    m = 1 - ring_contrast * (late - late.mean()) + fiber * (0.6 * fibers + 0.4 * fine) + figure * cloud
    height = -late * 0.6 + 0.15 * fibers
    if pores:
        dash = noise(n, rng, 5.0, 0.6)
        pore = _smooth(1.6, 2.6, dash)
        m = m - pores * pore
        height = height - pore * 1.2
    return m, height


def _weave(n, rng, period, contrast, jitter, slub=0.0, fuzz=0.04):
    """Plain weave: warp (along v) and weft (along u) threads alternate over/under in a checker."""
    k = max(2, round(n / period / 2) * 2)  # even thread count per tile keeps the checker periodic
    u, v = _grid(n)
    cu, cv = np.floor(u * k).astype(int), np.floor(v * k).astype(int)
    pu, pv = u * k - cu, v * k - cv
    warp_top = ((cu + cv) % 2) == 0
    hw = np.sin(np.pi * pu) * (0.55 + 0.45 * np.sin(np.pi * pv))
    hf = np.sin(np.pi * pv) * (0.55 + 0.45 * np.sin(np.pi * pu))
    height = np.where(warp_top, hw, hf).astype(np.float32)
    jw = rng.standard_normal(k).astype(np.float32)[cu]
    jf = rng.standard_normal(k).astype(np.float32)[cv]
    tone = np.where(warp_top, jw, jf) * jitter
    if slub:
        sl_w = noise(n, rng, 0.8, n / 14.0)
        sl_f = noise(n, rng, n / 14.0, 0.8)
        tone = tone + slub * np.where(warp_top, sl_w, sl_f)
        height = height * (1 + 0.25 * np.where(warp_top, sl_w, sl_f))
    m = 1 + contrast * (height - height.mean()) + tone + fuzz * noise(n, rng, 0.8) + 0.03 * noise(n, rng, n / 6.0)
    return m, height


def _boucle(n, rng):
    """Nubbly loops: ridged band-pass noise at loop size (~4 mm on a 0.2 m tile) plus clumps."""
    a = 1 - np.abs(bandpass(n, rng, 46, 0.35))
    b = 1 - np.abs(bandpass(n, rng, 70, 0.35))
    loops = np.clip(np.maximum(a, b), 0.0, 1.0) ** 2.5
    clumps = bandpass(n, rng, 18, 0.4)
    height = loops + 0.25 * clumps
    m = 1 + 0.32 * (loops - loops.mean()) + 0.07 * clumps + 0.03 * noise(n, rng, 0.8)
    return m, height


def _velvet(n, rng):
    """Crushed pile: soft mottling with directional sheen bands, very fine fibre noise."""
    crush = noise(n, rng, n / 12.0, n / 22.0, angle=0.6)
    sheen = noise(n, rng, n / 5.0, n / 16.0, angle=-0.4)
    m = 1 + 0.075 * crush + 0.06 * sheen + 0.018 * noise(n, rng, 0.7)
    return m, None


def _chenille(n, rng):
    """Soft horizontal ribs of fuzzy yarn plus mottling."""
    _, v = _grid(n)
    ribs = 0.5 + 0.5 * np.sin(2 * np.pi * v * 64 + 0.6 * noise(n, rng, n / 10.0, 2.0))
    fuzz = noise(n, rng, 1.2)
    mott = noise(n, rng, n / 8.0)
    m = 1 + 0.12 * (ribs - 0.5) + 0.05 * fuzz + 0.05 * mott
    return m, ribs + 0.3 * fuzz


def _cells(n, rng, cells):
    """Periodic Voronoi F1/F2 distances (in cell units) for `cells` x `cells` jittered seeds."""
    pts = rng.random((cells, cells, 2)).astype(np.float32)
    i = (np.arange(n, dtype=np.float32) + 0.5) / n * cells
    gu, gv = i[None, :].repeat(n, 0), i[:, None].repeat(n, 1)
    cu, cv = np.floor(gu).astype(int), np.floor(gv).astype(int)
    f1 = np.full((n, n), 9.0, np.float32)
    f2 = np.full((n, n), 9.0, np.float32)
    for dv in (-1, 0, 1):
        for du in (-1, 0, 1):
            nu, nv = cu + du, cv + dv
            p = pts[nv % cells, nu % cells]
            d = np.sqrt((nu + p[..., 0] - gu) ** 2 + (nv + p[..., 1] - gv) ** 2)
            f2 = np.where(d < f1, f1, np.minimum(f2, d))
            f1 = np.minimum(f1, d)
    return f1, f2


def _leather(n, rng, cells, crease, mottle):
    """Pebble grain (Voronoi cells with sunken borders), a few long creases and aniline mottling."""
    f1, f2 = _cells(n, rng, cells)
    border = _smooth(0.0, 0.22, f2 - f1)
    pebble = border * (1 - 0.35 * f1)
    creases = 1 - np.abs(noise(n, rng, n / 6.0, n / 40.0, angle=0.35))
    creases = _smooth(0.82, 1.0, creases)
    mott = noise(n, rng, n / 7.0)
    height = pebble - crease * creases
    m = 1 + 0.18 * (pebble - pebble.mean()) - 0.16 * crease * (creases - creases.mean()) + mottle * mott
    return m, height


def _brushed(n, rng):
    m = 1 + 0.05 * noise(n, rng, n / 3.0, 0.6) + 0.035 * noise(n, rng, n / 18.0, 0.8) + 0.02 * noise(n, rng, n / 4.0)
    return m, None


def _powder(n, rng):
    return 1 + 0.06 * noise(n, rng, 0.8) + 0.03 * noise(n, rng, n / 14.0), None


def _paint(n, rng, amount):
    return 1 + amount * (noise(n, rng, 1.2) + 0.8 * noise(n, rng, n / 10.0) + 0.5 * noise(n, rng, n / 3.0, 3.0)), None


def _marble(n, rng):
    """Two vein families (integer wave directions keep the tile periodic) warped by fBm, plus cloudiness."""
    u, v = _grid(n)
    turb = _fbm(n, rng, n / 4.0, 5)
    p1 = 2 * np.pi * (1 * u + 1 * v) + 3.2 * turb
    s1 = np.sin(p1 / 2) ** 2  # one vein per wave period
    fade = np.clip(0.5 + 0.6 * noise(n, rng, n / 5.0), 0.0, 1.0)  # veins come and go along their length
    vein1 = (np.exp(-s1 / 0.006) + 0.3 * np.exp(-s1 / 0.08)) * fade   # crisp core with a soft halo
    crack = np.exp(-np.abs(bandpass(n, rng, 10, 0.5)) / 0.05)        # ridged noise: a thin branching network
    vein2 = crack * np.clip(noise(n, rng, n / 6.0) - 0.2, 0.0, 1.0)
    cloud = _fbm(n, rng, n / 3.0, 3)
    m = 1 - 0.45 * vein1 - 0.3 * vein2 + 0.06 * cloud
    return m, None


def _wool(n, rng):
    """Rug pile: short fibres at several angles, tufts and heathered mottling."""
    fib = sum(noise(n, rng, 4.0, 0.7, angle=a) for a in rng.uniform(0, np.pi, 4)) / 2.0
    tufts = bandpass(n, rng, 60, 0.4)
    mott = noise(n, rng, n / 6.0)
    m = 1 + 0.07 * fib + 0.07 * tufts + 0.05 * mott
    return m, 0.6 * tufts + 0.4 * fib


def _shag(n, rng):
    """High-pile rug: long curly strands in clumps with deep shadows between them."""
    clumps = bandpass(n, rng, 24, 0.5)
    strands = sum(noise(n, rng, 9.0, 1.0, angle=a) for a in rng.uniform(0, np.pi, 6)) / 2.4
    m = 1 + 0.16 * clumps + 0.12 * strands + 0.04 * noise(n, rng, n / 6.0)
    return m, 0.7 * clumps + 0.3 * strands


def _quilted(n, rng):
    """Mattress ticking: fine weave with a diamond quilting stitch grid (puffs between stitches)."""
    u, v = _grid(n)
    k = 4
    a = (u + v) * k
    b = (u - v) * k
    puff = np.sin(np.pi * (a - np.floor(a))) * np.sin(np.pi * (b - np.floor(b)))
    stitch = np.maximum(_smooth(0.06, 0.0, np.abs(a - np.round(a))), _smooth(0.06, 0.0, np.abs(b - np.round(b))))
    wm, wh = _weave(n, rng, 4, 0.08, 0.01, fuzz=0.02)
    m = wm + 0.08 * (puff - puff.mean()) - 0.12 * stitch
    return m, 2.0 * puff - 0.6 * stitch + 0.1 * wh


GENERATORS = {
    "oak": lambda n, r: _wood(n, r, rings=11, wobble=1.3, ring_contrast=0.24, fiber=0.05, pores=0.07),
    "walnut": lambda n, r: _wood(n, r, rings=9, wobble=2.2, ring_contrast=0.32, fiber=0.06, pores=0.03, figure=0.08),
    "white_oak": lambda n, r: _wood(n, r, rings=16, wobble=0.7, ring_contrast=0.16, fiber=0.04, pores=0.05),
    "pine": lambda n, r: _wood(n, r, rings=7, wobble=1.6, ring_contrast=0.38, fiber=0.035, pores=0.0, knots=2),
    "painted": lambda n, r: _paint(n, r, 0.012),
    "lacquer": lambda n, r: _paint(n, r, 0.006),
    "linen": lambda n, r: _weave(n, r, 6, 0.26, 0.05, slub=0.05),
    "weave": lambda n, r: _weave(n, r, 8, 0.30, 0.035),
    "boucle": _boucle,
    "velvet": _velvet,
    "chenille": _chenille,
    "leather": lambda n, r: _leather(n, r, 56, 0.45, 0.07),
    "faux_leather": lambda n, r: _leather(n, r, 80, 0.2, 0.03),
    "brushed_metal": _brushed,
    "black_metal": _powder,
    "glass": lambda n, r: (1 + 0.01 * noise(n, r, n / 4.0), None),
    "marble": _marble,
    "wool": _wool,
    "quilted": _quilted,
    "shag": _shag,
    "suede": _velvet,
    "cotton": lambda n, r: _weave(n, r, 7, 0.22, 0.04, slub=0.03),
    "ceramic": lambda n, r: _paint(n, r, 0.008),
    "enamel": lambda n, r: _paint(n, r, 0.004),
    "rattan": lambda n, r: _weave(n, r, 5, 0.42, 0.08, slub=0.06),
}
assert set(GENERATORS) == set(PRESETS)

_PATTERNS: dict[tuple, tuple] = {}


def pattern(surface: str, n: int | None = None):
    """(modulation, height) for a surface at n px (memoized; color independent)."""
    n = n or PRESETS[surface]["px"]
    key = (surface, n)
    if key not in _PATTERNS:
        m, height = GENERATORS[surface](n, _rng(surface, str(n)))
        _PATTERNS[key] = (np.asarray(m, np.float32), None if height is None else np.asarray(height, np.float32))
    return _PATTERNS[key]


# ---------------------------------------------------------------- color

def srgb_to_linear(c):
    c = np.asarray(c, np.float32)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(c):
    c = np.clip(np.asarray(c, np.float32), 0.0, 1.0)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * c ** (1 / 2.4) - 0.055)


def hex_linear(hex_color: str) -> np.ndarray:
    h = hex_color.strip().lstrip("#")
    return srgb_to_linear([int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)])


def tint(m: np.ndarray, rgb_linear) -> np.ndarray:
    """Modulation -> linear RGB whose per-channel mean equals rgb_linear (iterated so clipping at white
    or black does not shift the average color)."""
    target = np.asarray(rgb_linear, np.float32)
    m = m / max(float(m.mean()), 1e-6)
    out = m[..., None] * target
    for _ in range(6):
        out = np.clip(out, 0.0, 1.0)
        mean = out.reshape(-1, 3).mean(0)
        out = out * np.where(mean > 1e-6, target / np.maximum(mean, 1e-6), 1.0)
    return np.clip(out, 0.0, 1.0)


def color_image(surface: str, hex_color: str, n: int | None = None) -> np.ndarray:
    """(n, n, 4) sRGB-encoded RGBA float image (alpha only differs from 1 for glass)."""
    m, _ = pattern(surface, n)
    hex_color = GLASS_TINT if surface == "glass" else hex_color
    rgb = linear_to_srgb(tint(m, hex_linear(hex_color)))
    alpha = np.full(m.shape + (1,), PRESETS[surface].get("alpha", 1.0), np.float32)
    return np.concatenate([rgb, alpha], axis=2)


def normal_image(surface: str, n: int | None = None) -> np.ndarray | None:
    """(n, n, 4) tangent-space normal map (OpenGL +Y, raw), strength baked in; None for flat surfaces."""
    strength = PRESETS[surface]["normal"]
    _, height = pattern(surface, n)
    if not strength or height is None:
        return None
    hgt = (height - height.mean()) / (height.std() + 1e-8)
    n_px = hgt.shape[0]
    k = strength * n_px / 512.0 * 0.06
    du = (np.roll(hgt, -1, 1) - np.roll(hgt, 1, 1)) * 0.5 * k
    dv = (np.roll(hgt, -1, 0) - np.roll(hgt, 1, 0)) * 0.5 * k
    nz = np.ones_like(hgt)
    length = np.sqrt(du ** 2 + dv ** 2 + 1.0)
    rgb = np.stack([-du / length, -dv / length, nz / length], axis=2) * 0.5 + 0.5
    return np.concatenate([rgb, np.ones(hgt.shape + (1,), np.float32)], axis=2).astype(np.float32)
