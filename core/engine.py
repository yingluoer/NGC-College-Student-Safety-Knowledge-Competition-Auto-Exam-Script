from __future__ import annotations

import base64
import json
import os
import queue
import random
import re
import threading
import time
import traceback
from typing import Any, Callable

from .bank import Bank, TextBank, normalize, split_answer
from .cdp import Browser, Page
from .paths import resource, user_dir

LOGIN_URL = "https://mars.mycourse.cn/deimos/#/"

MODULES = {
    "seq": ["顺序练习"],
    "rand": ["随机练习"],
    "mock": ["模拟考试"],
    "exam": ["正式考试"],
}

class Bus:

    def __init__(self) -> None:
        self._subs: list[queue.Queue] = []
        self._lock = threading.Lock()

    def sub(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=1000)
        with self._lock:
            self._subs.append(q)
        return q

    def unsub(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)

    def pub(self, evt: dict) -> None:
        with self._lock:
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait(evt)
            except queue.Full:
                try:
                    q.get_nowait()
                    q.put_nowait(evt)
                except Exception:
                    pass

class Engine:
    def __init__(self) -> None:
        self.bus = Bus()
        self.phase = "idle"
        self.running = False
        self.stop_flag = False
        self.paused = False
        self._login_abort = False
        self.error = ""
        self.captcha = ""
        self.current: dict[str, Any] = {}
        self.stats = {"answered": 0, "exact": 0, "fuzzy": 0, "miss": 0, "right": 0, "wrong": 0,
                      "text": 0, "started_at": 0.0}
        self.missed: list[dict] = []
        self.logs: list[dict] = []
        self.settings = {
            "school": "",
            "user": "",
            "password": "",
            "delay": 0.30,
            "on_miss": "first",
            "auto_submit": False,
            "headless": False,
            "threshold": 0.86,
            "auto_captcha": True,
            "mode": "top",
            "target": 84,
            "ceiling": 92,
            "floor": 80,
            "speed_min": 3.0,
            "speed_max": 10.0,
            "accuracy": 85,
        }
        self.browser: Browser | None = None
        self.page: Page | None = None
        self._inject_src = ""
        self._inject_ver = ""
        self._worker = queue.Queue()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        self._load_bank()

    def _load_bank(self) -> None:
        path = resource("assets", "answer.js")
        try:
            self.bank = Bank.from_js(path)
            self.log("info", f"题库加载完成，共 {len(self.bank)} 题")
        except Exception as e:
            self.bank = Bank({})
            self.log("error", f"题库加载失败：{e}")

        bundled = resource("assets", "bank_text.json")
        self.textbank = TextBank(
            os.path.join(user_dir(), "bank_text.json"),
            bundled if os.path.exists(bundled) else None,
        )
        if len(self.textbank):
            self.log("info", f"官方答案题库已加载：{len(self.textbank)} 题（文本匹配优先）")

    def log(self, level: str, msg: str) -> None:
        item = {"t": time.strftime("%H:%M:%S"), "level": level, "msg": msg}
        self.logs.append(item)
        if len(self.logs) > 600:
            del self.logs[:200]
        self.bus.pub({"type": "log", **item})

    def _phase(self, p: str, msg: str = "") -> None:
        self.phase = p
        self.bus.pub({"type": "phase", "phase": p, "msg": msg})

    def submit(self, fn: Callable, *args) -> None:
        self._worker.put((fn, args))

    def _loop(self) -> None:
        while True:
            fn, args = self._worker.get()
            try:
                fn(*args)
            except Exception as e:
                self.error = f"{e}"
                self.phase = "error"
                self.running = False
                self.log("error", f"{e}")
                self.bus.pub({"type": "phase", "phase": "error", "msg": str(e)})
                traceback.print_exc()

    def _pick_cdp_port(self) -> int:
        import socket
        for p in range(9222, 9322):
            with socket.socket() as s:
                try:
                    s.bind(("127.0.0.1", p))
                    return p
                except OSError:
                    continue
        return 9222

    def _ensure_browser(self, url: str = LOGIN_URL) -> Page:
        if self.browser is None:
            self.browser = Browser(port=self._pick_cdp_port(), headless=self.settings["headless"])
            self.log("info", "启动 Chromium 内核浏览器…（约 3~8 秒）")
            self.browser.start(url)
            time.sleep(1.2)
        if self.page is None:
            self.page = Page.attach(self.browser)
            self.page.enable()
        return self.page

    def inject(self) -> None:
        if self.page is None:
            return
        if not self._inject_src:
            with open(resource("assets", "inject.js"), "r", encoding="utf-8") as f:
                self._inject_src = f.read()
            m = re.search(r"version:\s*'([\d.]+)'", self._inject_src)
            self._inject_ver = m.group(1) if m else ""
        try:
            ver = self.page.eval("window.__EF && window.__EF.version || ''")
            if self._inject_ver and ver == self._inject_ver:
                return
            self.page.eval(self._inject_src)
        except Exception as e:
            self.log("warn", f"注入脚本失败：{e}")

    def _wait_for(self, js_cond: str, timeout: float = 15.0) -> bool:
        end = time.time() + timeout
        while time.time() < end:
            try:
                if self.page and self.page.eval(js_cond):
                    return True
            except Exception:
                pass
            time.sleep(0.25)
        return False

    def _click_input(self, placeholder_keyword: str) -> bool:
        js = f"""(() => {{
          const ins = Array.from(document.querySelectorAll('input'));
          const el = ins.find(i => (i.placeholder||'').includes({json.dumps(placeholder_keyword)}));
          if(!el) return false;
          el.scrollIntoView({{block:'center'}});
          el.focus();
          el.click();
          return true;
        }})()"""
        return bool(self.page and self.page.eval(js))

    def _insert_text(self, text: str) -> None:
        assert self.page
        self.page.send("Input.insertText", {"text": text})

    def _type_field(self, placeholder: str, value: str, clear: bool = True, blur: bool = True) -> bool:
        if not self._click_input(placeholder):
            return False
        time.sleep(0.12)
        if clear:

            self.page.send("Input.dispatchKeyEvent", {"type": "keyDown", "modifiers": 2, "key": "a", "code": "KeyA", "windowsVirtualKeyCode": 65})
            self.page.send("Input.dispatchKeyEvent", {"type": "keyUp", "modifiers": 2, "key": "a", "code": "KeyA", "windowsVirtualKeyCode": 65})
        self._insert_text(value)
        time.sleep(0.1)
        if blur:
            self.page.eval("document.activeElement && document.activeElement.blur()")
        return True

    def launch(self, settings: dict) -> None:
        self.settings.update({k: v for k, v in settings.items() if k in self.settings})
        self.submit(self._launch)

    def _launch(self) -> None:
        self.stop_flag = False
        self._phase("booting", "启动浏览器")
        page = self._ensure_browser(LOGIN_URL)
        try:
            page.navigate(LOGIN_URL)
        except Exception:
            pass
        self._phase("login", "等待登录页")
        ok = self._wait_for("!!document.querySelector('input[placeholder*=\"账号\"], input[placeholder*=\"学校\"]')", 25)
        if not ok:
            self.log("warn", "登录页元素没等到，可能已登录或网络慢")
        self.inject()
        self.log("info", "填入学校 / 账号 / 密码")
        self._fill_user_fields()
        self._refresh_captcha()
        if self.settings.get("auto_captcha", True):
            self.log("info", "自动识别验证码并登录…")
            self._login()
        else:
            self._phase("captcha", "等待验证码")
            self.bus.pub({"type": "state"})

    def _fill_user_fields(self) -> None:
        school = str(self.settings.get("school") or "").strip()
        if school:

            if not self._type_field("学校", school, blur=False):
                self.log("warn", "未找到学校输入框")
            else:
                js_pick = """(() => {
                  const key = %s;
                  const items = Array.from(document.querySelectorAll('.el-select-dropdown__item'))
                    .filter(e => e.getBoundingClientRect().height > 0);
                  const norm = (s) => (s || '').replace(/\\s+/g, '');
                  const target = items.find(e => norm(e.innerText) === key)
                    || items.find(e => norm(e.innerText).includes(key));
                  if (!target) return '';
                  target.click();
                  return target.innerText.trim();
                })()"""
                picked = ""
                school_key = re.sub(r"\s+", "", school)
                for _ in range(24):
                    try:
                        picked = self.page.eval(js_pick % json.dumps(school_key))
                    except Exception:
                        picked = ""
                    if picked:
                        break
                    time.sleep(0.15)
                if picked:
                    self.log("ok", f"学校已选择：{picked}")
                else:
                    self.log("warn", "下拉里没匹配到学校名，请手动确认")
                self.page.eval("document.activeElement && document.activeElement.blur()")
        user = str(self.settings.get("user") or "").strip()
        if user:
            self._type_field("账号", user)
        pwd = str(self.settings.get("password") or "").strip()
        if pwd:
            self._type_field("密码", pwd)

    def refresh_captcha(self) -> None:
        self.submit(self._refresh_captcha)

    def _refresh_captcha(self) -> None:
        assert self.page
        try:

            self.page.eval(
                """(() => {
                  const img = document.querySelector('img[src*="getCaptcha"]');
                  if (!img) return false;
                  img.click();
                  setTimeout(() => {
                    if (!img.complete || !img.naturalWidth) {
                      const u = img.src.split('?')[0];
                      img.src = u + '?timestamp=' + Date.now();
                    }
                  }, 400);
                  return true;
                })()"""
            )
        except Exception:
            pass
        time.sleep(0.9)
        data = ""
        try:
            data = self.page.eval(
                """(async () => {
                  const img = document.querySelector('img[src*="getCaptcha"]');
                  if (!img) return '';
                  for (let i = 0; i < 30 && !(img.complete && img.naturalWidth); i++) {
                    await new Promise(r => setTimeout(r, 100));
                  }
                  try {
                    const c = document.createElement('canvas');
                    c.width = img.naturalWidth || 150;
                    c.height = img.naturalHeight || 50;
                    c.getContext('2d').drawImage(img, 0, 0);
                    const d = c.toDataURL('image/png');
                    if (d && d.length > 300) return d;
                  } catch (e) {}
                  try {
                    const r = await fetch(img.src, { credentials: 'include', cache: 'no-store' });
                    const blob = await r.blob();
                    return await new Promise(res => {
                      const fr = new FileReader();
                      fr.onload = () => res(fr.result);
                      fr.onerror = () => res('');
                      fr.readAsDataURL(blob);
                    });
                  } catch (e) { return img.src; }
                })()"""
            )
        except Exception as e:
            self.log("warn", f"取验证码失败：{e}")
        self.captcha = data or ""
        if self.captcha:
            self.log("info", "验证码已抓取，等待输入")
        else:
            self.log("warn", "验证码抓取为空，请在浏览器窗口里直接看")
        self.bus.pub({"type": "captcha", "data": self.captcha})

    def login(self, code: str) -> None:

        self._login_abort = True
        self.settings["captcha_code"] = code
        self.submit(self._login, True)

    def _get_ocr(self):
        if getattr(self, "_ocr", None) is None:
            try:
                import ddddocr
                self._ocr = ddddocr.DdddOcr(show_ad=False)
                self.log("ok", "验证码识别引擎就绪（ddddocr）")
            except Exception as e:
                self._ocr = False
                self.log("warn", f"OCR 不可用，改为手动输入：{e}")
        return self._ocr or None

    def _ocr_captcha(self, data_url: str) -> str:
        ocr = self._get_ocr()
        if not ocr or not data_url or "," not in data_url:
            return ""
        try:
            raw = base64.b64decode(data_url.split(",", 1)[1])
            txt = ocr.classification(raw) or ""
            return re.sub(r"[^A-Za-z0-9]", "", txt).upper()
        except Exception:
            return ""

    def _do_login_once(self, code: str) -> str:
        assert self.page
        self._phase("logging", "提交登录")
        if code:

            self._type_field("验证码", code, clear=True)
        time.sleep(0.2)

        clicked = self.page.eval(
            """(() => {
              const all = Array.from(document.querySelectorAll('.login-btn, button, .el-button, div, span, a'));
              const cands = all.filter(e => {
                const t = (e.innerText || '').trim();
                const r = e.getBoundingClientRect();
                return t === '登录' && r.width > 20 && r.height > 10 && r.height < 90 && e.children.length <= 2;
              });
              const b = cands[cands.length - 1];
              if (!b) return false;
              b.scrollIntoView({ block: 'center' });
              b.click();
              return true;
            })()"""
        )
        if not clicked:
            self.log("warn", "没找到登录按钮，尝试回车提交")
            self.page.send("Input.dispatchKeyEvent", {"type": "keyDown", "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13})
            self.page.send("Input.dispatchKeyEvent", {"type": "keyUp", "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13})
        end = time.time() + 14
        while time.time() < end:
            if self._login_abort:
                return "abort"
            txt = self.page.eval("document.body.innerText") or ""
            if "顺序练习" in txt or "随机练习" in txt:
                self._phase("ready", "登录成功")
                self.log("ok", "登录成功，已进入平台首页")
                self._dismiss_dialogs()
                self.inject()
                return "ok"

            if any(k in txt for k in ("验证码错误", "验证码不正确", "验证码已过期", "请输入正确的验证码")):
                return "bad_captcha"
            if any(k in txt for k in ("账号或密码错误", "用户名或密码错误", "账号不存在", "密码错误")):
                return "bad_pwd"
            time.sleep(0.5)
        return "unknown"

    def _login(self, manual: bool = False) -> None:
        assert self.page

        if manual:
            self._login_abort = False
            code = str(self.settings.get("captcha_code") or "").strip()
            if not code:
                self._phase("captcha", "请输入验证码")
                return
            res = self._do_login_once(code)
            if res == "ok":
                return
            if res == "bad_pwd":
                self.log("error", "账号或密码错误，请检查学号/密码")
                self._phase("captcha", "账号或密码错误")
                return
            self.log("warn", "验证码不对，已换一张，请重新输入")
            self._refresh_captcha()
            self._phase("captcha", "请重新输入验证码")
            return

        if self._get_ocr() is None:
            self.log("warn", "OCR 不可用，改为手动输入验证码")
            self._phase("captcha", "请手动输入验证码")
            return

        self._login_abort = False
        for attempt in range(1, 4):
            if self._login_abort:
                self.log("info", "已切换手动登录，自动识别停止")
                return
            code = self._ocr_captcha(self.captcha)
            if not code:
                self.log("warn", f"第 {attempt} 次识别失败，换一张")
                self._refresh_captcha()
                continue
            self.log("info", f"第 {attempt} 次尝试，验证码识别为 {code}")
            res = self._do_login_once(code)
            if res == "ok":
                return
            if res == "abort":
                self.log("info", "已切换手动登录，自动识别停止")
                return
            if res == "bad_pwd":
                self.log("error", "账号或密码错误，请检查学号/密码")
                self._phase("captcha", "账号或密码错误")
                return
            if res == "bad_captcha":
                self.log("warn", "验证码不对，换一张重试")
                self._refresh_captcha()
                continue
            self.log("warn", "登录状态未知，刷新验证码重试")
            self._refresh_captcha()

        self.log("error", "自动识别没成功，请手动输入左侧验证码")
        self._phase("captcha", "请手动输入验证码")

    def _dismiss_dialogs(self) -> None:
        js = """(words => {
          const nodes = Array.from(document.querySelectorAll('button, .el-button, span, div'))
            .filter(e => { const r = e.getBoundingClientRect(); return r.width > 4 && r.height > 4; });
          for (const w of words) {
            const t = nodes.find(e => (e.innerText || '').trim() === w);
            if (t) { t.click(); return w; }
          }
          return '';
        })(%s)"""
        for words in (["暂不修改"], ["我知道了", "知道了"], ["确定", "确认"]):
            try:
                hit = self.page.eval(js % json.dumps(words))
                if hit:
                    self.log("info", f"关闭弹窗：{hit}")
                    time.sleep(0.5)
            except Exception:
                pass

    def enter(self, module: str) -> None:
        self.submit(self._enter, module)

    def _enter(self, module: str) -> None:
        assert self.page
        self.inject()
        name = MODULES.get(module, ["顺序练习"])[0]
        self._phase("entering", f"开始 {name}")

        hit = self.page.eval(
            """(name => {
              const blocks = Array.from(document.querySelectorAll('.block'));
              const b = blocks.find(e => ((e.querySelector('h5') || {}).innerText || '').trim() === name);
              if (!b) return '';
              const btns = Array.from(b.querySelectorAll('button'));
              const s = btns.find(x => /开\\s*始/.test(x.innerText || ''));
              if (!s) return '';
              s.scrollIntoView({ block: 'center' });
              s.click();
              return 'ok';
            })(%s)""" % json.dumps(name)
        )
        if not hit:
            self.log("warn", f"首页没找到「{name}」卡片，尝试按文本点击")
            self.page.eval("__EF.clickByText([%s])" % json.dumps(name))
        else:
            self.log("ok", f"点击「{name} · 开 始」")

        time.sleep(1.2)

        for _ in range(5):
            try:
                if "exam" in (self.page.url() or ""):
                    break
            except Exception:
                pass
            clicked = self.page.eval(
                """(() => {
                  const dlg = Array.from(document.querySelectorAll('.el-dialog__wrapper'))
                    .find(e => e.getBoundingClientRect().height > 0);
                  if (!dlg) return false;
                  const btns = Array.from(dlg.querySelectorAll('button'));
                  const b = btns.find(x => /开\\s*始|确\\s*定|进\\s*入|确\\s*认/.test(x.innerText || ''))
                    || btns[btns.length - 1];
                  if (!b) return false;
                  b.click();
                  return true;
                })()"""
            )
            if clicked:
                self.log("info", "确认弹窗已点掉")
            time.sleep(1.3)

        self.inject()
        end = time.time() + 10
        st = None
        while time.time() < end:
            try:
                st = self.page.eval("__EF ? __EF.probe() : null")
            except Exception:
                st = None
            if st and st.get("options"):
                break
            time.sleep(0.4)

        if st and st.get("options"):
            self.log("ok", f"已进入答题界面：{st.get('type')} / {len(st['options'])} 个选项")
            self.current = st
            self._phase("answering", "就绪")
            self.bus.pub({"type": "question", **st})
        else:
            self.log("warn", "没检测到答题界面，请在浏览器里手动点进去后再按「开始答题」")
            self._phase("manual", "等待手动进入")

    def collect(self) -> None:
        self.submit(self._collect)

    def _reveal_answer(self) -> list[str]:
        assert self.page
        try:
            self.page.eval("__EF.clickByText(['查看答案'])")
        except Exception:
            return []
        letters: list[str] = []
        for _ in range(16):
            time.sleep(0.15)
            try:
                box = self.page.eval(
                    """(() => {
                      const b = document.querySelector('.el-message-box');
                      return b && b.getBoundingClientRect().height > 5 ? (b.innerText || '') : '';
                    })()"""
                ) or ""
            except Exception:
                box = ""
            m = re.search(r"正确选项[:：]\s*([A-H][A-H,，、\s]*)", box)
            if m:
                letters = [c for c in m.group(1) if c in "ABCDEFGH"]
                break
        try:

            self.page.eval(
                """(() => {
                  const b = document.querySelector('.el-message-box__btns button');
                  if (!b) return false;
                  b.click();
                  return true;
                })()"""
            )
        except Exception:
            pass
        time.sleep(0.3)
        return letters

    def _back_to_first(self) -> None:
        assert self.page
        for _ in range(400):
            total, idx = self._read_progress()
            if idx <= 1:
                return
            before = idx
            self.page.eval("__EF.clickByText(['上一题'])")
            for _ in range(20):
                time.sleep(0.1)
                _, cur = self._read_progress()
                if cur and cur != before:
                    break
            else:
                return

    def _collect(self) -> None:
        assert self.page
        self.running = True
        self.stop_flag = False
        self.stats["started_at"] = time.time()
        self._phase("collecting", "采集中")
        self.log("info", "开始采集官方答案（顺序练习 · 查看答案）")

        self.inject()
        st = self.page.eval("__EF ? __EF.probe() : null")
        if not st or not st.get("options"):
            self.log("info", "不在答题页，自动进入顺序练习…")
            try:
                self._enter("seq")
                time.sleep(1.2)
                self.inject()
            except Exception as e:
                self.log("error", f"进入顺序练习失败：{e}")
            st = self.page.eval("__EF ? __EF.probe() : null")
            if not st or not st.get("options"):
                self.log("error", "无法进入答题页，请先手动点「顺序练习」")
                self._phase("manual", "请先进入顺序练习")
                self.running = False
                return

        self._back_to_first()
        total, idx = self._read_progress()
        self.log("info", f"已回到第 {idx} 题，共 {total or '?'} 题")

        if self.textbank is None:
            self.textbank = TextBank(os.path.join(user_dir(), "bank_text.json"))

        added = 0
        while not self.stop_flag:
            while self.paused and not self.stop_flag:
                time.sleep(0.2)
            try:
                self.inject()
                st = self.page.eval("__EF ? __EF.probe() : null")
            except Exception as e:
                self.log("error", f"读取页面失败：{e}")
                break
            if not st or not st.get("options"):
                self.log("ok", "已到末尾，采集结束")
                break

            q = st["question"]

            try:
                first_key = st["options"][0]["key"] if st["options"] else "A"
                self.page.eval(f"__EF.answer({json.dumps(first_key)})")
                time.sleep(0.15)
            except Exception:
                pass
            letters = self._reveal_answer()
            if letters:
                opt_text = {o["key"]: o["text"] for o in st["options"]}
                texts = [opt_text[k] for k in letters if k in opt_text]
                if texts:
                    self.textbank.add(q, texts)
                    added += 1
                    total_n, cur = self._read_progress()
                    self.log("ok", f"[{cur}/{total_n}] {''.join(letters)} ← {q[:28]}")
                else:
                    self.log("warn", f"答案字母映射失败：{''.join(letters)} / {q[:24]}")
            else:
                self.log("warn", f"没读到正确选项：{q[:28]}")

            if added and added % 25 == 0:
                self.textbank.save()
                self.log("info", f"已保存 {len(self.textbank)} 题到 bank_text.json")

            self.stats["answered"] = added
            self.bus.pub({"type": "stats", **self.stats})

            if not st.get("hasNext"):
                self.log("ok", "没有下一题，采集结束")
                break

            old = q
            self.page.eval("__EF.next()")
            for _ in range(40):
                time.sleep(0.12)
                try:
                    cur_q = self.page.eval("__EF.probe().question") or ""
                except Exception:
                    cur_q = ""
                if cur_q and cur_q != old:
                    break

        self.textbank.save()
        self.running = False
        self._phase("done", "采集结束")
        self.log("ok", f"采集完成：本次新增 {added} 题，题库共 {len(self.textbank)} 题")
        self.bus.pub({"type": "stats", **self.stats})

    def _match_text_keys(self, st: dict, texts: list[str]) -> str | None:
        def strip(t: str) -> str:
            return normalize(re.sub(r"^[A-H]\s*[\.．、\)）:：]?\s*", "", t or ""))

        keys: list[str] = []
        opts = st.get("options") or []
        for t in texts:
            w = strip(t)
            hit = None
            for o in opts:
                if strip(o["text"]) == w:
                    hit = o["key"]
                    break
            if hit is None:
                return None
            keys.append(hit)
        return "".join(sorted(set(keys))) if keys else None

    def run(self) -> None:
        self.submit(self._run_all)

    def _read_progress(self) -> tuple[int, int]:
        try:
            txt = self.page.eval("document.body.innerText") or ""
        except Exception:
            return 0, 0
        m = re.search(r"当前[:：]\s*(\d+)\s*/\s*(\d+)", txt)
        if m:
            return int(m.group(2)), int(m.group(1))
        return 0, 0

    def _time_left(self) -> int:
        try:
            txt = self.page.eval("document.body.innerText") or ""
        except Exception:
            return 0
        m = re.search(r"(\d+)\s*时\s*(\d+)\s*分\s*(\d+)\s*秒", txt)
        if m:
            return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
        return 0

    def _target_right(self, total: int) -> int:
        mode = self.settings.get("mode")
        if mode == "top":
            return total
        if mode == "custom":
            acc = float(self.settings.get("accuracy") or 85)
            return max(int(total * acc / 100.0), int(total * 0.8))
        return int(self.settings.get("target") or 84)

    def _pace(self, idx: int, total: int) -> float:
        mode = self.settings.get("mode")
        if mode in ("real", "custom"):
            lo = float(self.settings.get("speed_min") or 3)
            hi = float(self.settings.get("speed_max") or 10)
            if hi < lo:
                lo, hi = hi, lo
            want = random.uniform(lo, hi)
        else:
            want = float(self.settings.get("delay") or 0.25)

        left = self._time_left()
        if left > 0 and total > 0 and idx > 0:
            remain_q = max(1, total - idx + 1)
            budget = left / remain_q * 0.75
            want = min(want, max(0.15, budget))
        return want

    def _should_miss(self, right: int, idx: int, total: int, target: int) -> bool:
        mode = self.settings.get("mode")
        if mode not in ("pass", "real", "custom"):
            return False

        if total <= 0 or total > 200:
            return False

        if mode == "custom":
            acc = float(self.settings.get("accuracy") or 85)
            # 不设人为上限：用户填 99 就该答对 99 题，之前卡 min(96, acc+6)
            # 导致 99% 只给到 96，白丢 3 题
            ceiling = 100
            floor = max(80, int(acc) - 5)
        else:
            ceiling = int(self.settings.get("ceiling") or 92)
            floor = int(self.settings.get("floor") or 80)
            ceiling = max(ceiling, target)   # 目标高于 92 时以目标为准，别把人卡在 92

        remaining = total - idx + 1
        need = target - right

        if right >= ceiling:
            return True
        if need <= 0:
            return True
        if right + remaining <= floor:
            return False
        if need >= remaining:
            return False
        p_right = need / remaining
        return random.random() > p_right

    def _wrong_keys(self, st: dict, keys: str) -> str:
        opts = st.get("options") or []
        all_keys = [o["key"] for o in opts]
        good = [k for k in keys if k in all_keys]
        bad = [k for k in all_keys if k not in good]
        if not all_keys:
            return keys
        if len(good) <= 1:
            if bad:
                return random.choice(bad)
            return ""
        if bad:
            keep = sorted(good)[:-1]
            return "".join(sorted(set(keep + [random.choice(bad)])))

        drop = random.choice(sorted(good))
        return "".join(k for k in sorted(good) if k != drop)

    def _click_options(self, keys: str) -> list[str]:
        assert self.page
        try:
            pts = self.page.eval(f"__EF.targets({json.dumps(keys)})") or []
        except Exception as e:
            self.log("warn", f"取选项坐标失败：{e}")
            pts = []
        if not pts:

            try:
                self.page.eval(f"__EF.answer({json.dumps(keys)})")
            except Exception:
                pass
            return []

        hit: list[str] = []
        for p in pts:
            x, y = float(p["x"]), float(p["y"])
            for typ in ("mousePressed", "mouseReleased"):
                self.page.send("Input.dispatchMouseEvent", {
                    "type": typ, "x": x, "y": y, "button": "left", "clickCount": 1,
                })
            hit.append(p["key"])
            time.sleep(0.15)
        return hit

    def _set_options(self, keys: str) -> None:
        want = sorted(set(keys))

        for k in want:
            try:
                self.page.eval(f"__EF.clickOne({json.dumps(k)})")
            except Exception:
                pass
            time.sleep(0.12)

        try:
            model = self.page.eval("__EF.model()")
        except Exception:
            model = None
        if isinstance(model, list) and len(model) != len(want):
            self.log("warn", f"Vue 状态 {len(model)}/{len(want)}，逐个补点")
            try:
                self.page.eval("__EF.clearAll()")
                time.sleep(0.15)
            except Exception:
                pass
            for k in want:
                try:
                    self.page.eval(f"__EF.clickOne({json.dumps(k)})")
                except Exception:
                    pass
                time.sleep(0.22)

    def _submit_paper(self) -> bool:
        assert self.page
        self.log("info", "自动交卷…")
        ok = False
        for _ in range(3):

            pt = None
            try:
                pt = self.page.eval("__EF.submitPoint()")
            except Exception:
                pt = None
            if pt:
                self.log("info", f"点「{pt.get('text')}」")
                for typ in ("mousePressed", "mouseReleased"):
                    self.page.send("Input.dispatchMouseEvent", {
                        "type": typ, "x": float(pt["x"]), "y": float(pt["y"]),
                        "button": "left", "clickCount": 1,
                    })
                ok = True
                break
            try:
                ok = bool(self.page.eval("__EF.submit()"))
            except Exception:
                ok = False
            if ok:
                break
            time.sleep(0.5)
        if not ok:
            self.log("error", "没找到提交按钮，请手动点交卷")
            return False

        time.sleep(1.3)

        for _ in range(3):
            hit = self.page.eval(
                """(() => {
                  const box = Array.from(document.querySelectorAll('.el-message-box, .el-dialog, [role=dialog]'))
                    .find(e => e.getBoundingClientRect().height > 20);
                  if (!box) return false;
                  const btns = Array.from(box.querySelectorAll('button'));
                  const txt = (x) => (x.innerText || '').replace(/\\s+/g, '');
                  const b = btns.find(x => txt(x) === '确定')
                    || btns.find(x => txt(x) === '确认')
                    || btns.find(x => /确定|确认|是$/.test(txt(x)))
                    || btns[btns.length - 1];
                  if (!b) return false;
                  b.scrollIntoView({ block: 'center' });
                  b.click();
                  return txt(b);
                })()"""
            )
            if not hit:
                break
            self.log("info", "已确认交卷")
            time.sleep(1.0)

        end = time.time() + 20
        while time.time() < end:
            try:
                body = self.page.eval("document.body.innerText") or ""
            except Exception:
                body = ""
            m = re.search(r"共计\s*(\d+)\s*\|?\s*.*?答对\s*(\d+)", body)
            if not m:
                m2 = re.search(r"(\d+)\s*分", body)
            if "很遗憾" in body or "恭喜" in body or "通过" in body:
                score = ""
                sm = re.search(r"(\d+)\s*分", body)
                if sm:
                    score = sm.group(1) + " 分"
                am = re.search(r"答对\s*(\d+)", body)
                self.log("ok", f"交卷完成{f'，成绩 {score}' if score else ''}{f'，答对 {am.group(1)}' if am else ''}")
                return True
            if any(k in body for k in ("成绩", "已提交", "查看解析")):
                self.log("ok", "交卷完成")
                return True
            time.sleep(0.6)
        self.log("warn", "交卷后没检测到成绩页，请到浏览器确认")
        return True

    def _run_all(self) -> None:
        assert self.page
        self.running = True
        self.stop_flag = False
        self.stats["started_at"] = time.time()
        self.stats.update({"right": 0, "wrong": 0, "text": 0})
        self._phase("running", "自动答题中")
        MODE_NAME = {"top": "速刷全对", "pass": "控分速刷", "real": "控分拟真", "custom": "自定义"}
        mode_txt = MODE_NAME.get(self.settings.get("mode"), "速刷全对")
        extra = ""
        if self.settings.get("mode") in ("real", "custom"):
            extra = f"，每题 {self.settings.get('speed_min')}~{self.settings.get('speed_max')}s"
        self.log("info", f"答题循环启动（{mode_txt}{extra}）")
        last_q = ""
        same_count = 0
        while not self.stop_flag:
            while self.paused and not self.stop_flag:
                time.sleep(0.2)
            try:
                self.inject()
                st = self.page.eval("__EF ? __EF.probe() : null")
            except Exception as e:
                self.log("error", f"读取页面失败：{e}")
                break
            if not st or not st.get("options"):
                txt = self.page.eval("document.body.innerText") or ""
                if "交卷" in txt or "成绩" in txt:
                    self.log("ok", "已到交卷/成绩页，循环结束")
                else:
                    self.log("warn", "当前页面没有题目，循环结束")
                break

            q = st["question"]
            if q == last_q:
                same_count += 1
                if same_count >= 3:
                    self.log("warn", "连续 3 次读到同一题，可能翻页失败，已停止")
                    break
            else:
                same_count = 0
            last_q = q

            ans, how, score = self.bank.lookup(q)
            planned = "".join(split_answer(ans)) if ans else ""

            if self.textbank:
                texts = self.textbank.lookup(q)
                if texts:
                    by_text = self._match_text_keys(st, texts)
                    if by_text:
                        planned = by_text
                        how = "text"
                        score = 1.0
                        self.stats["text"] += 1

            if not planned:
                self.stats["miss"] += 1
                self.missed.append({"question": q, "type": st.get("type"), "url": st.get("url")})
                mode = self.settings.get("on_miss", "first")
                if mode == "stop":
                    self.log("error", "遇到题库未命中的题，按要求停止")
                    break
                if mode == "skip":
                    self.log("warn", f"未命中，跳过：{q[:36]}")
                else:
                    planned = st["options"][0]["key"] if st.get("options") else "A"
                    self.log("warn", f"未命中，随机选 {planned}：{q[:36]}")
            else:
                self.stats["exact" if how in ("exact", "text") else "fuzzy"] += 1
            click_keys = planned
            on_purpose = False

            total, idx = self._read_progress()
            tgt = self._target_right(total) if total else 0
            if click_keys and total and self._should_miss(self.stats["right"], idx, total, tgt):
                w = self._wrong_keys(st, click_keys)
                if w and w != click_keys:
                    click_keys = w
                    on_purpose = True

            self.current = {**st, "answer": click_keys, "planned": planned,
                            "how": "planned" if on_purpose else how, "score": round(score, 3)}
            self.bus.pub({"type": "question", **self.current})
            keys = click_keys

            if keys:
                try:

                    self._set_options(keys)
                    time.sleep(min(0.28, float(self.settings.get("delay", 0.3)) + 0.08))
                    chk = self.page.eval("__EF.checked()") or []
                    model = self.page.eval("__EF.model()")
                    if not chk:
                        self.log("error", f"选项没选中（应选 {keys}），可能页面结构变了")
                    elif set(chk) != set(list(keys)):
                        self.log("warn", f"选中项与预期不一致：期望 {keys}，实际 {''.join(chk)}")
                    elif model is not None and isinstance(model, list) and len(model) == 0:

                        self.log("warn", "点击未写入 Vue 状态，重试")
                        self._click_options(keys)
                        time.sleep(0.25)
                        chk = self.page.eval("__EF.checked()") or []
                    if on_purpose:
                        self.stats["wrong"] += 1
                        self.log("warn", f"[控分] {''.join(chk)} ← {q[:30]}  (故意错，正解 {planned})")
                    else:
                        self.stats["right"] += 1
                        self.log("ok" if how != "miss" else "warn",
                                 f"[{st.get('type','')}] {''.join(chk)} ← {q[:34]}  ({how} {score:.2f})")
                    self.bus.pub({"type": "picked", "picked": chk, "keys": keys})
                except Exception as e:
                    self.log("error", f"选项点击失败：{e}")
            pace = self._pace(idx, total)
            if pace > 1.0:
                self.bus.pub({"type": "pace", "sec": round(pace, 1)})
            time.sleep(pace)

            self.stats["answered"] += 1
            self.bus.pub({"type": "stats", **self.stats})

            if not st.get("hasNext"):
                self.log("ok", "没有「下一题」按钮，本题为最后一题")
                if self.settings.get("auto_submit"):
                    self._submit_paper()
                break

            old = q
            try:
                self.page.eval("__EF.next()")
            except Exception as e:
                self.log("error", f"翻页失败：{e}")
                break
            changed = False
            end = time.time() + 8
            while time.time() < end:
                time.sleep(0.15)
                try:
                    cur = self.page.eval("__EF ? __EF.probe().question : ''") or ""
                except Exception:
                    cur = ""
                if cur and cur != old:
                    changed = True
                    break
            if not changed:

                try:
                    body = self.page.eval("document.body.innerText") or ""
                except Exception:
                    body = ""
                if any(k in body for k in ("交卷", "提交", "成绩", "考试结束", "已完成")):
                    self.log("ok", "已到交卷/成绩页，循环结束")
                    if self.settings.get("auto_submit"):
                        self._submit_paper()
                    break
                self.log("warn", "题目未变化，尝试再点一次下一题")
                try:
                    self.page.eval("__EF.next()")
                except Exception:
                    pass
                time.sleep(1.2)
                try:
                    cur = self.page.eval("__EF ? __EF.probe().question : ''") or ""
                except Exception:
                    cur = ""
                if cur == old:
                    self.log("warn", "翻页无效，停止")
                    break

        self.running = False
        self._phase("done", "答题结束")
        self.bus.pub({"type": "stats", **self.stats})
        self.log("ok", f"结束：共 {self.stats['answered']} 题｜文本命中 {self.stats.get('text', 0)}｜"
                       f"字母命中 {self.stats['exact']}｜模糊 {self.stats['fuzzy']}｜未命中 {self.stats['miss']}")

    def stop(self) -> None:
        self.stop_flag = True
        self.running = False
        self.log("info", "已请求停止")

    def toggle_pause(self, paused: bool) -> None:
        self.paused = paused
        self.log("info", "暂停" if paused else "继续")

    def screenshot(self) -> str:
        if self.page is None:
            return ""
        try:

            res = self.page.send("Page.captureScreenshot", {"format": "jpeg", "quality": 62}, timeout=6)
            return "data:image/jpeg;base64," + res.get("data", "")
        except Exception:
            return ""

    def export_missed(self) -> str:
        p = os.path.join(user_dir(), "missed.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(self.missed, f, ensure_ascii=False, indent=2)
        return p

    def snapshot(self) -> dict:
        elapsed = 0
        if self.stats["started_at"]:
            elapsed = int(time.time() - self.stats["started_at"])
        return {
            "phase": self.phase,
            "running": self.running,
            "paused": self.paused,
            "error": self.error,
            "bank": len(self.bank),
            "textbank": len(self.textbank) if self.textbank else 0,
            "stats": {**self.stats, "elapsed": elapsed},
            "current": self.current,
            "settings": self.settings,
            "logs": self.logs[-120:],
            "missed": len(self.missed),
            "has_captcha": bool(self.captcha),
        }
