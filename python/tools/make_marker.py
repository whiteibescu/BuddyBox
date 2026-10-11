import argparse
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

DPI = 300
A4_MM = (210, 297)


def mm_to_px(mm):
    return int(round(mm / 25.4 * DPI))


def main():
    ap = argparse.ArgumentParser(description="프린트용 ArUco/AprilTag 마커 PDF(A4, 실측 크기) 생성")
    ap.add_argument("--dict", default="apriltag_36h11")
    ap.add_argument("--id", type=int, default=0)
    ap.add_argument("--size-mm", type=float, default=150.0, help="마커 한 변의 인쇄 크기 (mm)")
    ap.add_argument("--out", default=None, help="출력 경로 (기본: docs/markers/)")
    args = ap.parse_args()

    const = "DICT_" + args.dict.upper()
    for cand in (const, const.replace("36H11", "36h11")):
        if hasattr(cv2.aruco, cand):
            d = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, cand))
            break
    else:
        raise SystemExit(f"알 수 없는 사전: {args.dict}")

    size_px = mm_to_px(args.size_mm)
    marker = cv2.aruco.generateImageMarker(d, args.id, size_px)

    page = Image.new("L", (mm_to_px(A4_MM[0]), mm_to_px(A4_MM[1])), 255)
    m = Image.fromarray(marker)
    x = (page.width - size_px) // 2
    y = (page.height - size_px) // 2
    page.paste(m, (x, y))

    draw = ImageDraw.Draw(draw_im := page)
    caption = (f"{args.dict}  id={args.id}  {args.size_mm:.0f}x{args.size_mm:.0f} mm"
               "  --  print at 100% scale (no fit-to-page)")
    draw.text((x, y + size_px + mm_to_px(6)), caption, fill=0)
    ruler_px = mm_to_px(100)
    ry = y + size_px + mm_to_px(14)
    draw.rectangle([x, ry, x + ruler_px, ry + mm_to_px(1.5)], fill=0)
    draw.text((x, ry + mm_to_px(3)), "ruler: exactly 100 mm (check print scale)", fill=0)

    stem = f"aruco_{args.dict}_id{args.id}_{args.size_mm:.0f}mm"
    out_dir = Path(args.out) if args.out else Path(__file__).resolve().parents[2] / "docs" / "markers"
    out_dir.mkdir(parents=True, exist_ok=True)
    png = out_dir / f"{stem}.png"
    pdf = out_dir / f"{stem}.pdf"
    Image.fromarray(marker).save(png)
    page.save(pdf, resolution=DPI)
    print(f"저장: {pdf}\n저장: {png}")


if __name__ == "__main__":
    main()
