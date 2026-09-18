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
#   commands  mode switches only, no image data at all.       ~42 KB
#   light     flat solid tiles, JPEG geometries only.          ~50 KB
#   jpeg      the real artwork, JPEG geometries only.         ~209 KB
#   full      the real artwork at every geometry, BMP too.   ~1732 KB  (legacy)
#
# Note the BMP passes are the entire difference in scale: BMP is uncompressed,
# so a "tiny" solid BMP tile is still 21-27KB and 30 of them is 1.6MB. Any
# strategy that touches BMP costs roughly what "full" costs, whatever it draws.
#
# Observed on real hardware: "full" renders (it is what the original script did,
# by accident -- it had a helper to avoid exactly that and never called it),
# while "commands" and "light" render nothing at all. So priming appears to need
# real image volume, not merely the mode switches, and the two BMP passes are
# ~1.45MB of that 1.5MB because BMP is uncompressed. "jpeg" is the middle
# ground: enough real data to prime, little enough to leave the device's
# budget for the draw that follows.
PRIME_STRATEGIES = ("commands", "light", "jpeg", "full")


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

    def keepalive(self) -> None:
        """Re-assert brightness, to stop the panel blanking itself when idle.

        Observed: a completed draw renders all 15 keys, then the panel goes dark
        on its own with the host sending nothing at all. So the device wants to
        hear from us. LIG is used for this because it is already part of the
        normal draw sequence and demonstrably does not clear the screens --
        unlike CONNECT, which does, and must never be used as a keepalive.
        """
        self.set_brightness(self.profile.brightness)

    def set_brightness(self, pct: int) -> None:
        self._cmd(crt(*_a("LIG"), 0, 0, max(0, min(100, int(pct)))))

    def _begin(self, mode: int, packet: int, clear: bool = True) -> None:
        """Open a session in `mode`, optionally blanking the screens.

        `clear=False` is for continuing a draw that is split across several
        sessions: only the first group may clear, or each group would wipe the
        groups before it.
        """
        self._cmd(crt(*_a("DIS")), packet);                    time.sleep(0.1)
        self._cmd(crt(*_a("LIG"), 0, 0, 0, 0), packet);        time.sleep(0.1)
        self._cmd(crt(*_a("MOD"), 0, 0, 0x30 + mode), packet); time.sleep(0.2)
        self._cmd(crt(*_a("LIG"), 0, 0, self.profile.brightness), packet)
        time.sleep(0.2)
        if clear:
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
        # Only "full" pays for the BMP geometries; see the note above.
        formats = (p.image, "BMP") if strategy == "full" else (p.image,)
        for mode in (0, 1):
            for fmt in formats:
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
            if strategy in ("full", "jpeg") and tiles:
                # Legacy behaviour: re-encode the real artwork at every priming
                # geometry. Enormous, and the reason the device gives up early.
                data = render.reencode(tiles[p.key_for_screen(screen)], size, fmt)
            else:
                data = render.solid_tile(size, fmt)
            self._cmd(crt(*_a("BAT"), 0, 0,
                          (len(data) >> 8) & 0xFF, len(data) & 0xFF, screen), packet)
            self._chunks(data, packet)

    def draw(self, tiles: dict[int, bytes], sweeps: int = 1,
             key_delay: float = 0.30, packet_pace: float = 0.0015,
             batch: int = 1, clear_first: bool = False) -> None:
        """Push tiles, keyed by KEY index.

        ONE IMAGE PER SESSION (batch=1) is the whole trick, and it is why this
        works on a device that otherwise renders almost nothing.

        However many images the device is willing to accept in a single display
        session -- and that number falls as the device is used, from 15 down to
        1 over an evening -- only the LAST ones survive. Giving every screen its
        own short session makes that capacity irrelevant: each image is the last
        one of its own batch. Verified by camera, twice in a row, on a device
        that moments earlier was accepting exactly one image per session.

        `clear_first` is off by default for the same reason: CLE wipes whatever
        previous passes managed to land. Every screen gets an image here anyway,
        so there is nothing to clear.

        Screen indices must ascend, and each image is committed with its own
        STP: batching the whole set overflows the device buffer once tiles get
        past about a kilobyte, and only the last few survive.

        `sweeps` defaults to 2 because the device evicts the earliest images of
        a batch, leaving the first screens blank after a single pass. That is a
        workaround for a cause still not understood, not a fix.
        """
        p = self.profile
        screens = list(range(1, p.keys + 1))
        groups = ([screens] if batch <= 0 else
                  [screens[i:i + batch] for i in range(0, len(screens), batch)])

        for gi, group in enumerate(groups):
            self._begin(MODE_DISPLAY, p.packet, clear=(clear_first and gi == 0))
            self._draw_group(group, tiles, sweeps, key_delay, packet_pace)
            self._cmd(crt(*_a("STP")))

    def _draw_group(self, group, tiles, sweeps, key_delay, packet_pace) -> None:
        p = self.profile
        for _ in range(sweeps):
            for screen in group:
                key = p.key_for_screen(screen)
                data = tiles.get(key)
                if not data:
                    continue
                self._cmd(crt(*_a("BAT"), 0, 0,
                              (len(data) >> 8) & 0xFF, len(data) & 0xFF, screen))
                self._chunks(data, p.packet, pace=packet_pace)
                self._cmd(crt(*_a("STP")))
                # The device evicts the EARLIEST images of a batch when pushed
                # faster than it commits them to the panels: with 50ms here only
                # the last 9-10 screens survived. Give it time to land each one.
                time.sleep(key_delay)
