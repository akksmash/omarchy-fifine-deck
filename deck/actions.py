"""Running what a key is bound to.

A binding is a command line, because that is the thing every desktop can already
do and every user already knows how to write. The only per-OS difference is
which shell interprets it, and how to detach it so a long-running program does
not outlive-or-block the daemon.
"""
from __future__ import annotations

import os
import shlex
import subprocess
import sys


def shell_command(cmd: str) -> list[str]:
    """Argv that runs `cmd` through this platform's shell."""
    if sys.platform == "win32":
        comspec = os.environ.get("COMSPEC", "cmd.exe")
        return [comspec, "/c", cmd]
    shell = os.environ.get("SHELL", "/bin/bash")
    # Login shell: key bindings routinely call things that live in a PATH set up
    # by the user's profile, which a bare systemd service does not inherit.
    return [shell, "-lc", cmd]


def _detach_kwargs() -> dict:
    if sys.platform == "win32":
        flags = 0
        flags |= getattr(subprocess, "DETACHED_PROCESS", 0)
        flags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        return {"creationflags": flags}
    return {"start_new_session": True}


def run(cmd: str, *, capture: bool = False, timeout: float | None = None):
    """Launch a key's command, detached. Returns the Popen, or CompletedProcess
    when `capture` is set (used by the editor's Test button)."""
    cmd = (cmd or "").strip()
    if not cmd:
        return None
    argv = shell_command(cmd)
    if capture:
        return subprocess.run(argv, capture_output=True, text=True,
                              timeout=timeout, check=False)
    return subprocess.Popen(argv, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, **_detach_kwargs())


def describe(cmd: str) -> str:
    """A short, safe rendering of a command for logs."""
    cmd = (cmd or "").strip()
    if len(cmd) <= 60:
        return cmd
    return cmd[:57] + "..."
