"""자동 제어 입력을 위한 안전 필터.

비전/AI 같은 자동 제어 로직이 만든 스틱 명령을 그대로 기체에 보내지 않고,
이 필터를 거쳐 세 가지를 강제한다:

1. 축별 최대 크기 제한 (예: roll/pitch ±0.5 이상 못 기울임)
2. 스로틀 상한 (예: 0.3 이상 못 올림)
3. 슬루 레이트 제한 (초당 변화량 제한 — 급격한 스틱 튐 방지)

사용 예:
    limiter = SafetyLimiter(max_tilt=0.5, max_throttle=0.0, max_rate_per_s=2.0)
    with BuddyBox() as bb:
        while True:
            cmd = my_controller()          # roll, pitch, yaw, throttle (-1~+1)
            safe = limiter.apply(cmd, time.monotonic())
            bb.set_sticks(**safe)
"""

import dataclasses


@dataclasses.dataclass
class StickCommand:
    roll: float = 0.0
    pitch: float = 0.0
    yaw: float = 0.0
    throttle: float = -1.0


class SafetyLimiter:
    """자동 제어 스틱 명령에 한계를 강제하는 필터.

    max_tilt        : roll/pitch 크기 상한 (0~1)
    max_yaw         : yaw 크기 상한 (0~1)
    max_throttle    : 스로틀 상한 (-1~+1). 초기 테스트에선 낮게(예: -0.4) 시작 권장
    max_rate_per_s  : 모든 축의 초당 최대 변화량 (정규화 단위/초)
    """

    def __init__(self, max_tilt=0.5, max_yaw=0.5, max_throttle=0.0, max_rate_per_s=2.0):
        self.max_tilt = max_tilt
        self.max_yaw = max_yaw
        self.max_throttle = max_throttle
        self.max_rate_per_s = max_rate_per_s
        self._last = StickCommand()
        self._last_t = None

    def apply(self, cmd, now):
        """명령에 한계를 적용해 새 StickCommand를 반환한다.

        cmd는 StickCommand 또는 {'roll': .., 'pitch': .., 'yaw': .., 'throttle': ..} dict.
        now는 time.monotonic() 같은 단조 증가 시각(초).
        """
        if isinstance(cmd, dict):
            cmd = StickCommand(**cmd)

        limited = StickCommand(
            roll=_clip(cmd.roll, -self.max_tilt, self.max_tilt),
            pitch=_clip(cmd.pitch, -self.max_tilt, self.max_tilt),
            yaw=_clip(cmd.yaw, -self.max_yaw, self.max_yaw),
            throttle=_clip(cmd.throttle, -1.0, self.max_throttle),
        )

        if self._last_t is not None:
            dt = max(0.0, now - self._last_t)
            step = self.max_rate_per_s * dt
            limited = StickCommand(
                roll=_slew(self._last.roll, limited.roll, step),
                pitch=_slew(self._last.pitch, limited.pitch, step),
                yaw=_slew(self._last.yaw, limited.yaw, step),
                throttle=_slew(self._last.throttle, limited.throttle, step),
            )

        self._last = limited
        self._last_t = now
        return dataclasses.asdict(limited)


def _clip(v, lo, hi):
    return max(lo, min(hi, float(v)))


def _slew(prev, target, step):
    if target > prev + step:
        return prev + step
    if target < prev - step:
        return prev - step
    return target
