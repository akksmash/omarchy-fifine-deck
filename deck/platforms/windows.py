"""Windows integration.

UNTESTED. Written against documented behaviour, never run on real Windows --
the development machine is Linux and has no virtualisation available. The wire
protocol is identical (hidapi hides the OS difference, and HID report IDs are
already part of every packet), so the risk is concentrated here, in the
install-time plumbing, rather than in the driver.

If you run this on Windows, please report what happened -- including that it
worked, which is just as useful.

Notes for whoever tests it first:
  * Windows needs no permission grant for vendor-defined HID: unlike Linux,
    non-exclusive access to a non-keyboard/mouse HID device is open to any
    process. So there is no equivalent of the udev rule.
  * hidapi.dll must be findable. Ship it beside the code, or install
    ImageMagick+hidapi via winget/vcpkg.
  * The deck also exposes a keyboard interface. Windows may claim it and turn
    key presses into keystrokes; the vendor interface (0) is the one used here.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys

NAME = "windows"


def _startup_dir() -> str:
    return os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows",
                        "Start Menu", "Programs", "Startup")


def _launcher_path() -> str:
    return os.path.join(_startup_dir(), "fifine-deck.cmd")


def install_udev(devices, *, sudo: bool = True) -> tuple[bool, str]:
    """No-op: Windows grants HID access to vendor-defined devices by default."""
    return True, "no permission setup needed on Windows"


def install_autostart(exec_path: str) -> tuple[bool, str]:
    """Start the daemon at logon via a Startup-folder launcher.

    A .cmd running pythonw keeps no console window open. Task Scheduler would
    be tidier but needs elevation, which an install script should not require.
    """
    d = _startup_dir()
    if not os.path.isdir(d):
        return False, f"startup folder not found: {d}"

    pyw = shutil.which("pythonw") or shutil.which("pythonw.exe") or sys.executable
    body = (
        "@echo off\r\n"
        "rem Starts the deck key daemon at logon. Delete this file to disable.\r\n"
        f'start "" "{pyw}" "{exec_path}" run\r\n'
    )
    try:
        with open(_launcher_path(), "w", newline="") as f:
            f.write(body)
    except OSError as e:
        return False, f"could not write launcher: {e}"
    return True, f"installed {_launcher_path()} (runs at logon)"


def reload_daemon() -> tuple[bool, str]:
    """Restart the daemon: kill any running copy and relaunch it detached."""
    subprocess.run(["taskkill", "/F", "/IM", "pythonw.exe", "/FI",
                    "WINDOWTITLE eq fifine-deck*"], check=False,
                   capture_output=True)
    launcher = _launcher_path()
    if not os.path.exists(launcher):
        return False, "no launcher installed; run the installer first"
    subprocess.Popen(["cmd", "/c", launcher],
                     creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
    return True, "relaunched the daemon"


def daemon_running() -> bool:
    r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq pythonw.exe"],
                       capture_output=True, text=True, check=False)
    return "pythonw.exe" in (r.stdout or "")


def notes() -> list[str]:
    out = ["Windows support is UNTESTED; please report what happens."]
    if not (shutil.which("magick") or shutil.which("convert")):
        out.append("ImageMagick not found: winget install ImageMagick.ImageMagick")
    return out
