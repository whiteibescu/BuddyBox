import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from buddybox.follow.controller import FollowConfig, FollowController, deadband, vertical_reference
from buddybox.vision.tracker import Track


def track(cx=0.5, cy=0.5, h=0.45, w=0.2, lost=False):
    return Track(cx=cx, cy=cy, w=w, h=h, conf=0.9, age=0.0, lost=lost)


def cfg(**kw):
    base = dict(lateral_kp=1.0, lateral_kd=0.0, pitch_kp=1.0, pitch_kd=0.0,
                throttle_kp=1.0, throttle_ki=0.0, throttle_kd=0.0, hover_throttle=-0.2,
                target_height=0.45, target_y=0.5, altitude_reference="center", trim_learning=False,
                deadzone_x=0.0, deadzone_y=0.0, deadzone_height=0.0)
    base.update(kw)
    return FollowConfig(**base)


def test_deadband_zero_inside_and_continuous_outside():
    assert deadband(0.05, 0.1) == 0.0
    assert deadband(-0.05, 0.1) == 0.0
    assert abs(deadband(0.1, 0.1)) < 1e-9
    assert abs(deadband(1.0, 0.1) - 1.0) < 1e-9
    assert deadband(-0.55, 0.1) < 0


def test_centered_target_gives_hover_sticks():
    c = FollowController(cfg())
    cmd = c.update(track(), now=0.0)
    assert cmd.roll == 0.0 and cmd.pitch == 0.0 and cmd.yaw == 0.0
    assert abs(cmd.throttle + 0.2) < 1e-9


def test_target_right_yaws_right():
    c = FollowController(cfg())
    cmd = c.update(track(cx=0.75), now=0.0)
    assert cmd.yaw > 0.0
    assert cmd.roll == 0.0


def test_roll_axis_option_uses_roll_instead_of_yaw():
    c = FollowController(cfg(lateral_axis="roll"))
    cmd = c.update(track(cx=0.25), now=0.0)
    assert cmd.roll < 0.0
    assert cmd.yaw == 0.0


def test_small_box_pitches_forward_and_large_box_backward():
    c = FollowController(cfg())
    assert c.update(track(h=0.2), now=0.0).pitch > 0.0
    c.reset()
    assert c.update(track(h=0.8), now=0.0).pitch < 0.0


def test_target_high_in_frame_raises_throttle():
    c = FollowController(cfg())
    cmd = c.update(track(cy=0.3), now=0.0)
    assert cmd.throttle > -0.2
    c.reset()
    cmd = c.update(track(cy=0.7), now=0.0)
    assert cmd.throttle < -0.2


def test_head_reference_uses_top_of_box():
    assert abs(vertical_reference(track(cy=0.5, h=0.3), "head") - 0.35) < 1e-9
    assert abs(vertical_reference(track(cy=0.5, h=0.3), "center") - 0.5) < 1e-9
    c = FollowController(cfg(altitude_reference="head", target_y=0.35))
    cmd = c.update(track(cy=0.5, h=0.3), now=0.0)
    assert abs(cmd.throttle + 0.2) < 1e-9
    c.reset()
    cmd = c.update(track(cy=0.9, h=0.3), now=0.0)
    assert cmd.throttle < -0.2
    c.reset()
    cmd = c.update(track(cy=0.7, h=0.9), now=0.0)
    assert cmd.throttle > -0.2


def test_inversion_flags_flip_signs():
    c = FollowController(cfg(invert_lateral=True, invert_pitch=True, invert_throttle=True))
    cmd = c.update(track(cx=0.75, h=0.2, cy=0.3), now=0.0)
    assert cmd.yaw < 0.0
    assert cmd.pitch < 0.0
    assert cmd.throttle < -0.2


def test_outputs_respect_limits():
    c = FollowController(cfg(lateral_kp=50, pitch_kp=50, throttle_kp=50,
                             max_lateral=0.3, max_pitch=0.2, max_throttle_delta=0.1))
    cmd = c.update(track(cx=1.0, h=0.05, cy=0.0), now=0.0)
    assert abs(cmd.yaw) <= 0.3 + 1e-9
    assert abs(cmd.pitch) <= 0.2 + 1e-9
    assert cmd.throttle <= -0.2 + 0.1 + 1e-9


def test_disabled_axes_stay_neutral():
    c = FollowController(cfg(distance_hold=False, altitude_assist=False))
    cmd = c.update(track(cx=0.9, h=0.1, cy=0.1), now=0.0)
    assert cmd.pitch == 0.0
    assert abs(cmd.throttle + 0.2) < 1e-9
    assert cmd.yaw > 0.0


def test_deadzone_suppresses_small_errors():
    c = FollowController(cfg(deadzone_x=0.2, deadzone_y=0.2, deadzone_height=0.2))
    cmd = c.update(track(cx=0.55, cy=0.45, h=0.42), now=0.0)
    assert cmd.yaw == 0.0 and cmd.pitch == 0.0
    assert abs(cmd.throttle + 0.2) < 1e-9


def test_trim_learning_accumulates_and_clamps():
    c = FollowController(cfg(trim_learning=True, trim_learn_rate=1.0, trim_learn_up=0.1, trim_learn_down=0.3,
                             max_throttle_delta=0.12))
    t = 0.0
    for _ in range(50):
        t += 0.1
        c.update(track(cy=0.2), now=t)
    assert 0.0 < c.trim_offset <= 0.1 + 1e-9
    assert abs(c.hover().throttle - (-0.2 + c.trim_offset)) < 1e-9
    learned = c.trim_offset
    c.reset()
    assert c.trim_offset == learned
    for _ in range(200):
        t += 0.1
        c.update(track(cy=0.9), now=t)
    assert abs(c.trim_offset + 0.3) < 1e-9


def test_trim_learning_disabled_keeps_offset_zero():
    c = FollowController(cfg(trim_learning=False))
    for i in range(20):
        c.update(track(cy=0.2), now=i * 0.1)
    assert c.trim_offset == 0.0


def test_adopt_and_reset_trim():
    c = FollowController(cfg(trim_learning=True, trim_learn_rate=1.0))
    for i in range(30):
        c.update(track(cy=0.2), now=i * 0.1)
    offset = c.trim_offset
    assert offset > 0.0
    new_trim = c.adopt_trim()
    assert abs(new_trim - (-0.2 + offset)) < 1e-9
    assert c.trim_offset == 0.0
    assert abs(c.hover().throttle - new_trim) < 1e-9
    for i in range(30):
        c.update(track(cy=0.2), now=10 + i * 0.1)
    c.reset_trim()
    assert c.trim_offset == 0.0


def test_offset_mode_sends_deltas_only():
    c = FollowController(cfg(throttle_mode="offset", trim_learning=True, trim_learn_rate=1.0))
    assert c.standby().throttle == 0.0
    assert c.hover().throttle == 0.0
    cmd = c.update(track(cy=0.3), now=0.0)
    assert 0.0 < cmd.throttle <= c.cfg.max_throttle_delta + 1e-9
    for i in range(30):
        c.update(track(cy=0.3), now=0.1 + i * 0.1)
    assert c.trim_offset == 0.0
    assert abs(c.cfg.max_throttle - c.cfg.max_throttle_delta) < 1e-9


def test_config_roundtrip_and_unknown_keys(tmp_path):
    original = cfg(lateral_kp=0.42, invert_pitch=True)
    path = original.save(tmp_path / "f.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    data["future_option"] = 123
    path.write_text(json.dumps(data), encoding="utf-8")
    loaded = FollowConfig.load(path)
    assert loaded.lateral_kp == 0.42
    assert loaded.invert_pitch is True
    assert loaded.extra == {"future_option": 123}
    assert FollowConfig.load(tmp_path / "missing.json").hover_throttle == FollowConfig().hover_throttle


def test_max_throttle_follows_trim_and_learning_headroom():
    c = cfg(hover_throttle=-0.3, max_throttle_delta=0.1, trim_learning=False)
    assert abs(c.max_throttle + 0.2) < 1e-9
    c = cfg(hover_throttle=-0.3, max_throttle_delta=0.1, trim_learning=True, trim_learn_up=0.1)
    assert abs(c.max_throttle + 0.1) < 1e-9
