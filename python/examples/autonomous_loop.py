"""자동 제어 루프의 표준 형태 (Phase 6 뼈대).

비전/AI 컨트롤러가 낸 명령 → SafetyLimiter → BuddyBox 순으로 흐른다.
기본은 시뮬레이션 모드라 하드웨어 없이 실행 가능하다.

실행:
    python autonomous_loop.py            # 시뮬레이션 (하드웨어 불필요)
    python autonomous_loop.py COM11      # 실제 Pro Micro로 송신
"""

import math
import sys
import time

sys.path.insert(0, "..")
from buddybox import BuddyBox
from buddybox.safety import SafetyLimiter, StickCommand

LOOP_HZ = 20
DURATION_S = 10


def my_controller(t):
    """여기를 실제 제어 로직(비전 추적, PID 등)으로 교체한다.

    지금은 데모로 8자 모양의 roll/pitch 명령을 만든다.
    """
    return StickCommand(
        roll=0.8 * math.sin(t * 2.0),        # 일부러 한계(0.5) 초과 → 필터가 자름
        pitch=0.8 * math.sin(t * 1.0),
        yaw=0.0,
        throttle=-1.0,                        # 데모에선 스로틀 최소 유지
    )


def main():
    port = sys.argv[1] if len(sys.argv) > 1 else "sim"
    limiter = SafetyLimiter(
        max_tilt=0.5,          # roll/pitch ±0.5 제한
        max_yaw=0.5,
        max_throttle=0.0,      # 스로틀 상한 (초기 테스트용으로 보수적)
        max_rate_per_s=2.0,    # 급격한 스틱 변화 방지
    )

    with BuddyBox(port) as bb:
        mode = "시뮬레이션" if bb.simulator else "실제 송신"
        print(f"모드: {mode} ({bb.port}), {LOOP_HZ}Hz 제어 루프 {DURATION_S}초")

        start = time.monotonic()
        while (now := time.monotonic()) - start < DURATION_S:
            raw = my_controller(now - start)
            safe = limiter.apply(raw, now)
            bb.set_sticks(**safe)

            if int((now - start) * 2) != int((now - start - 1 / LOOP_HZ) * 2):
                us = bb.get_channels_us()
                print(f"  raw roll={raw.roll:+.2f} -> safe {safe['roll']:+.2f} | "
                      f"CH1-4(us): {us[:4]}")
            time.sleep(1 / LOOP_HZ)

        bb.neutral()
        if bb.simulator:
            print(f"시뮬레이션 종료: 프레임 {bb.simulator.frames_sent}개 송신됨")


if __name__ == "__main__":
    main()
