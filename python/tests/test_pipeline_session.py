import os
import sys
import time
from threading import Thread

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")

from buddybox import BuddyBox
from buddybox.follow.controller import FollowConfig
from buddybox.follow.pipeline import FollowPipeline
from buddybox.follow.session import load_session
from buddybox.follow.state import Mode
from buddybox.vision.capture import FrameSource
from buddybox.vision.detector import Detection


class FakeSource(FrameSource):
    def __init__(self, fps=30.0, size=(64, 48)):
        super().__init__()
        self._fps = fps
        self.size = size
        self.description = "fake"
        self.thread.start()

    def _loop(self):
        i = 0
        while self.running:
            frame = np.zeros((self.size[1], self.size[0], 3), dtype=np.uint8)
            cv2.rectangle(frame, (10 + i % 20, 8), (30 + i % 20, 40), (255, 255, 255), -1)
            self._publish(frame)
            i += 1
            time.sleep(1.0 / self._fps)

    @property
    def fps(self):
        return self._fps


class FakeDetector:
    name = "fake"
    provider = "CPU"

    def __call__(self, frame, threshold):
        H, W = frame.shape[:2]
        return [Detection("person", 1, 0.9, int(W * 0.3), int(H * 0.2), int(W * 0.6), int(H * 0.9))]


def run_pipeline(tmp_path, auto_session, session_max_s=300.0, actions=()):
    src = FakeSource()
    src.wait_first()
    bb = BuddyBox("sim")
    p = FollowPipeline(src, FakeDetector(), bb, FollowConfig(), every=1, rec_dir=tmp_path,
                       auto_session=auto_session, session_max_s=session_max_s, annotated_video=False)
    p.start()
    try:
        for delay, action in actions:
            time.sleep(delay)
            action(p)
    finally:
        p.stop()
        src.release()
        bb.close()
    return p


def test_always_mode_records_from_first_frame_and_rolls_over(tmp_path):
    p = run_pipeline(tmp_path, "always", session_max_s=0.7,
                     actions=[(0.5, lambda p: p.set_mode(Mode.FOLLOW)), (1.6, lambda p: None)])
    dirs = sorted(tmp_path.glob("session_*"))
    assert len(dirs) >= 2
    assert p.session_count == len(dirs)
    first = load_session(dirs[0])
    assert first["frames"]
    assert first["frames"][0]["mode"] == "STANDBY"
    assert any(e["kind"] == "mode" and e.get("mode") == "FOLLOW" for e in first["events"])
    assert any(e["kind"] == "rollover" for e in first["events"])
    assert "motion" in first["frames"][-1]
    assert any(f["motion"] > 0.0 for f in first["frames"])
    assert any(f["status"] == "TRACKING" for f in first["frames"])
    last = load_session(dirs[-1])
    assert last["meta"]["ended"]


def test_mode_auto_session_only_outside_standby(tmp_path):
    seen = {}

    def check_none(p):
        seen["standby"] = p.session_active

    def to_hover(p):
        p.set_mode(Mode.HOVER)

    def check_active(p):
        seen["hover"] = p.session_active

    def to_standby(p):
        p.set_mode(Mode.STANDBY)

    def check_closed(p):
        seen["closed"] = p.session_active

    run_pipeline(tmp_path, "mode", actions=[(0.4, check_none), (0.0, to_hover), (0.4, check_active),
                                            (0.0, to_standby), (0.4, check_closed)])
    assert seen == {"standby": False, "hover": True, "closed": False}
    assert len(list(tmp_path.glob("session_*"))) == 1


def test_manual_stop_pauses_auto_until_manual_start(tmp_path):
    seen = {}

    def stop(p):
        seen["before"] = p.session_active
        p.stop_session(manual=True)

    def check_paused(p):
        seen["paused"] = p.session_active

    def restart(p):
        p.start_session(manual=True)

    def check_running(p):
        seen["running"] = p.session_active

    run_pipeline(tmp_path, "always", actions=[(0.4, stop), (0.4, check_paused), (0.0, restart),
                                              (0.3, check_running)])
    assert seen == {"before": True, "paused": False, "running": True}
    assert len(list(tmp_path.glob("session_*"))) == 2


def test_off_mode_never_records(tmp_path):
    run_pipeline(tmp_path, "off", actions=[(0.3, lambda p: p.set_mode(Mode.FOLLOW)), (0.4, lambda p: None)])
    assert not list(tmp_path.glob("session_*"))
