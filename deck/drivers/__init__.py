"""Driver interface and registry.

A driver owns exactly one thing: how to talk to a particular family of deck over
a Transport. Everything above it -- the key config, tile rendering, the editor,
running key actions -- is device-agnostic and must stay that way.

To support a new protocol family, add a module here exposing a Driver subclass
and register it in _REGISTRY. To support another deck that speaks a family's
existing protocol, add a Profile to deck/devices.py instead; no code required.
"""
from __future__ import annotations

from .. import transport as _transport
from ..devices import DEVICES, Profile, find_profile


class DeckNotFound(Exception):
    pass


class Driver:
    """Wire-level operations a deck must support."""

    def __init__(self, tr: _transport.Transport, profile: Profile):
        self.tr = tr
        self.profile = profile

    # -- input ------------------------------------------------------------
    def activate_keys(self) -> None:
        """Put the deck into its key-reporting mode."""
        raise NotImplementedError

    def read_events(self, timeout_ms: int = 1000):
        """Yield (key_index, state) pairs. state 1 = press, 0 = release."""
        raise NotImplementedError

    # -- output -----------------------------------------------------------
    def draw(self, tiles: dict[int, bytes]) -> None:
        """Push encoded images, keyed by KEY index (not screen index)."""
        raise NotImplementedError

    def clear(self) -> None:
        raise NotImplementedError

    def set_brightness(self, pct: int) -> None:
        raise NotImplementedError

    def close(self) -> None:
        self.tr.close()

    def __enter__(self): return self
    def __exit__(self, *exc): self.close()


def _registry():
    from . import crt
    return {"crt": crt.CrtDriver}


def discover(profiles=None):
    """Every attached deck we recognise, as (Profile, DeviceInfo) pairs."""
    found = []
    for p in (profiles or DEVICES):
        for info in _transport.enumerate_devices(p.vendor_id, p.product_id):
            if info.is_vendor_interface():
                found.append((p, info))
    return found


def open_deck(profile: Profile | None = None) -> Driver:
    """Open the first recognised deck. Raises DeckNotFound if there is none."""
    candidates = discover([profile] if profile else None)
    if not candidates:
        raise DeckNotFound(
            "no supported deck found. Check it is plugged in, and on Linux that "
            "the udev rule granted you its hidraw nodes (ls -l /dev/hidraw*).")
    prof, info = candidates[0]
    cls = _registry().get(prof.driver)
    if cls is None:
        raise DeckNotFound(f"no driver {prof.driver!r} for {prof.name}")
    return cls(_transport.open_device(info), prof)
