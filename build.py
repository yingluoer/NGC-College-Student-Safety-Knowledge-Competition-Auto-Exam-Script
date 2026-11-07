from __future__ import annotations

import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
NAME = "NGC-大学生安全知识竞赛速刷"

def main() -> int:
    onedir = "--onedir" in sys.argv
    sep = ";" if os.name == "nt" else ":"

    args = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--onedir" if onedir else "--onefile",
        "--noconsole",
        "--name", NAME,
        "--icon", os.path.join(ROOT, "assets", "app.ico"),
        "--add-data", f"{os.path.join(ROOT, 'web')}{sep}web",
        "--add-data", f"{os.path.join(ROOT, 'assets', 'answer.js')}{sep}assets",
        "--add-data", f"{os.path.join(ROOT, 'assets', 'inject.js')}{sep}assets",
        "--add-data", f"{os.path.join(ROOT, 'assets', 'app.ico')}{sep}assets",
        "--add-data", f"{os.path.join(ROOT, 'assets', 'donate.jpg')}{sep}assets",
        "--add-data", f"{os.path.join(ROOT, 'assets', 'bank_text.json')}{sep}assets",
        "--hidden-import", "core.engine",
        "--hidden-import", "core.server",
        "--hidden-import", "core.cdp",
        "--hidden-import", "core.bank",
        "--hidden-import", "core.paths",
        "--exclude-module", "tkinter",
        "--exclude-module", "unittest",
        "--exclude-module", "pydoc",
        os.path.join(ROOT, "main.py"),
    ]

    try:
        import ddddocr
        dd = os.path.dirname(ddddocr.__file__)

        onnx = os.path.join(dd, "common_old.onnx")
        if not os.path.isfile(onnx):
            onnx = os.path.join(dd, "common.onnx")
        if os.path.isfile(onnx):
            args[args.index(os.path.join(ROOT, "main.py")):args.index(os.path.join(ROOT, "main.py"))] = [
                "--add-data", f"{onnx}{sep}ddddocr",
                "--hidden-import", "ddddocr",
                "--collect-submodules", "ddddocr",
                "--hidden-import", "onnxruntime",
                "--collect-binaries", "onnxruntime",
                "--collect-submodules", "onnxruntime",
            ]
            print(f"ddddocr model: {os.path.getsize(onnx)/1048576:.0f} MB")
    except Exception as e:
        print(f"skip ddddocr: {e}")
    print(" ".join(args))
    rc = subprocess.call(args, cwd=ROOT)
    if rc != 0:
        return rc

    exe = os.path.join(ROOT, "dist", NAME + (".exe" if os.name == "nt" else ""))
    if onedir:
        exe = os.path.join(ROOT, "dist", NAME, NAME + (".exe" if os.name == "nt" else ""))
    if os.path.exists(exe):
        print(f"\nOK  {exe}  {os.path.getsize(exe)/1048576:.1f} MB")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
