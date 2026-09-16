"""The "CRT" protocol family (Fifine D6, Mirabox Stream Dock, Ajazz, clones).

Every command is  00 "CRT" 00 00 <CMD...>  padded to 1 + packet_size, sent on
the vendor HID interface. The leading 0x00 is the HID report ID.

    MOD 1   key reporting on. Events arrive as
            41 43 4B 00 00 4F 4B 00 00 <key> <state>   ("ACK\\0\\0OK\\0\\0")
    MOD 2   display mode. Images are JPEG, tile-sized, in packet-sized chunks.
    DIS     begin a session          LIG n   brightness
    CLE ff  clear all screens        STP     commit
    BAT     begin one image: length hi, length lo, screen index

Two hard-won facts, both of which produce convincing false negatives:

  * MOD 2 does not render on a cold device. Modes 0 and 1 have to be exercised
    first, with settling time between mode switches. That is what prime() is for.
  * The device never ACKs anything. There is no feedback channel at all, so a
    change to this file cannot be verified from software -- only by looking at
    the panel. Do not "fix" timings here without eyes on the hardware.
"""
from __future__ import annotations

import time

from . import Driver

ACK_PREFIX = bytes([0x41, 0x43, 0x4B, 0x00, 0x00, 0x4F, 0x4B, 0x00, 0x00])

MODE_KEYS = 1
MODE_DISPLAY = 2

# How much throwaway data to push while priming the device into an accepting
# state. The device tolerates a limited total volume before it stops rendering
# until power-cycled, so this matters a great deal:
#
#   commands  mode switches only, no image data at all.      ~0 KB
#   light     one tiny solid tile per screen per pass.       ~80 KB
#   full      the real artwork, at every priming geometry.   ~1.4 MB  (legacy)
#
# "full" is what the original script did -- by accident, since it had a helper
# to avoid exactly that and never called it. It is kept only for A/B testing.
PRIME_STRATEGIES = ("commands", "light", "full")


def crt(*payload: int) -> bytes:
    return bytes([0x00, 0x43, 0x52, 0x54, 0x00, 0x00]) + bytes(payload)


def _a(s: str):
    return tuple(s.encode())


class CrtDriver(Driver):

    def __init__(self, tr, profile):
        super().__init__(tr, profile)
        self._buf = b""

    # -- plumbing ---------------------------------------------------------

    def _cmd(self, payload: bytes, packet: int | None = None) -> None:
        pkt = packet or self.profile.packet
        self.tr.write(payload + b"\x00" * (1 + pkt - len(payload)))

    def _chunks(self, data: bytes, packet: int, pace: float = 0.0) -> None:
        for off in range(0, len(data), packet):
            c = data[off:off + packet]
            self.tr.write(b"\x00" + c + b"\x00" * (packet - len(c)))
            if pace:
                time.sleep(pace)

    # -- input ------------------------------------------------------------

    def activate_keys(self) -> None:
        """MOD 1 turns key reporting on.

        Deliberately no CONNECT: it clears the screens, and key events arrive
        perfectly well without it.
        """
        self._cmd(crt(*_a("MOD"), 0x00, 0x00, 0x30 + MODE_KEYS))
        time.sleep(0.2)

    def read_events(self, timeout_ms: int = 1000):
        """Yield (key, state), tolerating partial and batched reports.

        Reports are located by scanning for the ACK prefix rather than by fixed
        offset, which also makes this indifferent to whether the transport
        hands back a leading report-ID byte.
        """
        data = self.tr.read(4096, timeout_ms)
        if not data:
            return
        buf = self._buf + data
        i = 0
        while True:
            j = buf.find(ACK_PREFIX, i)
            if j < 0:
                break
            if j + len(ACK_PREFIX) + 1 >= len(buf):
                break                      # truncated; keep for the next read
            yield buf[j + 9], buf[j + 10]
            i = j + 11
        # Retain only a possible partial tail, never an unbounded backlog.
        self._buf = buf[max(i, len(buf) - len(ACK_PREFIX) - 1):]

    # -- output -----------------------------------------------------------

    def set_brightness(self, pct: int) -> None:
        self._cmd(crt(*_a("LIG"), 0, 0, max(0, min(100, int(pct)))))

    def _begin(self, mode: int, packet: int) -> None:
        """Open a session in `mode` and blank the screens."""
        self._cmd(crt(*_a("DIS")), packet);                    time.sleep(0.1)
        self._cmd(crt(*_a("LIG"), 0, 0, 0, 0), packet);        time.sleep(0.1)
        self._cmd(crt(*_a("MOD"), 0, 0, 0x30 + mode), packet); time.sleep(0.2)
        self._cmd(crt(*_a("LIG"), 0, 0, self.profile.brightness), packet)
        time.sleep(0.2)
        self._cmd(crt(*_a("CLE"), 0, 0, 0, 0xFF), packet)
        self._cmd(crt(*_a("STP")), packet)
        time.sleep(0.25)

    def clear(self) -> None:
        self._begin(MODE_DISPLAY, self.profile.packet)
        self._cmd(crt(*_a("STP")))

    def prime(self, strategy: str = "light", tiles: dict[int, bytes] | None = None) -> None:
        """Walk the device through modes 0 and 1 so MOD 2 will render.

        Skipping this on a cold device produces a lit backlight and no image,
        which looks exactly like a protocol bug and is not one.
        """
        if strategy not in PRIME_STRATEGIES:
            raise ValueError(f"unknown prime strategy {strategy!r}")

        p = self.profile
        geometries = ((p.tile, p.packet), (p.tile + 10, p.packet * 2))
        for mode in (0, 1):
            for fmt in (p.image, "BMP"):
                for size, packet in geometries:
                    self._begin(mode, packet)
                    if strategy != "commands":
                        self._prime_images(size, fmt, packet, strategy, tiles)
                    self._cmd(crt(*_a("STP")), packet)
                    time.sleep(2.0)        # mode switches need settling time

    def _prime_images(self, size, fmt, packet, strategy, tiles) -> None:
        from .. import render
        p = self.profile
        for screen in range(1, p.keys + 1):
            if strategy == "full" and tiles:
                # Legacy behaviour: re-encode the real artwork at every priming
                # geometry. Enormous, and the reason the device gives up early.
                data = render.reencode(tiles[p.key_for_screen(screen)], size, fmt)
            else:
                data = render.solid_tile(size, fmt)
            self._cmd(crt(*_a("BAT"), 0, 0,
                          (len(data) >> 8) & 0xFF, len(data) & 0xFF, screen), packet)
            self._chunks(data, packet)

    def draw(self, tiles: dict[int, bytes], sweeps: int = 2) -> None:
        """Push tiles, keyed by KEY index.

        Screen indices must ascend, and each image is committed with its own
        STP: batching the whole set overflows the device buffer once tiles get
        past about a kilobyte, and only the last few survive.

        `sweeps` defaults to 2 because the device evicts the earliest images of
        a batch, leaving the first screens blank after a single pass. That is a
        workaround for a cause still not understood, not a fix.
        """
        p = self.profile
        self._begin(MODE_DISPLAY, p.packet)
        for _ in range(sweeps):
            for screen in range(1, p.keys + 1):
                key = p.key_for_screen(screen)
                data = tiles.get(key)
                if not data:
                    continue
                self._cmd(crt(*_a("BAT"), 0, 0,
                              (len(data) >> 8) & 0xFF, len(data) & 0xFF, screen))
                self._chunks(data, p.packet, pace=0.0015)
                self._cmd(crt(*_a("STP")))
                time.sleep(0.05)
        self._cmd(crt(*_a("STP")))
