"""Supported devices, as data.

The Fifine AmpliGame D6 is one of a family of HID decks that all speak the same
"CRT" command protocol (Mirabox Stream Dock, Ajazz, and the various
"HOTSPOTEKUSB HID DEMO" clones). For those, adding support is a table entry
rather than code: the wire protocol is identical and only the geometry differs.

A genuinely different deck (Elgato, for instance) speaks a different protocol
and needs a new driver module in deck/drivers/ — but everything above the wire
(config, rendering, the editor, key actions) is already device-agnostic, so a
driver only has to implement the Driver interface in deck/drivers/__init__.py.

ADDING A DEVICE
---------------
Plug it in and run `deck-status --probe`. If it reports a vendor interface with
usage page 0xff__, it is very likely a member of this family: add a Profile
below with its VID/PID and grid, and try `deck-icons --dry-run`. Please send a
pull request with what you find, including whether it worked.
"""
from __future__ import annotations


class Profile:
    """Everything that differs between decks of the same protocol family."""

    def __init__(self, *, name, vendor_id, product_id, driver="crt",
                 cols=5, rows=3, tile=85, packet=512, image="JPEG",
                 rotate=180, flip_rows=True, max_tile_bytes=2300,
                 brightness=100, tested=False, notes=""):
        self.name = name
        self.vendor_id = vendor_id
        self.product_id = product_id
        self.driver = driver
        self.cols = cols
        self.rows = rows
        self.tile = tile
        self.packet = packet
        self.image = image
        self.rotate = rotate
        self.flip_rows = flip_rows
        self.max_tile_bytes = max_tile_bytes
        self.brightness = brightness
        self.tested = tested
        self.notes = notes

    @property
    def keys(self) -> int:
        return self.cols * self.rows

    @property
    def key_range(self):
        return range(1, self.keys + 1)

    def screen_index(self, key: int) -> int:
        """Map a key index to the screen index that sits under it.

        Key events are numbered in reading order (top-left = 1). On this family
        the panel is mounted inverted, so the screens are numbered bottom-up
        (bottom-left = 1). Without the flip every icon lands one row away from
        the key that triggers it.
        """
        if not self.flip_rows:
            return key
        row, col = divmod(key - 1, self.cols)
        return (self.rows - 1 - row) * self.cols + col + 1

    def key_for_screen(self, screen: int) -> int:
        """Inverse of screen_index(). The row flip is its own inverse."""
        return self.screen_index(screen)

    def __repr__(self):
        return (f"<Profile {self.name} {self.vendor_id:04x}:{self.product_id:04x} "
                f"{self.cols}x{self.rows}>")


DEVICES = [
    Profile(
        name="Fifine AmpliGame D6",
        vendor_id=0x3142, product_id=0x0060,
        cols=5, rows=3, tile=85, packet=512, image="JPEG",
        tested=True,
        notes="Reverse-engineered by photographing the panel; product string "
              "'HOTSPOTEKUSB HID DEMO'. The reference device for this project.",
    ),
    # Community-reported sibling. opendeck-ampgd6 targets this PID, so the
    # hardware exists, but nobody has run THIS code against one. Same family,
    # so the geometry below is the D6's and may need adjusting.
    Profile(
        name="Fifine AmpliGame D6 (rev 0007)",
        vendor_id=0x3142, product_id=0x0007,
        cols=5, rows=3, tile=85, packet=512, image="JPEG",
        tested=False,
        notes="UNTESTED. Reported by opendeck-ampgd6 as a different revision. "
              "If you own one, please report whether this profile works.",
    ),
]


def find_profile(vendor_id: int, product_id: int) -> Profile | None:
    for p in DEVICES:
        if p.vendor_id == vendor_id and p.product_id == product_id:
            return p
    return None


def default_profile() -> Profile:
    return DEVICES[0]
