import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from buddybox.follow.pid import PID


def test_proportional_only():
    pid = PID(kp=0.5, out_limit=1.0)
    assert abs(pid.update(0.4, 0.0) - 0.2) < 1e-9
    assert abs(pid.update(-0.4, 0.1) + 0.2) < 1e-9


def test_output_is_clamped():
    pid = PID(kp=10.0, out_limit=0.3)
    assert pid.update(1.0, 0.0) == 0.3
    assert pid.update(-1.0, 0.1) == -0.3


def test_integral_accumulates_and_is_bounded():
    pid = PID(kp=0.0, ki=1.0, out_limit=0.2)
    t = 0.0
    out = 0.0
    for _ in range(50):
        t += 0.1
        out = pid.update(1.0, t)
    assert abs(out - 0.2) < 1e-9
    for _ in range(3):
        t += 0.1
        out = pid.update(-1.0, t)
    assert out < 0.2


def test_integral_disabled_when_ki_zero():
    pid = PID(kp=0.0, ki=0.0, out_limit=1.0)
    for i in range(10):
        pid.update(1.0, i * 0.1)
    assert pid.update(0.0, 2.0) == 0.0


def test_derivative_opposes_change():
    pid = PID(kp=0.0, kd=0.1, out_limit=1.0, d_filter=1.0)
    pid.update(0.0, 0.0)
    out = pid.update(0.5, 0.1)
    assert out > 0.0
    out2 = pid.update(0.0, 0.2)
    assert out2 < 0.0


def test_reset_clears_state():
    pid = PID(kp=0.0, ki=1.0, out_limit=1.0)
    for i in range(10):
        pid.update(1.0, i * 0.1)
    pid.reset()
    assert pid.update(0.0, 5.0) == 0.0
