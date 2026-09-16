#!/usr/bin/env bash
# Install the deck driver, daemon and editor for the current user.
#
#   ./install.sh              copy into ~/.local and enable the service
#   ./install.sh --dev        symlink to this checkout instead of copying
#   ./install.sh --no-udev    skip the permission rule (skips the sudo prompt)
#   ./install.sh --uninstall  remove everything except your keys.toml
#
# Nothing here needs root except the udev rule, which grants your user access
# to the deck's hidraw nodes. Without it the device is root-only and the daemon
# will sit there reporting that it cannot open it.

set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PREFIX="${PREFIX:-$HOME/.local}"
APPDIR="$PREFIX/share/fifine-deck/app"
BINDIR="$PREFIX/bin"
CMDS=(deck-daemon deck-icons deck-editor deck-ctl deck-icon-gen)

DEV=0; NO_UDEV=0; UNINSTALL=0
for a in "$@"; do
  case "$a" in
    --dev) DEV=1 ;;
    --no-udev) NO_UDEV=1 ;;
    --uninstall) UNINSTALL=1 ;;
    -h|--help) sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $a" >&2; exit 2 ;;
  esac
done

say() { printf '  %s\n' "$*"; }

# ---------------------------------------------------------------- uninstall
if [ "$UNINSTALL" = 1 ]; then
  echo "Removing the deck install..."
  systemctl --user disable --now fifine-deckd.service 2>/dev/null || true
  rm -f "$HOME/.config/systemd/user/fifine-deckd.service"
  rm -f "$HOME/.config/systemd/user/fifine-deck-icons.service"
  systemctl --user daemon-reload 2>/dev/null || true
  for c in "${CMDS[@]}"; do rm -f "$BINDIR/$c"; done
  rm -f "$BINDIR/fifine-deckd" "$BINDIR/deck-status"
  rm -rf "$APPDIR"
  rm -f "$PREFIX/share/applications/fifine-deck-editor.desktop"
  say "removed. Your config in ~/.config/fifine-deck was left alone."
  say "The udev rule needs root: sudo rm -f /etc/udev/rules.d/99-fifine-deck.rules"
  exit 0
fi

# ------------------------------------------------------------- requirements
echo "Checking requirements..."
PYV=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo none)
case "$PYV" in
  none) echo "  python3 is required." >&2; exit 1 ;;
  3.1[1-9]|3.[2-9][0-9]) say "python $PYV" ;;
  *) say "python $PYV - needs 3.11+, or 'pip install tomli' for TOML support" ;;
esac

if command -v magick >/dev/null || command -v convert >/dev/null; then
  say "ImageMagick found"
else
  say "ImageMagick NOT found - key icons cannot be rendered."
  say "  Arch: sudo pacman -S imagemagick   Debian: sudo apt install imagemagick"
fi

if python3 -c 'import ctypes.util,sys; sys.exit(0 if ctypes.util.find_library("hidapi-hidraw") or ctypes.util.find_library("hidapi-libusb") or ctypes.util.find_library("hidapi") else 1)'; then
  say "hidapi found"
else
  say "hidapi not found - falling back to raw hidraw (Linux only, works fine)."
fi

# ------------------------------------------------------------------ install
echo "Installing to $APPDIR..."
mkdir -p "$BINDIR" "$APPDIR"

if [ "$DEV" = 1 ]; then
  rm -rf "$APPDIR"
  mkdir -p "$(dirname "$APPDIR")"
  ln -sfn "$SRC" "$APPDIR"
  say "symlinked $APPDIR -> $SRC (dev mode)"
else
  rm -rf "$APPDIR"
  mkdir -p "$APPDIR"
  cp -r "$SRC/deck" "$SRC/bin" "$APPDIR/"
  say "copied deck/ and bin/"
fi

for c in "${CMDS[@]}"; do
  [ -f "$APPDIR/bin/$c" ] || continue
  chmod +x "$APPDIR/bin/$c"
  ln -sfn "$APPDIR/bin/$c" "$BINDIR/$c"
done
say "linked ${CMDS[*]} into $BINDIR"

# The old entry points, kept so existing habits and the bar widget keep working.
ln -sfn "$APPDIR/bin/deck-daemon" "$BINDIR/fifine-deckd"
printf '#!/bin/sh\nexec "%s" status --json "$@"\n' "$BINDIR/deck-ctl" > "$BINDIR/deck-status"
chmod +x "$BINDIR/deck-status"

# --------------------------------------------------------------- first config
if [ ! -f "$HOME/.config/fifine-deck/keys.toml" ] && [ -f "$SRC/keys.example.toml" ]; then
  mkdir -p "$HOME/.config/fifine-deck"
  cp "$SRC/keys.example.toml" "$HOME/.config/fifine-deck/keys.toml"
  say "installed a starter keys.toml"
fi

# ------------------------------------------------------------------ desktop
if [ -d "$PREFIX/share/applications" ] || mkdir -p "$PREFIX/share/applications"; then
  cat > "$PREFIX/share/applications/fifine-deck-editor.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Deck Editor
Comment=Customise your stream deck's keys
Exec=$BINDIR/deck-editor
Icon=input-keyboard
Terminal=false
Categories=Utility;Settings;HardwareSettings;
EOF
  say "added a Deck Editor desktop entry"
fi

# --------------------------------------------------- permissions + autostart
echo "Setting up permissions and autostart..."
if [ "$NO_UDEV" = 1 ]; then
  "$BINDIR/deck-ctl" install --no-sudo || true
else
  "$BINDIR/deck-ctl" install || true
fi

echo
echo "Done."
"$BINDIR/deck-ctl" status || true
echo
echo "  deck-editor     customise your keys (drag and drop)"
echo "  deck-ctl status check on things"
echo "  deck-ctl redraw redraw the screens"
echo
echo "If the deck is plugged in but dark, unplug and replug it: this hardware"
echo "stops accepting images after a number of draws until it is power-cycled."
