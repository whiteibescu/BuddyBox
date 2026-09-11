import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from buddybox.follow.controller import FollowConfig, FollowController
from buddybox.follow.state import FlightSupervisor, Mode, Status
from buddybox.vision.tracker import Track


def make(**kw):
    base = dict(hover_throttle=-0.25, deadzone_x=0.0, lateral_kp=1.0, lateral_kd=0.0, throttle_kd=0.0,
                altitude_reference="center", trim_learning=False,
                lost_descend_after_s=3.0, lost_descend_rate=0.02, lost_descend_max=0.15)
    base.update(kw)
    c = FollowController(FollowConfig(**base))
    return c, FlightSupervisor(c)


def trk(cx=0.5, lost=False):
    return Track(cx=cx, cy=0.5, w=0.2, h=0.45, conf=0.9, age=0.0, lost=lost)


def test_standby_sends_throttle_min_regardless_of_track():
    _, sup = make()
    cmd, status = sup.step(trk(cx=0.9), video_ok=True, now=0.0)
    assert status == Status.STANDBY
    assert cmd.throttle == -1.0 and cmd.yaw == 0.0


def test_hover_mode_holds_trim():
    _, sup = make()
    sup.set_mode(Mode.HOVER)
    cmd, status = sup.step(trk(cx=0.9), video_ok=True, now=0.0)
    assert status == Status.HOVER
    assert abs(cmd.throttle + 0.25) < 1e-9 and cmd.yaw == 0.0


def test_follow_tracks_when_target_valid():
    _, sup = make()
    sup.set_mode("FOLLOW")
    cmd, status = sup.step(trk(cx=0.9), video_ok=True, now=0.0)
    assert status == Status.TRACKING
    assert cmd.yaw > 0.0


def test_follow_falls_back_to_hover_on_lost_or_missing_target():
    _, sup = make()
    sup.set_mode(Mode.FOLLOW)
    cmd, status = sup.step(trk(cx=0.9, lost=True), video_ok=True, now=0.0)
    assert status == Status.LOST and cmd.yaw == 0.0 and abs(cmd.throttle + 0.25) < 1e-9
    cmd, status = sup.step(None, video_ok=True, now=0.1)
    assert status == Status.NO_TARGET and cmd.yaw == 0.0


def test_no_video_overrides_follow_and_hover():
    _, sup = make()
    sup.set_mode(Mode.FOLLOW)
    cmd, status = sup.step(trk(cx=0.9), video_ok=False, now=0.0)
    assert status == Status.NO_VIDEO and cmd.yaw == 0.0
    sup.set_mode(Mode.HOVER)
    _, status = sup.step(None, video_ok=False, now=0.1)
    assert status == Status.NO_VIDEO


def test_panic_returns_to_standby():
    _, sup = make()
    sup.set_mode(Mode.FOLLOW)
    sup.panic()
    cmd, status = sup.step(trk(), video_ok=True, now=0.0)
    assert sup.mode == Mode.STANDBY and cmd.throttle == -1.0


def test_controller_reset_when_tracking_interrupted():
    c, sup = make()
    c.cfg.throttle_ki = 0.5
    c.apply_config(c.cfg)
    sup.set_mode(Mode.FOLLOW)
    t = 0.0
    for _ in range(20):
        t += 0.1
        sup.step(Track(cx=0.5, cy=0.2, w=0.2, h=0.45, conf=0.9, age=0.0, lost=False), True, t)
    assert c.throttle._integral > 0.0
    sup.step(None, True, t + 0.1)
    assert c.throttle._integral == 0.0


def test_lost_descend_starts_after_delay_and_is_bounded():
    _, sup = make()
    sup.set_mode(Mode.FOLLOW)
    cmd, _ = sup.step(None, True, 0.0)
    assert abs(cmd.throttle + 0.25) < 1e-9
    cmd, _ = sup.step(None, True, 3.0)
    assert abs(cmd.throttle + 0.25) < 1e-9
    cmd, _ = sup.step(None, True, 5.0)
    assert abs(cmd.throttle - (-0.25 - 0.04)) < 1e-9
    assert abs(sup.descend - 0.04) < 1e-9
    cmd, _ = sup.step(trk(lost=True), True, 100.0)
    assert abs(cmd.throttle - (-0.25 - 0.15)) < 1e-9


def test_descend_resets_when_tracking_resumes_or_mode_changes():
    _, sup = make()
    sup.set_mode(Mode.FOLLOW)
    sup.step(None, True, 0.0)
    sup.step(None, True, 10.0)
    assert sup.descend > 0.0
    cmd, status = sup.step(trk(), True, 10.1)
    assert status == Status.TRACKING and sup.descend == 0.0
    sup.step(None, True, 20.0)
    sup.step(None, True, 30.0)
    assert sup.descend > 0.0
    sup.set_mode(Mode.HOVER)
    cmd, _ = sup.step(None, True, 30.1)
    assert sup.descend == 0.0 and abs(cmd.throttle + 0.25) < 1e-9


def test_hover_mode_never_descends():
    _, sup = make()
    sup.set_mode(Mode.HOVER)
    for t in (0.0, 10.0, 60.0):
        cmd, _ = sup.step(None, True, t)
        assert abs(cmd.throttle + 0.25) < 1e-9


def test_lost_hover_uses_learned_trim():
    c, sup = make(trim_learning=True, trim_learn_rate=1.0)
    sup.set_mode(Mode.FOLLOW)
    t = 0.0
    for _ in range(30):
        t += 0.1
        sup.step(Track(cx=0.5, cy=0.2, w=0.2, h=0.45, conf=0.9, age=0.0, lost=False), True, t)
    learned = c.trim_offset
    assert learned > 0.0
    cmd, status = sup.step(None, True, t + 0.1)
    assert status == Status.NO_TARGET
    assert abs(cmd.throttle - (-0.25 + learned)) < 1e-9
