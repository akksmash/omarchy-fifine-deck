"""Where things live, per OS.

Linux keeps the XDG locations the project has always used, so an existing
install keeps its config without being migrated.
"""
from __future__ import annotations

import os
import sys

APP = "fifine-deck"


def _linux_dirs():
    cfg = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    data = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    cache = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return os.path.join(cfg, APP), os.path.join(data, APP), os.path.join(cache, APP)


def _windows_dirs():
    roaming = os.environ.get("APPDATA") or os.path.expanduser("~\\AppData\\Roaming")
    local = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~\\AppData\\Local")
    return (os.path.join(roaming, APP), os.path.join(local, APP),
            os.path.join(local, APP, "cache"))


def _macos_dirs():
    base = os.path.expanduser("~/Library/Application Support")
    return (os.path.join(base, APP), os.path.join(base, APP),
            os.path.join(os.path.expanduser("~/Library/Caches"), APP))


if sys.platform == "win32":
    CONFIG_DIR, DATA_DIR, CACHE_DIR = _windows_dirs()
elif sys.platform == "darwin":
    CONFIG_DIR, DATA_DIR, CACHE_DIR = _macos_dirs()
else:
    CONFIG_DIR, DATA_DIR, CACHE_DIR = _linux_dirs()

CONFIG_FILE = os.environ.get("FIFINE_DECK_CONFIG") or os.path.join(CONFIG_DIR, "keys.toml")
ART_DIR = os.path.join(DATA_DIR, "art")


def ensure_dirs() -> None:
    for d in (CONFIG_DIR, DATA_DIR, ART_DIR, CACHE_DIR):
        os.makedirs(d, exist_ok=True)
