# -*- coding: utf-8 -*-
"""增量同步 endfield 源码到 GitHub，并替换 Release 里的 exe。"""
import base64
import hashlib
import json
import os
import subprocess
import time

import requests
import urllib3

urllib3.disable_warnings()

REPO = "yingluoer/NGC-College-Student-Safety-Knowledge-Competition-Auto-Exam-Script"
API = "https://api.github.com"
BRANCH = "main"
TAG = "v1.0.0"
ROOT = r"D:\workbuddyhc\2026-10-30-23-31-27\endfield"
EXE = os.path.join(ROOT, "dist", "NGC-大学生安全知识竞赛速刷.exe")
ASSET_NAME = "NGC-Safety-Exam-Speedrun.exe"

TOKEN = subprocess.run(["git", "credential", "fill"],
                       input="protocol=https\nhost=github.com\n\n",
                       capture_output=True, text=True, encoding="utf-8").stdout
TOKEN = [l.split("=", 1)[1] for l in TOKEN.splitlines() if l.startswith("password=")][0].strip()
S = requests.Session()
S.headers.update({"Authorization": "token " + TOKEN, "Accept": "application/vnd.github+json"})
S.verify = False

SKIP_DIRS = {"build", "dist", "__pycache__", "test", ".git"}


def git_blob_sha(path):
    with open(path, "rb") as f:
        data = f.read()
    h = hashlib.sha1(b"blob %d\0" % len(data))
    h.update(data)
    return h.hexdigest()


def collect():
    out = []
    for root, dirs, names in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for n in names:
            p = os.path.join(root, n)
            rel = os.path.relpath(p, ROOT).replace(os.sep, "/")
            if rel.endswith(".spec") or rel in ("preview_bank.png", "_push.py"):
                continue
            out.append(rel)
    return sorted(out)


def sync(rel_path):
    local = os.path.join(ROOT, rel_path)
    r = S.get(f"{API}/repos/{REPO}/contents/{rel_path}?ref={BRANCH}", timeout=30)
    remote_sha = r.json()["sha"] if r.status_code == 200 else None
    local_sha = git_blob_sha(local)
    if remote_sha == local_sha:
        return "same"
    with open(local, "rb") as f:
        raw = f.read()
    body = {"message": "chore: sync latest source", "content": base64.b64encode(raw).decode(),
            "branch": BRANCH}
    if remote_sha:
        body["sha"] = remote_sha
    r = S.put(f"{API}/repos/{REPO}/contents/{rel_path}", data=json.dumps(body), timeout=180)
    print(f"  {rel_path}: HTTP {r.status_code}", flush=True)
    return "updated" if r.status_code in (200, 201) else "failed"


def release():
    return S.get(f"{API}/repos/{REPO}/releases/tags/{TAG}", timeout=30).json()


def upload(rel, path, name):
    for a in rel.get("assets", []):
        if a["name"] == name:
            S.delete(f"{API}/repos/{REPO}/releases/assets/{a['id']}", timeout=30)
            print("  删除旧 asset:", a["id"])
    size = os.path.getsize(path)
    url = f"https://uploads.github.com/repos/{REPO}/releases/{rel['id']}/assets"
    for i in range(5):
        try:
            with open(path, "rb") as f:
                r = S.post(url, params={"name": name},
                           headers={"Content-Type": "application/octet-stream"},
                           data=f, timeout=(60, 3600), allow_redirects=False)
            print(f"  {name} 第{i+1}次: HTTP {r.status_code}", flush=True)
            if r.status_code in (200, 201):
                d = r.json()
                print(f"    {d['size']} / {size} state={d.get('state')}")
                print("   ", d["browser_download_url"])
                return d.get("state") == "uploaded"
            if r.status_code == 307:
                loc = r.headers.get("Location")
                with open(path, "rb") as f:
                    r2 = S.post(loc, params={"name": name},
                                headers={"Content-Type": "application/octet-stream"},
                                data=f, timeout=(60, 3600), allow_redirects=False)
                print("  重定向后:", r2.status_code, flush=True)
                if r2.status_code in (200, 201):
                    d = r2.json()
                    print(f"    {d['size']} / {size} state={d.get('state')}")
                    print("   ", d["browser_download_url"])
                    return d.get("state") == "uploaded"
        except Exception as e:
            print("  异常:", str(e)[:140], flush=True)
        time.sleep(5)
    return False


if __name__ == "__main__":
    files = collect()
    changed = []
    for f in files:
        st = sync(f)
        if st == "updated":
            changed.append(f)
    print("变更文件:", changed or "无")

    rel = release()
    print("上传 exe %.0f MB" % (os.path.getsize(EXE) / 1048576), flush=True)
    ok = upload(rel, EXE, ASSET_NAME)
    print("exe 上传:", ok)
    print("release:", rel["html_url"])
