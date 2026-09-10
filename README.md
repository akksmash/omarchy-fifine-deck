# Fifine D6 Deck — Omarchy plugin

Bar widget for the **Fifine AmpliGame D6** stream deck (USB `3142:0060`) on Linux.
Shows whether the deck is connected and its key daemon is running; click to redraw
the key icons.

The D6 has no vendor Linux support. This plugin sits on top of a reverse-engineered
driver — see [the protocol notes](docs/protocol.md). Short version: `MOD 1` enables
key reporting, `MOD 2` drives the LCD screens, and no Windows software is required.

## Requires

- `fifine-deckd` — key daemon (systemd user unit)
- `deck-icons` — renders and pushes key icons
- `deck-status` — the JSON status line this widget reads
- udev rule granting your user the deck's hidraw nodes

## Install

```bash
omarchy plugin add https://github.com/akksmash/omarchy-fifine-deck --enable
```

## Settings

| Key | Default | Meaning |
|---|---|---|
| `intervalSeconds` | 15 | how often to poll `deck-status` |
| `showLabel` | true | show the text label beside the icon |

## Credits

Protocol work by **Steve** ([steve1.ai](https://steve1.ai)), done through a phone
webcam pointed at the device, led by **AK** ([@akksmash](https://instagram.com/akksmash)).
