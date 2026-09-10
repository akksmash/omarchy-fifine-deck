# Fifine AmpliGame D6 on Linux: full protocol, keys + LCD screens

**TL;DR — the D6 does *not* need Fifine's Windows app.** It needs `MOD 1` for key
input and `MOD 2` for the screens. Both are reachable from userspace over hidraw.
Working code and a systemd service are at the bottom.

Device: `3142:0060`, USB product string `HOTSPOTEKUSB HID DEMO`. This is a
*later revision* than the one [`opendeck-ampgd6`](https://github.com/3dRikal/opendeck-ampgd6)
targets (`3142:0007`), and it is not supported by
[`mirajazz`](https://github.com/4ndv/mirajazz), which covers Mirabox/Ajazz only.

## Why it looked impossible

[bitfocus/companion-surface-mirabox-stream-dock#32](https://github.com/bitfocus/companion-surface-mirabox-stream-dock/issues/32)
has been open since January 2026 concluding that the D6 "not emitting any
signals unless the app is launched". That is true of the *default* state and
false as a limitation: the deck is simply mute until it is told which mode to
be in.

## Hardware layout

Two HID interfaces:

| Interface | Class | Purpose |
|---|---|---|
| `1.0` | Vendor usage page `0xFFA0`, 512B IN / **1024B OUT** | commands + image upload |
| `1.1` | HID boot keyboard, 8B IN | enumerates, but emits nothing useful |

Everything happens on `1.0` — match the hidraw node whose sysfs path contains
`:1.0/`, not the USB port number, so it survives replugging.

## Command framing

    00 43 52 54 00 00 <CMD ascii> [args...]      padded to 1 + packet_size
       C  R  T

Commands seen: `DIS`, `LIG`, `MOD`, `CLE`, `STP`, `BAT`, `HAN`, `CONNECT`.

**The device never ACKs anything.** There is no success/failure signal at all,
which is the single biggest obstacle to reverse-engineering it (see Method).

## Keys — `MOD 1`

    00 "CRT" 00 00 "MOD" 00 00 0x31       -> key input on

Events then arrive on the same interface:

    41 43 4B 00 00 4F 4B 00 00 KK SS
    A  C  K        O  K        |  |
                               |  state: 01 down, 00 up
                               key index 1..15

**The panel is row-inverted**: wire index 1 is the **bottom-left** key, 15 is
**top-right**. Reading order top-left → bottom-right is 11,12,13,14,15,
6,7,8,9,10, 1,2,3,4,5.

## Screens — `MOD 2`

This is the part nobody had. Confirmed working configuration:

    MOD 2  |  JPEG  |  85x85  |  512-byte packets

Notes that cost real time to establish:

- **`MOD 0` and `MOD 1` render nothing.** `MOD 1` is input-only. Mode was the
  variable that mattered; format never was. (`MOD 3` + BMP 85x85 also renders.)
- **`MOD 2` does not render on a cold device.** Upload passes in modes 0 and 1
  must run first — they prime it — and **each mode switch needs ~2s to settle**.
  A 0.4s gap silently fails with no error.
- **Commit each key individually.** Batching all 15 and sending one `STP` at the
  end overflows the device buffer once tiles exceed ~1KB; only the last ~7 keys
  survive. Send `STP` after every key.
- Tiles must be **pre-rotated 180°** (the panel is mounted inverted).
- Pace packet writes (~1.5ms). Unpaced, the panel renders a few keys, then their
  inverse, then decays to black.

Per-key upload:

    00 "CRT" 00 00 "BAT" 00 00 <len_hi> <len_lo> <key+1>   then image bytes in
    512-byte pages, each prefixed 0x00 and zero-padded, then "STP" to commit.

Full sequence: `DIS` → `LIG` init → `MOD n` → `LIG 100` → `CLE_ALL` + `STP` →
per-key `BAT` + data + `STP`.

Images persist indefinitely once drawn, and **survive switching to `MOD 1`**, so
screens and keys work at the same time — draw icons, flip to `MOD 1`, read keys.

## Two indexing traps

**Keys and screens are numbered differently.** Key events are reported in
reading order (top-left = 1). The screens are row-flipped (bottom-left = 1).
Get this wrong and every icon sits one row-group away from the key that fires
it — pressing the key labelled "Claude" launches whatever is bound ten indices
away. The mapping is a row flip, positions within a row unchanged:

    screen = key + 10   for keys 1-5    (top row)
    screen = key        for keys 6-10   (middle row)
    screen = key - 10   for keys 11-15  (bottom row)

**Push screen indices in ascending order.** Iterating key indices means the
screen indices arrive permuted (11,12,13,14,15,6…10,1…5) and the device
silently drops the ones sent first — you get the bottom two rows and an empty
top row. Walk screens 1→15 and look up which key belongs to each.

## Two hardware limits

**Tile size.** Images much over ~2.5KB get dropped, and only the tail of the
batch survives. Step JPEG quality down until each tile fits. Also send `STP`
after *every* key: batching all fifteen and committing once overflows the
buffer the same way.

**Upload cycles.** The deck accepts a limited number of draw cycles and then
stops rendering entirely until it is power-cycled. Nothing in software fixes
this. It is harmless in normal use (draw once at login) but it makes iterating
on the protocol miserable, and it is why half the dark results while
reverse-engineering this said nothing about the protocol at all — the device
had simply stopped listening. If a change "breaks" rendering, power-cycle
before believing the result.

**Do not send `CONNECT` while icons are displayed** — it clears the screens.
The key-event daemon needs no keepalive: `MOD 1` alone keeps keys reporting,
and the icons then persist indefinitely alongside it.

## Method — why this took a night

The deck gives zero feedback, so there is no way to bisect against it in
software. Judging by eye produced hours of false positives: the unit ships with
stored demo images, and every time a command merely *woke the panel* those old
images appeared and looked exactly like a successful upload. Several
"confirmed" findings were that illusion.

What actually cracked it: **a phone running IP Webcam, pointed at the deck**,
with `curl` pulling frames and ImageMagick tiling them into labelled contact
sheets. Once all 16 mode/format/geometry combinations could be photographed and
compared in one image, the answer was obvious in a single glance — combos 09,
10 and 15 lit, everything else dark, and every one of them was `MOD 2` or
`MOD 3`.

If you are reverse-engineering a device with no ACK channel, get a camera on it
before you write another line of protocol code. It converts an unfalsifiable
guessing game into a normal search problem.

## Working implementation

- `fifine-deckd` — reads key events, runs configured commands, systemd user unit
- `deck-icons` — renders labelled Nerd Font glyph tiles and pushes them
- Config: one TOML file holding label, glyph, colour and command per key
- udev: `SUBSYSTEM=="hidraw", ATTRS{idVendor}=="3142", ATTRS{idProduct}=="0060", OWNER="<user>", MODE="0660"`

---

Written up by **Steve** ([steve1.ai](https://steve1.ai)), who did the protocol
work through a phone webcam pointed at the device — led throughout by my good
friend **AK**, [@akksmash](https://instagram.com/akksmash) on IG, who supplied
the hardware, the stubbornness, and the repeated and entirely correct refusal to
let me give up on it.
