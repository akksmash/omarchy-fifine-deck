"""Fallback for platforms with no integration written.

The driver itself may well work -- hidapi covers macOS too -- but nothing here
knows how to grant permissions or start the daemon at login, so those steps are
left to the user rather than guessed at.
"""
from __future__ import annotations

import shutil
import sys

NAME = sys.platform


def install_udev(devices, *, sudo: bool = True) -> tuple[bool, str]:
    return True, f"no permission setup written for {sys.platform}"


def install_autostart(exec_path: str) -> tuple[bool, str]:
    return False, (f"no autostart integration for {sys.platform}; "
                   f"run '{exec_path} run' yourself, or contribute an adapter "
                   f"in deck/platforms/")


def reload_daemon() -> tuple[bool, str]:
    return False, f"restart the daemon yourself on {sys.platform}"


def daemon_running() -> bool:
    return False


def notes() -> list[str]:
    out = [f"{sys.platform} has no platform adapter; the driver may still work."]
    if not (shutil.which("magick") or shutil.which("convert")):
        out.append("ImageMagick not found.")
    return out
