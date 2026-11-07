import base64, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core.cdp import Browser, Page

url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8791/"
out = sys.argv[2] if len(sys.argv) > 2 else "shot.png"
w = int(sys.argv[3]) if len(sys.argv) > 3 else 1500
h = int(sys.argv[4]) if len(sys.argv) > 4 else 940

b = Browser(port=9336, profile=os.path.join(os.environ.get("TEMP", "."), "ef-shot"), headless=True)
b.start("about:blank", width=w, height=h)
p = Page.attach(b)
p.enable()
p.send("Emulation.setDeviceMetricsOverride", {"width": w, "height": h, "deviceScaleFactor": 1, "mobile": False})
p.navigate(url)
time.sleep(2.6)
res = p.send("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False})
open(out, "wb").write(base64.b64decode(res["data"]))
print("saved", out, os.path.getsize(out), p.eval("[innerWidth, innerHeight]"))
