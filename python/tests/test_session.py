import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")

from buddybox.follow.controller import FollowConfig, FollowError
from buddybox.follow.session import Session, load_session
from buddybox.safety import StickCommand
from buddybox.vision.tracker import Track

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import session_replay
import session_report


def make_session(tmp_path, steps=40):
    cfg = FollowConfig()
    frame = np.zeros((48, 64, 3), dtype=np.uint8)
    s = Session(tmp_path, "test", (64, 48), 30, cfg, detector_info={"name": "fake", "conf": 0.5, "every": 1})
    s.event("mode", mode="FOLLOW", prev="STANDBY")
    for i in range(steps):
        cx = 0.5 + 0.2 * np.sin(i / 5.0)
        track = Track(cx=cx, cy=0.5, w=0.2, h=0.45, conf=0.9, age=0.0, lost=False, frames=i)
        err = FollowError(x=(cx - 0.5) * 2, y=0.0, size=0.0, raw_x=(cx - 0.5) * 2, raw_y=0.0, raw_size=0.0)
        raw = StickCommand(roll=0.0, pitch=0.0, yaw=err.x * 0.6, throttle=-0.35)
        safe = {"roll": 0.0, "pitch": 0.0, "yaw": err.x * 0.6, "throttle": -0.35}
        tele = {"mode": "FOLLOW", "status": "TRACKING", "fps": 30.0, "infer_ms": 50.0, "video_ok": True,
                "track": track, "error": err, "raw": raw, "safe": safe, "channels_us": [1500, 1500, 1320, 1500, 1500],
                "trim": -0.35, "trim_offset": 0.0, "descend": 0.0, "det_seq": i}
        persons = [(0.9, cx - 0.1, 0.275, cx + 0.1, 0.725)]
        s.step(frame, frame, tele, seq=i + 1, new_frame=True, persons=persons)
        s.t0 -= 1.0 / 30.0
    return s.close()


def test_session_writes_files_and_loads_back(tmp_path):
    d, raw_n = make_session(tmp_path)
    assert (d / "raw.mp4").exists() and (d / "raw.mp4").stat().st_size > 0
    assert (d / "annotated.mp4").exists()
    assert raw_n >= 40
    sess = load_session(d)
    assert len(sess["frames"]) == 40
    assert sess["meta"]["steps"] == 40
    assert sess["config"]["hover_throttle"] == FollowConfig().hover_throttle
    kinds = [e["kind"] for e in sess["events"]]
    assert kinds[0] == "session_start" and kinds[-1] == "session_end" and "mode" in kinds
    rec = sess["frames"][5]
    assert rec["track"]["cx"] > 0 and rec["persons"] and rec["safe"]["throttle"] == -0.35
    assert rec["det_seq"] == 5


def test_report_summary_and_outputs(tmp_path):
    d, _ = make_session(tmp_path)
    sess = load_session(d)
    summary = session_report.summarize(sess)
    assert summary["steps"] == 40
    assert summary["status_share"]["TRACKING"] == 100.0
    assert summary["tracking_steps"] == 40
    assert summary["osc_x"]["zero_crossings"] >= 1
    md = session_report.render_markdown(summary)
    assert "세션 리포트" in md and "TRACKING" in md
    sheet = session_report.contact_sheet(sess, d / "sheet.png", n=4, cols=2)
    assert sheet is not None and sheet.exists()
    csv_path = session_report.export_csv(sess, d / "frames.csv")
    assert csv_path.exists() and len(csv_path.read_text(encoding="utf-8").splitlines()) == 41
    frames = session_report.export_frames(sess, [0.5], d)
    assert len(frames) == 1 and frames[0].exists()


def test_replay_reproduces_trace_length_and_reacts_to_gain(tmp_path):
    d, _ = make_session(tmp_path)
    sess = load_session(d)
    base = FollowConfig.from_dict(sess["config"])
    trace = session_replay.replay(sess, base)
    assert len(trace) == 40
    assert trace[-1]["mode"] == "FOLLOW"
    assert any(r["status"] == "TRACKING" for r in trace)
    strong = session_replay.apply_overrides(base, ["lateral_kp=2.0", "deadzone_x=0.0"])
    trace2 = session_replay.replay(sess, strong)
    yaw1 = max(abs(r["safe"]["yaw"]) for r in trace)
    yaw2 = max(abs(r["safe"]["yaw"]) for r in trace2)
    assert yaw2 >= yaw1
    result = session_replay.compare(sess["frames"], trace2)
    assert "throttle" in result and result["replay_tracking_steps"] > 0
