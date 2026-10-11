import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from buddybox.follow.controller import FollowConfig, FollowController
from buddybox.follow.sensors import RangeFlowSample, compute_sample
from buddybox.follow.state import FlightSupervisor, Mode, Status
from buddybox.vision.tracker import Track

TRIM = -0.25


def cfg(**kw):
    base = dict(hover_throttle=TRIM, trim_learning=False, alt_hold=True, pos_hold=True,
                alt_target_m=1.0, alt_kp=0.3, alt_ki=0.0, alt_kd=0.0, max_throttle_delta=0.2,
                pos_kp=0.0, pos_kv=0.5, max_pos_tilt=0.2, sensor_timeout_s=0.4,
                lost_descend_after_s=1.0, lost_descend_m_s=0.1, alt_land_m=0.2,
                lost_descend_rate=0.02, lost_descend_max=0.15,
                lateral_kp=1.0, lateral_kd=0.0, deadzone_x=0.0, altitude_reference="center")
    base.update(kw)
    return FollowConfig(**base)


def sample(t, alt=1.0, vx=0.0, vy=0.0):
    return RangeFlowSample(t=t, seq=1, alt_m=alt, vx=vx, vy=vy)


def trk(cx=0.5, lost=False):
    return Track(cx=cx, cy=0.5, w=0.2, h=0.45, conf=0.9, age=0.0, lost=lost)


# ---- compute_sample ----

def test_compute_sample_scales_flow_by_altitude_and_inverts():
    debug = [0] * 8
    debug[6], debug[7] = 200, -100  # 0.2 rad/s, -0.1 rad/s
    s = compute_sample(0.0, 1, 0.5, debug)
    assert abs(s.flow_x - 0.2) < 1e-9 and abs(s.flow_y + 0.1) < 1e-9
    assert abs(s.vx - 0.1) < 1e-9 and abs(s.vy + 0.05) < 1e-9
    s = compute_sample(0.0, 1, None, debug, invert_x=True)
    assert s.alt_m is None and not s.alt_valid and s.vx == 0.0 and s.flow_x < 0


# ---- HoverHold via controller.hover ----

def test_hover_without_sensor_is_open_loop_trim():
    c = FollowController(cfg())
    c.set_sensor(None)
    cmd = c.hover(now=1.0)
    assert abs(cmd.throttle - TRIM) < 1e-9 and cmd.roll == 0.0 and cmd.pitch == 0.0
    assert not c.sensor_hold_active


def test_hover_alt_hold_raises_throttle_when_below_target():
    c = FollowController(cfg())
    c.set_sensor(sample(1.0, alt=0.5))          # 0.5 m 아래 → err +0.5 → Δ = 0.15
    cmd = c.hover(now=1.0)
    assert c.sensor_hold_active
    assert abs(cmd.throttle - (TRIM + 0.15)) < 1e-9
    c.set_sensor(sample(1.1, alt=1.5))          # 위 → 내려야
    cmd = c.hover(now=1.1)
    assert cmd.throttle < TRIM


def test_hover_alt_hold_disabled_or_invalid_falls_back():
    c = FollowController(cfg(alt_hold=False))
    c.set_sensor(sample(1.0, alt=0.5))
    assert abs(c.hover(now=1.0).throttle - TRIM) < 1e-9
    c = FollowController(cfg())
    c.set_sensor(sample(1.0, alt=None))          # 범위 밖
    assert abs(c.hover(now=1.0).throttle - TRIM) < 1e-9 and not c.sensor_hold_active
    c.set_sensor(sample(1.0, alt=0.05))          # alt_min_m 미만
    assert abs(c.hover(now=1.0).throttle - TRIM) < 1e-9
    c.set_sensor(sample(1.0, alt=1.0))
    assert c.hover(now=2.0).throttle == TRIM     # 1초 지난 샘플 → stale


def test_hover_pos_hold_tilts_against_velocity():
    c = FollowController(cfg())
    c.set_sensor(sample(1.0, alt=1.0, vx=0.2, vy=-0.1))
    cmd = c.hover(now=1.0)
    assert abs(cmd.roll + 0.1) < 1e-9       # 오른쪽으로 흐름 → 왼쪽으로 기울임
    assert abs(cmd.pitch - 0.05) < 1e-9     # 뒤로 흐름 → 앞으로
    c.apply_config(cfg(flow_invert_x=True))
    cmd = c.hover(now=1.05)
    assert cmd.roll > 0


def test_pos_hold_output_is_clipped():
    c = FollowController(cfg(pos_kv=5.0))
    c.set_sensor(sample(1.0, vx=1.0))
    assert abs(c.hover(now=1.0).roll + 0.2) < 1e-9


def test_pos_hold_drift_integral_accumulates_and_resets():
    c = FollowController(cfg(pos_kp=1.0, pos_kv=0.0))
    c.set_sensor(sample(0.0, vx=0.5))
    c.hover(now=0.0)
    c.set_sensor(sample(0.1, vx=0.5))
    cmd = c.hover(now=0.1)                       # drift 0.05 m → roll -0.05
    assert abs(cmd.roll + 0.05) < 1e-9
    c.set_sensor(None)
    c.hover(now=0.2)                             # 센서 사라짐 → 드리프트 리셋
    c.set_sensor(sample(0.3, vx=0.0))
    assert c.hover(now=0.3).roll == 0.0


def test_alt_hold_learns_trim_like_vision_assist():
    c = FollowController(cfg(trim_learning=True, trim_learn_rate=1.0))
    c.set_sensor(sample(0.0, alt=0.5))
    c.hover(now=0.0)
    c.set_sensor(sample(1.0, alt=0.5))
    c.hover(now=1.0)
    assert c.trim_offset > 0.0


# ---- FOLLOW 모드 통합 ----

def test_follow_uses_sensor_altitude_and_roll_pos_hold_when_yaw_tracking():
    c = FollowController(cfg(lateral_axis="yaw", distance_hold=True))
    c.set_sensor(sample(1.0, alt=0.5, vx=0.2, vy=0.2))
    cmd = c.update(trk(cx=0.5), now=1.0)
    assert abs(cmd.throttle - (TRIM + 0.15)) < 1e-9     # 센서 고도
    assert abs(cmd.roll + 0.1) < 1e-9                   # roll은 비어 있어 위치 유지
    assert cmd.pitch == 0.0                             # pitch는 거리 유지(오차 0)가 소유


def test_follow_pos_hold_skips_roll_when_lateral_axis_is_roll():
    c = FollowController(cfg(lateral_axis="roll", distance_hold=False))
    c.set_sensor(sample(1.0, alt=1.0, vx=0.2, vy=0.2))
    cmd = c.update(trk(cx=0.5), now=1.0)
    assert cmd.roll == 0.0                              # 영상 좌우 오차 0, 위치 유지는 roll 안 건드림
    assert abs(cmd.pitch + 0.1) < 1e-9                  # 거리 유지 꺼짐 → pitch 위치 유지


# ---- Supervisor: LOST 하강이 목표 고도로 바뀜 ----

def test_supervisor_hover_mode_passes_sample():
    c = FollowController(cfg())
    sup = FlightSupervisor(c)
    sup.set_mode(Mode.HOVER)
    cmd, status = sup.step(None, True, 1.0, sample(1.0, alt=0.5))
    assert status == Status.HOVER and abs(cmd.throttle - (TRIM + 0.15)) < 1e-9


def test_supervisor_lost_lowers_target_altitude_with_sensor():
    c = FollowController(cfg())
    sup = FlightSupervisor(c)
    sup.set_mode(Mode.FOLLOW)
    cmd, status = sup.step(None, True, 0.0, sample(0.0, alt=1.0))
    assert status == Status.NO_TARGET and sup.descend_m == 0.0 and abs(cmd.throttle - TRIM) < 1e-9
    cmd, _ = sup.step(None, True, 3.0, sample(3.0, alt=1.0))   # 대기 1s 후 2s × 0.1 = 0.2 m 하강
    assert abs(sup.descend_m - 0.2) < 1e-9 and sup.descend == 0.0
    assert cmd.throttle < TRIM                                 # 목표 0.8 < 실측 1.0 → 내려감
    cmd, _ = sup.step(None, True, 30.0, sample(30.0, alt=1.0))
    assert abs(sup.descend_m - 0.8) < 1e-9                     # alt_land_m 0.2 에서 멈춤


def test_supervisor_lost_falls_back_to_throttle_descend_without_sensor():
    c = FollowController(cfg())
    sup = FlightSupervisor(c)
    sup.set_mode(Mode.FOLLOW)
    sup.step(None, True, 0.0, None)
    cmd, _ = sup.step(None, True, 3.0, None)
    assert abs(sup.descend - 0.04) < 1e-9 and sup.descend_m == 0.0
    assert abs(cmd.throttle - (TRIM - 0.04)) < 1e-9


def test_supervisor_standby_ignores_sensor():
    c = FollowController(cfg())
    sup = FlightSupervisor(c)
    cmd, status = sup.step(None, True, 1.0, sample(1.0, alt=0.3))
    assert status == Status.STANDBY and cmd.throttle == -1.0


def test_hold_snapshot_reports_state():
    c = FollowController(cfg())
    s = sample(1.0, alt=0.9, vx=0.1)
    c.set_sensor(s)
    c.hover(now=1.0)
    snap = c.hold.snapshot(s, 1.0)
    assert snap["alt_hold"] and snap["pos_hold"] and snap["sensor_ok"] and snap["alt_m"] == 0.9
    assert abs(snap["alt_err"] - 0.1) < 1e-9
    snap = c.hold.snapshot(None, 1.0)
    assert not snap["sensor"] and snap["alt_m"] is None
