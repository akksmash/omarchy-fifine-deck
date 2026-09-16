# Deck

Drive a **Fifine AmpliGame D6** stream deck — 15 keys, each with its own LCD —
on Linux and Windows, with no vendor software. Includes a drag-and-drop editor
for the keys.

The D6 has no Linux support of any kind from its manufacturer. This is a
reverse-engineered driver: `MOD 1` turns on key reporting, `MOD 2` drives the
screens, and no Windows software is needed to set any of it up. The full
protocol is written down in [docs/protocol.md](docs/protocol.md).

```
┌────────────────────────────────────────────┐
│  Deck Editor            [Redraw]  [Save]   │
├─────────────────────────┬──────────────────┤
│  ▣ ▣ ▣ ▣ ▣              │  Key 3           │
│  ▣ ▣ ▣ ▣ ▣   drag to    │  Label   [ ... ] │
│  ▣ ▣ ▣ ▣ ▣   rearrange  │  Command [ ... ] │
└─────────────────────────┴──────────────────┘
```

## Install

```bash
git clone https://github.com/akksmash/omarchy-fifine-deck
cd omarchy-fifine-deck
./install.sh
```

Needs Python 3.11+ and ImageMagick. `hidapi` is used when present and is
required off Linux; on Linux the driver falls back to raw `hidraw` with no
dependencies at all.

Then:

```bash
deck-editor          # customise the keys, drag and drop
deck-ctl status      # is it connected? is the daemon up?
deck-ctl redraw      # redraw the screens
```

## How it behaves

The daemon owns the device and redraws the keys **whenever the deck is plugged
in** — at boot with it attached, or when you plug it in later. Nothing else
opens the deck behind its back; the editor and `deck-ctl` ask the daemon to act.

That indirection is not ceremony. This hardware stops accepting images after a
limited volume of writes and only a power cycle clears that, so two processes
drawing at once is how you end up staring at a lit but empty panel.

## The editor

`deck-editor` serves a page on loopback and opens it. Drag a key onto another to
swap them (the generated artwork travels with the binding). Click a key to edit
its label, caption, command, colour, glyph and art prompt, with a live preview of
the key face. **Test command** runs the binding and shows you its output, which
beats finding out later on the hardware with no error message.

Nothing is written until you press **Save**; **Revert** really does revert.
Saving rewrites `~/.config/fifine-deck/keys.toml` and asks the daemon to redraw.

The editor runs shell commands — that is what a key binding *is* — so it binds
127.0.0.1 only, behind a per-run token that is never written to disk, rejects
non-loopback `Host` headers (DNS rebinding), and requires that token in a header
for anything that changes state.

## Configuration

`~/.config/fifine-deck/keys.toml`. Key indices are as the deck reports them, in
reading order — the screens are numbered differently and that is handled for you.

```toml
[deck]
prime = "commands"        # commands | light | full
sweeps = 2
brightness = 100
draw_on_attach = true

[keys."1"]
label   = "Terminal"
cmd     = "alacritty"
caption = "Terminal"
color   = "#abb2bf"
art     = "a terminal prompt chevron and cursor"
```

## Other decks

The D6 is one of a family that all speak the same `CRT` protocol (Mirabox Stream
Dock, Ajazz, the various *HOTSPOTEKUSB HID DEMO* clones). For those, support is a
table entry, not code — see [`deck/devices.py`](deck/devices.py). Run
`deck-ctl probe` to see what your device reports.

A deck speaking a *different* protocol needs a new module in `deck/drivers/`,
implementing the four methods in `deck/drivers/__init__.py`. Everything above the
wire — config, rendering, the editor, key actions — is already device-agnostic.

Pull requests adding a device are very welcome, including ones that just report
that a profile did or did not work.

## Platform support

| | |
|---|---|
| **Linux** | Tested. udev rule for permissions, systemd user service. |
| **Windows** | **Untested.** Written against documented hidapi behaviour; the wire protocol is identical. See `deck/platforms/windows.py`. Reports welcome. |
| **macOS** | Not supported. The driver may well work; no integration written. |

## Troubleshooting

**The deck is lit but blank, or only the last key drew.** It has stopped
accepting images. Unplug it and plug it back in — the daemon redraws on attach.
If it happens routinely, you are drawing too often or pushing too much: keep
`prime = "commands"`.

**Nothing at all, ever.** Check the udev rule took: `ls -l /dev/hidraw*` should
show the deck's nodes owned by you. Then `deck-ctl probe`.

**A key does nothing.** `deck-ctl status` to confirm the daemon is up, then
`journalctl --user -u fifine-deckd -f` and press it.

**Changed a caption but the key looks the same.** It shouldn't — tiles are cached
by content hash. If it persists, `rm -rf ~/.cache/fifine-deck`.

## Omarchy plugin

This repo is also an Omarchy plugin: a bar widget showing whether the deck is
connected and its daemon running, which redraws the icons when clicked.

```bash
omarchy plugin add https://github.com/akksmash/omarchy-fifine-deck --enable
```

| Setting | Default | Meaning |
|---|---|---|
| `intervalSeconds` | 15 | how often to poll `deck-ctl status --json` |
| `showLabel` | true | show the text label beside the icon |

## Credits

Protocol work by **Steve** ([steve1.ai](https://steve1.ai)), done with a phone
camera pointed at the panel, led by **AK**
([@akksmash](https://instagram.com/akksmash)).

Reported upstream as
[bitfocus/companion-surface-mirabox-stream-dock#32](https://github.com/bitfocus/companion-surface-mirabox-stream-dock/issues/32).

MIT licensed.
