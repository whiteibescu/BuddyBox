import dataclasses
import json
from dataclasses import dataclass, field
from pathlib import Path

from ..safety import StickCommand
from .pid import PID


@dataclass
class FollowConfig:
    hover_throttle: float = -0.35
    throttle_mode: str = "absolute"
    lateral_axis: str = "yaw"
    lateral_kp: float = 0.6
    lateral_ki: float = 0.0
    lateral_kd: float = 0.05
    pitch_kp: float = 0.8
    pitch_ki: float = 0.0
    pitch_kd: float = 0.05
    throttle_kp: float = 0.25
    throttle_ki: float = 0.0
    throttle_kd: float = 0.08
    altitude_reference: str = "head"
    target_height: float = 0.45
    target_y: float = 0.35
    deadzone_x: float = 0.06
    deadzone_y: float = 0.06
    deadzone_height: float = 0.05
    max_lateral: float = 0.35
    max_pitch: float = 0.25
    max_throttle_delta: float = 0.12
    invert_lateral: bool = False
    invert_pitch: bool = False
    invert_throttle: bool = False
    distance_hold: bool = True
    altitude_assist: bool = True
    trim_learning: bool = True
    trim_learn_rate: float = 0.15
    trim_learn_up: float = 0.10
    trim_learn_down: float = 0.30
    lost_descend_after_s: float = 3.0
    lost_descend_rate: float = 0.02
    lost_descend_max: float = 0.15
    max_tilt: float = 0.5
    max_yaw: float = 0.5
    max_rate_per_s: float = 2.0
    max_throttle_rate_per_s: float = 0.6
    lost_after_s: float = 0.6
    video_timeout_s: float = 1.0
    extra: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data):
        names = {f.name for f in dataclasses.fields(cls)}
        known = {k: v for k, v in data.items() if k in names and k != "extra"}
        cfg = cls(**known)
        cfg.extra = {k: v for k, v in data.items() if k not in names}
        return cfg

    def to_dict(self):
        d = dataclasses.asdict(self)
        d.pop("extra", None)
        return d

    @classmethod
    def load(cls, path):
        path = Path(path)
        if not path.exists():
            return cls()
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def save(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    @property
    def offset_mode(self):
        return self.throttle_mode == "offset"

    @property
    def max_throttle(self):
        if self.offset_mode:
            return min(1.0, self.max_throttle_delta)
        learn_up = self.trim_learn_up if self.trim_learning else 0.0
        return min(1.0, self.hover_throttle + learn_up + self.max_throttle_delta)


@dataclass
class FollowError:
    x: float = 0.0
    y: float = 0.0
    size: float = 0.0
    raw_x: float = 0.0
    raw_y: float = 0.0
    raw_size: float = 0.0


def deadband(value, zone):
    if zone <= 0.0:
        return value
    if abs(value) <= zone:
        return 0.0
    sign = 1.0 if value > 0 else -1.0
    return sign * (abs(value) - zone) / max(1e-6, 1.0 - zone)


def _clip(v, lo, hi):
    return max(lo, min(hi, v))


def vertical_reference(track, mode):
    if mode == "head":
        return track.cy - track.h / 2.0
    return track.cy


class FollowController:
    def __init__(self, cfg=None):
        self.cfg = cfg or FollowConfig()
        self.lateral = PID()
        self.pitch = PID()
        self.throttle = PID()
        self.trim_offset = 0.0
        self._last_t = None
        self.last_error = FollowError()
        self.apply_config(self.cfg)
        self.last_command = self.hover()

    def apply_config(self, cfg):
        self.cfg = cfg
        self.lateral.kp, self.lateral.ki, self.lateral.kd = cfg.lateral_kp, cfg.lateral_ki, cfg.lateral_kd
        self.lateral.out_limit = self.lateral.i_limit = cfg.max_lateral
        self.pitch.kp, self.pitch.ki, self.pitch.kd = cfg.pitch_kp, cfg.pitch_ki, cfg.pitch_kd
        self.pitch.out_limit = self.pitch.i_limit = cfg.max_pitch
        self.throttle.kp, self.throttle.ki, self.throttle.kd = cfg.throttle_kp, cfg.throttle_ki, cfg.throttle_kd
        self.throttle.out_limit = self.throttle.i_limit = cfg.max_throttle_delta
        self.trim_offset = _clip(self.trim_offset, -cfg.trim_learn_down, cfg.trim_learn_up)

    def reset(self):
        self.lateral.reset()
        self.pitch.reset()
        self.throttle.reset()
        self._last_t = None
        self.last_error = FollowError()

    def reset_trim(self):
        self.trim_offset = 0.0

    def adopt_trim(self):
        if not self.cfg.offset_mode:
            self.cfg.hover_throttle = _clip(self.cfg.hover_throttle + self.trim_offset, -1.0, 1.0)
        self.trim_offset = 0.0
        return self.cfg.hover_throttle

    @property
    def base_throttle(self):
        return 0.0 if self.cfg.offset_mode else self.cfg.hover_throttle

    @property
    def effective_trim(self):
        return _clip(self.base_throttle + self.trim_offset, -1.0, 1.0)

    def hover(self):
        return StickCommand(roll=0.0, pitch=0.0, yaw=0.0, throttle=self.effective_trim)

    def standby(self):
        return StickCommand(roll=0.0, pitch=0.0, yaw=0.0, throttle=0.0 if self.cfg.offset_mode else -1.0)

    def errors(self, track):
        cfg = self.cfg
        ref_y = vertical_reference(track, cfg.altitude_reference)
        raw_x = _clip((track.cx - 0.5) * 2.0, -1.0, 1.0)
        raw_y = _clip((cfg.target_y - ref_y) * 2.0, -1.0, 1.0)
        raw_size = _clip((cfg.target_height - track.h) / max(1e-6, cfg.target_height), -1.0, 1.0)
        return FollowError(
            x=deadband(raw_x, cfg.deadzone_x),
            y=deadband(raw_y, cfg.deadzone_y),
            size=deadband(raw_size, cfg.deadzone_height),
            raw_x=raw_x,
            raw_y=raw_y,
            raw_size=raw_size,
        )

    def update(self, track, now):
        cfg = self.cfg
        err = self.errors(track)
        self.last_error = err
        dt = 0.0 if self._last_t is None else max(0.0, now - self._last_t)
        self._last_t = now

        lateral = self.lateral.update(err.x, now)
        if cfg.invert_lateral:
            lateral = -lateral

        pitch = 0.0
        if cfg.distance_hold:
            pitch = self.pitch.update(err.size, now)
            if cfg.invert_pitch:
                pitch = -pitch
        else:
            self.pitch.reset()

        delta = 0.0
        if cfg.altitude_assist:
            delta = self.throttle.update(err.y, now)
            if cfg.invert_throttle:
                delta = -delta
            if cfg.trim_learning and not cfg.offset_mode and dt > 0.0:
                self.trim_offset = _clip(self.trim_offset + delta * cfg.trim_learn_rate * dt,
                                         -cfg.trim_learn_down, cfg.trim_learn_up)
        else:
            self.throttle.reset()

        roll, yaw = (lateral, 0.0) if cfg.lateral_axis == "roll" else (0.0, lateral)
        cmd = StickCommand(
            roll=_clip(roll, -cfg.max_lateral, cfg.max_lateral),
            pitch=_clip(pitch, -cfg.max_pitch, cfg.max_pitch),
            yaw=_clip(yaw, -cfg.max_lateral, cfg.max_lateral),
            throttle=_clip(self.effective_trim + delta, -1.0, 1.0),
        )
        self.last_command = cmd
        return cmd
