"""BuddyBox Person Follow — Qt(PySide6) 대시보드 UI.

레이아웃은 지상관제(GCS)/비전 툴의 정석 구성을 따른다.

  ┌ 툴바: 카메라·프리셋·연결 | 백엔드·연결 | 검출기 ─────────────────────┐
  │ ┌──────────────────────────────┐ ┌ 비행 제어 (dock) ──────────────┐ │
  │ │                              │ │  [STANDBY][HOVER][FOLLOW]      │ │
  │ │        영상 뷰 (중앙)         │ │  ARM ─ CH ─ 상태 / 긴급 정지     │ │
  │ │   클릭=타깃 / 우클릭=해제      │ │  모드·상태 대형 표시, 텔레메트리  │ │
  │ │                              │ ├ 튜닝 (dock) ───────────────────┤ │
  │ │                              │ │  [트림/고도][PID][도구] 탭       │ │
  │ └──────────────────────────────┘ └────────────────────────────────┘ │
  │ ┌ 로그 (dock, 하단) ────────────────────────────────────────────────┐ │
  └ 상태바: 메시지 · 검출기 · 영상 · REC ───────────────────────────────┘

파이프라인/설정/인자 파싱은 tkinter 버전(person_follow.py)과 공유한다.
"""

import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from threading import Thread

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

for _s in (sys.stdout, sys.stderr):
    if _s is not None and hasattr(_s, "reconfigure"):
        _s.reconfigure(errors="replace")

if sys.platform == "win32" and not getattr(sys, "frozen", False):
    # Qt 6.11+ 는 Windows 시스템 ICU(System32\icuuc.dll)를 쓰는데, conda/miniforge 는 자체 ICU
    # (Library\bin\icuuc.dll, 버전 접미사 심볼)를 DLL 검색 경로에 넣어 "지정된 프로시저를 찾을 수
    # 없습니다" 로 QtCore 임포트가 깨진다. 시스템 ICU 를 먼저 올려 두면 이름 해석이 그쪽으로 붙는다.
    import ctypes

    for _dll in ("icuuc.dll", "icuin.dll"):
        _p = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", _dll)
        if os.path.exists(_p):
            try:
                ctypes.CDLL(_p)
            except OSError:
                pass

import cv2
from PySide6.QtCore import QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QAction, QColor, QFont, QImage, QKeySequence, QPainter, QPalette,
                           QShortcut)
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QComboBox, QDockWidget,
                               QDoubleSpinBox, QFileDialog, QFormLayout, QFrame, QGridLayout,
                               QGroupBox, QHBoxLayout, QLabel, QMainWindow, QPlainTextEdit,
                               QPushButton, QScrollArea, QSizePolicy, QSlider, QSpinBox,
                               QStatusBar, QTabWidget, QToolBar, QVBoxLayout, QWidget)

from buddybox import find_promicro_port
from buddybox.follow.controller import FollowConfig
from buddybox.follow.overlay import draw_overlay
from buddybox.follow.pipeline import FollowPipeline
from buddybox.follow.state import Mode
from buddybox.vision.capture import (PRESETS, VIDEO_SUFFIXES, VRX_DEVICE_NAME, device_names,
                                     open_source, probe_devices)
from person_follow import (AUTO_SESSION_LABELS, COMBOS, FROZEN, PID_TAB, REPORT_TOOL, TOGGLES,
                           TRIM_TAB, make_arm_verifier, make_backend, make_detector, parse_args,
                           serial_ports)

# ── 테마 ──────────────────────────────────────────────────────────────────────

C_BG = "#1b1e23"
C_BASE = "#12151a"
C_PANEL = "#23272e"
C_BORDER = "#343a44"
C_TEXT = "#e4e6ea"
C_MUTED = "#8d95a3"
C_ACCENT = "#3d8bfd"
C_OK = "#2e9e4f"
C_WARN = "#d08700"
C_DANGER = "#c62828"

MODE_COLORS = {"STANDBY": "#5c6675", "HOVER": "#2f7fd8", "FOLLOW": "#2e9e4f"}
ARM_COLORS = {"ARMED": C_OK, "DISARMED": "#7a8290", "ARM FAILED": C_DANGER,
              "DISARM FAILED": C_DANGER, "ARM?": C_WARN, "DISARM?": C_WARN}

STYLE = f"""
QMainWindow, QDialog {{ background: {C_BG}; }}
QWidget {{ color: {C_TEXT}; font-family: 'Segoe UI', 'Malgun Gothic', sans-serif; font-size: 10pt; }}
QToolBar {{ background: {C_PANEL}; border-bottom: 1px solid {C_BORDER}; spacing: 6px; padding: 4px; }}
QToolBar QLabel {{ color: {C_MUTED}; padding: 0 2px 0 6px; }}
QDockWidget {{ titlebar-close-icon: none; titlebar-normal-icon: none; }}
QDockWidget::title {{ background: {C_PANEL}; padding: 5px 8px; border-bottom: 1px solid {C_BORDER};
                      font-weight: 600; }}
QGroupBox {{ border: 1px solid {C_BORDER}; border-radius: 6px; margin-top: 10px; padding: 8px 6px 6px 6px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {C_MUTED}; }}
QTabWidget::pane {{ border: 1px solid {C_BORDER}; border-radius: 4px; top: -1px; }}
QTabBar::tab {{ background: {C_PANEL}; padding: 6px 14px; border: 1px solid {C_BORDER}; border-bottom: none;
                border-top-left-radius: 4px; border-top-right-radius: 4px; }}
QTabBar::tab:selected {{ background: {C_BG}; color: {C_ACCENT}; font-weight: 600; }}
QScrollArea {{ border: none; }}
QPushButton {{ background: #2c313a; border: 1px solid {C_BORDER}; border-radius: 4px; padding: 5px 10px; }}
QPushButton:hover {{ background: #363c47; }}
QPushButton:pressed {{ background: #1f232a; }}
QPushButton:disabled {{ color: #5f6672; background: #22262d; }}
QPushButton[role="primary"] {{ background: {C_ACCENT}; border-color: {C_ACCENT}; color: white; font-weight: 600; }}
QPushButton[role="primary"]:hover {{ background: #5a9dff; }}
QPushButton[role="danger"] {{ background: {C_DANGER}; border-color: {C_DANGER}; color: white; font-weight: 700;
                              padding: 9px; font-size: 11pt; }}
QPushButton[role="danger"]:hover {{ background: #e53935; }}
QPushButton[role="arm"] {{ font-weight: 700; min-width: 64px; }}
QPushButton[role="arm"][pending="true"] {{ background: {C_WARN}; border-color: {C_WARN}; color: white; }}
QPushButton[role="mode"] {{ padding: 9px 4px; font-weight: 700; font-size: 11pt; }}
QPushButton[role="mode"]:checked {{ background: {C_OK}; border-color: {C_OK}; color: white; }}
QComboBox, QDoubleSpinBox, QSpinBox, QLineEdit {{ background: {C_BASE}; border: 1px solid {C_BORDER};
                                                   border-radius: 4px; padding: 3px 6px; }}
QComboBox QAbstractItemView {{ background: {C_PANEL}; selection-background-color: {C_ACCENT}; }}
QSlider::groove:horizontal {{ height: 4px; background: {C_BORDER}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {C_ACCENT}; border-radius: 2px; }}
QSlider::handle:horizontal {{ width: 14px; height: 14px; margin: -5px 0; border-radius: 7px; background: #dfe3ea; }}
QSlider::handle:horizontal:hover {{ background: white; }}
QCheckBox::indicator {{ width: 15px; height: 15px; }}
QPlainTextEdit {{ background: {C_BASE}; border: none; font-family: Consolas, monospace; font-size: 9pt; }}
QStatusBar {{ background: {C_PANEL}; border-top: 1px solid {C_BORDER}; }}
QStatusBar QLabel {{ padding: 0 8px; color: {C_MUTED}; }}
QLabel[role="hint"] {{ color: {C_MUTED}; font-size: 9pt; }}
QLabel[role="mono"] {{ font-family: Consolas, monospace; font-size: 10pt; }}
QLabel[role="modebig"] {{ color: white; font-size: 16pt; font-weight: 800; padding: 8px; border-radius: 6px; }}
QLabel[role="armstate"] {{ font-weight: 700; font-size: 11pt; }}
QLabel[role="reason"] {{ color: #ef6c6c; font-size: 9pt; }}
"""


def apply_theme(app):
    app.setStyle("Fusion")
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(C_BG))
    pal.setColor(QPalette.WindowText, QColor(C_TEXT))
    pal.setColor(QPalette.Base, QColor(C_BASE))
    pal.setColor(QPalette.AlternateBase, QColor(C_PANEL))
    pal.setColor(QPalette.Text, QColor(C_TEXT))
    pal.setColor(QPalette.Button, QColor(C_PANEL))
    pal.setColor(QPalette.ButtonText, QColor(C_TEXT))
    pal.setColor(QPalette.Highlight, QColor(C_ACCENT))
    pal.setColor(QPalette.HighlightedText, QColor("white"))
    pal.setColor(QPalette.ToolTipBase, QColor(C_PANEL))
    pal.setColor(QPalette.ToolTipText, QColor(C_TEXT))
    pal.setColor(QPalette.PlaceholderText, QColor(C_MUTED))
    pal.setColor(QPalette.Disabled, QPalette.Text, QColor("#5f6672"))
    pal.setColor(QPalette.Disabled, QPalette.ButtonText, QColor("#5f6672"))
    app.setPalette(pal)
    app.setStyleSheet(STYLE)


def repolish(w):
    w.style().unpolish(w)
    w.style().polish(w)
    w.update()


# ── 위젯 ──────────────────────────────────────────────────────────────────────

class VideoView(QWidget):
    """레터박스 맞춤으로 프레임을 그리는 영상 뷰. 클릭 좌표를 0~1 정규화해 내보낸다."""

    clicked = Signal(float, float)
    right_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._image = None
        self._rect = QRectF()
        self.setMinimumSize(320, 180)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setCursor(Qt.CrossCursor)
        self.setFocusPolicy(Qt.StrongFocus)

    def set_frame(self, bgr):
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        h, w = rgb.shape[:2]
        self._image = QImage(rgb.data, w, h, rgb.strides[0], QImage.Format_RGB888).copy()
        self.update()

    def clear(self):
        self._image = None
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#000"))
        if self._image is None:
            p.setPen(QColor(C_MUTED))
            p.setFont(QFont("Segoe UI", 13))
            p.drawText(self.rect(), Qt.AlignCenter, "카메라 미연결\n툴바에서 카메라와 백엔드를 연결하세요")
            return
        iw, ih = self._image.width(), self._image.height()
        x = (self.width() - iw) / 2
        y = (self.height() - ih) / 2
        self._rect = QRectF(x, y, iw, ih)
        p.drawImage(self._rect.topLeft(), self._image)

    def mousePressEvent(self, event):
        self.setFocus()
        if event.button() == Qt.RightButton:
            self.right_clicked.emit()
            return
        if event.button() != Qt.LeftButton or self._image is None or self._rect.isEmpty():
            return
        pos = event.position()
        x = (pos.x() - self._rect.x()) / self._rect.width()
        y = (pos.y() - self._rect.y()) / self._rect.height()
        if 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0:
            self.clicked.emit(x, y)


class ParamRow(QWidget):
    """슬라이더 + 스핀박스가 서로 동기화되는 실수 파라미터 한 줄."""

    changed = Signal(str, float)

    def __init__(self, key, lo, hi, step, parent=None):
        super().__init__(parent)
        self.key, self.lo, self.step = key, lo, step
        self._n = max(1, int(round((hi - lo) / step)))
        self._syncing = False
        decimals = max(0, -int(f"{step:e}".split("e")[1])) if step < 1 else 0
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, self._n)
        self.slider.setFocusPolicy(Qt.NoFocus)
        self.spin = QDoubleSpinBox()
        self.spin.setRange(lo, hi)
        self.spin.setSingleStep(step)
        self.spin.setDecimals(decimals)
        self.spin.setFixedWidth(78)
        self.spin.setAlignment(Qt.AlignRight)
        self.spin.setKeyboardTracking(False)
        lay.addWidget(self.slider, 1)
        lay.addWidget(self.spin)
        self.slider.valueChanged.connect(self._from_slider)
        self.spin.valueChanged.connect(self._from_spin)

    def value(self):
        return float(self.spin.value())

    def set_value(self, v, silent=True):
        self._syncing = silent
        self.spin.setValue(float(v))
        self.slider.setValue(int(round((float(v) - self.lo) / self.step)))
        self._syncing = False

    def _from_slider(self, i):
        if self._syncing:
            return
        v = self.lo + i * self.step
        self._syncing = True
        self.spin.setValue(v)
        self._syncing = False
        self.changed.emit(self.key, self.spin.value())

    def _from_spin(self, v):
        if self._syncing:
            return
        self._syncing = True
        self.slider.setValue(int(round((v - self.lo) / self.step)))
        self._syncing = False
        self.changed.emit(self.key, float(v))


def scroll_tab(inner):
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setWidget(inner)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    return area


def hline():
    f = QFrame()
    f.setFrameShape(QFrame.HLine)
    f.setStyleSheet(f"color: {C_BORDER};")
    return f


# ── 메인 윈도우 ───────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    _camera_ready = Signal(object, object, object)
    _camera_failed = Signal(object)
    _post = Signal(object)  # 작업 스레드 → 메인 스레드 콜백

    def __init__(self, args):
        super().__init__()
        self.args = args
        self.cfg = FollowConfig.load(args.config)
        self.rec_dir = Path(args.rec_dir)
        self.pipeline = None
        self.source = None
        self.backend = None
        self.detector = None
        self._connecting = False
        self._syncing = False
        self._arm_confirm_t = 0.0
        self._last_mode = None
        self._fps_t = time.perf_counter()
        self._fps_n = 0

        self.setWindowTitle("BuddyBox Person Follow")
        self.resize(1480, 860)
        self._build_toolbar()
        self._build_central()
        self._build_control_dock()
        self._build_tuning_dock()
        self._build_log_dock()
        self._build_statusbar()
        self._build_menu()
        self._bind_keys()

        self._camera_ready.connect(self._on_camera_ready)
        self._camera_failed.connect(self._on_camera_failed)
        self._post.connect(lambda fn: fn())

        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.timeout.connect(self._refresh_once)
        self._timer.start(15)

        self._push_cfg_to_ui()
        self._update_panic_label()
        if not args.no_autoconnect:
            QTimer.singleShot(100, self.connect_all)

    # ── 구성 ────────────────────────────────────────────────────────────────

    def _build_toolbar(self):
        tb = QToolBar("연결")
        tb.setMovable(False)
        tb.setIconSize(QSize(16, 16))
        self.addToolBar(Qt.TopToolBarArea, tb)

        names = device_names()
        camera = self.args.camera
        if camera == VRX_DEVICE_NAME and names and not any(camera.lower() in n.lower() for n in names):
            camera = names[0]
        tb.addWidget(QLabel("카메라"))
        self.camera_box = QComboBox()
        self.camera_box.setEditable(True)
        self.camera_box.addItems(names)
        self.camera_box.setCurrentText(camera)
        self.camera_box.setMinimumWidth(230)
        tb.addWidget(self.camera_box)
        self.preset_box = QComboBox()
        self.preset_box.addItems(list(PRESETS))
        self.preset_box.setCurrentText(self.args.preset)
        tb.addWidget(self.preset_box)
        self.cam_btn = QPushButton("카메라 연결")
        self.cam_btn.setProperty("role", "primary")
        self.cam_btn.clicked.connect(self.toggle_camera)
        tb.addWidget(self.cam_btn)
        b = QPushButton("파일…")
        b.clicked.connect(self.pick_file)
        tb.addWidget(b)
        b = QPushButton("탐색")
        b.clicked.connect(self.scan_devices)
        tb.addWidget(b)

        tb.addSeparator()
        port = self.args.port
        if port == "sim":
            real = find_promicro_port()
            if real:
                port = real
        tb.addWidget(QLabel("백엔드"))
        self.port_box = QComboBox()
        self.port_box.setEditable(True)
        self.port_box.addItems(["sim", "sitl", "auto"] + serial_ports())
        self.port_box.setCurrentText(port)
        self.port_box.setMinimumWidth(130)
        tb.addWidget(self.port_box)
        self.backend_btn = QPushButton("백엔드 연결")
        self.backend_btn.setProperty("role", "primary")
        self.backend_btn.clicked.connect(self.toggle_backend)
        tb.addWidget(self.backend_btn)

        tb.addSeparator()
        tb.addWidget(QLabel("검출"))
        self.detector_box = QComboBox()
        self.detector_box.addItems(["사람", "AprilTag"])
        self.detector_box.setCurrentText("AprilTag" if self.args.detector == "aruco" else "사람")
        self.detector_box.currentTextChanged.connect(lambda _t: self._on_detector())
        tb.addWidget(self.detector_box)

    def _build_central(self):
        self.view = VideoView()
        self.view.clicked.connect(self.on_view_click)
        self.view.right_clicked.connect(lambda: self.pipeline and self.pipeline.clear_target())
        wrap = QWidget()
        lay = QVBoxLayout(wrap)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.addWidget(self.view, 1)
        hint = QLabel("클릭=타깃 선택 · 우클릭=해제 · 1/2/3=모드 · Space/Esc=긴급 정지 · "
                      "W/S=호버 스로틀 ±0.01 · R=세션 · P=스냅샷")
        hint.setProperty("role", "hint")
        hint.setAlignment(Qt.AlignCenter)
        lay.addWidget(hint)
        self.setCentralWidget(wrap)

    def _build_control_dock(self):
        panel = QWidget()
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(8)

        self.mode_label = QLabel("STANDBY")
        self.mode_label.setProperty("role", "modebig")
        self.mode_label.setAlignment(Qt.AlignCenter)
        self.mode_label.setStyleSheet(f"background: {MODE_COLORS['STANDBY']};")
        lay.addWidget(self.mode_label)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        self.mode_buttons = {}
        for mode, label in ((Mode.STANDBY, "1  STANDBY"), (Mode.HOVER, "2  HOVER"), (Mode.FOLLOW, "3  FOLLOW")):
            b = QPushButton(label)
            b.setCheckable(True)
            b.setProperty("role", "mode")
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(lambda _c=False, m=mode: self.set_mode(m))
            self.mode_group.addButton(b)
            self.mode_buttons[mode] = b
            row.addWidget(b, 1)
        lay.addLayout(row)

        self.panic_btn = QPushButton("긴급 정지 · DISARM  (Space)")
        self.panic_btn.setProperty("role", "danger")
        self.panic_btn.setFocusPolicy(Qt.NoFocus)
        self.panic_btn.clicked.connect(self.disarm)
        lay.addWidget(self.panic_btn)

        arm = QGroupBox("ARM")
        g = QGridLayout(arm)
        g.setHorizontalSpacing(8)
        self.arm_btn = QPushButton("ARM")
        self.arm_btn.setProperty("role", "arm")
        self.arm_btn.setEnabled(False)
        self.arm_btn.setFocusPolicy(Qt.NoFocus)
        self.arm_btn.clicked.connect(self.arm)
        g.addWidget(self.arm_btn, 0, 0)
        g.addWidget(QLabel("CH"), 0, 1)
        self.arm_ch = QSpinBox()
        self.arm_ch.setRange(1, 8)
        self.arm_ch.setValue(self.args.arm_channel)
        self.arm_ch.setFixedWidth(52)
        self.arm_ch.valueChanged.connect(lambda _v: self._on_arm_channel())
        g.addWidget(self.arm_ch, 0, 2)
        self.arm_status = QLabel("—")
        self.arm_status.setProperty("role", "armstate")
        g.addWidget(self.arm_status, 0, 3)
        g.setColumnStretch(3, 1)
        self.arm_reason = QLabel("")
        self.arm_reason.setProperty("role", "reason")
        self.arm_reason.setWordWrap(True)
        g.addWidget(self.arm_reason, 1, 0, 1, 4)
        lay.addWidget(arm)

        tele = QGroupBox("텔레메트리")
        tl = QVBoxLayout(tele)
        self.status_label = QLabel("—")
        self.status_label.setStyleSheet("font-weight: 700; font-size: 11pt;")
        tl.addWidget(self.status_label)
        self.trim_label = QLabel("")
        self.trim_label.setProperty("role", "mono")
        self.trim_label.setWordWrap(True)
        tl.addWidget(self.trim_label)
        lay.addWidget(tele)
        lay.addStretch(1)

        dock = QDockWidget("비행 제어", self)
        dock.setObjectName("control")
        dock.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable)
        dock.setWidget(panel)
        dock.setMinimumWidth(380)
        self.addDockWidget(Qt.RightDockWidgetArea, dock)
        self.control_dock = dock

    def _build_tuning_dock(self):
        self.params = {}
        self.toggles = {}
        self.combos = {}
        tabs = QTabWidget()
        tabs.setDocumentMode(True)

        # 트림/고도
        trim = QWidget()
        form = QFormLayout(trim)
        form.setContentsMargins(8, 8, 8, 8)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        for key, label, lo, hi, step in TRIM_TAB:
            form.addRow(label, self._param(key, lo, hi, step))
        form.addRow(hline())
        for key, label, values in COMBOS:
            box = QComboBox()
            box.addItems(values)
            box.currentTextChanged.connect(lambda _t, k=key: self._on_tune(k))
            self.combos[key] = box
            form.addRow(label, box)
        form.addRow(hline())
        for key, label in TOGGLES:
            cb = QCheckBox(label)
            cb.toggled.connect(lambda _c, k=key: self._on_tune(k))
            self.toggles[key] = cb
            form.addRow(cb)
        btns = QHBoxLayout()
        b = QPushButton("학습값 → 트림 반영")
        b.clicked.connect(self.adopt_trim)
        btns.addWidget(b, 1)
        b = QPushButton("학습 초기화")
        b.clicked.connect(self.reset_trim)
        btns.addWidget(b, 1)
        form.addRow(btns)
        tabs.addTab(scroll_tab(trim), "트림/고도")

        # PID
        pid = QWidget()
        form = QFormLayout(pid)
        form.setContentsMargins(8, 8, 8, 8)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        groups = (("좌우 (yaw/roll)", "lateral_"), ("거리 (pitch)", "pitch_"), ("고도 (throttle)", "throttle_"))
        done = set()
        for title, prefix in groups:
            box = QGroupBox(title)
            gf = QFormLayout(box)
            gf.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
            gf.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
            for key, label, lo, hi, step in PID_TAB:
                if key.startswith(prefix):
                    gf.addRow(label.split(" ", 1)[-1], self._param(key, lo, hi, step))
                    done.add(key)
            form.addRow(box)
        box = QGroupBox("데드존 · 한계")
        gf = QFormLayout(box)
        gf.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        gf.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        for key, label, lo, hi, step in PID_TAB:
            if key not in done:
                gf.addRow(label, self._param(key, lo, hi, step))
        form.addRow(box)
        tabs.addTab(scroll_tab(pid), "PID")

        # 도구
        tools = QWidget()
        g = QGridLayout(tools)
        g.setContentsMargins(8, 8, 8, 8)
        self.rec_btn = QPushButton("세션 기록 시작 (R)")
        self.rec_btn.clicked.connect(self.toggle_session)
        g.addWidget(self.rec_btn, 0, 0, 1, 2)
        g.addWidget(QLabel("자동 기록"), 1, 0)
        self.auto_session_box = QComboBox()
        self.auto_session_box.addItems(list(AUTO_SESSION_LABELS.values()))
        self.auto_session_box.setCurrentText(AUTO_SESSION_LABELS[self.args.auto_session])
        self.auto_session_box.currentTextChanged.connect(lambda _t: self._on_auto_session())
        g.addWidget(self.auto_session_box, 1, 1)
        for r, (l1, f1, l2, f2) in enumerate((
                ("스냅샷 (P)", self.snapshot, "세션 폴더 열기", self.open_rec_dir),
                ("설정 저장", self.save_config, "설정 불러오기", self.reload_config)), start=2):
            b = QPushButton(l1)
            b.clicked.connect(f1)
            g.addWidget(b, r, 0)
            b = QPushButton(l2)
            b.clicked.connect(f2)
            g.addWidget(b, r, 1)
        self.report_btn = QPushButton("마지막 세션 리포트 생성")
        self.report_btn.clicked.connect(self.make_report)
        g.addWidget(self.report_btn, 4, 0, 1, 2)
        g.setRowStretch(5, 1)
        tabs.addTab(scroll_tab(tools), "도구")

        for p in self.params.values():
            p.changed.connect(self._on_tune)

        dock = QDockWidget("튜닝", self)
        dock.setObjectName("tuning")
        dock.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable)
        dock.setWidget(tabs)
        dock.setMinimumWidth(380)
        self.addDockWidget(Qt.RightDockWidgetArea, dock)
        self.tuning_dock = dock

    def _build_log_dock(self):
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(500)
        dock = QDockWidget("로그", self)
        dock.setObjectName("log")
        dock.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable
                         | QDockWidget.DockWidgetClosable)
        dock.setWidget(self.log)
        self.addDockWidget(Qt.BottomDockWidgetArea, dock)
        self.resizeDocks([dock], [130], Qt.Vertical)
        self.log_dock = dock

    def _build_statusbar(self):
        sb = QStatusBar()
        self.setStatusBar(sb)
        self.det_label = QLabel("검출기: —")
        self.video_label = QLabel("영상: —")
        self.fps_label = QLabel("UI 0 fps")
        self.rec_label = QLabel("")
        self.rec_label.setStyleSheet("color: #ff5252; font-weight: 700;")
        for w in (self.det_label, self.video_label, self.fps_label, self.rec_label):
            sb.addPermanentWidget(w)

    def _build_menu(self):
        m = self.menuBar().addMenu("파일")
        for text, fn, key in (("설정 저장", self.save_config, "Ctrl+S"),
                              ("설정 불러오기", self.reload_config, "Ctrl+O"),
                              ("세션 폴더 열기", self.open_rec_dir, None)):
            a = QAction(text, self)
            if key:
                a.setShortcut(QKeySequence(key))
            a.triggered.connect(fn)
            m.addAction(a)
        m.addSeparator()
        a = QAction("종료", self)
        a.setShortcut(QKeySequence("Ctrl+Q"))
        a.triggered.connect(self.close)
        m.addAction(a)
        v = self.menuBar().addMenu("보기")
        for d in (self.control_dock, self.tuning_dock, self.log_dock):
            v.addAction(d.toggleViewAction())

    def _param(self, key, lo, hi, step):
        row = ParamRow(key, lo, hi, step)
        self.params[key] = row
        return row

    def _bind_keys(self):
        for key, fn in (("1", lambda: self.set_mode(Mode.STANDBY)),
                        ("2", lambda: self.set_mode(Mode.HOVER)),
                        ("3", lambda: self.set_mode(Mode.FOLLOW)),
                        ("Space", self.disarm), ("Escape", self.disarm),
                        ("W", lambda: self.nudge_trim(+0.01)), ("S", lambda: self.nudge_trim(-0.01)),
                        ("R", self.toggle_session), ("P", self.snapshot)):
            sc = QShortcut(QKeySequence(key), self)
            sc.setContext(Qt.WindowShortcut)
            sc.activated.connect(fn)

    # ── 공용 ────────────────────────────────────────────────────────────────

    def info(self, text):
        self.statusBar().showMessage(text.splitlines()[0])
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log.appendPlainText(f"[{stamp}] {text}")
        print(text)

    def connect_all(self):
        if self.backend is None:
            self.toggle_backend()
        if self.source is None:
            self.toggle_camera()

    def _detector_text(self, det):
        threads = getattr(det, "threads", None)
        return f"{det.name} ({det.provider}{', threads=' + str(threads) if threads else ''})"

    def _ensure_detector(self):
        if self.detector is None:
            self.info("검출기 로딩 중…")
            QApplication.processEvents()
            self.detector = make_detector(self.args)
            self.det_label.setText("검출기: " + self._detector_text(self.detector))
            self.info("검출기: " + self._detector_text(self.detector))
        return self.detector

    # ── 연결 ────────────────────────────────────────────────────────────────

    def toggle_backend(self):
        if self.backend is not None:
            self._teardown_pipeline()
            self.backend.close()
            self.backend = None
            self.backend_btn.setText("백엔드 연결")
            self.arm_btn.setEnabled(False)
            self.info("백엔드 해제")
            return
        try:
            self.backend = make_backend(self.port_box.currentText(), self.args.sitl_host)
        except Exception as exc:
            self.info(f"백엔드 오류: {exc}")
            return
        self.backend_btn.setText(f"백엔드 해제 ({self.backend.port})")
        self.arm_btn.setEnabled(True)
        self.info(f"백엔드 연결: {self.backend.port}")
        self._maybe_start_pipeline()

    def toggle_camera(self):
        if self.source is not None:
            self._teardown_pipeline()
            self.source.release()
            self.source = None
            self.view.clear()
            self.cam_btn.setText("카메라 연결")
            self.video_label.setText("영상: —")
            self.info("카메라 해제")
            return
        if self._connecting:
            return
        spec = self.camera_box.currentText().strip()
        preset = self.preset_box.currentText()
        self._connecting = True
        self.cam_btn.setEnabled(False)
        self.cam_btn.setText("연결 중…")
        self.info("카메라 연결 중…")

        def work():
            src = None
            try:
                det = self.detector or make_detector(self.args)
                src = open_source(spec, preset, self.args.cap_backend)
                first = src.wait_first()
            except Exception as exc:
                if src is not None:
                    src.release()
                self._camera_failed.emit(exc)
                return
            self._camera_ready.emit(det, src, first)

        Thread(target=work, daemon=True).start()

    def _on_camera_failed(self, exc):
        self._connecting = False
        self.cam_btn.setEnabled(True)
        self.cam_btn.setText("카메라 연결")
        self.info(f"카메라 오류: {exc}")

    def _on_camera_ready(self, det, src, first):
        self._connecting = False
        if self.detector is None:
            self.detector = det
            self.det_label.setText("검출기: " + self._detector_text(det))
            self.info("검출기: " + self._detector_text(det))
        self.source = src
        H, W = first.shape[:2]
        self.cam_btn.setEnabled(True)
        self.cam_btn.setText("카메라 해제")
        self.video_label.setText(f"영상: {W}x{H} @ {src.fps:.0f}fps")
        self.info(f"영상: {src.description} {W}x{H} @ {src.fps:.0f}fps")
        self._maybe_start_pipeline()

    def pick_file(self):
        flt = "Video (" + " ".join("*" + s for s in VIDEO_SUFFIXES) + ")"
        path, _ = QFileDialog.getOpenFileName(self, "동영상 파일", "", flt)
        if path:
            self.camera_box.setCurrentText(path)
            if self.source is not None:
                self.toggle_camera()
            self.toggle_camera()

    def scan_devices(self):
        rows = probe_devices(self.args.cap_backend)
        current = self.camera_box.currentText()
        self.camera_box.clear()
        self.camera_box.addItems(device_names())
        self.camera_box.setCurrentText(current)
        text = "\n".join(f"[{i}] {name} — {probe}" for i, name, probe in rows) or "장치 없음"
        self.info(text)

    def _maybe_start_pipeline(self):
        if self.source is None or self.backend is None or self.pipeline is not None:
            return
        self._ensure_detector()
        verifier = make_arm_verifier(self.port_box.currentText(), self.args.sitl_host)
        self.pipeline = FollowPipeline(self.source, self.detector, self.backend, self.cfg,
                                       conf=self.args.conf, every=self.args.every,
                                       label="marker" if self.args.detector == "aruco" else "person",
                                       rec_dir=self.rec_dir,
                                       auto_session=self.auto_session_mode(),
                                       annotated_video=self.args.annotated_video,
                                       session_max_s=max(30.0, self.args.session_split_min * 60.0),
                                       arm_verifier=verifier, arm_channel=self.arm_ch.value() - 1)
        self.pipeline.start()
        self.set_mode(Mode.STANDBY)
        free = self.pipeline.free_gb()
        if free is not None:
            self.info(f"세션 기록: {self.auto_session_box.currentText()} · 저장 폴더 여유 {free:.1f} GB")

    def auto_session_mode(self):
        label = self.auto_session_box.currentText()
        for key, value in AUTO_SESSION_LABELS.items():
            if value == label:
                return key
        return "off"

    def _teardown_pipeline(self):
        if self.pipeline is not None:
            self.pipeline.stop()
            self.pipeline = None
        self.rec_btn.setText("세션 기록 시작 (R)")
        self.rec_label.setText("")

    # ── 모드 / ARM ──────────────────────────────────────────────────────────

    def set_mode(self, mode):
        if self.pipeline is None:
            self.info("파이프라인이 없습니다 (카메라+백엔드 연결 필요)")
            self._sync_mode_buttons(None)
            return
        self.pipeline.set_mode(mode)
        self._sync_mode_buttons(mode)

    def _sync_mode_buttons(self, mode):
        for m, b in self.mode_buttons.items():
            b.setChecked(m == mode)
        if mode is not None and mode != self._last_mode:
            self._last_mode = mode
            self.mode_label.setStyleSheet(f"background: {MODE_COLORS.get(mode.value, C_MUTED)};")

    def panic(self):
        if self.pipeline is not None:
            self.pipeline.panic()
            self.set_mode(Mode.STANDBY)
        elif self.backend is not None:
            self.backend.neutral()
        what = "오프셋 0 (조종기 스틱 그대로)" if self.cfg.offset_mode else "스틱 중립 + 스로틀 최소"
        self.info(f"PANIC: {what}")

    def _on_arm_channel(self):
        ch = self.arm_ch.value()
        aux = f"AUX{ch - 4}" if ch >= 5 else f"CH{ch}"
        if self.pipeline is not None:
            self.pipeline.set_arm_channel(ch - 1)
        self.info(f"ARM 채널 = CH{ch} ({aux}, 인덱스 {ch - 1})")

    def _set_arm_pending(self, pending):
        self.arm_btn.setText("ARM? 한 번 더" if pending else "ARM")
        self.arm_btn.setProperty("pending", "true" if pending else "false")
        repolish(self.arm_btn)

    def arm(self):
        if self.pipeline is None:
            self.info("파이프라인이 없습니다 (카메라+백엔드 연결 필요)")
            return
        if self.pipeline.mode != Mode.STANDBY:
            self.info("ARM 은 STANDBY 에서만 가능합니다 (먼저 1 STANDBY)")
            return
        now = time.time()
        if now - self._arm_confirm_t > 3.0:
            self._arm_confirm_t = now
            self._set_arm_pending(True)
            self.info("ARM 확인: 3초 안에 ARM 을 한 번 더 누르세요 (프롭 주의)")
            return
        self._arm_confirm_t = 0.0
        self._set_arm_pending(False)
        ch = self.arm_ch.value()
        state = self.pipeline.arm()
        if state and state["verifiable"]:
            self.info(f"ARM 명령 전송 (CH{ch}=1900) · FC 응답 확인 중")
        else:
            self.info(f"ARM 명령 전송 (CH{ch}=1900). 실물은 조종기 트레이너가 CH{ch}까지 넘겨야 "
                      f"기체에 도달합니다 (기본 설정은 CH1~4만) — ARM 은 조종기 SA 스위치 권장")

    def disarm(self):
        self._arm_confirm_t = 0.0
        self._set_arm_pending(False)
        if self.pipeline is not None:
            self.pipeline.disarm()
            self.set_mode(Mode.STANDBY)
        elif self.backend is not None:
            self.backend.neutral()
            self.backend.set_channel_us(4, 1000)
        self.info("DISARM (AUX1=1000) + 스로틀 최소")

    # ── 튜닝 ────────────────────────────────────────────────────────────────

    def nudge_trim(self, delta):
        row = self.params["hover_throttle"]
        row.set_value(round(max(-1.0, min(1.0, row.value() + delta)), 3))
        self._on_tune("hover_throttle")

    def adopt_trim(self):
        if self.pipeline is None:
            return
        value = self.pipeline.adopt_trim()
        self.params["hover_throttle"].set_value(round(value, 3))
        self.info(f"학습값 반영: 호버 스로틀 = {value:+.3f}")

    def reset_trim(self):
        if self.pipeline is not None:
            self.pipeline.reset_trim()
            self.info("트림 학습값 초기화")

    def _collect_cfg(self):
        for key, row in self.params.items():
            setattr(self.cfg, key, row.value())
        for key, cb in self.toggles.items():
            setattr(self.cfg, key, bool(cb.isChecked()))
        for key, box in self.combos.items():
            setattr(self.cfg, key, box.currentText())
        return self.cfg

    def _on_tune(self, _key, _value=None):
        if self._syncing:
            return
        self._collect_cfg()
        if self.pipeline is not None:
            self.pipeline.apply_config(self.cfg)
        self._update_panic_label()

    def _update_panic_label(self):
        self.panic_btn.setText("긴급 정지 · DISARM (Space) — 오프셋 0" if self.cfg.offset_mode
                               else "긴급 정지 · DISARM (Space) — 스로틀 최소")

    def _config_path_for(self, det):
        base = Path(self.args.config)
        if det == "aruco":
            return base if "aruco" in base.name else base.with_name("person_follow_aruco.json")
        return base.with_name("person_follow.json") if "aruco" in base.name else base

    def _on_detector(self):
        want = "aruco" if self.detector_box.currentText() == "AprilTag" else "onnx"
        if want == self.args.detector:
            return
        was_running = self.pipeline is not None
        if was_running:
            self._teardown_pipeline()
        self.detector = None
        self.det_label.setText("검출기: —")
        self.args.detector = want
        cfg_path = self._config_path_for(want)
        self.args.config = str(cfg_path)
        self.cfg = FollowConfig.load(cfg_path)
        self._push_cfg_to_ui()
        self.info(f"검출기 전환: {self.detector_box.currentText()} · 설정 {cfg_path.name}")
        if was_running and self.source is not None and self.backend is not None:
            try:
                self._ensure_detector()
            except Exception as exc:
                self.info(f"검출기 오류: {exc}")
                return
            self._maybe_start_pipeline()

    def _on_auto_session(self):
        if self.pipeline is not None:
            self.pipeline.set_auto_session(self.auto_session_mode())
        self.info(f"자동 기록: {self.auto_session_box.currentText()}")

    def _push_cfg_to_ui(self):
        self._syncing = True
        for key, row in self.params.items():
            row.set_value(getattr(self.cfg, key))
        for key, cb in self.toggles.items():
            cb.setChecked(bool(getattr(self.cfg, key)))
        for key, box in self.combos.items():
            box.setCurrentText(str(getattr(self.cfg, key)))
        self._syncing = False
        self._update_panic_label()

    def save_config(self):
        path = self._collect_cfg().save(self.args.config)
        self.info(f"설정 저장: {path}")

    def reload_config(self):
        self.cfg = FollowConfig.load(self.args.config)
        self._push_cfg_to_ui()
        if self.pipeline is not None:
            self.pipeline.apply_config(self.cfg)
        self.info(f"설정 불러옴: {self.args.config}")

    # ── 세션 / 도구 ─────────────────────────────────────────────────────────

    def toggle_session(self):
        if self.pipeline is None:
            return
        if self.pipeline.session_active:
            result = self.pipeline.stop_session(manual=True)
            self.rec_btn.setText("세션 기록 시작 (R)")
            if result:
                self.info(f"세션 종료: {result[0].name} ({result[1]} frames) — 자동 기록은 R 로 다시 켤 때까지 멈춤")
        else:
            path = self.pipeline.start_session(manual=True)
            if path:
                self.rec_btn.setText("세션 기록 중지 (R)")
                self.info(f"세션 시작: {path.name}")

    def snapshot(self):
        if self.pipeline is None:
            return
        path = self.pipeline.snapshot()
        if path:
            self.info(f"스냅샷: {path}")

    def _session_target(self):
        if self.pipeline is not None:
            return self.pipeline.session_dir or self.pipeline.last_session_dir
        return None

    def open_rec_dir(self):
        target = self._session_target() or self.rec_dir
        target.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(str(target))
        else:
            self.info(str(target))

    def make_report(self):
        target = None
        if self.pipeline is not None:
            target = self.pipeline.last_session_dir or self.pipeline.session_dir
        if target is None:
            sessions = sorted(self.rec_dir.glob("session_*"))
            target = sessions[-1] if sessions else None
        if target is None:
            self.info("세션이 없습니다")
            return
        self.info(f"리포트 생성 중: {target.name}")
        self.report_btn.setEnabled(False)
        cmd = [str(REPORT_TOOL)] if FROZEN else [sys.executable, str(REPORT_TOOL)]

        def work():
            proc = subprocess.run(cmd + [str(target), "--sheet", "--plot"],
                                  capture_output=True, text=True, encoding="utf-8", errors="replace")
            tail = (proc.stdout or proc.stderr or "").strip().splitlines()[-3:]

            def done():
                self.report_btn.setEnabled(True)
                self.info("리포트: " + (" | ".join(tail) if tail else f"exit {proc.returncode}"))
                if proc.returncode == 0 and sys.platform == "win32":
                    os.startfile(str(target))

            self._post.emit(done)

        Thread(target=work, daemon=True).start()

    # ── 갱신 ────────────────────────────────────────────────────────────────

    def _refresh_arm(self, arm):
        label = arm.get("label") or "—"
        color = ARM_COLORS.get(label, "#b07000")
        suffix = ""
        if label in ("ARM SENT", "DISARM SENT") and not arm.get("verifiable"):
            suffix = " · 확인 불가"
        self.arm_status.setText(label + suffix)
        self.arm_status.setStyleSheet(f"color: {color}; font-weight: 700; font-size: 11pt;")
        reasons = arm.get("reasons") or []
        if arm.get("result") == "failed" and reasons:
            self.arm_reason.setText("막힌 이유: " + ", ".join(reasons))
        elif arm.get("error"):
            self.arm_reason.setText("FC 확인 불가: " + arm["error"])
        else:
            self.arm_reason.setText("")

    def on_view_click(self, x, y):
        if self.pipeline is None:
            return
        self.pipeline.select_target(x, y)
        self.info(f"타깃 선택 요청: ({x:.2f}, {y:.2f})")

    def _refresh_once(self):
        if self.pipeline is None:
            return
        disp, tele = self.pipeline.latest_display()
        if disp is not None:
            frame, boxes, track = disp
            cw, ch = max(160, self.view.width()), max(90, self.view.height())
            fh, fw = frame.shape[:2]
            scale = min(cw / fw, ch / fh)
            size = (max(1, int(fw * scale)), max(1, int(fh * scale)))
            small = cv2.resize(frame, size, interpolation=cv2.INTER_AREA)
            draw_overlay(small, boxes, track, self.cfg, tele)
            self.view.set_frame(small)
            self._fps_n += 1
            now = time.perf_counter()
            if now - self._fps_t >= 1.0:
                self.fps_label.setText(f"UI {self._fps_n / (now - self._fps_t):.0f} fps")
                self._fps_t, self._fps_n = now, 0

        mode = tele.get("mode")
        status = tele.get("status")
        self.mode_label.setText(f"{mode}" + (f"  ·  {status}" if status and status != mode else ""))
        try:
            self._sync_mode_buttons(Mode(mode))
        except ValueError:
            pass
        line = f"{mode} · {status}"
        safe = tele.get("safe")
        if safe:
            line += f"   T {safe['throttle']:+.3f}"
        self.status_label.setText(line)
        if "trim" in tele:
            us = tele.get("channels_us") or [0, 0, 0]
            text = f"trim {tele['trim']:+.3f}  learned {tele.get('trim_offset', 0.0):+.3f}  thr {us[2]}us\n"
            if tele.get("descend"):
                text += f"descend -{tele['descend']:.3f}  "
            text += f"motion {tele.get('motion', 0.0):.3f}"
            self.trim_label.setText(text)
        self._refresh_arm(tele.get("arm") or {})
        rec = tele.get("rec")
        self.rec_label.setText(f"● {rec}" if rec else "")
        active = self.pipeline.session_active
        if active and self.rec_btn.text().startswith("세션 기록 시작"):
            self.rec_btn.setText("세션 기록 중지 (R)")
        elif not active and self.rec_btn.text().startswith("세션 기록 중지"):
            self.rec_btn.setText("세션 기록 시작 (R)")
        if self.pipeline.errors:
            self.info(self.pipeline.errors.pop(0))

    def closeEvent(self, event):
        self._timer.stop()
        self._teardown_pipeline()
        if self.source is not None:
            self.source.release()
        if self.backend is not None:
            self.backend.neutral()
            self.backend.close()
        event.accept()


def main():
    args = parse_args()
    if args.list:
        for i, name, probe in probe_devices(args.cap_backend):
            print(f"[{i}] {name} — {probe}")
        return
    app = QApplication(sys.argv)
    apply_theme(app)
    win = MainWindow(args)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
