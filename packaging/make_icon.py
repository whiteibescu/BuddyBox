"""BuddyBox exe 아이콘 생성: 훕 드론(4덕트) + 추적 타깃."""
from pathlib import Path

from PIL import Image, ImageDraw

S = 256
BG = (24, 28, 34, 255)
DUCT = (56, 189, 248, 255)      # cyan
FRAME = (100, 116, 139, 255)    # slate
TARGET = (74, 222, 128, 255)    # green


def rounded(draw, box, r, **kw):
    draw.rounded_rectangle(box, radius=r, **kw)


def main():
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    rounded(d, (8, 8, S - 8, S - 8), 52, fill=BG)

    c = S // 2
    off = 62
    duct_r = 44
    lw = 11
    centers = [(c - off, c - off), (c + off, c - off), (c - off, c + off), (c + off, c + off)]

    for (x, y) in centers:
        d.line([(c, c), (x, y)], fill=FRAME, width=14)
    for (x, y) in centers:
        d.ellipse([x - duct_r, y - duct_r, x + duct_r, y + duct_r],
                  outline=DUCT, width=lw)

    # 중앙 추적 타깃 (크로스헤어 + 점)
    tr = 30
    d.ellipse([c - tr, c - tr, c + tr, c + tr], fill=BG, outline=TARGET, width=8)
    d.ellipse([c - 9, c - 9, c + 9, c + 9], fill=TARGET)
    tick = 16
    for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
        x0, y0 = c + dx * (tr - 2), c + dy * (tr - 2)
        x1, y1 = c + dx * (tr + tick), c + dy * (tr + tick)
        d.line([(x0, y0), (x1, y1)], fill=TARGET, width=8)

    out = Path(__file__).parent / "buddybox.ico"
    img.save(out, sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
    img.save(out.with_suffix(".png"))
    print(f"저장: {out}")


if __name__ == "__main__":
    main()
