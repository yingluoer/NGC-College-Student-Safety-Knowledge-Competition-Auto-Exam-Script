from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import webbrowser

from core import server as srv
from core.cdp import find_browser
from core.engine import Engine
from core.paths import user_dir
from core.server import serve

IDLE_GRACE = 40.0
IDLE_TIMEOUT = 9.0

def write_log(msg: str) -> None:
    try:
        with open(os.path.join(user_dir(), "run.log"), "a", encoding="utf-8") as f:
            f.write(time.strftime("[%Y-%m-%d %H:%M:%S] ") + msg + "\n")
    except Exception:
        pass
    try:
        if sys.stdout:
            sys.stdout.write(msg + "\n")
            sys.stdout.flush()
    except Exception:
        pass

def open_shell(url: str) -> tuple[subprocess.Popen | None, str]:
    try:
        exe = find_browser()
    except FileNotFoundError:
        return None, ""
    profile = os.path.join(tempfile.gettempdir(), f"endfield-ui-{os.getpid()}")
    shutil.rmtree(profile, ignore_errors=True)
    os.makedirs(profile, exist_ok=True)
    args = [
        exe,
        f"--app={url}",
        f"--user-data-dir={profile}",
        "--window-size=1500,940",
        "--window-position=110,50",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-features=Translate,msEdgeSplitScreen,SessionRestore",
        "--disable-session-crashed-bubble",
        "--disable-background-networking",
    ]
    try:
        return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL), profile
    except Exception:
        return None, profile

def close_shell(profile: str) -> None:
    if not profile:
        return
    key = os.path.basename(profile)
    ps = (
        "Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\" | "
        f"Where-Object {{ $_.CommandLine -like '*{key}*' }} | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True,
            timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:
        pass

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--no-gui", action="store_true")
    ap.add_argument("--keep", action="store_true", help="不因窗口关闭而退出")
    a = ap.parse_args()

    engine = Engine()
    httpd, port = serve(engine, a.port or None)
    url = f"http://127.0.0.1:{port}/"
    write_log(f"terminal ready: {url}  bank={len(engine.bank)}")

    proc = None
    profile = ""
    if not a.no_gui:
        proc, profile = open_shell(url)
        if proc is None:
            write_log("app 窗口打开失败，回退到默认浏览器")
            webbrowser.open(url)

    started = time.time()
    try:
        while True:
            time.sleep(0.5)
            if a.keep or a.no_gui:
                continue

            idle = srv.idle_seconds()
            if time.time() - started > IDLE_GRACE and idle > IDLE_TIMEOUT:
                write_log(f"frontend idle {idle:.0f}s, shutting down")
                break
    except KeyboardInterrupt:
        pass
    finally:

        close_shell(profile)
        try:
            engine.stop()
        except Exception:
            pass
        try:
            httpd.shutdown()
        except Exception:
            pass
        if profile:
            shutil.rmtree(profile, ignore_errors=True)
    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        write_log("FATAL\n" + traceback.format_exc())
        raise
