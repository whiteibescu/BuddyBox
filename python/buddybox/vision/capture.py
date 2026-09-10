import sys
import time
from pathlib import Path
from threading import Lock, Thread

import cv2

BACKENDS = {
    "dshow": cv2.CAP_DSHOW,
    "msmf": cv2.CAP_MSMF,
    "v4l2": cv2.CAP_V4L2,
    "any": cv2.CAP_ANY,
}

PRESETS = {
    "vrx1080": {"width": 1920, "height": 1080, "fps": 30, "fourcc": "MJPG"},
    "vrx720": {"width": 1280, "height": 720, "fps": 60, "fourcc": "MJPG"},
    "webcam720": {"width": 1280, "height": 720, "fps": 30, "fourcc": None},
    "raw": {"width": 0, "height": 0, "fps": 0, "fourcc": None},
}

VRX_DEVICE_NAME = "UVC Camera"
VIDEO_SUFFIXES = {".mp4", ".avi", ".mkv", ".mov", ".m4v", ".webm"}


def default_backend():
    return "dshow" if sys.platform == "win32" else "v4l2"


def device_names():
    try:
        from pygrabber.dshow_graph import FilterGraph

        return FilterGraph().get_input_devices()
    except Exception:
        return []


def resolve_camera(spec):
    spec = str(spec)
    if spec.lstrip("-").isdigit():
        return int(spec)
    names = device_names()
    for i, n in enumerate(names):
        if spec.lower() in n.lower():
            return i
    raise ValueError(f"{spec!r} 이름의 UVC 장치를 찾지 못했습니다. 연결된 장치: {names or '(없음)'}")


def probe_devices(backend="dshow", limit=8):
    names = device_names()
    api = BACKENDS[backend] if isinstance(backend, str) else backend
    rows = []
    for i in range(limit):
        cap = cv2.VideoCapture(i, api)
        if not cap.isOpened():
            cap.release()
            continue
        ok, frame = cap.read()
        probe = f"{frame.shape[1]}x{frame.shape[0]}" if ok else "no frame"
        rows.append((i, names[i] if i < len(names) else "?", probe))
        cap.release()
    return rows


class FrameSource:
    def __init__(self):
        self.frame = None
        self.seq = 0
        self.lock = Lock()
        self.running = True
        self.thread = Thread(target=self._loop, daemon=True)
        self.description = ""

    def _loop(self):
        raise NotImplementedError

    def _publish(self, frame):
        with self.lock:
            self.frame = frame
            self.seq += 1

    def read(self):
        with self.lock:
            if self.frame is None:
                return None, 0
            return self.frame, self.seq

    def wait_first(self, timeout=10.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            frame, _ = self.read()
            if frame is not None:
                return frame
            time.sleep(0.02)
        raise RuntimeError("영상 소스에서 프레임이 오지 않습니다")

    @property
    def fps(self):
        return 0.0

    def release(self):
        self.running = False
        self.thread.join(timeout=2.0)


class UvcSource(FrameSource):
    def __init__(self, index, backend="dshow", width=1920, height=1080, fps=30, fourcc="MJPG"):
        super().__init__()
        api = BACKENDS[backend] if isinstance(backend, str) else backend
        self.cap = cv2.VideoCapture(index, api)
        if not self.cap.isOpened():
            raise RuntimeError(f"카메라 {index} 를 열 수 없습니다 (--list 로 확인)")
        if fourcc:
            self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter.fourcc(*fourcc))
        if width:
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        if height:
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        if fps:
            self.cap.set(cv2.CAP_PROP_FPS, fps)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self.description = f"uvc:{index} {backend} {fourcc or ''}".strip()
        self.thread.start()

    def _loop(self):
        while self.running:
            ok, frame = self.cap.read()
            if not ok:
                time.sleep(0.005)
                continue
            self._publish(frame)

    @property
    def fps(self):
        v = self.cap.get(cv2.CAP_PROP_FPS)
        return v if v and v > 1 else 0.0

    def release(self):
        super().release()
        self.cap.release()


class FileSource(FrameSource):
    def __init__(self, path, loop=True, speed=1.0):
        super().__init__()
        self.path = Path(path)
        self.cap = cv2.VideoCapture(str(self.path))
        if not self.cap.isOpened():
            raise RuntimeError(f"영상 파일을 열 수 없습니다: {path}")
        self.loop = loop
        self._fps = self.cap.get(cv2.CAP_PROP_FPS) or 30.0
        self.interval = 1.0 / (self._fps * max(0.05, speed))
        self.description = f"file:{self.path.name}"
        self.thread.start()

    def _loop(self):
        next_t = time.perf_counter()
        while self.running:
            ok, frame = self.cap.read()
            if not ok:
                if not self.loop:
                    break
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                continue
            self._publish(frame)
            next_t += self.interval
            delay = next_t - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
            else:
                next_t = time.perf_counter()

    @property
    def fps(self):
        return self._fps

    def release(self):
        super().release()
        self.cap.release()


def open_source(spec, preset="vrx1080", backend=None, loop=True):
    p = Path(str(spec))
    if p.suffix.lower() in VIDEO_SUFFIXES and p.exists():
        return FileSource(p, loop=loop)
    settings = PRESETS[preset]
    index = resolve_camera(spec)
    return UvcSource(index, backend or default_backend(), **settings)
