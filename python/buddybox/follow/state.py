from enum import Enum

from ..safety import StickCommand


class Mode(str, Enum):
    STANDBY = "STANDBY"
    HOVER = "HOVER"
    FOLLOW = "FOLLOW"


class Status(str, Enum):
    STANDBY = "STANDBY"
    HOVER = "HOVER"
    TRACKING = "TRACKING"
    LOST = "LOST"
    NO_TARGET = "NO TARGET"
    NO_VIDEO = "NO VIDEO"


class FlightSupervisor:
    def __init__(self, controller):
        self.controller = controller
        self.mode = Mode.STANDBY
        self.status = Status.STANDBY
        self.descend = 0.0        # 개루프 LOST 하강량 (스로틀 단위)
        self.descend_m = 0.0      # 센서 홀드 LOST 하강량 (목표 고도 m)
        self._was_tracking = False
        self._fallback_since = None

    def set_mode(self, mode):
        mode = Mode(mode)
        if mode != self.mode:
            self.controller.reset()
            self._was_tracking = False
            self._fallback_since = None
            self.descend = 0.0
            self.descend_m = 0.0
        self.mode = mode

    def panic(self):
        self.set_mode(Mode.STANDBY)

    def step(self, track, video_ok, now, sample=None):
        """sample: 하방 센서 RangeFlowSample (없으면 None → 기존 개루프 호버)."""
        self.controller.set_sensor(sample, now)
        if self.mode == Mode.STANDBY:
            self.status = Status.STANDBY
            self._not_tracking()
            self._fallback_since = None
            self.descend = 0.0
            self.descend_m = 0.0
            return self.controller.standby(), self.status

        if not video_ok:
            self.status = Status.NO_VIDEO
            self._not_tracking()
            return self._fallback_hover(now), self.status

        if self.mode == Mode.HOVER:
            self.status = Status.HOVER
            self._not_tracking()
            self._fallback_since = None
            self.descend = 0.0
            self.descend_m = 0.0
            return self.controller.hover(now), self.status

        if track is None:
            self.status = Status.NO_TARGET
            self._not_tracking()
            return self._fallback_hover(now), self.status
        if track.lost:
            self.status = Status.LOST
            self._not_tracking()
            return self._fallback_hover(now), self.status

        self.status = Status.TRACKING
        self._was_tracking = True
        self._fallback_since = None
        self.descend = 0.0
        self.descend_m = 0.0
        return self.controller.update(track, now), self.status

    def _fallback_hover(self, now):
        """타깃/영상 없음: 호버 유지 후 일정 시간 지나면 서서히 하강.

        센서 고도 홀드가 살아 있으면 목표 고도를 m 단위로 낮추고(착지 고도까지),
        아니면 기존처럼 트림 스로틀에서 조금씩 뺀다.
        """
        cfg = self.controller.cfg
        if self._fallback_since is None:
            self._fallback_since = now
        waited = max(0.0, now - self._fallback_since - cfg.lost_descend_after_s)
        target = max(cfg.alt_land_m, cfg.alt_target_m - waited * cfg.lost_descend_m_s)
        cmd = self.controller.hover(now, target_alt_m=target)
        if self.controller.sensor_hold_active:
            self.descend = 0.0
            self.descend_m = cfg.alt_target_m - target
            return cmd
        self.descend_m = 0.0
        self.descend = min(cfg.lost_descend_max, waited * cfg.lost_descend_rate)
        return StickCommand(roll=cmd.roll, pitch=cmd.pitch, yaw=0.0,
                            throttle=max(-1.0, cmd.throttle - self.descend))

    def _not_tracking(self):
        if self._was_tracking:
            self.controller.reset()
        self._was_tracking = False
