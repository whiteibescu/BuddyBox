"""SafetyLimiter 동작 테스트 — 하드웨어 불필요."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from buddybox.safety import SafetyLimiter, StickCommand


def test_tilt_is_clipped():
    lim = SafetyLimiter(max_tilt=0.5, max_rate_per_s=1000)
    out = lim.apply(StickCommand(roll=1.0, pitch=-1.0), now=0.0)
    assert out["roll"] == 0.5
    assert out["pitch"] == -0.5


def test_throttle_cap():
    lim = SafetyLimiter(max_throttle=0.0, max_rate_per_s=1000)
    out = lim.apply(StickCommand(throttle=1.0), now=0.0)
    assert out["throttle"] == 0.0


def test_throttle_can_go_to_minimum():
    lim = SafetyLimiter(max_throttle=0.0, max_rate_per_s=1000)
    lim.apply(StickCommand(throttle=0.0), now=0.0)
    out = lim.apply(StickCommand(throttle=-1.0), now=100.0)
    assert out["throttle"] == -1.0


def test_slew_rate_limits_step_change():
    lim = SafetyLimiter(max_tilt=1.0, max_rate_per_s=2.0)
    lim.apply(StickCommand(roll=0.0), now=0.0)
    # 0.1초 뒤 갑자기 +1.0 요구 → 최대 2.0*0.1 = 0.2만 이동 가능
    out = lim.apply(StickCommand(roll=1.0), now=0.1)
    assert abs(out["roll"] - 0.2) < 1e-9


def test_slew_rate_converges_over_time():
    lim = SafetyLimiter(max_tilt=1.0, max_rate_per_s=2.0)
    lim.apply(StickCommand(roll=0.0), now=0.0)
    t, out = 0.0, None
    for _ in range(20):
        t += 0.1
        out = lim.apply(StickCommand(roll=1.0), now=t)
    assert abs(out["roll"] - 1.0) < 1e-9


def test_dict_input_accepted():
    lim = SafetyLimiter(max_rate_per_s=1000)
    out = lim.apply({"roll": 0.1, "pitch": 0.0, "yaw": 0.0, "throttle": -1.0}, now=0.0)
    assert abs(out["roll"] - 0.1) < 1e-9
