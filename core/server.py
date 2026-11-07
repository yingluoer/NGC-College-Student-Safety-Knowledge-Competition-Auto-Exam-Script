from __future__ import annotations

import json
import mimetypes
import os
import queue
import socket
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .engine import Engine
from .paths import resource

LAST_SEEN = time.time()

def touch() -> None:
    global LAST_SEEN
    LAST_SEEN = time.time()

def idle_seconds() -> float:
    return time.time() - LAST_SEEN

class Handler(BaseHTTPRequestHandler):
    engine: Engine
    server_version = "EndfieldTerm/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:
            pass

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:
            return {}

    def do_GET(self) -> None:
        try:
            self._route_get()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:

            try:
                self._json({"ok": False, "err": f"{type(e).__name__}: {e}"}, 500)
            except Exception:
                pass

    def _route_get(self) -> None:
        touch()
        path = urllib.parse.urlparse(self.path).path
        if path in ("/", "/index.html"):
            return self._static("index.html")
        if path in ("/app.css", "/app.js"):
            return self._static(path.lstrip("/"))
        if path == "/donate.jpg":
            return self._asset("donate.jpg")
        if path == "/api/state":
            return self._json(self.engine.snapshot())
        if path == "/api/events":
            return self._sse()
        if path == "/api/shot":
            return self._json({"img": self.engine.screenshot()})
        if path == "/api/missed":
            return self._json(self.engine.missed)
        if path == "/api/export":
            p = self.engine.export_missed()
            return self._json({"path": p})
        if path == "/api/ping":
            return self._json({"ok": True})
        return self._send(404, b"not found", "text/plain")

    def do_POST(self) -> None:
        try:
            self._route_post()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            try:
                self._json({"ok": False, "err": f"{type(e).__name__}: {e}"}, 500)
            except Exception:
                pass

    def _route_post(self) -> None:
        touch()
        path = urllib.parse.urlparse(self.path).path
        data = self._body()
        e = self.engine
        if path == "/api/launch":
            e.launch(data)
        elif path == "/api/login":
            e.login(data.get("code", ""))
        elif path == "/api/captcha":
            e.refresh_captcha()
        elif path == "/api/enter":
            e.enter(data.get("module", "seq"))
        elif path == "/api/run":
            e.run()
        elif path == "/api/collect":
            e.collect()
        elif path == "/api/stop":
            e.stop()
        elif path == "/api/pause":
            e.toggle_pause(bool(data.get("paused")))
        elif path == "/api/settings":

            e.settings.update({k: v for k, v in data.items() if k in e.settings})
        elif path == "/api/manual":

            js = str(data.get("js") or "")
            if not js:
                return self._json({"ok": False, "err": "empty js"}, 400)
            return self._json({"ok": True, "value": e.page.eval(js) if e.page else None})
        else:
            return self._json({"ok": False, "err": "unknown"}, 404)
        return self._json({"ok": True, "state": e.snapshot()})

    def _asset(self, name: str) -> None:
        p = resource("assets", name)
        if not os.path.isfile(p):
            return self._send(404, b"missing", "text/plain")
        with open(p, "rb") as f:
            self._send(200, f.read(), "image/jpeg")

    def _static(self, name: str) -> None:
        p = resource("web", name)
        if not os.path.isfile(p):
            return self._send(404, b"missing " + name.encode(), "text/plain")
        ctype = mimetypes.guess_type(p)[0] or "application/octet-stream"
        if name.endswith(".css"):
            ctype = "text/css; charset=utf-8"
        elif name.endswith(".js"):
            ctype = "application/javascript; charset=utf-8"
        elif name.endswith(".html"):
            ctype = "text/html; charset=utf-8"
        with open(p, "rb") as f:
            self._send(200, f.read(), ctype)

    def _sse(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        q = self.engine.bus.sub()
        try:
            self._chunk(json.dumps({"type": "hello", "state": self.engine.snapshot()}, ensure_ascii=False))
            touch()
            while True:
                try:
                    evt = q.get(timeout=4.0)
                    self._chunk(json.dumps(evt, ensure_ascii=False))
                except queue.Empty:

                    self._chunk(json.dumps({"type": "ping"}))
                touch()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            self.engine.bus.unsub(q)

    def _chunk(self, payload: str) -> None:
        data = ("data: " + payload + "\n\n").encode("utf-8")
        self.wfile.write(b"%X\r\n" % len(data) + data + b"\r\n")
        self.wfile.flush()

def pick_port(start: int = 8791) -> int:
    for p in range(start, start + 40):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    return start

def serve(engine: Engine, port: int | None = None) -> tuple[ThreadingHTTPServer, int]:
    port = port or pick_port()
    Handler.engine = engine
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    httpd.daemon_threads = True
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd, port
