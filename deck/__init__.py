"""Drive HID stream decks with per-key LCDs.

Layered so that only the bottom layer knows about any particular device:

    transport   HID I/O          (hidapi, or raw hidraw on Linux)
    devices     device table     (geometry and quirks, as data)
    drivers     wire protocols   (one module per protocol family)
    render      key faces        (ImageMagick)
    config      keys.toml
    actions     running bindings
    platforms   permissions and autostart, per OS
    editor      the drag-and-drop editor, served over loopback
"""

__version__ = "2.0.0"
