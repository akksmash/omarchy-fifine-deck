"""Reading and writing keys.toml.

Written by hand as well as by the editor, so saving preserves the shape and the
explanatory header rather than round-tripping through a TOML writer that would
discard them.
"""
from __future__ import annotations

import os
import shutil
import tempfile

try:
    import tomllib                      # 3.11+
except ModuleNotFoundError:             # pragma: no cover
    import tomli as tomllib             # type: ignore

from .paths import CONFIG_FILE, ensure_dirs

FIELDS = ("label", "cmd", "icon", "color", "caption", "art")

# [deck] settings, with the defaults used when the section is absent.
SETTINGS = {
    # commands | light | jpeg | full  (see drivers/crt.py for what each costs).
    # "full" is the legacy behaviour and the only value yet observed to render
    # anything on real hardware; the cheaper ones are unverified. Do not lower
    # this default until the ladder has been bisected with eyes on the panel.
    "prime": "full",
    "sweeps": 2,                # times to walk the key set when drawing
    "brightness": 100,
    # Bytes per tile. The device drops tiles over some threshold, and the only
    # key that has ever survived a draw is also the smallest one -- so this is
    # the knob for testing whether size, not position, is what decides.
    "max_tile_bytes": 2300,
    "draw_on_attach": True,     # redraw whenever the deck is plugged in
    "reactivate_keys": True,    # re-enter key mode after drawing
}

HEADER = """\
# Deck key bindings.
#
# Key indices are as the deck REPORTS them when pressed, in reading order:
#
#     top     1  2  3  4  5
#     middle  6  7  8  9 10
#     bottom 11 12 13 14 15
#
# The screens are numbered differently (row-flipped); this is handled for you,
# so only these numbers matter here.
#
# Edit by hand, or run `deck-editor` for a drag-and-drop editor.
# Reload after a hand edit:  deck-ctl reload
"""


def _quote(s: str) -> str:
    """TOML basic string. Values here are short and human-written."""
    out = str(s).replace("\\", "\\\\").replace('"', '\\"')
    out = out.replace("\n", "\\n").replace("\t", "\\t").replace("\r", "")
    return f'"{out}"'


def load(path: str | None = None) -> dict[int, dict]:
    """Key specs by integer key index. Missing file is an empty config."""
    path = path or CONFIG_FILE
    if not os.path.exists(path):
        return {}
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    out: dict[int, dict] = {}
    for k, v in (raw.get("keys") or {}).items():
        try:
            idx = int(k)
        except (TypeError, ValueError):
            continue                     # ignore non-numeric key names
        if isinstance(v, dict):
            out[idx] = {f: v.get(f, "") for f in FIELDS if v.get(f, "") != ""}
    return out


def dump(keys: dict[int, dict], settings: dict | None = None) -> str:
    lines = [HEADER]
    if settings:
        changed = {k: v for k, v in settings.items()
                   if k in SETTINGS and v != SETTINGS[k]}
        if changed:
            lines.append("[deck]")
            for k in sorted(changed):
                v = changed[k]
                lines.append(f"{k} = " + ("true" if v is True else
                                          "false" if v is False else
                                          _quote(v) if isinstance(v, str) else str(v)))
            lines.append("")
    for idx in sorted(keys):
        spec = keys[idx]
        if not any(str(spec.get(f, "")).strip() for f in FIELDS):
            continue                     # an entirely blank key writes nothing
        lines.append(f'[keys."{idx}"]')
        for f in FIELDS:
            val = spec.get(f, "")
            if str(val).strip():
                lines.append(f"{f} = {_quote(val)}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def save(keys: dict[int, dict], path: str | None = None,
         settings: dict | None = None) -> str:
    """Write atomically, keeping one backup. Never half-write the live config."""
    path = path or CONFIG_FILE
    ensure_dirs()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    text = dump(keys, settings)

    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        if os.path.exists(path):
            shutil.copy2(path, path + ".bak")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return path


def load_settings(path: str | None = None) -> dict:
    """The [deck] section, merged over the defaults."""
    path = path or CONFIG_FILE
    out = dict(SETTINGS)
    if not os.path.exists(path):
        return out
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    for k, v in (raw.get("deck") or {}).items():
        if k in out and isinstance(v, type(out[k])):
            out[k] = v
    return out


def blank(profile) -> dict[int, dict]:
    return {k: {} for k in profile.key_range}
