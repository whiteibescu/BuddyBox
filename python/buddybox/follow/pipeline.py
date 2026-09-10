import shutil
import time
from pathlib import Path
from threading import Lock, Thread

import cv2

from ..safety import SafetyLimiter
from ..vision.recorder import save_snapshot
from ..vision.tracker import TargetTracker
from .arming import AUX1, ArmController
from .controller import FollowController
from .overlay import draw_overlay
from .session import Session
from .state import FlightSupervisor, Mode, Status

AUTO_SESSION_MODES = ("always", "mode", "off")
MOTION_SIZE = (64, 36)


class DetectWorker:
    def __init__(self, source, detector, conf, every, label):
        self.source = source
        self.detector = detector
        self.conf = conf
        self.every = max(1, int(every))
        self.label = label
        self.lock = Lock()
        self.result = ([], 0, 0.0, None)
        self.errors = []
        self.running = False
        self.thread = None

    def start(self):
        self.running = True
        self.thread = Thread(target=self._loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.thread is not None:
            self.thread.join(timeout=3.0)

    def latest(self):
        with self.lock:
            return self.result

    def _loop(self):
        last_seq = 0
        while self.running:
            frame, seq = self.source.read()
            if frame is None or seq < last_seq + self.every:
                time.sleep(0.002)
                continue
            last_seq = seq
            t0 = time.perf_counter()
            try:
                dets = self.detector(frame, self.conf)
            except Exception as exc:
                dets = []
                self.errors.append(f"detector: {exc}")
            infer_ms = (time.perf_counter() - t0) * 1000.0
            H, W = frame.shape[:2]
            people = [d for d in dets if d.label == self.label]
            boxes = [(d.conf, d.x1 / W, d.y1 / H, d.x2 / W, d.y2 / H) for d in people]
            with self.lock:
                self.result = (people, seq, infer_ms, boxes)


def motion_score(frame, prev_small):
    small = cv2.cvtColor(cv2.resize(frame, MOTION_SIZE, interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
    if prev_small is None:
        return 0.0, small
    diff = cv2.absdiff(small, prev_small)
    return float(diff.mean()) / 255.0, small


class FollowPipeline:
    def __init__(self, source, detector, backend, cfg, conf=0.5, every=2, loop_hz=30.0,
                 rec_dir="recordings", label="person", auto_session="always", annotated_video=False,
                 session_max_s=300.0, min_free_gb=1.0, arm_verifier=None):
        self.source = source
        self.detector = detector
        self.backend = backend
        self.cfg = cfg
        self.loop_hz = loop_hz
        self.rec_dir = Path(rec_dir)
        self.auto_session = auto_session if auto_session in AUTO_SESSION_MODES else "off"
        self.annotated_video = annotated_video
        self.session_max_s = session_max_s
        self.min_free_gb = min_free_gb

        self.worker = DetectWorker(source, detector, conf, every, label)
        self.tracker = TargetTracker(lost_after_s=cfg.lost_after_s)
        self.controller = FollowController(cfg)
        self.supervisor = FlightSupervisor(self.controller)
        self.limiter = self._make_limiter(cfg)
        self.arming = ArmController(backend, verifier=arm_verifier, on_result=self._on_arm_result)

        self._lock = Lock()
        self._sess_lock = Lock()
        self._annotated = None
        self._tele = {"mode": Mode.STANDBY.value, "status": Status.STANDBY.value,
                      "fps": 0.0, "infer_ms": 0.0, "detector": getattr(detector, "name", "?")}
        self._running = False
        self._thread = None
        self._session = None
        self._session_manual = False
        self._auto_paused = False
        self.last_session_dir = None
        self.session_count = 0
        self.last_frame = None
        self.frame_size = None
        self.errors = self.worker.errors

    @staticmethod
    def _make_limiter(cfg):
        return SafetyLimiter(max_tilt=cfg.max_tilt, max_yaw=cfg.max_yaw,
                             max_throttle=cfg.max_throttle, max_rate_per_s=cfg.max_rate_per_s,
                             max_throttle_rate_per_s=cfg.max_throttle_rate_per_s)

    def detector_info(self):
        d = self.detector
        return {
            "name": getattr(d, "name", "?"),
            "provider": getattr(d, "provider", "?"),
            "threads": getattr(d, "threads", None),
            "model": str(getattr(d, "model_path", "")),
            "input": [getattr(d, "in_w", None), getattr(d, "in_h", None)],
            "conf": self.worker.conf,
            "every": self.worker.every,
        }

    @property
    def conf(self):
        return self.worker.conf

    @conf.setter
    def conf(self, value):
        self.worker.conf = float(value)

    def apply_config(self, cfg):
        with self._lock:
            self.cfg = cfg
            self.controller.apply_config(cfg)
            self.tracker.lost_after_s = cfg.lost_after_s
            self.limiter.max_tilt = cfg.max_tilt
            self.limiter.max_yaw = cfg.max_yaw
            self.limiter.max_throttle = cfg.max_throttle
            self.limiter.max_rate_per_s = cfg.max_rate_per_s
            self.limiter.max_throttle_rate_per_s = cfg.max_throttle_rate_per_s
            if self._session is not None:
                self._session.write_config(cfg)
                self._session.event("config", config=cfg.to_dict())

    def reset_trim(self):
        with self._lock:
            self.controller.reset_trim()
        self._event("trim_reset")

    def adopt_trim(self):
        with self._lock:
            value = self.controller.adopt_trim()
            self.limiter.max_throttle = self.cfg.max_throttle
        self._event("trim_adopt", hover_throttle=value)
        return value

    @property
    def effective_trim(self):
        return self.controller.effective_trim

    @property
    def mode(self):
        return self.supervisor.mode

    def set_mode(self, mode):
        mode = Mode(mode)
        with self._lock:
            prev = self.supervisor.mode
            self.supervisor.set_mode(mode)
        if mode != prev:
            self._event("mode", mode=mode.value, prev=prev.value)

    def set_auto_session(self, mode):
        self.auto_session = mode if mode in AUTO_SESSION_MODES else "off"
        self._auto_paused = False

    def panic(self):
        with self._lock:
            self.supervisor.panic()
            self.limiter = self._make_limiter(self.cfg)
        self.backend.neutral()
        self._event("panic")

    def set_hover_throttle(self, value):
        self.cfg.hover_throttle = max(-1.0, min(1.0, float(value)))
        self.apply_config(self.cfg)

    @property
    def arm_state(self):
        return self.arming.snapshot()

    def arm(self):
        if self.supervisor.mode != Mode.STANDBY:
            return None
        state = self.arming.arm()
        self._event("arm", verifiable=state["verifiable"])
        return state

    def disarm(self):
        self.panic()
        state = self.arming.disarm()
        self._event("disarm", verifiable=state["verifiable"])
        return state

    def _on_arm_result(self, result, commanded, reasons):
        self._event("arm_result", result=result, commanded=bool(commanded), reasons=list(reasons))

    def set_sitl_arm(self, armed):
        return self.arm() if armed else self.disarm()

    def select_target(self, x, y):
        self.tracker.select_at(x, y)
        self._event("select_target", x=round(x, 3), y=round(y, 3))

    def clear_target(self):
        self.tracker.clear()
        self._event("clear_target")

    def note(self, text):
        self._event("note", text=str(text))

    def start(self):
        if self._running:
            return
        self._running = True
        self.worker.start()
        self._thread = Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        self.worker.stop()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
        self.stop_session()
        self.arming.stop()
        self.backend.neutral()

    def latest(self):
        with self._lock:
            return self._annotated, dict(self._tele)

    def _event(self, kind, **data):
        with self._lock:
            session = self._session
        if session is not None:
            session.event(kind, **data)

    def free_gb(self):
        try:
            self.rec_dir.mkdir(parents=True, exist_ok=True)
            return shutil.disk_usage(self.rec_dir).free / 1e9
        except OSError:
            return None

    def start_session(self, manual=True):
        with self._sess_lock:
            return self._start_session_locked(manual)

    def _start_session_locked(self, manual):
        if self._session is not None or self.frame_size is None:
            return None
        free = self.free_gb()
        if free is not None and free < self.min_free_gb:
            self.errors.append(f"디스크 여유 {free:.1f} GB < {self.min_free_gb} GB — 세션 기록 안 함")
            self._auto_paused = True
            return None
        fps = self.source.fps or self.loop_hz
        try:
            session = Session(self.rec_dir, self.source.description, self.frame_size, fps, self.cfg,
                              detector_info=self.detector_info(), annotated=self.annotated_video)
        except Exception as exc:
            self.errors.append(f"session: {exc}")
            self._auto_paused = True
            return None
        session.event("mode", mode=self.supervisor.mode.value, prev=None)
        session.event("auto_session", mode=self.auto_session, manual=bool(manual), index=self.session_count)
        with self._lock:
            self._session = session
            self._session_manual = manual
            if manual:
                self._auto_paused = False
            self.session_count += 1
        return session.dir

    def stop_session(self, manual=False):
        with self._sess_lock:
            with self._lock:
                if manual:
                    self._auto_paused = True
                session = self._session
                self._session = None
                self._session_manual = False
            if session is None:
                return None
            result = session.close()
            self.last_session_dir = session.dir
            return result

    @property
    def session_active(self):
        return self._session is not None

    @property
    def session_dir(self):
        return self._session.dir if self._session is not None else None

    def snapshot(self):
        annotated, _ = self.latest()
        if annotated is None:
            return None
        if self._session is not None:
            return self._session.snapshot(annotated)
        return save_snapshot(annotated, self.rec_dir)

    def _auto_wants_session(self, mode):
        if self._auto_paused:
            return False
        if self.auto_session == "always":
            return True
        if self.auto_session == "mode":
            return mode != Mode.STANDBY
        return False

    def _manage_session(self, mode):
        with self._lock:
            session = self._session
            manual = self._session_manual
            wants = self._auto_wants_session(mode)
        if session is None:
            if wants and self.frame_size is not None:
                self.start_session(manual=False)
            return
        if session.elapsed > self.session_max_s:
            session.event("rollover", next_index=self.session_count)
            self.stop_session()
            self.start_session(manual=manual)
            return
        if not manual and not wants:
            self.stop_session()

    def _loop(self):
        last_seq = 0
        last_det_seq = 0
        frames = 0
        fps = 0.0
        tick = time.monotonic()
        last_frame_t = None
        interval = 1.0 / self.loop_hz
        dets = []
        boxes_now = []
        motion = 0.0
        prev_small = None
        while self._running:
            t_start = time.monotonic()
            frame, seq = self.source.read()
            now = time.monotonic()
            new_frame = frame is not None and seq != last_seq
            if new_frame:
                last_seq = seq
                last_frame_t = now
                frames += 1
                self.last_frame = frame
                if self.frame_size is None:
                    self.frame_size = (frame.shape[1], frame.shape[0])
                try:
                    motion, prev_small = motion_score(frame, prev_small)
                except cv2.error:
                    motion = 0.0

            dets, det_seq, infer_ms, boxes = self.worker.latest()
            if boxes is not None and det_seq != last_det_seq:
                last_det_seq = det_seq
                boxes_now = boxes
                track = self.tracker.update(boxes, now)
            else:
                track = self.tracker.peek(now)

            if now - tick >= 0.5:
                fps = frames / (now - tick)
                frames = 0
                tick = now

            video_ok = last_frame_t is not None and (now - last_frame_t) <= self.cfg.video_timeout_s
            with self._lock:
                raw, status = self.supervisor.step(track, video_ok, now)
                safe = self.limiter.apply(raw, now)
                mode = self.supervisor.mode
            self.backend.set_sticks(**safe)
            us = self.backend.get_channels_us()

            self._manage_session(mode)
            with self._lock:
                session = self._session

            tele = {
                "mode": mode.value,
                "status": status.value,
                "fps": fps,
                "infer_ms": infer_ms,
                "detector": getattr(self.detector, "name", "?"),
                "track": track,
                "error": self.controller.last_error if status == Status.TRACKING else None,
                "raw": raw,
                "safe": safe,
                "channels_us": us,
                "rec": f"REC {session.elapsed:5.1f}s {session.dir.name[8:]}" if session is not None else "",
                "session": session.dir.name if session is not None else "",
                "video_ok": video_ok,
                "persons": len(dets),
                "det_seq": det_seq,
                "motion": motion,
                "arm": self.arming.snapshot(),
                "trim": self.controller.effective_trim,
                "trim_offset": self.controller.trim_offset,
                "descend": self.supervisor.descend,
            }

            annotated = None
            if frame is not None:
                annotated = frame.copy()
                draw_overlay(annotated, dets, track, self.cfg, tele)

            if session is not None:
                try:
                    session.step(frame, annotated, tele, seq, new_frame, boxes_now)
                except Exception as exc:
                    self.errors.append(f"session: {exc}")

            with self._lock:
                if annotated is not None:
                    self._annotated = annotated
                self._tele = tele

            elapsed = time.monotonic() - t_start
            if elapsed < interval:
                time.sleep(interval - elapsed)
