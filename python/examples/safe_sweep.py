"""보수적 채널 스윕 — Betaflight Receiver 탭 검증용 (Phase 5 step 1).

SafetyLimiter로 제한:
  - Roll/Pitch/Yaw 진폭 ±0.2 (풀스케일의 20%, 약 1398~1602us)
  - 스로틀 최소(-1.0) 고정, 상한도 -1.0으로 잠금
  - 슬루 레이트 0.5/s — 급격한 튐 원천 차단
  - 채널당 8초 느린 사인파

실행:
    python safe_sweep.py [COM포트]
"""

import math
import sys
import time

sys.path.insert(0, "..")
from buddybox import BuddyBox
from buddybox.safety import SafetyLimiter

SWEEP_SECONDS = 8
AMPLITUDE = 0.2

AXES = [("Roll", "roll"), ("Pitch", "pitch"), ("Yaw", "yaw")]


def main():
    port = sys.argv[1] if len(sys.argv) > 1 else None
    limiter = SafetyLimiter(max_tilt=AMPLITUDE, max_yaw=AMPLITUDE,
                            max_throttle=-1.0, max_rate_per_s=0.5)
    with BuddyBox(port) as bb:
        print(f"연결됨: {bb.port} | 진폭 ±{AMPLITUDE}, 스로틀 최소 고정", flush=True)
        try:
            while True:
                for name, axis in AXES:
                    print(f"  {name} 스윕 (±{AMPLITUDE})...", flush=True)
                    start = time.time()
                    while time.time() - start < SWEEP_SECONDS:
                        t = (time.time() - start) / SWEEP_SECONDS
                        cmd = {"roll": 0.0, "pitch": 0.0, "yaw": 0.0, "throttle": -1.0}
                        cmd[axis] = AMPLITUDE * math.sin(t * 2 * math.pi)
                        bb.set_sticks(**limiter.apply(cmd, time.monotonic()))
                        time.sleep(0.02)
        except KeyboardInterrupt:
            pass
        finally:
            bb.neutral()
            time.sleep(0.1)
            print("중립 복귀 후 종료.", flush=True)


if __name__ == "__main__":
    main()
