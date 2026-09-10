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
        self.descend = 0.0
        self._was_tracking = False
        self._fallback_since = None

    def set_mode(self, mode):
        mode = Mode(mode)
        if mode != self.mode:
            self.controller.reset()
            self._was_tracking = False
            self._fallback_since = None
            self.descend = 0.0
        self.mode = mode

    def panic(self):
        self.set_mode(Mode.STANDBY)

    def step(self, track, video_ok, now):
        if self.mode == Mode.STANDBY:
            self.status = Status.STANDBY
            self._not_tracking()
            self._fallback_since = None
            self.descend = 0.0
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
            return self.controller.hover(), self.status

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
        return self.controller.update(track, now), self.status

    def _fallback_hover(self, now):
        cfg = self.controller.cfg
        if self._fallback_since is None:
            self._fallback_since = now
        waited = max(0.0, now - self._fallback_since - cfg.lost_descend_after_s)
        self.descend = min(cfg.lost_descend_max, waited * cfg.lost_descend_rate)
        cmd = self.controller.hover()
        return StickCommand(roll=0.0, pitch=0.0, yaw=0.0,
                            throttle=max(-1.0, cmd.throttle - self.descend))

    def _not_tracking(self):
        if self._was_tracking:
            self.controller.reset()
        self._was_tracking = False
