import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

// Fifine AmpliGame D6 status. deck-ctl prints one JSON line describing
// whether the deck is plugged in and whether fifine-deckd is running.
// Click asks the daemon to redraw the key icons (deck-ctl redraw).
// Not deck-icons: that would open the device behind the daemon's back,
// and this hardware does not tolerate two writers.
//
// The visible content lives on a child WidgetButton: Ui/BarWidget is a bare
// Item that only carries bar/moduleName/settings, so text, tooltipText,
// colour and the pressed signal all belong to the button, not to the root.
BarWidget {
  id: root
  moduleName: "ak.fifine-deck"

  property bool present: false
  property string daemon: "unknown"
  property int keyCount: 0
  property bool showLabel: setting("showLabel", true)
  property int intervalSeconds: Math.max(5, setting("intervalSeconds", 15))

  readonly property bool healthy: present && daemon === "active"

  // A vertical bar has no room for the text label regardless of the setting.
  readonly property bool labelWanted: showLabel && !vertical

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

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: root.labelWanted ? (root.glyph() + "  " + root.label()) : root.glyph()
    tooltipText: root.tip()
    foreground: root.healthy ? Color.foreground : (root.present ? Color.muted : Color.urgent)
    useActiveColor: false
    onPressed: function (b) {
      if (root.bar) root.bar.run("deck-ctl redraw")
    }
  }

  Process {
    id: poll
    command: ["bash", "-lc", "deck-ctl status --json"]
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
}
