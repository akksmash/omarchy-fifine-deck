"""Per-OS integration: device permissions, and starting the daemon at login.

Everything here is install-time plumbing. Nothing in the driver, renderer,
config or editor may import from it beyond `current()`.
"""
from __future__ import annotations

import sys


def current():
    if sys.platform == "win32":
        from . import windows
        return windows
    if sys.platform == "darwin":
        from . import unsupported
        return unsupported
    from . import linux
    return linux
