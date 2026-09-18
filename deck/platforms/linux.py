"""Linux integration: a udev rule for permissions, one systemd user unit.

Only ONE unit is installed, deliberately. An earlier layout had a second
oneshot unit that drew the icons, ordered After= the daemon and WantedBy=
graphical-session.target -- while the daemon was itself After= that target.
systemd spotted the loop and resolved it the only way it can:

    graphical-session.target: Found ordering cycle: ...
    Job fifine-deck-icons.service/start deleted to break ordering cycle

The icons unit was silently dropped at every login, so the deck stayed dark and
nothing reported an error. Drawing now belongs to the daemon, which already
detects hotplug, so there is no second unit and no cycle to fall into again.
"""
from __future__ import annotations

import os
import shutil
import subprocess

NAME = "linux"
UNIT = "fifine-deckd.service"
LEGACY_UNITS = ("fifine-deck-icons.service",)
UDEV_RULE = "/etc/udev/rules.d/99-fifine-deck.rules"
LEGACY_UDEV = "/etc/udev/rules.d/99-fifine-d6.rules"

UNIT_DIR = os.path.expanduser("~/.config/systemd/user")


def unit_text(exec_path: str) -> str:
    return f"""\
[Unit]
Description=Deck key daemon (Fifine AmpliGame D6 and friends)
Documentation=https://github.com/akksmash/omarchy-fifine-deck
After=graphical-session.target
PartOf=graphical-session.target

# Deliberately no second unit for drawing icons: the daemon draws on hotplug.
# A separate icons unit ordered after this one, but wanted by
# graphical-session.target, forms an ordering cycle that systemd resolves by
# silently deleting the icons job -- which is exactly how this deck spent a
# week dark. See the module docstring.

[Service]
Type=simple
ExecStart={exec_path} run
Restart=always
RestartSec=3

[Install]
WantedBy=graphical-session.target
"""


def udev_text(devices) -> str:
    lines = [
        "# Deck devices: grant the logged-in user the hidraw nodes.",
        "# OWNER is set as well as uaccess because uaccess ACLs are applied by",
        "# systemd-logind on hotplug only, and do not appear on `udevadm trigger`.",
        "",
    ]
    for d in devices:
        vid, pid = f"{d.vendor_id:04x}", f"{d.product_id:04x}"
        lines.append(f"# {d.name}")
        for sub in ("usb", "hidraw", "input"):
            lines.append(
                f'SUBSYSTEM=="{sub}", ATTRS{{idVendor}}=="{vid}", '
                f'ATTRS{{idProduct}}=="{pid}", MODE="0660", TAG+="uaccess"')
        lines.append("")
    return "\n".join(lines)


def _run(argv, **kw):
    return subprocess.run(argv, check=False, text=True, **kw)


def install_udev(devices, *, sudo: bool = True) -> tuple[bool, str]:
    """Write the udev rule. Needs root, so this shells out to sudo."""
    text = udev_text(devices)
    tmp = "/tmp/99-fifine-deck.rules"
    with open(tmp, "w") as f:
        f.write(text)
    pre = ["sudo"] if sudo and os.geteuid() != 0 else []
    r = _run(pre + ["install", "-m", "0644", tmp, UDEV_RULE])
    if r.returncode != 0:
        return False, f"could not write {UDEV_RULE} (need root)"
    _run(pre + ["udevadm", "control", "--reload-rules"])
    _run(pre + ["udevadm", "trigger"])
    msg = f"installed {UDEV_RULE}"
    if os.path.exists(LEGACY_UDEV):
        _run(pre + ["rm", "-f", LEGACY_UDEV])
        msg += f"; removed superseded {LEGACY_UDEV}"
    return True, msg


def install_autostart(exec_path: str) -> tuple[bool, str]:
    """Install and enable the daemon unit; remove the cycle-forming legacy one."""
    os.makedirs(UNIT_DIR, exist_ok=True)
    notes = []

    for legacy in LEGACY_UNITS:
        path = os.path.join(UNIT_DIR, legacy)
        if os.path.exists(path):
            _run(["systemctl", "--user", "disable", "--now", legacy],
                 capture_output=True)
            os.unlink(path)
            notes.append(f"removed {legacy} (it formed an ordering cycle and "
                         f"never ran)")

    with open(os.path.join(UNIT_DIR, UNIT), "w") as f:
        f.write(unit_text(exec_path))
    _run(["systemctl", "--user", "daemon-reload"])
    r = _run(["systemctl", "--user", "enable", "--now", UNIT], capture_output=True)
    ok = r.returncode == 0
    notes.append(f"{'enabled' if ok else 'FAILED to enable'} {UNIT}")
    return ok, "; ".join(notes)


def reload_daemon() -> tuple[bool, str]:
    r = _run(["systemctl", "--user", "restart", UNIT], capture_output=True)
    if r.returncode == 0:
        return True, f"restarted {UNIT}"
    return False, (r.stderr or "").strip() or "restart failed"


def daemon_running() -> bool:
    r = _run(["systemctl", "--user", "is-active", "--quiet", UNIT])
    return r.returncode == 0


def notes() -> list[str]:
    out = []
    if not shutil.which("magick") and not shutil.which("convert"):
        out.append("ImageMagick is not installed: pacman -S imagemagick")
    return out
