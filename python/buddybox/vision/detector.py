import json
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np

MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32).reshape(1, 1, 3)
STD = np.array([0.229, 0.224, 0.225], dtype=np.float32).reshape(1, 1, 3)

MODEL_CANDIDATES = [
    Path(__file__).resolve().parents[2] / "models" / "rfdetr_nano_coco.onnx",
    Path(r"D:\VisionWorkspace\unity-prototypes\Vision_POC\rf-detr\models\exported\rfdetr_nano_coco.onnx"),
]


@dataclass
class Detection:
    label: str
    cid: int
    conf: float
    x1: int
    y1: int
    x2: int
    y2: int

    @property
    def width(self):
        return self.x2 - self.x1

    @property
    def height(self):
        return self.y2 - self.y1


def default_threads():
    env = os.environ.get("BUDDYBOX_ORT_THREADS")
    if env and env.isdigit():
        return int(env)
    return max(1, (os.cpu_count() or 2) // 2)


def find_default_model():
    env = os.environ.get("BUDDYBOX_MODEL")
    if env and Path(env).exists():
        return Path(env)
    for p in MODEL_CANDIDATES:
        if p.exists():
            return p
    return None


def load_classes(model_path, spec=None):
    if spec:
        p = Path(spec)
        if p.suffix == ".json" and p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else data.get("classes", [])
        return [c.strip() for c in spec.split(",") if c.strip()]
    model_path = Path(model_path)
    sidecar = model_path.parent / f"{model_path.stem}.classes.json"
    if sidecar.exists():
        data = json.loads(sidecar.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else data.get("classes", [])
    return []


def decode_rfdetr(boxes, logits, classes, threshold, width, height):
    scores = 1.0 / (1.0 + np.exp(-np.asarray(logits, dtype=np.float32)))
    n = len(classes)
    if n and scores.shape[1] >= n:
        scores = scores[:, :n]
    cls = scores.argmax(axis=1)
    conf = scores[np.arange(len(scores)), cls]
    keep = conf >= threshold
    if not keep.any():
        return []
    boxes = np.asarray(boxes, dtype=np.float32)
    cx, cy, bw, bh = boxes[keep].T
    x1 = (cx - bw / 2) * width
    y1 = (cy - bh / 2) * height
    x2 = (cx + bw / 2) * width
    y2 = (cy + bh / 2) * height
    out = []
    for i, idx in enumerate(np.where(keep)[0]):
        cid = int(cls[idx])
        label = classes[cid] if cid < len(classes) else str(cid)
        out.append(Detection(label, cid, float(conf[idx]),
                             int(x1[i]), int(y1[i]), int(x2[i]), int(y2[i])))
    out.sort(key=lambda d: -d.conf)
    return out


class OnnxDetector:
    name = "rf-detr"

    def __init__(self, model_path, classes=None, provider="cpu", threads=None, spin=True):
        import onnxruntime as ort

        wanted = ["CPUExecutionProvider"]
        if provider == "cuda":
            wanted = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        elif provider == "tensorrt":
            wanted = ["TensorrtExecutionProvider", "CUDAExecutionProvider", "CPUExecutionProvider"]
        if threads is None:
            threads = default_threads()
        opts = ort.SessionOptions()
        if threads:
            opts.intra_op_num_threads = int(threads)
        if not spin:
            opts.add_session_config_entry("session.intra_op.allow_spinning", "0")
        self.model_path = Path(model_path)
        self.sess = ort.InferenceSession(str(self.model_path), opts, providers=wanted)
        self.threads = threads
        self.spin = spin
        self.provider = self.sess.get_providers()[0].replace("ExecutionProvider", "")
        shape = self.sess.get_inputs()[0].shape
        self.in_h = shape[2] if isinstance(shape[2], int) else 560
        self.in_w = shape[3] if isinstance(shape[3], int) else 560
        self.input_name = self.sess.get_inputs()[0].name
        self.classes = classes if classes is not None else load_classes(self.model_path)

    def warmup(self):
        blank = np.zeros((self.in_h, self.in_w, 3), dtype=np.uint8)
        self(blank, 1.0)

    def __call__(self, frame, threshold):
        import cv2

        H, W = frame.shape[:2]
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        small = cv2.resize(rgb, (self.in_w, self.in_h), interpolation=cv2.INTER_LINEAR)
        x = small.astype(np.float32) / 255.0
        x = (x - MEAN) / STD
        x = np.ascontiguousarray(x.transpose(2, 0, 1)[None])
        outputs = self.sess.run(None, {self.input_name: x})
        return decode_rfdetr(outputs[0][0], outputs[1][0], self.classes, threshold, W, H)


class HogDetector:
    name = "hog"
    provider = "CPU"
    classes = ["person"]

    def __init__(self, work_width=640):
        import cv2

        self.hog = cv2.HOGDescriptor()
        self.hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
        self.work_width = work_width

    def warmup(self):
        pass

    def __call__(self, frame, threshold):
        import cv2

        H, W = frame.shape[:2]
        scale = min(1.0, self.work_width / float(W))
        small = cv2.resize(frame, (int(W * scale), int(H * scale))) if scale < 1.0 else frame
        rects, weights = self.hog.detectMultiScale(small, winStride=(8, 8), padding=(8, 8), scale=1.05)
        out = []
        for (x, y, w, h), wgt in zip(rects, np.asarray(weights).reshape(-1)):
            conf = float(min(1.0, wgt / 2.0))
            if conf < threshold:
                continue
            out.append(Detection("person", 1, conf,
                                 int(x / scale), int(y / scale), int((x + w) / scale), int((y + h) / scale)))
        out.sort(key=lambda d: -d.conf)
        return out


def persons(dets, label="person"):
    return [d for d in dets if d.label == label]
