from __future__ import annotations

import base64
import json
import os
import socket
import struct
import subprocess
import threading
import time
import urllib.request
from typing import Any, Callable

class WS:

    def __init__(self, url: str, timeout: float = 30.0):

        assert url.startswith("ws://")
        rest = url[5:]
        hostport, _, path = rest.partition("/")
        host, _, port = hostport.partition(":")
        self.sock = socket.create_connection((host, int(port or 80)), timeout=timeout)
        self.sock.settimeout(timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        req = (
            f"GET /{path} HTTP/1.1\r\n"
            f"Host: {hostport}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "Origin: http://127.0.0.1\r\n\r\n"
        )
        self.sock.sendall(req.encode())

        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("websocket handshake closed")
            buf += chunk
        head, _, tail = buf.partition(b"\r\n\r\n")
        if b"101" not in head.split(b"\r\n")[0]:
            raise ConnectionError("websocket handshake failed: " + head[:200].decode(errors="ignore"))
        self._buf = tail

    def _recv_exact(self, n: int) -> bytes:
        while len(self._buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("websocket closed")
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def send_text(self, text: str) -> None:
        payload = text.encode()
        header = bytearray([0x81])
        n = len(payload)
        if n < 126:
            header.append(0x80 | n)
        elif n < (1 << 16):
            header.append(0x80 | 126)
            header += struct.pack(">H", n)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", n)
        mask = os.urandom(4)
        header += mask

        masked = bytes(b ^ mask[i & 3] for i, b in enumerate(payload))
        self.sock.sendall(bytes(header) + masked)

    def recv_text(self) -> str:
        chunks: list[bytes] = []
        while True:
            b0, b1 = self._recv_exact(2)
            fin = b0 & 0x80
            opcode = b0 & 0x0F
            masked = b1 & 0x80
            length = b1 & 0x7F
            if length == 126:
                length = struct.unpack(">H", self._recv_exact(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", self._recv_exact(8))[0]
            mask = self._recv_exact(4) if masked else b"\x00" * 4
            data = self._recv_exact(length) if length else b""
            if masked:
                data = bytes(b ^ mask[i & 3] for i, b in enumerate(data))
            if opcode == 0x9:
                self._send_control(0xA, data)
                continue
            if opcode == 0x8:
                raise ConnectionError("websocket close frame")
            if opcode == 0xA:
                continue
            chunks.append(data)
            if fin:
                return b"".join(chunks).decode("utf-8", errors="replace")

    def _send_control(self, opcode: int, data: bytes) -> None:
        header = bytearray([0x80 | opcode])
        header.append(0x80 | len(data))
        mask = os.urandom(4)
        header += mask
        self.sock.sendall(bytes(header) + bytes(b ^ mask[i & 3] for i, b in enumerate(data)))

    def close(self) -> None:
        try:
            self._send_control(0x8, b"")
        except Exception:
            pass
        try:
            self.sock.close()
        except Exception:
            pass

def find_browser() -> str:
    cands = [
        os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%LocalAppData%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
    ]
    for p in cands:
        if os.path.isfile(p):
            return p
    raise FileNotFoundError("未找到 Edge / Chrome 可执行文件")

class Browser:

    def __init__(self, port: int = 9222, profile: str | None = None, headless: bool = False):
        self.port = port
        self.profile = profile or os.path.join(os.path.expanduser("~"), ".endfield-exam-profile")
        self.headless = headless
        self.proc: subprocess.Popen | None = None
        self.exe = ""

    def _spawn(self, url: str, width: int, height: int) -> None:
        args = [
            self.exe,
            f"--remote-debugging-port={self.port}",
            f"--user-data-dir={self.profile}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-popup-blocking",
            "--disable-session-crashed-bubble",
            "--remote-allow-origins=*",
            f"--window-size={width},{height}",
            url,
        ]
        if self.headless:
            args.insert(1, "--headless=new")
        self.proc = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if self.headless else 0,
        )

    def start(self, url: str = "about:blank", width: int = 1280, height: int = 860) -> None:
        self.exe = find_browser()
        os.makedirs(self.profile, exist_ok=True)

        for name in ("SingletonLock", "SingletonCookie", "SingletonSocket", "lockfile"):
            p = os.path.join(self.profile, name)
            try:
                if os.path.islink(p) or os.path.isfile(p):
                    os.remove(p)
            except Exception:
                pass

        if not self._alive():
            self._spawn(url, width, height)
        try:
            self.wait_ready(timeout=15)
            return
        except TimeoutError:

            try:
                if self.proc and self.proc.poll() is None:
                    self.proc.kill()
            except Exception:
                pass
            import tempfile
            self.profile = tempfile.mkdtemp(prefix="ef-profile-")
            self.port = self.port + 1 if self.port < 9300 else self.port
            self._spawn(url, width, height)
            self.wait_ready(timeout=25)

    def _alive(self) -> bool:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json/version", timeout=0.6) as r:
                return r.status == 200
        except Exception:
            return False

    def wait_ready(self, timeout: float = 20.0) -> dict:
        end = time.time() + timeout
        while time.time() < end:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json/version", timeout=1.0) as r:
                    return json.loads(r.read().decode())
            except Exception:
                time.sleep(0.25)
        raise TimeoutError("浏览器调试端口未就绪")

    def pages(self) -> list[dict]:
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json/list", timeout=3) as r:
            return [p for p in json.loads(r.read().decode()) if p.get("type") == "page"]

    def new_page(self, url: str) -> dict:
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/json/new?{url}",
            method="PUT",
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode())

    def kill(self) -> None:
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.terminate()
            except Exception:
                pass

class Page:

    def __init__(self, ws_url: str):
        self.ws = WS(ws_url, timeout=60.0)
        self._id = 0
        self._lock = threading.Lock()
        self._events: list[Callable[[dict], None]] = []

    @classmethod
    def attach(cls, browser: Browser, url_hint: str = "") -> "Page":
        pages = browser.pages()
        target = None
        for p in pages:
            if url_hint and url_hint in (p.get("url") or ""):
                target = p
                break
        if target is None and pages:
            target = pages[0]
        if target is None:
            target = browser.new_page("about:blank")
        return cls(target["webSocketDebuggerUrl"])

    def send(self, method: str, params: dict | None = None, timeout: float = 45.0) -> Any:
        with self._lock:
            self._id += 1
            mid = self._id
            self.ws.send_text(json.dumps({"id": mid, "method": method, "params": params or {}}))
            end = time.time() + timeout
            while time.time() < end:
                msg = json.loads(self.ws.recv_text())
                if msg.get("id") == mid:
                    if "error" in msg:
                        raise RuntimeError(f"CDP {method} 失败: {msg['error']}")
                    return msg.get("result", {})
                for cb in list(self._events):
                    try:
                        cb(msg)
                    except Exception:
                        pass
            raise TimeoutError(f"CDP {method} 超时")

    def eval(self, expr: str, await_promise: bool = True, timeout: float = 45.0) -> Any:
        res = self.send(
            "Runtime.evaluate",
            {
                "expression": expr,
                "returnByValue": True,
                "awaitPromise": await_promise,
                "userGesture": True,
            },
            timeout=timeout,
        )
        if res.get("exceptionDetails"):
            d = res["exceptionDetails"]
            text = (d.get("exception") or {}).get("description") or d.get("text")
            raise RuntimeError(f"页面脚本异常: {text}")
        return (res.get("result") or {}).get("value")

    def navigate(self, url: str) -> None:
        self.send("Page.navigate", {"url": url})

    def url(self) -> str:
        return self.eval("location.href") or ""

    def enable(self) -> None:
        self.send("Page.enable")
        self.send("Runtime.enable")

    def close(self) -> None:
        self.ws.close()
