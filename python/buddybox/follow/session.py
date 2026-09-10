import json
import subprocess
import sys
import time
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path

import cv2

from ..vision.recorder import Recorder

FRAMES_FILE = "frames.jsonl"
EVENTS_FILE = "events.jsonl"
META_FILE = "meta.json"
CONFIG_FILE = "config.json"
RAW_VIDEO = "raw.mp4"
ANNOTATED_VIDEO = "annotated.mp4"


def _git_hash():
    try:
        root = Path(__file__).resolve().parents[3]
        out = subprocess.run(["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=3)
        return out.stdout.strip() or None
    except Exception:
        return None


def _plain(obj):
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if is_dataclass(obj):
        return {k: _plain(v) for k, v in asdict(obj).items()}
    if isinstance(obj, dict):
        return {str(k): _plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_plain(v) for v in obj]
    if hasattr(obj, "value"):
        return obj.value
    return str(obj)


def new_session_dir(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    base = f"session_{datetime.now():%Y%m%d_%H%M%S}"
    for i in range(100):
        d = root / (base if i == 0 else f"{base}_{i}")
        try:
            d.mkdir()
            return d
        except FileExistsError:
            continue
    raise RuntimeError(f"세션 폴더를 만들 수 없습니다: {base}")


class Session:
    def __init__(self, root, source_desc, frame_size, fps, cfg, detector_info=None, annotated=True):
        self.dir = new_session_dir(root)
        self.frame_size = tuple(frame_size)
        self.fps = int(round(fps)) or 30
        self.t0 = time.monotonic()
        self.started_at = datetime.now()
        self.raw = Recorder(self.dir / RAW_VIDEO, self.frame_size, self.fps)
        self.annotated = Recorder(self.dir / ANNOTATED_VIDEO, self.frame_size, self.fps) if annotated else None
        self._frames = open(self.dir / FRAMES_FILE, "w", encoding="utf-8")
        self._events = open(self.dir / EVENTS_FILE, "w", encoding="utf-8")
        self.steps = 0
        self.meta = {
            "started": self.started_at.isoformat(timespec="seconds"),
            "source": source_desc,
            "frame_size": list(self.frame_size),
            "fps": self.fps,
            "detector": detector_info or {},
            "git": _git_hash(),
            "python": sys.version.split()[0],
            "opencv": cv2.__version__,
        }
        self.write_config(cfg)
        self._write_meta()
        self.event("session_start")

    def _write_meta(self):
        (self.dir / META_FILE).write_text(json.dumps(self.meta, indent=2, ensure_ascii=False), encoding="utf-8")

    def write_config(self, cfg):
        data = cfg.to_dict() if hasattr(cfg, "to_dict") else _plain(cfg)
        (self.dir / CONFIG_FILE).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    @property
    def elapsed(self):
        return time.monotonic() - self.t0

    def event(self, kind, **data):
        rec = {"t": round(self.elapsed, 3), "kind": kind}
        rec.update(_plain(data))
        self._events.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self._events.flush()

    def step(self, raw_frame, annotated_frame, tele, seq, new_frame, persons):
        if new_frame and raw_frame is not None:
            self.raw.write_once(raw_frame)
            if self.annotated is not None and annotated_frame is not None:
                self.annotated.write_once(annotated_frame)
        track = tele.get("track")
        err = tele.get("error")
        raw = tele.get("raw")
        rec = {
            "t": round(self.elapsed, 3),
            "seq": seq,
            "det_seq": tele.get("det_seq"),
            "new": bool(new_frame),
            "rec_frame": max(0, self.raw.written - 1),
            "mode": tele.get("mode"),
            "status": tele.get("status"),
            "fps": round(tele.get("fps", 0.0), 1),
            "infer_ms": round(tele.get("infer_ms", 0.0), 1),
            "video_ok": tele.get("video_ok"),
            "motion": round(tele.get("motion", 0.0), 4),
            "arm": (tele.get("arm") or {}).get("label", ""),
            "persons": [[round(p[0], 3), round(p[1], 4), round(p[2], 4), round(p[3], 4), round(p[4], 4)]
                        for p in persons],
            "track": None if track is None else {
                "cx": round(track.cx, 4), "cy": round(track.cy, 4), "w": round(track.w, 4), "h": round(track.h, 4),
                "conf": round(track.conf, 3), "age": round(track.age, 2), "lost": track.lost, "frames": track.frames,
            },
            "err": None if err is None else {k: round(v, 4) for k, v in asdict(err).items()},
            "raw": None if raw is None else {k: round(v, 4) for k, v in asdict(raw).items()},
            "safe": {k: round(v, 4) for k, v in tele["safe"].items()} if tele.get("safe") else None,
            "us": tele.get("channels_us"),
            "trim": round(tele.get("trim", 0.0), 4),
            "trim_offset": round(tele.get("trim_offset", 0.0), 4),
            "descend": round(tele.get("descend", 0.0), 4),
        }
        self._frames.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self.steps += 1
        if self.steps % 30 == 0:
            self._frames.flush()

    def snapshot(self, image, tag="shot"):
        shots = self.dir / "shots"
        shots.mkdir(exist_ok=True)
        path = shots / f"{tag}_{self.elapsed:07.2f}s.png"
        cv2.imwrite(str(path), image)
        self.event("snapshot", path=path.name)
        return path

    def close(self):
        self.event("session_end", steps=self.steps, raw_frames=self.raw.written)
        self._frames.close()
        self._events.close()
        _, raw_n = self.raw.close()
        ann_n = self.annotated.close()[1] if self.annotated is not None else 0
        self.meta.update({"ended": datetime.now().isoformat(timespec="seconds"),
                          "steps": self.steps, "raw_frames": raw_n, "annotated_frames": ann_n,
                          "duration_s": round(self.elapsed, 2)})
        self._write_meta()
        return self.dir, raw_n


def load_session(path):
    path = Path(path)
    meta = json.loads((path / META_FILE).read_text(encoding="utf-8"))
    config = json.loads((path / CONFIG_FILE).read_text(encoding="utf-8"))
    frames = [json.loads(line) for line in (path / FRAMES_FILE).read_text(encoding="utf-8").splitlines() if line.strip()]
    events_path = path / EVENTS_FILE
    events = []
    if events_path.exists():
        events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return {"dir": path, "meta": meta, "config": config, "frames": frames, "events": events}
