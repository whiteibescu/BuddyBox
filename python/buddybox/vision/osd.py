"""Betaflight OSD 텍스트 판독 — Walksnail 영상에 그려진 OSD 숫자를 PC에서 읽는다.

비행 중 FC→PC 다운링크가 없을 때, 이미 캡처하고 있는 VRX 영상의 OSD 요소를 OCR 해서
레인지파인더 거리·옵티컬 플로우 값을 얻는다 (추가 하드웨어 없음, 지연 = 영상 지연).

Betaflight 2026.6.2 OSD 요소 (osd_elements.c):
    OSD_LIDAR_DIST  "RF:%3d"                 rangefinderGetLatestAltitude() cm, 무효 = "RF:---"
    OSD_DEBUG2      "D2  %5d %5d %5d %5d"    debug[4..7]  (debug_mode = OPTICALFLOW:
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
D2_LEN = 4 + 5 + 3 * 6           # "D2  %5d %5d %5d %5d" (D2 뒤 공백 2칸, 27자)
DEFAULT_RF = OsdElement("rf", 1, 18, RF_LEN, r"RF:\s*(-{3}|-?\d{1,3})")
DEFAULT_D2 = OsdElement("d2", 10, 18, D2_LEN, r"D2\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)")

RF_FMT = "RF:{:3d}"
D2_FMT = "D2  {:5d} {:5d} {:5d} {:5d}"


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

_OUTLINE_KERNEL = np.ones((19, 19), np.uint8)   # 외곽선에서 9px 이내 (Walksnail 1080p 획 두께 8~12px)


def text_mask(bgr, min_gray=170, max_sat=80, outline_gray=80):
    """OSD 흰 글자 마스크.

    흰색(밝고 채도 낮음)이면서 **검은 외곽선 근처**인 픽셀만 남긴다 — OSD 글자는 항상 검은 테두리를
    갖지만 흰 벽·하늘은 그렇지 않아, 밝은 배경 위에서도 글자만 분리된다.
    """
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    sat = bgr.max(axis=2).astype(np.int16) - bgr.min(axis=2).astype(np.int16)
    white = ((gray >= min_gray) & (sat <= max_sat)).astype(np.uint8)
    near_dark = cv2.dilate((gray <= outline_gray).astype(np.uint8), _OUTLINE_KERNEL)
    return white & near_dark


CELL_MARGIN = 0.3        # 셀 좌우로 더 보는 비율 (격자 오차·글자 밀림 흡수)
CELL_V_CORE = 0.82       # 셀 세로 중 글자로 보는 비율 — 아래쪽은 Walksnail 자체 상태 표시가 침범함
MIN_GLYPH_PX = 0.01      # 셀 면적 대비 최소 잉크 (이보다 작으면 공백)


def _ink_runs(profile):
    runs, start = [], None
    for i, on in enumerate(profile):
        if on and start is None:
            start = i
        elif not on and start is not None:
            runs.append((start, i))
            start = None
    if start is not None:
        runs.append((start, len(profile)))
    return runs


def glyph_from_cell(mask, box, margin=CELL_MARGIN):
    """셀 상자(+여유)에서 글자 하나를 찾아 **경계상자 기준으로 정규화**한 템플릿 이미지를 돌려준다.

    반환: (glyph (TEMPLATE_H, TEMPLATE_W) float32, ink, center_x)
      ink      = 글자 픽셀 수 / 셀 면적 (0 = 공백)
      center_x = 글자 중심의 프레임 x 좌표 (격자 피치 추정용), 공백이면 None
    글자 위치가 셀 안에서 몇 px 밀려도 같은 결과가 나오도록 한다.
    """
    x, y, w, h = box
    H, W = mask.shape[:2]
    mx = int(round(w * margin))
    cx0, cx1 = max(0, x - mx), min(W, x + w + mx)
    cy0, cy1 = max(0, y), min(H, y + int(round(h * CELL_V_CORE)))
    blank = np.zeros((TEMPLATE_H, TEMPLATE_W), np.float32)
    if cx1 <= cx0 or cy1 <= cy0:
        return blank, 0.0, None
    crop = mask[cy0:cy1, cx0:cx1]
    col_ink = crop.sum(axis=0)
    runs = _ink_runs(col_ink > 0)
    # 글자 사이 1~2px 끊김은 이어 붙인다
    merged = []
    for r in runs:
        if merged and r[0] - merged[-1][1] <= 2:
            merged[-1] = (merged[-1][0], r[1])
        else:
            merged.append(r)
    core0, core1 = x - cx0, x - cx0 + w          # 원래 셀 구간 (크롭 좌표)
    best, best_ov = None, 0
    for r0, r1 in merged:
        center = (r0 + r1) / 2.0
        if not (core0 - 2 <= center < core1 + 2):
            continue                              # 중심이 셀 밖이면 이웃 글자의 침범
        ov = min(r1, core1) - max(r0, core0)
        if ov > best_ov:
            best, best_ov = (r0, r1), ov
    if best is None:
        return blank, 0.0, None
    r0, r1 = best
    sub = crop[:, r0:r1]
    rows = np.where(sub.sum(axis=1) > 0)[0]
    if rows.size == 0:
        return blank, 0.0, None
    ink_px = int(sub.sum())
    ink = ink_px / float(w * h)
    if ink < MIN_GLYPH_PX:
        return blank, ink, None
    g = sub[rows.min():rows.max() + 1].astype(np.float32)
    gh, gw = g.shape
    # 종횡비 유지해 템플릿 캔버스 중앙에 배치
    scale = min(TEMPLATE_W / gw, TEMPLATE_H / gh)
    nw, nh = max(1, int(round(gw * scale))), max(1, int(round(gh * scale)))
    g = cv2.resize(g, (nw, nh), interpolation=cv2.INTER_AREA)
    out = blank.copy()
    ox, oy = (TEMPLATE_W - nw) // 2, (TEMPLATE_H - nh) // 2
    out[oy:oy + nh, ox:ox + nw] = g
    return out, ink, cx0 + (r0 + r1) / 2.0


def element_glyphs(mask, grid, elem):
    """요소의 각 셀 → (glyph, ink, center_x) 목록."""
    H, W = mask.shape[:2]
    return [glyph_from_cell(mask, grid.cell_box(elem.col + i, elem.row, W, H)) for i in range(elem.length)]


def element_cells(mask, grid, elem):
    """요소의 각 셀 → 정규화된 글리프 이미지 목록 (공백은 0 이미지)."""
    return [g for g, _, _ in element_glyphs(mask, grid, elem)]


# ---- 글리프 템플릿 ----

@dataclass
class GlyphBook:
    templates: dict = field(default_factory=dict)   # char → (H, W) float32 [0,1]
    counts: dict = field(default_factory=dict)
    grid: OsdGrid = field(default_factory=OsdGrid)
    rf: OsdElement = field(default_factory=lambda: OsdElement(**DEFAULT_RF.__dict__))
    d2: OsdElement = field(default_factory=lambda: OsdElement(**DEFAULT_D2.__dict__))
    blank_ink: float = 0.006      # 셀 잉크 비율이 이보다 작으면 공백 ('-' 는 약 0.02~0.03)
    min_score: float = 0.55

    def set_positions(self, rf_pos=None, d2_pos=None):
        """(col, row) 로 요소 위치를 바꾼다 (Betaflight 의 osd_*_pos 와 같은 칸)."""
        if rf_pos is not None:
            self.rf.col, self.rf.row = int(rf_pos[0]), int(rf_pos[1])
        if d2_pos is not None:
            self.d2.col, self.d2.row = int(d2_pos[0]), int(d2_pos[1])
        return self

    def learn(self, cell, ch):
        if ch == " ":
            return
        n = self.counts.get(ch, 0)
        t = self.templates.get(ch)
        self.templates[ch] = cell.copy() if t is None else (t * n + cell) / (n + 1)
        self.counts[ch] = n + 1

    def classify(self, cell):
        """→ (char, score). 잉크가 없으면(공백 글리프) ' '. 템플릿과 상관이 낮으면 '?'."""
        if float(cell.max()) <= 0.0 or float(cell.mean()) < self.blank_ink:
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
            "rf_pos": [self.rf.col, self.rf.row],
            "d2_pos": [self.d2.col, self.d2.row],
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
        book.set_positions(d.get("rf_pos"), d.get("d2_pos"))
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
    def __init__(self, book, rf=None, d2=None):
        self.book = book
        self.rf = rf or book.rf
        self.d2 = d2 or book.d2

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


def estimate_grid(mask, grid, elems=(DEFAULT_RF, DEFAULT_D2), min_points=6):
    """글자 중심 x 를 열 번호에 회귀시켜 실제 셀 피치·원점을 추정한다.

    여러 프레임의 마스크를 누적하려면 (x, col) 점을 모아 fit_grid_points 를 직접 쓴다.
    반환: (OsdGrid, points_used, rms_px). 점이 부족하면 입력 격자를 그대로 돌려준다.
    """
    H, W = mask.shape[:2]
    pts = grid_points(mask, grid, elems)
    return fit_grid_points(pts, grid.resolved(W, H), min_points)


def grid_points(mask, grid, elems=(DEFAULT_RF, DEFAULT_D2)):
    """(col, center_x) 점 목록 — 글자가 있는 셀만."""
    pts = []
    for elem in elems:
        for i, (_, ink, cx) in enumerate(element_glyphs(mask, grid, elem)):
            if cx is not None:
                pts.append((elem.col + i, cx))
    return pts


def fit_grid_points(pts, base, min_points=6):
    if len(pts) < min_points:
        return base, len(pts), None
    cols = np.array([c for c, _ in pts], np.float64)
    xs = np.array([x for _, x in pts], np.float64)
    pitch, icpt = np.polyfit(cols, xs, 1)           # x_center = x0 + (col + 0.5) * pitch
    if not (0.7 * base.cell_w <= pitch <= 1.3 * base.cell_w):
        return base, len(pts), None
    x0 = icpt - 0.5 * pitch
    resid = xs - (icpt + pitch * cols)
    rms = float(np.sqrt(np.mean(resid ** 2)))
    return OsdGrid(base.cols, base.rows, float(x0), base.y0, float(pitch), base.cell_h), len(pts), rms
