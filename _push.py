# -*- coding: utf-8 -*-
"""endfield 项目发布：源码推 GitHub + exe 传 Release。"""
import base64
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

BODY = """## 免责声明

1. 本程序为开源技术学习项目，用于网页自动化与 CDP 协议的学习实践。是否使用、如何使用，由使用者自行判断并承担全部后果。
2. 程序按「现状」（AS IS）提供，作者不对其可用性、稳定性、兼容性及使用结果作任何明示或默示担保。
3. 因使用或无法使用本程序造成的任何直接或间接损失（包括但不限于成绩作废、账号处罚、纪律处分及其他法律责任），作者不承担任何责任。
4. 请在使用前自行确认所在院校的相关规定与平台用户协议。使用者应自行确保操作对象为本人账号，答题记录代表本人真实水平。
5. 程序不采集、不上传任何个人信息。账号、密码、会话与运行日志仅保存在本机。
6. 作者保留随时修改、暂停或终止更新的权利，且不承担技术支持义务。下载、运行即视为已阅读并接受本声明。

## 下载说明

- `NGC-Safety-Exam-Speedrun.exe`：单文件，约 92 MB（GitHub Release 不支持中文文件名，故用英文名，内容与 `NGC-大学生安全知识竞赛速刷.exe` 完全一致）
- 无需安装 Python 或 Chrome，双击即用

使用教程见仓库 README。
"""

TOKEN = subprocess.run(["git", "credential", "fill"],
                       input="protocol=https\nhost=github.com\n\n",
                       capture_output=True, text=True, encoding="utf-8").stdout
TOKEN = [l.split("=", 1)[1] for l in TOKEN.splitlines() if l.startswith("password=")][0].strip()
S = requests.Session()
S.headers.update({"Authorization": "token " + TOKEN, "Accept": "application/vnd.github+json"})
S.verify = False

SKIP_DIRS = {"build", "dist", "__pycache__", "test", ".git"}


def collect():
    out = []
    for root, dirs, names in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for n in names:
            p = os.path.join(root, n)
            rel = os.path.relpath(p, ROOT).replace(os.sep, "/")
            if rel.endswith(".spec"):
                continue
            if rel in ("preview_bank.png", "ENDFIELD-Terminal.spec"):
                continue
            out.append(rel)
    return sorted(out)


def put(rel_path, msg):
    local = os.path.join(ROOT, rel_path)
    r = S.get(f"{API}/repos/{REPO}/contents/{rel_path}?ref={BRANCH}", timeout=30)
    sha = r.json()["sha"] if r.status_code == 200 else None
    with open(local, "rb") as f:
        raw = f.read()
    body = {"message": msg, "content": base64.b64encode(raw).decode(), "branch": BRANCH}
    if sha:
        body["sha"] = sha
    r = S.put(f"{API}/repos/{REPO}/contents/{rel_path}", data=json.dumps(body), timeout=180)
    print(f"  {rel_path}: HTTP {r.status_code}", flush=True)
    return r.status_code in (200, 201)


def release():
    r = S.get(f"{API}/repos/{REPO}/releases/tags/{TAG}", timeout=30)
    if r.status_code == 200:
        print("release 已存在:", r.json()["id"])
        return r.json()
    body = {"tag_name": TAG, "name": "NGC-ZDPJ-Safety " + TAG, "body": BODY,
            "target_commitish": BRANCH, "draft": False, "prerelease": False}
    r = S.post(f"{API}/repos/{REPO}/releases", data=json.dumps(body), timeout=60)
    print("创建 release: HTTP", r.status_code, flush=True)
    if r.status_code not in (200, 201):
        print(r.text[:300])
        return None
    return r.json()


def upload(rel, path, name):
    for a in rel.get("assets", []):
        if a["name"] == name:
            S.delete(f"{API}/repos/{REPO}/releases/assets/{a['id']}", timeout=30)
            print("  删除同名 asset")
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
    print("上传源码", len(files), "个文件", flush=True)
    for f in files:
        put(f, "docs: publish source, usage guide and disclaimer")
    rel = release()
    if rel:
        print("上传 exe %.0f MB" % (os.path.getsize(EXE) / 1048576), flush=True)
        ok = upload(rel, EXE, ASSET_NAME)
        print("exe 上传:", ok, flush=True)
        print("release:", rel["html_url"], flush=True)
