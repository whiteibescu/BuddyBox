"""Betaflight OSD 텍스트 판독 — Walksnail 영상에 그려진 OSD 숫자를 PC에서 읽는다.

비행 중 FC→PC 다운링크가 없을 때, 이미 캡처하고 있는 VRX 영상의 OSD 요소를 OCR 해서
레인지파인더 거리·옵티컬 플로우 값을 얻는다 (추가 하드웨어 없음, 지연 = 영상 지연).

Betaflight 2026.6.2 OSD 요소 (osd_elements.c):
    OSD_LIDAR_DIST  "RF:%3d"                 rangefinderGetLatestAltitude() cm, 무효 = "RF:---"
    OSD_DEBUG2      "D2 %5d %5d %5d %5d"     debug[4..7]  (debug_mode = OPTICALFLOW:
                                             [4],[5] 회전 제거 플로우 X,Y  [6],[7] 필터링 X,Y, 0.001 rad/s)

HD 캔버스는 53×20 셀. 기본 격자는 프레임 전체를 53×20 으로 등분한 것이며, VRX 출력이
레터박스/오프셋을 갖는 경우 `OsdGrid(x0, y0, cell_w, cell_h)` 로 보정한다 (tools/osd_calibrate.py).

글리프(문자) 템플릿은 벤치에서 MSP 실측값을 정답으로 삼아 학습한다 — 폰트 팩과 무관.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

HD_COLS = 53
HD_ROWS = 20
TEMPLATE_W = 16
TEMPLATE_H = 24

# ---- Betaflight OSD 위치값 인코딩 (osd.h) ----
OSD_POSITION_BITS = 5
OSD_POSITION_XY_MASK = (1 << OSD_POSITION_BITS) - 1
OSD_POSITION_BIT_XHD = 10
OSD_PROFILE_BITS_POS = 11
OSD_TYPE_MASK = 0xC000


def osd_pos(x, y, profiles=(1,), elem_type=0):
    """(col, row) → `set osd_*_pos` 값. HD 캔버스(x ≥ 32)는 XHD 비트를 쓴다."""
    v = (x & OSD_POSITION_XY_MASK) | ((y & OSD_POSITION_XY_MASK) << OSD_POSITION_BITS)
    if x & 32:
        v |= 1 << OSD_POSITION_BIT_XHD
    for p in profiles:
        v |= 1 << (p - 1 + OSD_PROFILE_BITS_POS)
    v |= (elem_type & 3) << 14
    return v


def decode_pos(value):
    x = value & OSD_POSITION_XY_MASK
    if value & (1 << OSD_POSITION_BIT_XHD):
        x |= 32
    y = (value >> OSD_POSITION_BITS) & OSD_POSITION_XY_MASK
    profiles = tuple(p for p in (1, 2, 3) if value & (1 << (p - 1 + OSD_PROFILE_BITS_POS)))
    return x, y, profiles, (value & OSD_TYPE_MASK) >> 14


# ---- 요소 정의 ----

@dataclass
class OsdElement:
    name: str
    col: int
    row: int
    length: int          # 문자 수 (고정 포맷)
    pattern: str         # 정규식


RF_LEN = 6                       # "RF:%3d"
D2_LEN = 2 + 4 * 6               # "D2 %5d %5d %5d %5d"
DEFAULT_RF = OsdElement("rf", 1, 18, RF_LEN, r"RF:\s*(-{3}|-?\d{1,3})")
DEFAULT_D2 = OsdElement("d2", 10, 18, D2_LEN, r"D2\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)")

RF_FMT = "RF:{:3d}"
D2_FMT = "D2 {:5d} {:5d} {:5d} {:5d}"


def rf_text(cm):
    return "RF:---" if cm is None or cm <= 0 else RF_FMT.format(int(cm))


def d2_text(debug):
    d = list(debug) + [0] * 8
    return D2_FMT.format(int(d[4]), int(d[5]), int(d[6]), int(d[7]))


def parse_rf(text):
    """'RF: 88' → 0.88 (m), 'RF:---' → None, 판독 실패 → KeyError 대신 ValueError."""
    m = re.search(DEFAULT_RF.pattern, text)
    if not m:
        raise ValueError(f"RF 판독 실패: {text!r}")
    v = m.group(1)
    if v == "---":
        return None
    cm = int(v)
    return None if cm < 0 else cm / 100.0


def parse_d2(text):
    m = re.search(DEFAULT_D2.pattern, text)
    if not m:
        raise ValueError(f"D2 판독 실패: {text!r}")
    return [int(m.group(i)) for i in range(1, 5)]


# ---- 격자 ----

@dataclass
class OsdGrid:
    cols: int = HD_COLS
    rows: int = HD_ROWS
    x0: float = 0.0           # 셀 (0,0) 좌상단 픽셀 (프레임 기준)
    y0: float = 0.0
    cell_w: float = 0.0       # 0 = 프레임 폭 / cols
    cell_h: float = 0.0

    def resolved(self, frame_w, frame_h):
        cw = self.cell_w or frame_w / self.cols
        ch = self.cell_h or frame_h / self.rows
        return OsdGrid(self.cols, self.rows, self.x0, self.y0, cw, ch)

    def cell_box(self, col, row, frame_w, frame_h):
        g = self.resolved(frame_w, frame_h)
        x = int(round(g.x0 + col * g.cell_w))
        y = int(round(g.y0 + row * g.cell_h))
        return x, y, int(round(g.cell_w)), int(round(g.cell_h))

    def to_dict(self):
        return {"cols": self.cols, "rows": self.rows, "x0": self.x0, "y0": self.y0,
                "cell_w": self.cell_w, "cell_h": self.cell_h}

    @classmethod
    def from_dict(cls, d):
        return cls(**{k: d[k] for k in ("cols", "rows", "x0", "y0", "cell_w", "cell_h") if k in d})


# ---- 이진화 / 셀 추출 ----

_OUTLINE_KERNEL = np.ones((7, 7), np.uint8)


def text_mask(bgr, min_gray=190, max_sat=70, outline_gray=70):
    """OSD 흰 글자 마스크.

    흰색(밝고 채도 낮음)이면서 **검은 외곽선 근처**인 픽셀만 남긴다 — OSD 글자는 항상 검은 테두리를
    갖지만 흰 벽·하늘은 그렇지 않아, 밝은 배경 위에서도 글자만 분리된다.
    """
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    sat = bgr.max(axis=2).astype(np.int16) - bgr.min(axis=2).astype(np.int16)
    white = ((gray >= min_gray) & (sat <= max_sat)).astype(np.uint8)
    near_dark = cv2.dilate((gray <= outline_gray).astype(np.uint8), _OUTLINE_KERNEL)
    return white & near_dark


def cell_crop(mask, box):
    x, y, w, h = box
    H, W = mask.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(W, x + w), min(H, y + h)
    if x1 <= x0 or y1 <= y0:
        return np.zeros((TEMPLATE_H, TEMPLATE_W), np.float32)
    crop = mask[y0:y1, x0:x1]
    return cv2.resize(crop.astype(np.float32), (TEMPLATE_W, TEMPLATE_H), interpolation=cv2.INTER_AREA)


def element_cells(mask, grid, elem):
    H, W = mask.shape[:2]
    return [cell_crop(mask, grid.cell_box(elem.col + i, elem.row, W, H)) for i in range(elem.length)]


# ---- 글리프 템플릿 ----

@dataclass
class GlyphBook:
    templates: dict = field(default_factory=dict)   # char → (H, W) float32 [0,1]
    counts: dict = field(default_factory=dict)
    grid: OsdGrid = field(default_factory=OsdGrid)
    blank_ink: float = 0.006      # 셀 잉크 비율이 이보다 작으면 공백 ('-' 는 약 0.02~0.03)
    min_score: float = 0.55

    def learn(self, cell, ch):
        if ch == " ":
            return
        n = self.counts.get(ch, 0)
        t = self.templates.get(ch)
        self.templates[ch] = cell.copy() if t is None else (t * n + cell) / (n + 1)
        self.counts[ch] = n + 1

    def classify(self, cell):
        """→ (char, score). 잉크가 거의 없으면 ' '. 템플릿과 상관이 낮으면 '?'."""
        if float(cell.mean()) < self.blank_ink:
            return " ", 1.0
        best, best_s = "?", -1.0
        a = cell - cell.mean()
        na = float(np.linalg.norm(a)) + 1e-6
        for ch, t in self.templates.items():
            b = t - t.mean()
            s = float((a * b).sum()) / (na * (float(np.linalg.norm(b)) + 1e-6))
            if s > best_s:
                best, best_s = ch, s
        if best_s < self.min_score:
            return "?", best_s
        return best, best_s

    def read(self, cells):
        chars, scores = [], []
        for c in cells:
            ch, s = self.classify(c)
            chars.append(ch)
            scores.append(s)
        return "".join(chars), (min(scores) if scores else 0.0)

    def save(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "template_size": [TEMPLATE_W, TEMPLATE_H],
            "grid": self.grid.to_dict(),
            "blank_ink": self.blank_ink,
            "min_score": self.min_score,
            "counts": self.counts,
            "templates": {ch: np.round(t, 3).tolist() for ch, t in self.templates.items()},
        }
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return path

    @classmethod
    def load(cls, path):
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        book = cls(grid=OsdGrid.from_dict(d.get("grid", {})),
                   blank_ink=d.get("blank_ink", 0.006), min_score=d.get("min_score", 0.55))
        book.counts = dict(d.get("counts", {}))
        book.templates = {ch: np.asarray(t, np.float32) for ch, t in d.get("templates", {}).items()}
        return book

    def preview(self, scale=4):
        """템플릿을 한 줄로 이어 붙인 미리보기 이미지 (디버깅)."""
        if not self.templates:
            return None
        tiles = [cv2.resize((t * 255).astype(np.uint8), (TEMPLATE_W * scale, TEMPLATE_H * scale),
                            interpolation=cv2.INTER_NEAREST) for _, t in sorted(self.templates.items())]
        return np.hstack(tiles)


# ---- 판독기 ----

@dataclass
class OsdReading:
    rf_text: str = ""
    d2_text: str = ""
    rf_score: float = 0.0
    d2_score: float = 0.0
    alt_m: object = None
    debug: list = field(default_factory=list)
    ok: bool = False
    error: str = ""


class OsdReader:
    def __init__(self, book, rf=DEFAULT_RF, d2=DEFAULT_D2):
        self.book = book
        self.rf = rf
        self.d2 = d2

    @property
    def grid(self):
        return self.book.grid

    def read(self, frame):
        mask = text_mask(frame)
        r = OsdReading()
        r.rf_text, r.rf_score = self.book.read(element_cells(mask, self.grid, self.rf))
        r.d2_text, r.d2_score = self.book.read(element_cells(mask, self.grid, self.d2))
        try:
            r.alt_m = parse_rf(r.rf_text)
            d = parse_d2(r.d2_text)
            r.debug = [0, 0, 0, 0] + d
            r.ok = True
        except ValueError as exc:
            r.error = str(exc)
        return r

    def draw(self, frame, reading=None, color=(0, 255, 255)):
        """격자 셀 박스를 그린다 (정렬 확인용)."""
        H, W = frame.shape[:2]
        for elem in (self.rf, self.d2):
            for i in range(elem.length):
                x, y, w, h = self.grid.cell_box(elem.col + i, elem.row, W, H)
                cv2.rectangle(frame, (x, y), (x + w, y + h), color, 1)
        if reading is not None:
            txt = f"OSD {reading.rf_text!r} {reading.d2_text!r}  {'OK' if reading.ok else reading.error}"
            cv2.putText(frame, txt, (12, H - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 3, cv2.LINE_AA)
            cv2.putText(frame, txt, (12, H - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 1, cv2.LINE_AA)
        return frame


def fit_grid(mask, grid, elem=DEFAULT_RF, shifts=(-0.5, 0.5, 0.05), scales=(0.9, 1.1, 0.01)):
    """RF 요소의 라벨('RF:')이 항상 있다는 점을 이용해 격자 원점·배율을 미세 조정한다.

    후보 격자마다 라벨 3셀 안의 잉크 비율에서 셀 경계 띠의 잉크를 뺀 점수를 매겨 최댓값을 고른다.
    """
    H, W = mask.shape[:2]
    base = grid.resolved(W, H)
    best, best_s = base, -1.0
    sx0, sx1, sstep = shifts
    sc0, sc1, scstep = scales
    for dx in np.arange(sx0, sx1 + 1e-9, sstep):
        for sc in np.arange(sc0, sc1 + 1e-9, scstep):
            g = OsdGrid(base.cols, base.rows, base.x0 + dx * base.cell_w, base.y0,
                        base.cell_w * sc, base.cell_h)
            score = 0.0
            for i in range(3):
                x, y, w, h = g.cell_box(elem.col + i, elem.row, W, H)
                inner = mask[y:y + h, x + 2:x + w - 2]
                edge = np.concatenate([mask[y:y + h, max(0, x - 1):x + 1].ravel(),
                                       mask[y:y + h, x + w - 1:x + w + 1].ravel()])
                if inner.size == 0:
                    continue
                score += float(inner.mean()) - 2.0 * (float(edge.mean()) if edge.size else 0.0)
            if score > best_s:
                best, best_s = g, score
    return best, best_s
