"""Cross-platform HID transport.

Two backends, chosen automatically:

  hidraw  raw /dev/hidraw* reads and writes. Linux only, no dependencies.
          PREFERRED ON LINUX -- see below.
  hidapi  ctypes binding to libhidapi. The only option off Linux, and the
          fallback on Linux when /dev/hidraw is unavailable.

Why hidraw wins on Linux, despite hidapi being the obvious choice: on the Fifine
D6, hidapi renders NOTHING. Not a single tile, ever. Raw hidraw on the same
machine, same device, same config renders the full set. Capturing both code
paths' complete output and diffing them byte for byte showed an identical command
stream -- 243 packets, same opcodes, same order -- so the difference is not in
what we ask for. Cause unknown; suspect something in how libhidapi issues the
write. Recorded here so nobody "tidies up" by preferring hidapi again.

Override either way with FIFINE_DECK_BACKEND=hidraw|hidapi.

Both present the same tiny surface: write(), read(), close(). Every packet the
protocol layer produces already begins with a 0x00 report-ID byte, which is
exactly what both backends expect, so the wire format is identical either way.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import glob
import os
import re
import sys

__all__ = ["DeviceInfo", "Transport", "enumerate_devices", "open_device", "backend_name"]

_FORCED = os.environ.get("FIFINE_DECK_BACKEND", "").strip().lower() or None

# A sysfs path component like "1-13:1.0" -> USB interface 0.
_IFACE_RE = re.compile(r"/\d+-[\d.]+:\d+\.(\d+)/")


class DeviceInfo:
    """One HID interface of one physical device."""

    __slots__ = ("path", "vendor_id", "product_id", "interface", "usage_page",
                 "product", "serial", "backend")

    def __init__(self, path, vendor_id, product_id, interface=-1, usage_page=0,
                 product="", serial="", backend=""):
        self.path = path
        self.vendor_id = vendor_id
        self.product_id = product_id
        self.interface = interface
        self.usage_page = usage_page
        self.product = product
        self.serial = serial
        self.backend = backend

    def is_vendor_interface(self) -> bool:
        """The command interface is USB interface 0 on every device in this family.

        Where the OS does not report an interface number (macOS, and some Windows
        non-composite paths) fall back to the vendor-defined usage page range,
        which is what interface 0 advertises.
        """
        if self.interface >= 0:
            return self.interface == 0
        return self.usage_page >= 0xFF00

    def __repr__(self):
        return (f"<DeviceInfo {self.vendor_id:04x}:{self.product_id:04x} "
                f"if={self.interface} usage={self.usage_page:#06x} {self.path!r}>")


class Transport:
    """A writable, readable handle on one HID interface."""

    def write(self, data: bytes) -> int: raise NotImplementedError
    def read(self, size: int, timeout_ms: int) -> bytes: raise NotImplementedError
    def close(self) -> None: raise NotImplementedError

    def __enter__(self): return self
    def __exit__(self, *exc): self.close()


# --------------------------------------------------------------------------
# hidapi backend
# --------------------------------------------------------------------------

class _HidDeviceInfoStruct(ctypes.Structure):
    pass


# Fields up to and including `next` must match libhidapi exactly. Later versions
# append `bus_type` after `next`; trailing additions do not shift these offsets,
# so declaring the prefix is both correct and forward-compatible.
_HidDeviceInfoStruct._fields_ = [
    ("path", ctypes.c_char_p),
    ("vendor_id", ctypes.c_ushort),
    ("product_id", ctypes.c_ushort),
    ("serial_number", ctypes.c_wchar_p),
    ("release_number", ctypes.c_ushort),
    ("manufacturer_string", ctypes.c_wchar_p),
    ("product_string", ctypes.c_wchar_p),
    ("usage_page", ctypes.c_ushort),
    ("usage", ctypes.c_ushort),
    ("interface_number", ctypes.c_int),
    ("next", ctypes.POINTER(_HidDeviceInfoStruct)),
]

_LIB_CANDIDATES = {
    "linux": ["libhidapi-hidraw.so.0", "libhidapi-hidraw.so",
              "libhidapi-libusb.so.0", "libhidapi-libusb.so"],
    "win32": ["hidapi.dll", "libhidapi-0.dll", "libhidapi.dll"],
    "darwin": ["libhidapi.dylib", "libhidapi.0.dylib"],
}

_lib = None
_lib_loaded = False


def _load_hidapi():
    global _lib, _lib_loaded
    if _lib_loaded:
        return _lib
    _lib_loaded = True

    names = list(_LIB_CANDIDATES.get(sys.platform, _LIB_CANDIDATES["linux"]))
    for n in ("hidapi-hidraw", "hidapi-libusb", "hidapi"):
        found = ctypes.util.find_library(n)
        if found:
            names.append(found)

    for name in names:
        try:
            lib = ctypes.CDLL(name)
        except OSError:
            continue
        try:
            lib.hid_init.restype = ctypes.c_int
            lib.hid_enumerate.restype = ctypes.POINTER(_HidDeviceInfoStruct)
            lib.hid_enumerate.argtypes = [ctypes.c_ushort, ctypes.c_ushort]
            lib.hid_free_enumeration.argtypes = [ctypes.POINTER(_HidDeviceInfoStruct)]
            lib.hid_open_path.restype = ctypes.c_void_p
            lib.hid_open_path.argtypes = [ctypes.c_char_p]
            lib.hid_write.restype = ctypes.c_int
            lib.hid_write.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t]
            lib.hid_read_timeout.restype = ctypes.c_int
            lib.hid_read_timeout.argtypes = [ctypes.c_void_p, ctypes.c_char_p,
                                             ctypes.c_size_t, ctypes.c_int]
            lib.hid_close.argtypes = [ctypes.c_void_p]
            lib.hid_error.restype = ctypes.c_wchar_p
            lib.hid_error.argtypes = [ctypes.c_void_p]
            lib.hid_init()
        except AttributeError:
            continue
        _lib = lib
        return _lib
    return None


class HidapiTransport(Transport):
    def __init__(self, handle, lib):
        self._h = handle
        self._lib = lib

    def write(self, data: bytes) -> int:
        n = self._lib.hid_write(self._h, data, len(data))
        if n < 0:
            raise OSError(f"hid_write failed: {self._lib.hid_error(self._h)}")
        return n

    def read(self, size: int, timeout_ms: int) -> bytes:
        buf = ctypes.create_string_buffer(size)
        n = self._lib.hid_read_timeout(self._h, buf, size, timeout_ms)
        if n < 0:
            raise OSError(f"hid_read failed: {self._lib.hid_error(self._h)}")
        return buf.raw[:n]

    def close(self) -> None:
        if self._h:
            self._lib.hid_close(self._h)
            self._h = None


def _hidapi_enumerate(vid, pid):
    lib = _load_hidapi()
    if lib is None:
        return None
    head = lib.hid_enumerate(vid, pid)
    out = []
    try:
        cur = head
        while cur:
            d = cur.contents
            out.append(DeviceInfo(
                path=d.path.decode("utf-8", "replace") if d.path else "",
                vendor_id=d.vendor_id, product_id=d.product_id,
                interface=d.interface_number, usage_page=d.usage_page,
                product=d.product_string or "", serial=d.serial_number or "",
                backend="hidapi"))
            cur = d.next
    finally:
        if head:
            lib.hid_free_enumeration(head)
    return out


def _hidapi_open(info: DeviceInfo) -> Transport:
    lib = _load_hidapi()
    if lib is None:
        raise OSError("libhidapi not available")
    h = lib.hid_open_path(info.path.encode())
    if not h:
        raise OSError(f"cannot open {info.path} (permissions? see the udev rule on Linux)")
    return HidapiTransport(h, lib)


# --------------------------------------------------------------------------
# hidraw backend (Linux only)
# --------------------------------------------------------------------------

class HidrawTransport(Transport):
    def __init__(self, fd):
        self._fd = fd

    def write(self, data: bytes) -> int:
        return os.write(self._fd, data)

    def read(self, size: int, timeout_ms: int) -> bytes:
        import select
        r, _, _ = select.select([self._fd], [], [], timeout_ms / 1000.0)
        if not r:
            return b""
        return os.read(self._fd, size)

    def close(self) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None


def _hidraw_enumerate(vid, pid):
    if not sys.platform.startswith("linux"):
        return []
    tag = f"{vid:04X}:{pid:04X}"
    out = []
    for d in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        rp = os.path.realpath(d)
        if tag not in rp.upper():
            continue
        # The USB interface number lives in a path component shaped like
        # "1-13:1.0" (bus-port:config.interface). It appears BEFORE the VID:PID
        # component, so it has to be matched on its own rather than relative to it.
        iface = -1
        m = _IFACE_RE.search(rp)
        if m:
            iface = int(m.group(1))
        out.append(DeviceInfo(path="/dev/" + os.path.basename(d),
                              vendor_id=vid, product_id=pid, interface=iface,
                              backend="hidraw"))
    return out


def _hidraw_open(info: DeviceInfo) -> Transport:
    return HidrawTransport(os.open(info.path, os.O_RDWR | os.O_NONBLOCK))


# --------------------------------------------------------------------------
# dispatch
# --------------------------------------------------------------------------

def backend_name() -> str:
    """Which backend enumerate_devices() will use, for diagnostics."""
    if _FORCED:
        return _FORCED
    if sys.platform.startswith("linux") and glob.glob("/sys/class/hidraw/hidraw*"):
        return "hidraw"
    return "hidapi" if _load_hidapi() is not None else "hidraw"


def enumerate_devices(vid: int, pid: int) -> list[DeviceInfo]:
    """Every HID interface matching vid:pid, preferred backend first."""
    if _FORCED == "hidraw":
        return _hidraw_enumerate(vid, pid)
    if _FORCED == "hidapi":
        return _hidapi_enumerate(vid, pid) or []
    # Linux first tries hidraw, because hidapi does not render on this hardware
    # (see the module docstring). Elsewhere hidapi is the only option.
    if sys.platform.startswith("linux"):
        found = _hidraw_enumerate(vid, pid)
        if found:
            return found
    return _hidapi_enumerate(vid, pid) or []


def open_device(info: DeviceInfo) -> Transport:
    if info.backend == "hidraw":
        return _hidraw_open(info)
    return _hidapi_open(info)
