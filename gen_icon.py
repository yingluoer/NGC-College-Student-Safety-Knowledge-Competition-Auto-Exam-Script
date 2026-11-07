"""生成应用图标：黑底 + 酸性黄绿菱形标记，导出多尺寸 ico。"""
import os
from PIL import Image, ImageDraw

ACC = (216, 255, 62, 255)
BG = (11, 12, 12, 255)
CYAN = (127, 231, 208, 255)


def render(n: int) -> Image.Image:
    S = n * 4  # 超采样后再缩，边缘更干净
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = int(S * 0.14)
    d.rounded_rectangle([0, 0, S - 1, S - 1], radius=r, fill=BG)

    # 外菱形
    cx = cy = S / 2
    k = S * 0.33
    outer = [(cx, cy - k), (cx + k, cy), (cx, cy + k), (cx - k, cy)]
    d.polygon(outer, outline=ACC, width=max(2, int(S * 0.028)))

    # 内菱形（实心）
    k2 = S * 0.13
    inner = [(cx, cy - k2), (cx + k2, cy), (cx, cy + k2), (cx - k2, cy)]
    d.polygon(inner, fill=ACC)

    # 右下角刻度，呼应终端界面的角标
    m = S * 0.16
    d.line([(S - m, S * 0.80), (S - m, S - m), (S * 0.80, S - m)], fill=CYAN, width=max(2, int(S * 0.016)))

    return img.resize((n, n), Image.LANCZOS)


def main() -> None:
    sizes = [256, 128, 64, 48, 32, 16]
    imgs = [render(s) for s in sizes]
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "app.ico")
    imgs[0].save(out, format="ICO", sizes=[(s, s) for s in sizes], append_images=imgs[1:])
    imgs[0].save(os.path.join(os.path.dirname(out), "app.png"))
    print("icon:", out, os.path.getsize(out))


if __name__ == "__main__":
    main()
