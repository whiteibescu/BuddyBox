"""MTF-02P 벤치 모니터 — FC(USB)에서 MSP로 레인지파인더 거리 + 옵티컬 플로우를 읽어 표시한다.

    python tools/mtf02p_monitor.py COM7                 # 10 Hz 표시
    python tools/mtf02p_monitor.py COM7 --hz 20 --csv out.csv
    python tools/mtf02p_monitor.py COM7 --check         # 장착 방향 확인 안내

전제: Betaflight 2026.6+, `feature RANGEFINDER OPTICALFLOW`, `debug_mode = OPTICALFLOW`.
배터리 연결(센서 5V) + USB. Betaflight App은 종료(포트 점유).

표시 항목
  alt    MSP_SONAR_ALTITUDE (m, 기울기 보정; --- = 범위 밖)
  fx/fy  debug[6]/[7] 필터링된 플로우 (rad/s)
  vx/vy  플로우 × 고도 = 지면 속도 (m/s)
  d[..]  debug 8채널 원시값
"""

import argparse
import csv
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from buddybox.follow.sensors import FLOW_SLOT_X, FLOW_SLOT_Y, SensorPoller  # noqa: E402
from buddybox.msp import open_msp  # noqa: E402

CHECK_TEXT = """
[장착 방향 확인 — Betaflight #15711 방법]
 1. 무늬 있는 바닥 위 20~50cm에서 기체를 손으로 잡고 **앞으로** 민다.
      → fy(debug[7])가 +로 커져야 한다. 반대면 `set opticalflow_rotation = 180` 등으로 회전 보정.
      → fx(debug[6])가 반응하면 rotation 90/270.
 2. **오른쪽**으로 민다.
      → fx(debug[6]) 부호를 기록. BuddyBox는 +X = 오른쪽으로 가정하므로 반대면
        설정 `flow_invert_x` 를 켠다(또는 `set opticalflow_flip_x = ON`).
 3. 거리 8cm 미만이거나 alt가 ---이면 플로우는 0으로 고정된다(FC가 무효 처리).
 4. MicoAssistant의 Flow Direction은 NONE 유지 (이중 회전 방지).
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("port", help="FC USB 포트 (COM7, /dev/ttyACM0) 또는 sitl")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--hz", type=float, default=10.0)
    ap.add_argument("--csv", default=None, help="CSV 저장 경로")
    ap.add_argument("--check", action="store_true", help="장착 방향 확인 안내 출력")
    ap.add_argument("--raw", action="store_true", help="debug 8채널 원시값도 표시")
    ap.add_argument("--sitl-host", default=os.environ.get("BUDDYBOX_SITL_HOST", "127.0.0.1"))
    args = ap.parse_args()

    client = open_msp(args.port, host=args.sitl_host, baud=args.baud)
    if client is None:
        ap.error("포트를 지정하세요")
    poller = SensorPoller(client, hz=args.hz)

    try:
        st = client.status()
        print(f"FC 연결 {client.description}  armed={st.armed}  cycle={st.cycle_time_us}us")
    except Exception as exc:
        print(f"FC 연결 실패: {exc}")
        return 1

    if args.check:
        print(CHECK_TEXT)

    writer = None
    fh = None
    if args.csv:
        fh = open(args.csv, "w", newline="", encoding="utf-8")
        writer = csv.writer(fh)
        writer.writerow(["t", "alt_m", "flow_x", "flow_y", "vx", "vy"] + [f"d{i}" for i in range(8)])

    t0 = time.monotonic()
    interval = 1.0 / max(1.0, args.hz)
    alt_min = alt_max = None
    print(f"{'t':>7} {'alt':>6} {'fx':>7} {'fy':>7} {'vx':>6} {'vy':>6}   (Ctrl+C 종료)")
    try:
        while True:
            tick = time.monotonic()
            s = poller.read_once(tick)
            if s is None:
                print(f"{tick - t0:7.2f}  읽기 실패: {poller.last_error}")
                time.sleep(0.5)
                continue
            if s.alt_m is not None:
                alt_min = s.alt_m if alt_min is None else min(alt_min, s.alt_m)
                alt_max = s.alt_m if alt_max is None else max(alt_max, s.alt_m)
            alt = f"{s.alt_m:6.2f}" if s.alt_m is not None else "   ---"
            line = f"{tick - t0:7.2f} {alt} {s.flow_x:+7.3f} {s.flow_y:+7.3f} {s.vx:+6.2f} {s.vy:+6.2f}"
            if args.raw:
                line += "   d" + " ".join(f"{v:6d}" for v in s.debug)
            print(line)
            if writer:
                writer.writerow([round(tick - t0, 3), s.alt_m, s.flow_x, s.flow_y, s.vx, s.vy] + list(s.debug))
            wait = interval - (time.monotonic() - tick)
            if wait > 0:
                time.sleep(wait)
    except KeyboardInterrupt:
        pass
    finally:
        if fh:
            fh.close()
        client.close()
    if alt_min is not None:
        print(f"\nalt 범위 {alt_min:.2f} ~ {alt_max:.2f} m, 오류 {poller.errors}회"
              f"{'  (debug 슬롯 X=%d Y=%d)' % (FLOW_SLOT_X, FLOW_SLOT_Y)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
