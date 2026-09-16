"""Tile rendering.

Key faces are drawn with ImageMagick: generated artwork if there is any, else an
accent gradient with a glyph. Either way a dark scrim and heavy white type go at
the bottom -- the panel is only 85x85, so contrast and type size are the whole
game.

Tiles are cached by a hash of everything that affects the result, so editing a
caption in the editor invalidates exactly the tiles that changed. (The original
script cached by key index alone, so config edits silently kept the old image.)
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

from .paths import ART_DIR, CACHE_DIR

__all__ = ["tile", "solid_tile", "reencode", "render_all", "preview_png",
           "art_path", "permute_art", "magick", "have_magick"]

_MAGICK = None


def magick() -> list[str]:
    """ImageMagick 7 ships `magick`; 6 ships `convert`. Accept either."""
    global _MAGICK
    if _MAGICK is None:
        for cand in ("magick", "convert", "magick.exe", "convert.exe"):
            p = shutil.which(cand)
            if p:
                _MAGICK = [p]
                break
        else:
            _MAGICK = []
    return _MAGICK


def have_magick() -> bool:
    return bool(magick())


def _run(args: list[str]) -> None:
    m = magick()
    if not m:
        raise RuntimeError(
            "ImageMagick not found. Install it (Arch: pacman -S imagemagick; "
            "Windows: winget install ImageMagick.ImageMagick).")
    subprocess.run(m + args, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


# -- fonts -----------------------------------------------------------------

_GLYPH_FONTS = [
    "/usr/share/fonts/TTF/JetBrainsMonoNerdFont-Regular.ttf",
    "/usr/share/fonts/TTF/SymbolsNerdFont-Regular.ttf",
    "/usr/share/fonts/noto/NotoSansSymbols2-Regular.ttf",
    "C:/Windows/Fonts/seguisym.ttf",
]
_TEXT_FONTS = [
    "/usr/share/fonts/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
]

_font_cache: dict[str, str | None] = {}


def _font(kind: str) -> str | None:
    """First font of `kind` that exists, else let ImageMagick pick a default."""
    if kind in _font_cache:
        return _font_cache[kind]
    for p in (_GLYPH_FONTS if kind == "glyph" else _TEXT_FONTS):
        if os.path.exists(p):
            _font_cache[kind] = p
            return p
    _font_cache[kind] = None
    return None


# -- helpers ---------------------------------------------------------------

def _shade(hexcol: str, factor: float) -> str:
    """Darken or lighten #rrggbb, for the background gradient."""
    h = hexcol.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    try:
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    except (ValueError, IndexError):
        r, g, b = 0x8A, 0xB4, 0xF8
    f = lambda v: max(0, min(255, int(v * factor)))
    return f"#{f(r):02x}{f(g):02x}{f(b):02x}"


def _caption_of(spec: dict) -> str:
    cap = spec.get("caption") or spec.get("label") or ""
    if len(cap) > 8 and " " in cap:
        head, _, tail = cap.partition(" ")
        cap = f"{head}\n{tail}"
    return cap


def art_path(key: int) -> str:
    return os.path.join(ART_DIR, f"{key}.png")


_art_path = art_path


def _cache_key(key, spec, size, fmt, rotate, use_art) -> str:
    art = art_path(key)
    stamp = None
    if use_art and os.path.exists(art):
        st = os.stat(art)
        stamp = (int(st.st_mtime), st.st_size)
    payload = json.dumps({
        "caption": _caption_of(spec), "icon": spec.get("icon", ""),
        "color": spec.get("color", ""), "size": size, "fmt": fmt,
        "rotate": rotate, "art": stamp,
    }, sort_keys=True)
    return hashlib.sha1(payload.encode()).hexdigest()[:16]


# -- public ----------------------------------------------------------------

def tile(key: int, spec: dict, *, size: int = 85, fmt: str = "JPEG",
         rotate: int = 180, max_bytes: int = 2300, use_art: bool = True,
         art_key: int | None = None) -> bytes:
    """Encoded image for one key face.

    `art_key` says which key's artwork to draw, when that differs from the key
    being drawn. The editor uses it to preview a pending drag-and-drop swap
    without moving any files: nothing on disk changes until the user saves.
    """
    art_key = key if art_key is None else art_key
    ext = "bmp" if fmt == "BMP" else "jpg"
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(
        CACHE_DIR, f"t_{_cache_key(art_key, spec, size, fmt, rotate, use_art)}.{ext}")
    if os.path.exists(path):
        with open(path, "rb") as f:
            return f.read()

    accent = spec.get("color") or "#8ab4f8"
    glyph = spec.get("icon", "")
    caption = _caption_of(spec)
    lines = caption.count("\n") + 1
    cpt = int(size * (0.165 if lines > 1 else 0.20))
    scrim_y = int(size * (0.60 if lines > 1 else 0.66))

    art = art_path(art_key)
    if use_art and os.path.exists(art):
        args = [art, "-resize", f"{size}x{size}!"]
    else:
        top, bottom = _shade(accent, 1.18), _shade(accent, 0.52)
        gpt = int(size * (0.36 if lines > 1 else 0.44))
        args = ["-size", f"{size}x{size}", f"gradient:{top}-{bottom}"]
        if glyph:
            gf = _font("glyph")
            args += (["-font", gf] if gf else []) + [
                "-pointsize", str(gpt), "-fill", "white", "-gravity", "north",
                "-annotate", f"+0+{int(size * 0.045)}", glyph]

    args += ["-fill", "rgba(0,0,0,0.58)", "-draw",
             f"rectangle 0,{scrim_y} {size},{size}"]
    if caption:
        tf = _font("text")
        args += (["-font", tf] if tf else []) + [
            "-pointsize", str(cpt), "-interline-spacing", "-3",
            "-gravity", "south", "-fill", "white",
            "-annotate", f"+0+{int(size * 0.035)}", caption]

    base = args + ["-rotate", str(rotate), "-alpha", "off"]
    # Tiles much over ~2.5KB get dropped by the device: only the tail of a batch
    # survives. Step quality down until the tile fits that envelope.
    for q in (92, 82, 72, 62, 54, 46):
        _run(base + ["-quality", str(q), f"{fmt}:{path}"])
        if fmt != "JPEG" or os.path.getsize(path) <= max_bytes:
            break
    with open(path, "rb") as f:
        return f.read()


_solid: dict[tuple, bytes] = {}


def solid_tile(size: int, fmt: str) -> bytes:
    """A flat dark tile, for priming.

    Priming only has to exercise the device's modes, not carry artwork, so this
    stays as small as the format allows.
    """
    k = (size, fmt)
    if k not in _solid:
        os.makedirs(CACHE_DIR, exist_ok=True)
        ext = "bmp" if fmt == "BMP" else "jpg"
        p = os.path.join(CACHE_DIR, f"prime_{size}_{fmt}.{ext}")
        if not os.path.exists(p):
            _run(["-size", f"{size}x{size}", "xc:#101216", "-alpha", "off",
                  "-quality", "40", f"{fmt}:{p}"])
        with open(p, "rb") as f:
            _solid[k] = f.read()
    return _solid[k]


def reencode(data: bytes, size: int, fmt: str) -> bytes:
    """Re-encode an existing tile at another geometry (legacy priming only)."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    ext = "bmp" if fmt == "BMP" else "jpg"
    src = os.path.join(CACHE_DIR, "reenc_src")
    dst = os.path.join(CACHE_DIR, f"reenc_{size}_{fmt}.{ext}")
    with open(src, "wb") as f:
        f.write(data)
    _run([src, "-resize", f"{size}x{size}!", "-alpha", "off", f"{fmt}:{dst}"])
    with open(dst, "rb") as f:
        return f.read()


def render_all(keys: dict, profile, *, use_art: bool = True,
               art_map: dict | None = None) -> dict[int, bytes]:
    """Every key face for a profile, keyed by key index."""
    return {k: tile(k, keys.get(k, {}), size=profile.tile, fmt=profile.image,
                    rotate=profile.rotate, max_bytes=profile.max_tile_bytes,
                    use_art=use_art,
                    art_key=(art_map or {}).get(k, k))
            for k in profile.key_range}


def preview_png(key: int, spec: dict, profile, out_path: str, *,
                scale: int = 150, use_art: bool = True,
                art_key: int | None = None) -> str:
    """An upright PNG of one key face, for the editor and for --preview."""
    data = tile(key, spec, size=profile.tile, fmt=profile.image,
                rotate=profile.rotate, max_bytes=profile.max_tile_bytes,
                use_art=use_art, art_key=art_key)
    tmp = os.path.join(tempfile.gettempdir(), f"pv_src_{key}.jpg")
    with open(tmp, "wb") as f:
        f.write(data)
    # Undo the panel rotation so a human sees it the right way up.
    _run([tmp, "-rotate", str(-profile.rotate), "-resize", f"{scale}x", out_path])
    return out_path


def permute_art(art_map: dict[int, int]) -> None:
    """Rearrange artwork files to match a key permutation.

    art_map maps a key index to the key whose artwork should end up on it.
    Applied in one go through temporary names, so a cycle of swaps cannot eat
    a file halfway through.
    """
    moves = {k: v for k, v in art_map.items() if k != v}
    if not moves:
        return
    staged = {}
    for dest, src in moves.items():
        s = art_path(src)
        if os.path.exists(s):
            tmp = os.path.join(ART_DIR, f".permute-{dest}.png")
            shutil.copy2(s, tmp)
            staged[dest] = tmp
    for dest in moves:
        d = art_path(dest)
        if dest in staged:
            os.replace(staged[dest], d)
        elif os.path.exists(d):
            os.unlink(d)          # source had no art; destination must not keep stale art
