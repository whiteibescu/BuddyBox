"""채널 스윕 테스트 — EdgeTX Trainer 화면에서 신호 확인용.

Roll → Pitch → Yaw 순서로 한 채널씩 -1 → +1 → 중립 왕복.
스로틀은 안전을 위해 최소로 고정한다.

실행:
    python channel_sweep.py [COM포트]
"""

import math
import sys
import time

sys.path.insert(0, "..")
from buddybox import BuddyBox, CH_ROLL, CH_PITCH, CH_YAW

SWEEP_SECONDS = 4


def main():
    port = sys.argv[1] if len(sys.argv) > 1 else None
    with BuddyBox(port) as bb:
        print(f"연결됨: {bb.port}")
        print("조종기 SYS → Trainer 화면에서 채널 막대를 확인하세요. Ctrl+C로 종료.")
        try:
            while True:
                for name, ch in [("Roll", CH_ROLL), ("Pitch", CH_PITCH), ("Yaw", CH_YAW)]:
                    print(f"  {name} 스윕...")
                    start = time.time()
                    while time.time() - start < SWEEP_SECONDS:
                        t = (time.time() - start) / SWEEP_SECONDS
                        bb.set_channel(ch, math.sin(t * 2 * math.pi))
                        time.sleep(0.02)
                    bb.set_channel(ch, 0.0)
        except KeyboardInterrupt:
            bb.neutral()
            print("\n중립 복귀 후 종료.")


if __name__ == "__main__":
    main()
