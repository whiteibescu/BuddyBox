"""하방 센서 기반 호버 홀드 — 레인지파인더 고도 유지 + 옵티컬 플로우 위치 유지.

FollowController가 소유하며, 유효한 RangeFlowSample이 있을 때만 출력한다.
센서가 없거나(None), 오래됐거나, 범위 밖이면 None을 돌려 호출자가 기존 개루프
(트림 스로틀 / 영상 기반 고도 보조)로 돌아가게 한다.

좌표 규약 (스틱 정규화 값):
  roll  +1 = 오른쪽,  pitch +1 = 앞으로,  throttle 트림 기준 보정량(Δ)
  샘플 vx +  = 오른쪽으로 이동 중,  vy + = 앞으로 이동 중
  → 위치 유지는 속도의 반대 방향으로 기울인다. 센서 부호가 반대면 flow_invert_x/y로 보정.
"""

from .pid import PID


def _clip(v, lo, hi):
    return max(lo, min(hi, v))


class HoverHold:
    def __init__(self, cfg):
        self.alt = PID()
        self.cfg = cfg
        self.drift_x = 0.0
        self.drift_y = 0.0
        self._last_t = None
        self.alt_active = False
        self.pos_active = False
        self.info = {}
        self.apply_config(cfg)

    def apply_config(self, cfg):
        self.cfg = cfg
        self.alt.kp, self.alt.ki, self.alt.kd = cfg.alt_kp, cfg.alt_ki, cfg.alt_kd
        self.alt.out_limit = self.alt.i_limit = cfg.max_throttle_delta
        self.alt.d_filter = cfg.alt_d_filter

    def reset(self):
        self.alt.reset()
        self.drift_x = 0.0
        self.drift_y = 0.0
        self._last_t = None
        self.alt_active = False
        self.pos_active = False
        self.info = {}

    # ---- 유효성 ----

    def sample_ok(self, sample, now):
        cfg = self.cfg
        return (sample is not None and sample.fresh(now, cfg.sensor_timeout_s)
                and sample.alt_valid and cfg.alt_min_m <= sample.alt_m <= cfg.alt_max_m)

    # ---- 출력 ----

    def altitude(self, sample, now, target_m):
        """고도 오차(m) → 스로틀 보정량. 사용 불가면 None."""
        if not self.cfg.alt_hold or not self.sample_ok(sample, now):
            if self.alt_active:
                self.alt.reset()
            self.alt_active = False
            return None
        self.alt_active = True
        err = target_m - sample.alt_m
        delta = self.alt.update(err, now)
        if self.cfg.invert_throttle:
            delta = -delta
        self.info.update(alt_target_m=target_m, alt_err=err, alt_delta=delta)
        return delta

    def position(self, sample, now, axes=("roll", "pitch")):
        """플로우 속도 → (roll, pitch). 사용 불가면 None. axes로 한 축만 쓸 수 있다."""
        cfg = self.cfg
        if not cfg.pos_hold or not self.sample_ok(sample, now):
            self.pos_active = False
            self.drift_x = self.drift_y = 0.0
            self._last_t = None
            return None
        dt = 0.0 if self._last_t is None else _clip(now - self._last_t, 0.0, 0.2)
        self._last_t = now
        if not self.pos_active:
            self.drift_x = self.drift_y = 0.0
        self.pos_active = True
        vx = -sample.vx if cfg.flow_invert_x else sample.vx
        vy = -sample.vy if cfg.flow_invert_y else sample.vy
        lim = cfg.pos_max_drift_m
        self.drift_x = _clip(self.drift_x + vx * dt, -lim, lim)
        self.drift_y = _clip(self.drift_y + vy * dt, -lim, lim)
        roll = pitch = 0.0
        if "roll" in axes:
            roll = -(cfg.pos_kv * vx + cfg.pos_kp * self.drift_x)
        else:
            self.drift_x = 0.0
        if "pitch" in axes:
            pitch = -(cfg.pos_kv * vy + cfg.pos_kp * self.drift_y)
        else:
            self.drift_y = 0.0
        roll = _clip(roll, -cfg.max_pos_tilt, cfg.max_pos_tilt)
        pitch = _clip(pitch, -cfg.max_pos_tilt, cfg.max_pos_tilt)
        self.info.update(drift_x=self.drift_x, drift_y=self.drift_y, pos_roll=roll, pos_pitch=pitch)
        return roll, pitch

    def snapshot(self, sample, now):
        """텔레메트리용 요약."""
        d = {
            "alt_hold": self.alt_active,
            "pos_hold": self.pos_active,
            "sensor": sample is not None,
            "sensor_ok": self.sample_ok(sample, now),
            "age": None if sample is None else round(now - sample.t, 3),
            "alt_m": None if sample is None else sample.alt_m,
            "vx": 0.0 if sample is None else sample.vx,
            "vy": 0.0 if sample is None else sample.vy,
        }
        d.update(self.info)
        return d
