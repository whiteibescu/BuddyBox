import time
from datetime import datetime
from pathlib import Path

import cv2


class Recorder:
    def __init__(self, path, size, fps):
        self.path = Path(path)
        self.fps = fps
        self.writer = cv2.VideoWriter(str(self.path), cv2.VideoWriter.fourcc(*"mp4v"), fps, size)
        if not self.writer.isOpened():
            raise RuntimeError(f"녹화 파일을 열 수 없습니다: {path}")
        self.start = None
        self.written = 0

    def write(self, frame):
        if self.start is None:
            self.start = time.time()
        target = int((time.time() - self.start) * self.fps) + 1
        target = min(target, self.written + 5)
        while self.written < target:
            self.writer.write(frame)
            self.written += 1

    def write_once(self, frame):
        if self.start is None:
            self.start = time.time()
        self.writer.write(frame)
        self.written += 1
        return self.written - 1

    @property
    def elapsed(self):
        return 0.0 if self.start is None else time.time() - self.start

    def close(self):
        self.writer.release()
        return self.path, self.written


def new_recording_path(rec_dir):
    rec_dir = Path(rec_dir)
    rec_dir.mkdir(parents=True, exist_ok=True)
    return rec_dir / f"follow_{datetime.now():%Y%m%d_%H%M%S}.mp4"


def save_snapshot(frame, rec_dir):
    rec_dir = Path(rec_dir)
    rec_dir.mkdir(parents=True, exist_ok=True)
    path = rec_dir / f"shot_{datetime.now():%Y%m%d_%H%M%S}.png"
    cv2.imwrite(str(path), frame)
    return path
