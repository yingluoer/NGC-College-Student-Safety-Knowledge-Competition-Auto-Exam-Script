from __future__ import annotations

import os
import sys

def base_dir() -> str:
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def resource(*parts: str) -> str:
    return os.path.join(base_dir(), *parts)

def user_dir() -> str:
    d = os.path.join(os.path.expanduser("~"), ".endfield-exam")
    os.makedirs(d, exist_ok=True)
    return d
