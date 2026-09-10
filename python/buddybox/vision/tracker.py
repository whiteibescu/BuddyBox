from dataclasses import dataclass


@dataclass
class Track:
    cx: float
    cy: float
    w: float
    h: float
    conf: float
    age: float
    lost: bool
    frames: int = 0


def iou(a, b):
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    iw = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    ih = max(0.0, min(ay2, by2) - max(ay1, by1))
    inter = iw * ih
    if inter <= 0.0:
        return 0.0
    union = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - inter
    return inter / union if union > 0 else 0.0


def _center(box):
    x1, y1, x2, y2 = box
    return (x1 + x2) / 2.0, (y1 + y2) / 2.0, x2 - x1, y2 - y1


class TargetTracker:
    def __init__(self, smoothing=0.5, max_jump=0.35, lost_after_s=0.6, drop_after_s=2.5,
                 min_height=0.03, auto_acquire=True):
        self.smoothing = smoothing
        self.max_jump = max_jump
        self.lost_after_s = lost_after_s
        self.drop_after_s = drop_after_s
        self.min_height = min_height
        self.auto_acquire = auto_acquire
        self._box = None
        self._conf = 0.0
        self._last_seen = None
        self._frames = 0
        self._pending_click = None

    @property
    def has_target(self):
        return self._box is not None

    def clear(self):
        self._box = None
        self._conf = 0.0
        self._last_seen = None
        self._frames = 0

    def select_at(self, x, y):
        self._pending_click = (x, y)

    def _to_track(self, now):
        if self._box is None:
            return None
        age = 0.0 if self._last_seen is None else max(0.0, now - self._last_seen)
        if age > self.drop_after_s:
            self.clear()
            return None
        cx, cy, w, h = _center(self._box)
        return Track(cx, cy, w, h, self._conf, age, age > self.lost_after_s, self._frames)

    def peek(self, now):
        return self._to_track(now)

    def update(self, boxes, now):
        cands = [b for b in boxes if (b[4] - b[2]) >= self.min_height]
        if self._pending_click is not None:
            px, py = self._pending_click
            self._pending_click = None
            hits = [b for b in cands if b[1] <= px <= b[3] and b[2] <= py <= b[4]]
            if hits:
                hits.sort(key=lambda b: (b[3] - b[1]) * (b[4] - b[2]))
                self._assign(hits[0], now, fresh=True)
                return self._to_track(now)

        if self._box is None:
            if cands and self.auto_acquire:
                best = max(cands, key=lambda b: b[4] - b[2])
                self._assign(best, now, fresh=True)
            return self._to_track(now)

        match = self._match(cands)
        if match is not None:
            self._assign(match, now, fresh=False)
        return self._to_track(now)

    def _match(self, cands):
        if not cands:
            return None
        cx, cy, _, _ = _center(self._box)
        best, best_key = None, None
        for b in cands:
            bx, by, _, _ = _center(b[1:5])
            dist = ((bx - cx) ** 2 + (by - cy) ** 2) ** 0.5
            if dist > self.max_jump:
                continue
            key = (-iou(self._box, b[1:5]), dist)
            if best_key is None or key < best_key:
                best, best_key = b, key
        return best

    def _assign(self, det, now, fresh):
        conf, x1, y1, x2, y2 = det[:5]
        if fresh or self._box is None:
            self._box = (x1, y1, x2, y2)
            self._frames = 1
        else:
            a = self.smoothing
            ox1, oy1, ox2, oy2 = self._box
            self._box = (
                ox1 + (x1 - ox1) * a,
                oy1 + (y1 - oy1) * a,
                ox2 + (x2 - ox2) * a,
                oy2 + (y2 - oy2) * a,
            )
            self._frames += 1
        self._conf = conf
        self._last_seen = now
