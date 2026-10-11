"""OSD 판독 캘리브레이션 — 벤치에서 FC(USB MSP) 실측값을 정답으로 OSD 글리프 템플릿을 학습한다.

    python tools/osd_calibrate.py --camera "UVC Camera" --msp COM7 --out osd_glyphs.json
    python tools/osd_calibrate.py --camera "UVC Camera" --show          # 격자 정렬만 확인 (MSP 없이)
    python tools/osd_calibrate.py --video session/raw.mp4 --show

전제 (Betaflight CLI):
    set osd_lidar_dist_pos = 2625     # RF:%3d  셀 (1,18) 프로파일 1
    set osd_debug2_pos = 2634         # D2 %5d %5d %5d %5d  셀 (10,18)
    set debug_mode = OPTICALFLOW
    save
VRX 영상(OSD 포함) 캡처 + FC USB 연결 + 배터리(센서 5V). 센서 앞에서 손을 움직이고 기체를 밀어
RF 값·플로우 값이 다양한 숫자를 거치게 하면 0~9, '-', ':' 템플릿이 고루 쌓인다.

결과 JSON 에는 격자(x0, y0, cell_w, cell_h)와 글리프 템플릿이 함께 저장된다.
"""

import argparse
import os
import sys
import time

import cv2

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from buddybox.msp import open_msp  # noqa: E402
from buddybox.vision.capture import PRESETS, default_backend, open_source  # noqa: E402
from buddybox.vision.osd import (DEFAULT_D2, DEFAULT_RF, GlyphBook, OsdGrid, OsdReader, d2_text,  # noqa: E402
                                 element_cells, fit_grid, osd_pos, rf_text, text_mask)


def parse_grid(spec):
    if not spec:
        return OsdGrid()
    x0, y0, cw, ch = (float(v) for v in spec.split(","))
    return OsdGrid(x0=x0, y0=y0, cell_w=cw, cell_h=ch)


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--camera", default=None, help="UVC 장치 이름 일부 / 인덱스")
    ap.add_argument("--video", default=None, help="녹화 파일 (카메라 대신)")
    ap.add_argument("--preset", choices=list(PRESETS), default="vrx1080")
    ap.add_argument("--cap-backend", default=default_backend())
    ap.add_argument("--msp", default="", help="FC USB 포트 (정답값). 없으면 --show 만 가능")
    ap.add_argument("--grid", default="", help="x0,y0,cell_w,cell_h 픽셀 (기본: 프레임을 53×20 등분)")
    ap.add_argument("--no-fit", action="store_true", help="RF 라벨 기반 격자 자동 미세조정 끄기")
    ap.add_argument("--out", default="osd_glyphs.json")
    ap.add_argument("--seconds", type=float, default=60.0, help="학습 시간")
    ap.add_argument("--show", action="store_true", help="격자·판독 결과를 창에 표시")
    ap.add_argument("--dump", default=None, help="셀 크롭 PNG 를 저장할 폴더 (디버깅)")
    ap.add_argument("--pos", action="store_true", help="CLI 위치값만 출력하고 종료")
    args = ap.parse_args()

    if args.pos:
        print(f"set osd_lidar_dist_pos = {osd_pos(DEFAULT_RF.col, DEFAULT_RF.row)}   # RF (col {DEFAULT_RF.col}, row {DEFAULT_RF.row})")
        print(f"set osd_debug2_pos = {osd_pos(DEFAULT_D2.col, DEFAULT_D2.row)}       # D2 (col {DEFAULT_D2.col}, row {DEFAULT_D2.row})")
        print("set debug_mode = OPTICALFLOW")
        return 0

    src_spec = args.video or args.camera
    if src_spec is None:
        ap.error("--camera 또는 --video 가 필요합니다")
    source = open_source(src_spec, preset=args.preset, backend=args.cap_backend, loop=False)
    client = open_msp(args.msp) if args.msp else None
    if client is None and not args.show:
        ap.error("--msp 없이 학습할 수 없습니다. 격자만 보려면 --show")

    book = GlyphBook(grid=parse_grid(args.grid))
    reader = OsdReader(book)
    fitted = False
    t0 = time.monotonic()
    n = 0
    stats = {"frames": 0, "learned": 0, "rf_ok": 0, "d2_ok": 0, "msp_err": 0}
    last_seq = -1
    if args.dump:
        os.makedirs(args.dump, exist_ok=True)
    print("학습 시작 — Ctrl+C / q 로 종료")
    try:
        while time.monotonic() - t0 < args.seconds:
            frame, seq = source.read()
            if frame is None or seq == last_seq:
                if args.video and frame is None:
                    break
                time.sleep(0.005)
                continue
            last_seq = seq
            stats["frames"] += 1
            mask = text_mask(frame)
            H, W = mask.shape[:2]
            if not fitted and not args.no_fit:
                book.grid, score = fit_grid(mask, book.grid)
                fitted = True
                g = book.grid
                print(f"격자: x0 {g.x0:.1f} y0 {g.y0:.1f} cell {g.cell_w:.2f}×{g.cell_h:.2f}  (score {score:.2f})")

            truth = None
            if client is not None:
                try:
                    cm = client.sonar_altitude_m()
                    debug = client.debug()
                    truth = (rf_text(None if cm is None else round(cm * 100)), d2_text(debug))
                except Exception as exc:
                    stats["msp_err"] += 1
                    truth = None
                    if stats["msp_err"] <= 3:
                        print(f"MSP 오류: {exc}")

            if truth is not None:
                for elem, text in ((DEFAULT_RF, truth[0]), (DEFAULT_D2, truth[1])):
                    cells = element_cells(mask, book.grid, elem)
                    for i, (cell, ch) in enumerate(zip(cells, text)):
                        book.learn(cell, ch)
                        if args.dump and n % 30 == 0 and ch != " ":
                            cv2.imwrite(os.path.join(args.dump, f"{elem.name}_{i:02d}_{ord(ch):03d}_{n:05d}.png"),
                                        (cell * 255).astype("uint8"))
                stats["learned"] += 1

            reading = reader.read(frame) if book.templates else None
            if reading is not None and truth is not None:
                stats["rf_ok"] += int(reading.rf_text == truth[0])
                stats["d2_ok"] += int(reading.d2_text == truth[1])
            n += 1
            if n % 30 == 0:
                msg = f"[{time.monotonic() - t0:5.1f}s] frames {stats['frames']} learned {stats['learned']}"
                if reading is not None:
                    msg += f"  read {reading.rf_text!r} {reading.d2_text!r}"
                if truth is not None:
                    msg += f"  truth {truth[0]!r} {truth[1]!r}"
                print(msg)
            if args.show:
                view = reader.draw(frame.copy(), reading)
                cv2.imshow("osd_calibrate", cv2.resize(view, None, fx=0.5, fy=0.5))
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
    except KeyboardInterrupt:
        pass
    finally:
        source.close()
        if client is not None:
            client.close()
        if args.show:
            cv2.destroyAllWindows()

    if book.templates:
        path = book.save(args.out)
        prev = book.preview()
        if prev is not None:
            cv2.imwrite(str(path.with_suffix(".png")), prev)
        learned = stats["learned"]
        print(f"\n저장: {path}  글리프 {len(book.templates)}개 {sorted(book.templates)}")
        if learned:
            print(f"자가 검증: RF {stats['rf_ok']}/{learned} ({100.0 * stats['rf_ok'] / learned:.0f}%)  "
                  f"D2 {stats['d2_ok']}/{learned} ({100.0 * stats['d2_ok'] / learned:.0f}%)")
        missing = [c for c in "0123456789-:RFD" if c not in book.templates]
        if missing:
            print(f"아직 못 본 글리프: {missing} — 값이 그 숫자를 지나도록 더 움직여서 다시 실행")
    else:
        print("학습된 글리프 없음 (MSP 연결·OSD 표시·격자 정렬을 확인)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
