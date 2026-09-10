#!/usr/bin/env python3
"""
Minimal, dependency-free driver for the Fifine AmpliGame D6 (USB 3142:0060).

    sudo cp 99-fifine-d6.rules /etc/udev/rules.d/
    sudo udevadm control --reload && sudo udevadm trigger --action=add
    python3 fifine_d6.py demo     # draw 15 numbered keys, then print presses

Only the standard library is used. Images are made with ImageMagick (`magick`),
which is the one external tool; swap draw_tile() for Pillow if you prefer.

Protocol summary
----------------
Commands are `00 "CRT" 00 00 <CMD ascii> [args]` padded to 1 + packet_size, on
the vendor HID interface (the hidraw node whose sysfs path contains ":1.0/").

    MOD 1   key reporting on. Events: 41 43 4B 00 00 4F 4B 00 00 <key> <state>
    MOD 2   display mode: JPEG, 85x85, 512-byte packets

Gotchas that will otherwise cost you a night:
  * MOD 2 does not render on a cold device. Run passes in modes 0 and 1 first
    to prime it, allowing ~2s per mode switch.
  * Keys and screens are indexed differently. Keys are reading-order
    (top-left = 1); screens are row-flipped (bottom-left = 1).
  * Push screen indices ascending, keep tiles under ~2.5KB, and send STP after
    every key. Batch commits overflow the buffer.
  * Never send CONNECT while icons are displayed - it clears them. No keepalive
    is needed; MOD 1 alone keeps keys reporting.
  * The device never ACKs anything, and stops rendering after a limited number
    of draw cycles until power-cycled. Power-cycle before believing a failure.
"""
import glob, os, select, subprocess, sys, tempfile, time

VID_PID   = "3142:0060"
PKT       = 512      # protocol v1 packet size
SIZE      = 85       # tile geometry the display mode expects
KEY_COUNT = 15
ACK       = bytes([0x41, 0x43, 0x4B, 0x00, 0x00, 0x4F, 0x4B, 0x00, 0x00])


def crt(*payload):
    """Frame a command: 00 'CRT' 00 00 <payload>."""
    return bytes([0x00, 0x43, 0x52, 0x54, 0x00, 0x00]) + bytes(payload)


def _a(text):
    return tuple(text.encode())


DIS      = crt(*_a("DIS"))
STP      = crt(*_a("STP"))
LIG_INIT = crt(*_a("LIG"), 0, 0, 0, 0)
LIG      = lambda pct: crt(*_a("LIG"), 0, 0, pct)
MOD      = lambda m: crt(*_a("MOD"), 0, 0, 0x30 + m)
CLE_ALL  = crt(*_a("CLE"), 0, 0, 0, 0xFF)
BAT      = lambda n, key: crt(*_a("BAT"), 0, 0, (n >> 8) & 0xFF, n & 0xFF, key)


def find_device():
    """The vendor interface is 1.0; 1.1 is a plain keyboard and is not useful.
    Match the interface suffix, not the USB port, so it survives replugging."""
    for node in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        real = os.path.realpath(node)
        if VID_PID in real and ":1.0/" in real:
            return "/dev/" + os.path.basename(node)
    raise SystemExit(f"Fifine D6 ({VID_PID}) not found. Plugged in? udev rule installed?")


def screen_index(key):
    """Key index (as reported when pressed) -> screen index. A row flip."""
    if key <= 5:
        return key + 10      # top row
    if key <= 10:
        return key           # middle row unchanged
    return key - 10          # bottom row


def key_for_screen(scr):
    if scr <= 5:
        return scr + 10
    if scr <= 10:
        return scr
    return scr - 10


class Deck:
    def __init__(self, path=None):
        self.fd = os.open(path or find_device(), os.O_RDWR | os.O_NONBLOCK)

    def _send(self, packet, pkt=PKT):
        os.write(self.fd, packet + b"\x00" * (1 + pkt - len(packet)))

    def _upload(self, tiles, mode, pkt=PKT, pace=False):
        """One upload pass: set the mode, clear, then push every screen."""
        self._send(DIS, pkt);      time.sleep(0.12)
        self._send(LIG_INIT, pkt); time.sleep(0.12)
        self._send(MOD(mode), pkt); time.sleep(0.22)
        self._send(LIG(100), pkt); time.sleep(0.22)
        self._send(CLE_ALL, pkt); self._send(STP, pkt); time.sleep(0.3)
        for scr in range(1, KEY_COUNT + 1):          # ascending screen order
            data = tiles[key_for_screen(scr)]
            self._send(BAT(len(data), scr), pkt)
            for off in range(0, len(data), pkt):
                chunk = data[off:off + pkt]
                os.write(self.fd, b"\x00" + chunk + b"\x00" * (pkt - len(chunk)))
                if pace:
                    time.sleep(0.0015)
            if pace:
                self._send(STP, pkt)                  # commit each key
                time.sleep(0.05)
        self._send(STP, pkt)

    def draw(self, tiles):
        """tiles: {key_index: jpeg_bytes} for keys 1..15."""
        for mode in (0, 1):                           # prime: MOD 2 is inert cold
            for size, pkt in ((85, 512), (95, 1024)):
                self._upload(tiles, mode, pkt)
                time.sleep(2.0)                       # mode switches need settling
        for _ in range(2):                            # twice: the device evicts
            self._upload(tiles, 2, PKT, pace=True)    # the earliest tiles

    def listen(self, on_press):
        """Enable key reporting and call on_press(key_index) for each press."""
        self._send(MOD(1)); time.sleep(0.25)
        while True:
            if select.select([self.fd], [], [], 1.0)[0]:
                buf, i = os.read(self.fd, 4096), 0
                while True:
                    j = buf.find(ACK, i)
                    if j < 0 or j + len(ACK) + 1 >= len(buf):
                        break
                    key, state = buf[j + 9], buf[j + 10]
                    if state == 1:
                        on_press(key)
                    i = j + 11


def draw_tile(text, color):
    """A JPEG key face. Pre-rotated 180 - the panel is mounted inverted."""
    path = os.path.join(tempfile.gettempdir(), f"d6_{text}_{color}.jpg")
    subprocess.run([
        "magick", "-size", f"{SIZE}x{SIZE}", f"xc:{color}",
        "-gravity", "center", "-fill", "white", "-pointsize", "34",
        "-annotate", "0", str(text), "-rotate", "180",
        "-alpha", "off", "-quality", "85", f"JPEG:{path}"], check=True)
    return open(path, "rb").read()


if __name__ == "__main__":
    colors = ["#e0245e", "#1db954", "#e06c2b", "#2f6fd0", "#8b46c9",
              "#0f9aa8", "#d1345b", "#5566a8", "#c8871f", "#12a594",
              "#d84a72", "#3f7fb8", "#a4557f", "#2f9e5f", "#c26a2c"]
    deck = Deck()
    print("drawing 15 keys (takes ~30s: the priming passes are unavoidable)")
    deck.draw({k: draw_tile(k, colors[k - 1]) for k in range(1, KEY_COUNT + 1)})
    print("done. press keys - Ctrl+C to stop.")
    try:
        deck.listen(lambda k: print(f"  key {k} pressed"))
    except KeyboardInterrupt:
        print()
