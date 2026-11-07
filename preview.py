import base64, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core.engine import Engine
from core.server import serve
from core.cdp import Browser, Page

eng = Engine()
httpd, port = serve(eng, 8792)

Q = {
    "type": "多选题",
    "question": "2026年境外间谍窃密手段不断升级，以下属于新型窃密手段的是____。",
    "options": [
        {"key": "A", "text": "A．在军事禁区外围定点蹲守拍照", "checked": False},
        {"key": "B", "text": "B．以学术合作名义索要未公开实验数据", "checked": False},
        {"key": "C", "text": "C．通过网络水军账号矩阵批量套取科研人员社交关系", "checked": True},
        {"key": "D", "text": "D．直接潜入实验室窃取纸质文件", "checked": False},
    ],
    "answer": "ABC",
    "how": "fuzzy",
    "score": 0.94,
    "hasNext": True,
}
eng.current = Q
eng.phase = "running"
eng.stats.update({"answered": 137, "exact": 118, "fuzzy": 16, "miss": 3, "started_at": time.time() - 421})
for lv, m in [("info", "答题循环启动"), ("ok", "[多选题] ABC ← 2026年境外间谍窃密手段不断升级 (fuzzy 0.94)"),
              ("warn", "未命中，随机选 A：某高校学生收到境外“学术期刊”约稿邮件"), ("ok", "[单选题] B ← 使用灭火器进行灭火的最佳位置是 (exact 1.00)")]:
    eng.log(lv, m)

w, h = 1500, 940
b = Browser(port=9337, profile=os.path.join(os.environ.get("TEMP", "."), "ef-prev"), headless=True)
b.start("about:blank", width=w, height=h)
p = Page.attach(b)
p.enable()
p.send("Emulation.setDeviceMetricsOverride", {"width": w, "height": h, "deviceScaleFactor": 1, "mobile": False})
p.navigate(f"http://127.0.0.1:{port}/")
time.sleep(2.2)
eng.bus.pub({"type": "question", **Q})
eng.bus.pub({"type": "stats", **eng.stats})
p.eval("document.querySelector('#captchaImg').src='data:image/svg+xml;base64," + base64.b64encode(
    b"""<svg xmlns='http://www.w3.org/2000/svg' width='150' height='50'><rect width='150' height='50' fill='#0f1211'/><text x='12' y='34' font-family='monospace' font-size='26' fill='#d8ff3e' letter-spacing='6'>W7K8</text></svg>"""
).decode() + "';document.querySelector('#captchaImg').classList.add('on');document.querySelector('#captchaMask').classList.add('hide');")
time.sleep(1.0)
res = p.send("Page.captureScreenshot", {"format": "png"})
open("ui3.png", "wb").write(base64.b64decode(res["data"]))
print("ok", os.path.getsize("ui3.png"))
