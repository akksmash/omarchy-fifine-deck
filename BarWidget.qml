import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

// Fifine AmpliGame D6 status. deck-status prints one JSON line describing
// whether the deck is plugged in and whether fifine-deckd is running.
// Click redraws the key icons (deck-icons).
BarWidget {
  id: root
  moduleName: "ak.fifine-deck"

  property bool present: false
  property string daemon: "unknown"
  property int keyCount: 0
  property bool showLabel: setting("showLabel", true)
  property int intervalSeconds: Math.max(5, setting("intervalSeconds", 15))

  readonly property bool healthy: present && daemon === "active"

  function glyph() {
    if (!present) return "󰌌"
    return healthy ? "󰍹" : "󰍺"
  }
  function label() {
    if (!present) return "no deck"
    if (daemon !== "active") return "deck idle"
    return keyCount + " keys"
  }
  function tip() {
    if (!present) return "Fifine D6 not connected"
    if (daemon !== "active") return "Deck connected, fifine-deckd is " + daemon
                                    + "\nClick to redraw icons"
    return "Fifine D6 · " + keyCount + " keys bound\nClick to redraw icons"
  }

  text: showLabel ? (glyph() + "  " + label()) : glyph()
  tooltipText: tip()
  color: healthy ? Color.foreground : (present ? Color.muted : Color.urgent)

  Process {
    id: poll
    command: ["bash", "-lc", "deck-status"]
    running: true
    stdout: SplitParser {
      onRead: function (line) {
        try {
          var d = JSON.parse(line)
          root.present = !!d.present
          root.daemon = String(d.daemon || "unknown")
          root.keyCount = Number(d.keys || 0)
        } catch (e) { /* ignore a partial line */ }
      }
    }
  }

  Timer {
    interval: root.intervalSeconds * 1000
    running: true
    repeat: true
    onTriggered: poll.running = true
  }

  onPressed: function () {
    if (root.bar) root.bar.run("deck-icons")
  }
}
