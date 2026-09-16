"""The drag-and-drop key editor, served over loopback.

A local HTTP server is the one UI toolkit every desktop already has, which is
why the editor is built this way rather than in GTK or Qt: it behaves the same
on Linux and Windows and adds no dependencies at all.

SECURITY. This server can run shell commands -- that is what a key binding is --
so it is not merely a viewer, and it is defended accordingly:

  * it binds 127.0.0.1 only, never a routable address;
  * every request must carry a per-run secret token, so another page in the
    same browser cannot drive it (a browser will happily send a cross-site POST,
    but it cannot read or guess this token);
  * the Host header must be a loopback literal, which blocks DNS rebinding --
    an attacker's domain resolving to 127.0.0.1 would otherwise reach a server
    that is "local only";
  * state-changing routes require the token in a header, not just the URL, so a
    leaked address bar or Referer does not hand over control.

Nothing here is exposed to the network, and the token dies with the process.
"""
from __future__ import annotations

import hmac
import json
import mimetypes
import os
import secrets
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .. import actions, config, render
from ..devices import default_profile
from ..paths import CACHE_DIR, CONFIG_FILE, ensure_dirs

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
TRIGGER = os.path.join(CACHE_DIR, "redraw.trigger")

# A key's command runs in a shell; a test run must not hang the editor.
TEST_TIMEOUT = 10


class EditorState:
    """The draft being edited. Saved only when the user asks."""

    def __init__(self):
        self.profile = default_profile()
        self.lock = threading.Lock()
        self.reload()

    def reload(self):
        with self.lock:
            self.keys = {k: dict(config.load().get(k, {}))
                         for k in self.profile.key_range}
            self.settings = config.load_settings()
            # Which key's artwork belongs on each key. Identity until a swap;
            # applied to disk only on save, so Revert really does revert.
            self.art_map = {k: k for k in self.profile.key_range}
            self.dirty = False

    def snapshot(self):
        with self.lock:
            return {k: dict(v) for k, v in self.keys.items()}, dict(self.settings)

    def set_key(self, key: int, spec: dict):
        with self.lock:
            clean = {f: str(spec.get(f, "") or "") for f in config.FIELDS}
            self.keys[key] = {k: v for k, v in clean.items() if v.strip()}
            self.dirty = True

    def swap(self, a: int, b: int):
        """Drag-and-drop: move a key onto another, swapping the two faces.

        The artwork is keyed by index too, so it has to travel with the binding
        or a swapped key keeps the picture of whatever used to be there. It is
        tracked here and written only on save -- moving files during a drag
        would survive a Revert and silently scramble the artwork.
        """
        with self.lock:
            self.keys[a], self.keys[b] = dict(self.keys[b]), dict(self.keys[a])
            self.art_map[a], self.art_map[b] = self.art_map[b], self.art_map[a]
            self.dirty = True

    def art_for(self, key: int) -> int:
        with self.lock:
            return self.art_map.get(key, key)

    def save(self) -> str:
        with self.lock:
            render.permute_art(self.art_map)
            self.art_map = {k: k for k in self.profile.key_range}
            path = config.save(self.keys, settings=self.settings)
            self.dirty = False
        return path


class Handler(BaseHTTPRequestHandler):
    server_version = "deck-editor"
    protocol_version = "HTTP/1.1"

    # -- helpers ---------------------------------------------------------

    def log_message(self, fmt, *args):
        if self.server.verbose:
            super().log_message(fmt, *args)

    def _authorised(self, *, mutating: bool) -> bool:
        host = (self.headers.get("Host") or "").split(":")[0]
        if host not in ("127.0.0.1", "localhost", "[::1]", "::1"):
            return False                   # DNS-rebinding guard
        supplied = self.headers.get("X-Deck-Token") or ""
        if not supplied and not mutating:
            supplied = parse_qs(urlparse(self.path).query).get("token", [""])[0]
        return hmac.compare_digest(supplied, self.server.token)

    def _send(self, code, body=b"", ctype="application/json", extra=None):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        # The editor loads nothing from anywhere else, so forbid it outright.
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; img-src 'self' data:; "
                         "style-src 'self' 'unsafe-inline'; script-src 'self'")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj), "application/json")

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > 1_000_000:
            return {}
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except (ValueError, UnicodeDecodeError):
            return {}

    # -- routes ----------------------------------------------------------

    def do_GET(self):
        url = urlparse(self.path)
        path = url.path
        # The page itself is token-gated too: it carries the API token inline,
        # so serving it unauthenticated would hand that token to any local
        # requester. Open the URL printed at startup, token and all.
        if not self._authorised(mutating=False):
            return self._send(403, b"Forbidden. Open the URL printed by "
                                   b"deck-editor, including its ?token=.",
                              "text/plain")
        if path == "/":
            return self._serve_static("index.html")
        if path.startswith("/static/"):
            return self._serve_static(os.path.basename(path))
        if path == "/api/state":
            return self._json(self._state())
        if path == "/api/tile":
            return self._tile(parse_qs(url.query))
        return self._send(404, b'{"error":"not found"}')

    def do_POST(self):
        if not self._authorised(mutating=True):
            return self._send(403, b'{"error":"forbidden"}')
        path = urlparse(self.path).path
        body = self._body()
        st = self.server.state

        if path == "/api/key":
            key = int(body.get("key", 0))
            if key not in st.profile.key_range:
                return self._json({"error": "bad key"}, 400)
            st.set_key(key, body.get("spec") or {})
            return self._json({"ok": True})

        if path == "/api/swap":
            a, b = int(body.get("a", 0)), int(body.get("b", 0))
            if a not in st.profile.key_range or b not in st.profile.key_range:
                return self._json({"error": "bad key"}, 400)
            if a != b:
                st.swap(a, b)
            return self._json({"ok": True})

        if path == "/api/settings":
            with st.lock:
                for k, v in (body.get("settings") or {}).items():
                    if k in config.SETTINGS and isinstance(v, type(config.SETTINGS[k])):
                        st.settings[k] = v
                st.dirty = True
            return self._json({"ok": True})

        if path == "/api/save":
            path_written = st.save()
            redrew = self._request_redraw()
            return self._json({"ok": True, "path": path_written, "redraw": redrew})

        if path == "/api/revert":
            st.reload()
            return self._json({"ok": True})

        if path == "/api/redraw":
            return self._json({"ok": self._request_redraw()})

        if path == "/api/test":
            return self._test(body)

        return self._send(404, b'{"error":"not found"}')

    # -- route bodies ----------------------------------------------------

    def _state(self):
        keys, settings = self.server.state.snapshot()
        p = self.server.state.profile
        from ..drivers import discover
        from ..platforms import current as platform
        found = discover()
        return {
            "profile": {"name": p.name, "cols": p.cols, "rows": p.rows,
                        "keys": p.keys},
            "keys": {str(k): v for k, v in keys.items()},
            "settings": settings,
            "fields": list(config.FIELDS),
            "config_path": CONFIG_FILE,
            "dirty": self.server.state.dirty,
            "status": {
                "present": bool(found),
                "device": found[0][0].name if found else None,
                "daemon": platform().daemon_running(),
                "magick": render.have_magick(),
            },
        }

    def _tile(self, q):
        """Render one key face from the DRAFT, so the grid shows unsaved edits."""
        try:
            key = int(q.get("key", ["0"])[0])
        except ValueError:
            return self._send(400, b'{"error":"bad key"}')
        st = self.server.state
        if key not in st.profile.key_range:
            return self._send(400, b'{"error":"bad key"}')
        keys, _ = st.snapshot()
        out = os.path.join(tempfile.gettempdir(), f"deck-editor-pv{key}.png")
        try:
            render.preview_png(key, keys.get(key, {}), st.profile, out, scale=180,
                               art_key=st.art_for(key))
            with open(out, "rb") as f:
                data = f.read()
        except Exception as e:
            return self._send(500, json.dumps({"error": str(e)}).encode())
        return self._send(200, data, "image/png")

    def _request_redraw(self) -> bool:
        try:
            ensure_dirs()
            with open(TRIGGER, "w") as f:
                f.write(str(time.time()))
            return True
        except OSError:
            return False

    def _test(self, body):
        """Run a key's command once, and report what it printed.

        This is the point of the editor: a binding you cannot try is a binding
        you find out about later, on the hardware, with no error message.
        """
        cmd = str(body.get("cmd") or "").strip()
        if not cmd:
            return self._json({"error": "nothing to run"}, 400)
        try:
            r = actions.run(cmd, capture=True, timeout=TEST_TIMEOUT)
        except Exception as e:
            return self._json({"ok": False, "output": f"{type(e).__name__}: {e}"})
        out = ((r.stdout or "") + (r.stderr or "")).strip()
        return self._json({"ok": r.returncode == 0, "code": r.returncode,
                           "output": out[:4000] or "(no output)"})

    def _serve_static(self, name):
        path = os.path.join(STATIC, os.path.basename(name))
        if not os.path.isfile(path):
            return self._send(404, b"not found", "text/plain")
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        with open(path, "rb") as f:
            data = f.read()
        if name == "index.html":
            # The page needs the token to call the API; it is injected rather
            # than written to disk so it never outlives the process.
            data = data.replace(b"__TOKEN__", self.server.token.encode())
        return self._send(200, data, ctype)


class EditorServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, addr, token, verbose=False):
        super().__init__(addr, Handler)
        self.token = token
        self.state = EditorState()
        self.verbose = verbose


def serve(host="127.0.0.1", port=8777, verbose=False):
    ensure_dirs()
    token = secrets.token_urlsafe(24)
    srv = EditorServer((host, port), token, verbose)
    return srv, f"http://{host}:{srv.server_address[1]}/?token={token}"
