"""OSD 판독 센서 뷰어 — 비행 중(또는 녹화 영상에서) OSD 숫자를 읽어 거리·플로우를 표시/저장한다.

    python tools/osd_sensor.py --camera "UVC Camera" --glyphs osd_glyphs.json          # 실시간
    python tools/osd_sensor.py --video recordings/session_x/raw.mp4 --glyphs osd_glyphs.json --csv out.csv
    python tools/osd_sensor.py --camera "UVC Camera" --glyphs osd_glyphs.json --show

글리프 파일은 tools/osd_calibrate.py 로 만든다. 수동 비행 중 PC 는 영상만 받으면 되고,
조종기·FC 쪽 추가 연결은 필요 없다.
"""

import argparse
import csv
import os
import sys
import time

import cv2

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from buddybox.follow.sensors import OsdSensorSource  # noqa: E402
from buddybox.vision.capture import PRESETS, default_backend, open_source  # noqa: E402
from buddybox.vision.osd import GlyphBook, OsdReader  # noqa: E402


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--camera", default=None)
    ap.add_argument("--video", default=None)
    ap.add_argument("--preset", choices=list(PRESETS), default="vrx1080")
    ap.add_argument("--cap-backend", default=default_backend())
    ap.add_argument("--glyphs", required=True, help="osd_calibrate.py 결과 JSON")
    ap.add_argument("--csv", default=None)
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--invert-x", action="store_true")
    ap.add_argument("--invert-y", action="store_true")
    ap.add_argument("--every", type=int, default=1, help="N 프레임마다 판독")
    args = ap.parse_args()

    spec = args.video or args.camera
    if spec is None:
        ap.error("--camera 또는 --video 가 필요합니다")
    source = open_source(spec, preset=args.preset, backend=args.cap_backend, loop=False)
    reader = OsdReader(GlyphBook.load(args.glyphs))
    sensor = OsdSensorSource(reader, invert_x=args.invert_x, invert_y=args.invert_y, every=args.every)

    writer = fh = None
    if args.csv:
        fh = open(args.csv, "w", newline="", encoding="utf-8")
        writer = csv.writer(fh)
        writer.writerow(["t", "frame", "alt_m", "flow_x", "flow_y", "vx", "vy", "rf_text", "d2_text", "ok"])

    t0 = time.monotonic()
    last_seq = -1
    frames = ok = 0
    print(f"{'t':>7} {'alt':>6} {'fx':>7} {'fy':>7} {'vx':>6} {'vy':>6}   RF / D2 텍스트")
    try:
        while True:
            frame, seq = source.read()
            if frame is None:
                if args.video:
                    break
                time.sleep(0.005)
                continue
            if seq == last_seq:
                time.sleep(0.002)
                continue
            last_seq = seq
            frames += 1
            now = time.monotonic()
            s = sensor.feed(frame, now)
            r = sensor.last_reading
            if s is not None:
                ok += 1
                alt = f"{s.alt_m:6.2f}" if s.alt_m is not None else "   ---"
                if frames % max(1, args.every) == 0 and (args.video or frames % 5 == 0):
                    print(f"{now - t0:7.2f} {alt} {s.flow_x:+7.3f} {s.flow_y:+7.3f} {s.vx:+6.2f} {s.vy:+6.2f}"
                          f"   {r.rf_text!r} {r.d2_text!r}")
            elif r is not None and frames % 30 == 0:
                print(f"{now - t0:7.2f}  판독 실패: {r.rf_text!r} {r.d2_text!r}  ({r.error})")
            if writer and r is not None:
                writer.writerow([round(now - t0, 3), seq,
                                 s.alt_m if s else "", s.flow_x if s else "", s.flow_y if s else "",
                                 s.vx if s else "", s.vy if s else "", r.rf_text, r.d2_text, int(s is not None)])
            if args.show:
                view = reader.draw(frame.copy(), r)
                cv2.imshow("osd_sensor", cv2.resize(view, None, fx=0.5, fy=0.5))
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
    except KeyboardInterrupt:
        pass
    finally:
        source.close()
        if fh:
            fh.close()
        if args.show:
            cv2.destroyAllWindows()
    print(f"\n프레임 {frames}, 판독 성공 {ok} ({100.0 * ok / max(1, frames):.0f}%), 오류 {sensor.errors}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
