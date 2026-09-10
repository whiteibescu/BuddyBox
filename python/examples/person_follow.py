import argparse
import os
import subprocess
import sys
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from buddybox import BuddyBox
from buddybox.follow.controller import FollowConfig
from buddybox.follow.pipeline import AUTO_SESSION_MODES, FollowPipeline
from buddybox.follow.state import Mode
from buddybox.msp import SITL_MSP_PORT, MspClient
from buddybox.sitl import BuddyBoxSitl
from buddybox.vision.capture import (
    PRESETS,
    VIDEO_SUFFIXES,
    VRX_DEVICE_NAME,
    default_backend,
    device_names,
    open_source,
    probe_devices,
)
from buddybox.vision.detector import HogDetector, OnnxDetector, find_default_model

HERE = Path(__file__).resolve().parent
DEFAULT_CONFIG = HERE / "person_follow.json"
DEFAULT_REC_DIR = HERE.parent / "recordings"
REPORT_TOOL = HERE.parent / "tools" / "session_report.py"

TRIM_TAB = [
    ("hover_throttle", "호버 스로틀", -1.0, 1.0, 0.005),
    ("max_throttle_delta", "스로틀 보정 폭", 0.0, 0.4, 0.01),
    ("target_y", "목표 세로 위치", 0.05, 0.95, 0.01),
    ("target_height", "목표 박스 높이", 0.1, 0.9, 0.01),
    ("trim_learn_rate", "트림 학습 속도", 0.0, 1.0, 0.01),
    ("lost_descend_after_s", "LOST 하강 대기(s)", 0.0, 10.0, 0.5),
    ("lost_descend_rate", "LOST 하강 속도", 0.0, 0.1, 0.005),
    ("max_throttle_rate_per_s", "스로틀 슬루(/s)", 0.1, 3.0, 0.05),
]

PID_TAB = [
    ("lateral_kp", "좌우 Kp", 0.0, 2.0, 0.01),
    ("lateral_ki", "좌우 Ki", 0.0, 0.5, 0.005),
    ("lateral_kd", "좌우 Kd", 0.0, 0.5, 0.005),
    ("pitch_kp", "거리 Kp", 0.0, 2.0, 0.01),
    ("pitch_ki", "거리 Ki", 0.0, 0.5, 0.005),
    ("pitch_kd", "거리 Kd", 0.0, 0.5, 0.005),
    ("throttle_kp", "고도 Kp", 0.0, 1.0, 0.01),
    ("throttle_ki", "고도 Ki", 0.0, 0.5, 0.005),
    ("throttle_kd", "고도 Kd", 0.0, 0.5, 0.005),
    ("deadzone_x", "데드존 X", 0.0, 0.3, 0.01),
    ("deadzone_y", "데드존 Y", 0.0, 0.3, 0.01),
    ("deadzone_height", "데드존 크기", 0.0, 0.3, 0.01),
    ("max_lateral", "좌우 최대", 0.05, 0.6, 0.01),
    ("max_pitch", "피치 최대", 0.05, 0.6, 0.01),
    ("lost_after_s", "LOST 판정(s)", 0.1, 3.0, 0.1),
]

TOGGLES = [
    ("distance_hold", "거리 유지 (피치)"),
    ("altitude_assist", "고도 보조 (스로틀)"),
    ("trim_learning", "호버 트림 자동 학습"),
    ("invert_lateral", "좌우 반전"),
    ("invert_pitch", "피치 반전"),
    ("invert_throttle", "스로틀 반전"),
]

COMBOS = [
    ("throttle_mode", "스로틀 모드", ["absolute", "offset"]),
    ("altitude_reference", "고도 기준점", ["head", "center"]),
    ("lateral_axis", "좌우 축", ["yaw", "roll"]),
]

AUTO_SESSION_LABELS = {
    "always": "항상 (카메라 연결 시)",
    "mode": "STANDBY 벗어날 때만",
    "off": "끔 (R 키로 수동)",
}


def parse_args():
    ap = argparse.ArgumentParser(description="Walksnail VRX Pro 피드로 사람 추적 + 호버링 유지 (BuddyBox)")
    ap.add_argument("--camera", default=VRX_DEVICE_NAME, help="장치 이름 일부 / 인덱스 / 동영상 파일 경로")
    ap.add_argument("--preset", choices=list(PRESETS), default="vrx1080")
    ap.add_argument("--cap-backend", default=default_backend(), help="dshow(권장)/msmf/v4l2/any")
    ap.add_argument("--detector", choices=["onnx", "hog"], default="onnx")
    ap.add_argument("--model", default=None, help="RF-DETR ONNX 경로 (기본: BUDDYBOX_MODEL 또는 자동 탐색)")
    ap.add_argument("--provider", choices=["cpu", "cuda", "tensorrt"], default="cpu")
    ap.add_argument("--threads", type=int, default=None,
                    help="onnxruntime CPU 스레드 수 (기본: 논리 코어의 절반, 배경 창에서도 안정)")
    ap.add_argument("--conf", type=float, default=0.5)
    ap.add_argument("--every", type=int, default=2, help="N 프레임마다 추론")
    ap.add_argument("--port", default="sim", help="sim / auto / COMx / sitl")
    ap.add_argument("--arm-channel", type=int, default=5, help="ARM 채널 (CH, 1~8, 기본 5=AUX1)")
    ap.add_argument("--sitl-host", default=os.environ.get("BUDDYBOX_SITL_HOST", "127.0.0.1"))
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    ap.add_argument("--rec-dir", default=str(DEFAULT_REC_DIR))
    ap.add_argument("--auto-session", choices=list(AUTO_SESSION_MODES), default="always",
                    help="자동 기록: always=카메라 연결 시 항상, mode=STANDBY 벗어날 때만, off=수동")
    ap.add_argument("--session-split-min", type=float, default=5.0, help="세션 파일 분할 간격(분)")
    ap.add_argument("--annotated-video", action="store_true", help="세션에 오버레이 영상도 저장 (용량 2배)")
    ap.add_argument("--scale", type=float, default=0.5, help="표시 배율")
    ap.add_argument("--no-autoconnect", action="store_true")
    ap.add_argument("--list", action="store_true", help="UVC 장치 목록만 출력")
    return ap.parse_args()


def make_detector(args):
    if args.detector == "hog":
        return HogDetector()
    model = Path(args.model) if args.model else find_default_model()
    if model is None or not model.exists():
        raise FileNotFoundError(
            "RF-DETR ONNX 모델을 찾지 못했습니다. --model 또는 BUDDYBOX_MODEL 을 지정하거나 "
            "python/models/rfdetr_nano_coco.onnx (+ .classes.json) 를 복사하세요. --detector hog 로 대체 가능")
    det = OnnxDetector(model, provider=args.provider, threads=args.threads)
    det.warmup()
    return det


def make_backend(spec, sitl_host):
    spec = (spec or "sim").strip()
    if spec.lower() == "sitl":
        return BuddyBoxSitl(host=sitl_host)
    if spec.lower() in ("sim", ""):
        return BuddyBox("sim")
    if spec.lower() == "auto":
        return BuddyBox(None)
    return BuddyBox(spec)


def make_arm_verifier(spec, sitl_host):
    if (spec or "").strip().lower() == "sitl":
        return MspClient(host=sitl_host, port=SITL_MSP_PORT)
    return None


def serial_ports():
    try:
        from serial.tools import list_ports

        return [p.device for p in list_ports.comports()]
    except Exception:
        return []


class App:
    def __init__(self, args):
        self.args = args
        self.cfg = FollowConfig.load(args.config)
        self.rec_dir = Path(args.rec_dir)
        self.pipeline = None
        self.source = None
        self.backend = None
        self.detector = None
        self.photo = None
        self.display_size = (960, 540)
        self._syncing = False
        self._arm_confirm_t = 0.0

        self.root = tk.Tk()
        self.root.title("BuddyBox Person Follow")
        self.root.configure(bg="#1e1e1e")
        self._build_ui()
        self._bind_keys()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        if not args.no_autoconnect:
            self.root.after(100, self.connect_all)
        self.root.after(30, self._refresh)

    def _build_ui(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        main = ttk.Frame(self.root)
        main.pack(fill="both", expand=True)

        self.canvas = tk.Canvas(main, width=self.display_size[0], height=self.display_size[1],
                                bg="black", highlightthickness=0, cursor="crosshair")
        self.canvas.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        self.canvas.bind("<Button-1>", self.on_canvas_click)
        self.canvas.bind("<Button-3>", lambda e: self.pipeline and self.pipeline.clear_target())
        self.canvas.bind("<Configure>", self._on_canvas_resize)
        main.columnconfigure(0, weight=1)
        main.rowconfigure(0, weight=1)

        panel = ttk.Frame(main, padding=6)
        panel.grid(row=0, column=1, sticky="ns")

        conn = ttk.LabelFrame(panel, text="연결", padding=6)
        conn.pack(fill="x")
        ttk.Label(conn, text="카메라").grid(row=0, column=0, sticky="w")
        self.camera_var = tk.StringVar(value=self.args.camera)
        self.camera_box = ttk.Combobox(conn, textvariable=self.camera_var, width=24, values=device_names())
        self.camera_box.grid(row=0, column=1, sticky="ew", pady=2)
        ttk.Label(conn, text="프리셋").grid(row=1, column=0, sticky="w")
        self.preset_var = tk.StringVar(value=self.args.preset)
        ttk.Combobox(conn, textvariable=self.preset_var, values=list(PRESETS), width=24,
                     state="readonly").grid(row=1, column=1, sticky="ew", pady=2)
        row = ttk.Frame(conn)
        row.grid(row=2, column=0, columnspan=2, sticky="ew", pady=2)
        self.cam_btn = ttk.Button(row, text="카메라 연결", command=self.toggle_camera)
        self.cam_btn.pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="파일…", command=self.pick_file, width=6).pack(side="left", padx=(4, 0))
        ttk.Button(row, text="탐색", command=self.scan_devices, width=6).pack(side="left", padx=(4, 0))

        ttk.Label(conn, text="백엔드").grid(row=3, column=0, sticky="w")
        self.port_var = tk.StringVar(value=self.args.port)
        self.port_box = ttk.Combobox(conn, textvariable=self.port_var, width=24,
                                     values=["sim", "sitl", "auto"] + serial_ports())
        self.port_box.grid(row=3, column=1, sticky="ew", pady=2)
        self.backend_btn = ttk.Button(conn, text="백엔드 연결", command=self.toggle_backend)
        self.backend_btn.grid(row=4, column=0, columnspan=2, sticky="ew", pady=2)
        conn.columnconfigure(1, weight=1)

        arm = ttk.LabelFrame(panel, text="ARM", padding=4)
        arm.pack(fill="x", pady=(6, 0))
        self.arm_btn = tk.Button(arm, text="ARM", width=6, command=self.arm, state="disabled")
        self.arm_btn.grid(row=0, column=0, padx=(0, 4), pady=1)
        ttk.Label(arm, text="CH").grid(row=0, column=1, sticky="e")
        self.arm_ch_var = tk.IntVar(value=self.args.arm_channel)
        tk.Spinbox(arm, from_=1, to=8, width=3, textvariable=self.arm_ch_var,
                   command=self._on_arm_channel).grid(row=0, column=2, padx=(2, 6))
        self.arm_status = tk.Label(arm, text="—", font=("Segoe UI", 10, "bold"), anchor="w")
        self.arm_status.grid(row=0, column=3, sticky="ew")
        self.arm_reason = tk.Label(arm, text="", fg="#c04040", wraplength=280, justify="left", font=("Segoe UI", 8))
        self.arm_reason.grid(row=1, column=0, columnspan=4, sticky="w")
        arm.columnconfigure(3, weight=1)

        modes = ttk.LabelFrame(panel, text="모드", padding=6)
        modes.pack(fill="x", pady=(6, 0))
        self.mode_buttons = {}
        for i, (mode, label) in enumerate(((Mode.STANDBY, "1 STANDBY"), (Mode.HOVER, "2 HOVER"),
                                           (Mode.FOLLOW, "3 FOLLOW"))):
            b = tk.Button(modes, text=label, width=10, command=lambda m=mode: self.set_mode(m))
            b.grid(row=0, column=i, padx=2, pady=2)
            self.mode_buttons[mode] = b
        self.panic_btn = tk.Button(modes, text="긴급 정지 · DISARM (Space)", bg="#b00020", fg="white",
                                   activebackground="#e02040", command=self.disarm)
        self.panic_btn.grid(row=1, column=0, columnspan=3, sticky="ew", padx=2, pady=(6, 2))
        self.status_var = tk.StringVar(value="—")
        ttk.Label(modes, textvariable=self.status_var, font=("Segoe UI", 11, "bold")).grid(
            row=2, column=0, columnspan=3, sticky="w", pady=(4, 0))
        self.trim_var = tk.StringVar(value="")
        ttk.Label(modes, textvariable=self.trim_var, font=("Consolas", 10)).grid(
            row=3, column=0, columnspan=3, sticky="w")

        nb = ttk.Notebook(panel)
        nb.pack(fill="both", expand=True, pady=(6, 0))
        self.tune_vars = {}
        self.toggle_vars = {}
        self.combo_vars = {}

        trim_tab = self._scroll_tab(nb, "트림/고도")
        r = 0
        for key, label, lo, hi, step in TRIM_TAB:
            self._add_scale(trim_tab, r, key, label, lo, hi, step)
            r += 1
        for key, label, values in COMBOS:
            ttk.Label(trim_tab, text=label, width=14).grid(row=r, column=0, sticky="w")
            var = tk.StringVar(value=getattr(self.cfg, key))
            ttk.Combobox(trim_tab, textvariable=var, values=values, state="readonly", width=10).grid(
                row=r, column=1, sticky="w")
            var.trace_add("write", lambda *_a, k=key: self._on_tune(k))
            self.combo_vars[key] = var
            r += 1
        for key, label in TOGGLES:
            var = tk.BooleanVar(value=getattr(self.cfg, key))
            ttk.Checkbutton(trim_tab, text=label, variable=var,
                            command=lambda k=key: self._on_tune(k)).grid(row=r, column=0, columnspan=2, sticky="w")
            self.toggle_vars[key] = var
            r += 1
        btns = ttk.Frame(trim_tab)
        btns.grid(row=r, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        ttk.Button(btns, text="학습값 → 트림 반영", command=self.adopt_trim).pack(side="left", fill="x", expand=True)
        ttk.Button(btns, text="학습 초기화", command=self.reset_trim).pack(side="left", fill="x", expand=True, padx=(4, 0))

        pid_tab = self._scroll_tab(nb, "PID")
        for r, (key, label, lo, hi, step) in enumerate(PID_TAB):
            self._add_scale(pid_tab, r, key, label, lo, hi, step)

        tools = self._scroll_tab(nb, "도구")
        self.rec_btn = ttk.Button(tools, text="세션 기록 시작 (R)", command=self.toggle_session)
        self.rec_btn.grid(row=0, column=0, columnspan=2, sticky="ew", padx=2, pady=2)
        ttk.Label(tools, text="자동 기록").grid(row=1, column=0, sticky="w")
        self.auto_session_var = tk.StringVar(value=AUTO_SESSION_LABELS[self.args.auto_session])
        auto_box = ttk.Combobox(tools, textvariable=self.auto_session_var, state="readonly", width=20,
                                values=list(AUTO_SESSION_LABELS.values()))
        auto_box.grid(row=1, column=1, sticky="ew", padx=2, pady=2)
        auto_box.bind("<<ComboboxSelected>>", lambda e: self._on_auto_session())
        ttk.Button(tools, text="스냅샷 (P)", command=self.snapshot).grid(row=2, column=0, sticky="ew", padx=2, pady=2)
        ttk.Button(tools, text="세션 폴더 열기", command=self.open_rec_dir).grid(row=2, column=1, sticky="ew", padx=2, pady=2)
        ttk.Button(tools, text="설정 저장", command=self.save_config).grid(row=3, column=0, sticky="ew", padx=2, pady=2)
        ttk.Button(tools, text="설정 불러오기", command=self.reload_config).grid(row=3, column=1, sticky="ew", padx=2, pady=2)
        ttk.Button(tools, text="마지막 세션 리포트 생성", command=self.make_report).grid(
            row=4, column=0, columnspan=2, sticky="ew", padx=2, pady=2)
        tools.columnconfigure(0, weight=1)
        tools.columnconfigure(1, weight=1)

        self.info_var = tk.StringVar(value="")
        ttk.Label(panel, textvariable=self.info_var, wraplength=320, foreground="#888").pack(
            fill="x", pady=(6, 0))
        ttk.Label(panel, text="클릭=타깃 선택  우클릭=해제  W/S=호버 스로틀 ±0.01  R=세션  P=스냅샷",
                  foreground="#888", wraplength=320).pack(fill="x")

    def _scroll_tab(self, notebook, title):
        outer = ttk.Frame(notebook)
        notebook.add(outer, text=title)
        canvas = tk.Canvas(outer, highlightthickness=0, width=320)
        vsb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas, padding=6)
        window = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(window, width=e.width))
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        def on_wheel(event):
            canvas.yview_scroll(int(-event.delta / 120), "units")

        inner.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", on_wheel))
        inner.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))
        return inner

    def _add_scale(self, parent, row, key, label, lo, hi, step):
        ttk.Label(parent, text=label, width=14).grid(row=row, column=0, sticky="w")
        var = tk.DoubleVar(value=getattr(self.cfg, key))
        tk.Scale(parent, from_=lo, to=hi, resolution=step, orient="horizontal", length=180,
                 variable=var, showvalue=True, command=lambda _v, k=key: self._on_tune(k)).grid(
            row=row, column=1, sticky="ew")
        self.tune_vars[key] = var

    def _bind_keys(self):
        r = self.root
        r.bind("1", lambda e: self.set_mode(Mode.STANDBY))
        r.bind("2", lambda e: self.set_mode(Mode.HOVER))
        r.bind("3", lambda e: self.set_mode(Mode.FOLLOW))
        r.bind("<space>", lambda e: self.disarm())
        r.bind("<Escape>", lambda e: self.disarm())
        r.bind("w", lambda e: self.nudge_trim(+0.01))
        r.bind("s", lambda e: self.nudge_trim(-0.01))
        r.bind("r", lambda e: self.toggle_session())
        r.bind("p", lambda e: self.snapshot())

    def _on_canvas_resize(self, event):
        self.display_size = (max(160, event.width), max(90, event.height))

    def info(self, text):
        self.info_var.set(text)
        print(text)

    def connect_all(self):
        if self.backend is None:
            self.toggle_backend()
        if self.source is None:
            self.toggle_camera()

    def _ensure_detector(self):
        if self.detector is None:
            self.info("검출기 로딩 중…")
            self.root.update_idletasks()
            self.detector = make_detector(self.args)
            threads = getattr(self.detector, "threads", None)
            self.info(f"검출기: {self.detector.name} ({self.detector.provider}"
                      f"{', threads=' + str(threads) if threads else ''})")
        return self.detector

    def toggle_backend(self):
        if self.backend is not None:
            self._teardown_pipeline()
            self.backend.close()
            self.backend = None
            self.backend_btn.config(text="백엔드 연결")
            self.arm_btn.config(state="disabled")
            self.info("백엔드 해제")
            return
        try:
            self.backend = make_backend(self.port_var.get(), self.args.sitl_host)
        except Exception as exc:
            messagebox.showerror("백엔드", str(exc))
            return
        self.backend_btn.config(text=f"백엔드 해제 ({self.backend.port})")
        self.arm_btn.config(state="normal")
        self.info(f"백엔드 연결: {self.backend.port}")
        self._maybe_start_pipeline()

    def toggle_camera(self):
        if self.source is not None:
            self._teardown_pipeline()
            self.source.release()
            self.source = None
            self.cam_btn.config(text="카메라 연결")
            self.info("카메라 해제")
            return
        spec = self.camera_var.get().strip()
        try:
            self._ensure_detector()
            self.source = open_source(spec, self.preset_var.get(), self.args.cap_backend)
            first = self.source.wait_first()
        except Exception as exc:
            if self.source is not None:
                self.source.release()
                self.source = None
            messagebox.showerror("카메라", str(exc))
            return
        H, W = first.shape[:2]
        self.cam_btn.config(text="카메라 해제")
        self.info(f"영상: {self.source.description} {W}x{H} @ {self.source.fps:.0f}fps")
        self._maybe_start_pipeline()

    def pick_file(self):
        path = filedialog.askopenfilename(title="동영상 파일",
                                          filetypes=[("Video", " ".join("*" + s for s in VIDEO_SUFFIXES))])
        if path:
            self.camera_var.set(path)
            if self.source is not None:
                self.toggle_camera()
            self.toggle_camera()

    def scan_devices(self):
        rows = probe_devices(self.args.cap_backend)
        self.camera_box.config(values=device_names())
        text = "\n".join(f"[{i}] {name} — {probe}" for i, name, probe in rows) or "장치 없음"
        self.info(text)

    def _maybe_start_pipeline(self):
        if self.source is None or self.backend is None or self.pipeline is not None:
            return
        verifier = make_arm_verifier(self.port_var.get(), self.args.sitl_host)
        self.pipeline = FollowPipeline(self.source, self.detector, self.backend, self.cfg,
                                       conf=self.args.conf, every=self.args.every,
                                       rec_dir=self.rec_dir,
                                       auto_session=self.auto_session_mode(),
                                       annotated_video=self.args.annotated_video,
                                       session_max_s=max(30.0, self.args.session_split_min * 60.0),
                                       arm_verifier=verifier, arm_channel=self.arm_ch_var.get() - 1)
        self.pipeline.start()
        self.set_mode(Mode.STANDBY)
        free = self.pipeline.free_gb()
        if free is not None:
            self.info(f"세션 기록: {self.auto_session_var.get()} · 저장 폴더 여유 {free:.1f} GB")

    def auto_session_mode(self):
        label = self.auto_session_var.get()
        for key, value in AUTO_SESSION_LABELS.items():
            if value == label:
                return key
        return "off"

    def _teardown_pipeline(self):
        if self.pipeline is not None:
            self.pipeline.stop()
            self.pipeline = None
        self.rec_btn.config(text="세션 기록 시작 (R)")

    def set_mode(self, mode):
        if self.pipeline is None:
            self.info("파이프라인이 없습니다 (카메라+백엔드 연결 필요)")
            return
        self.pipeline.set_mode(mode)
        for m, b in self.mode_buttons.items():
            b.config(relief="sunken" if m == mode else "raised",
                     bg="#2e7d32" if m == mode else "SystemButtonFace",
                     fg="white" if m == mode else "black")

    def panic(self):
        if self.pipeline is not None:
            self.pipeline.panic()
            self.set_mode(Mode.STANDBY)
        elif self.backend is not None:
            self.backend.neutral()
        what = "오프셋 0 (조종기 스틱 그대로)" if self.cfg.offset_mode else "스틱 중립 + 스로틀 최소"
        self.info(f"PANIC: {what}")

    def _on_arm_channel(self):
        ch = max(1, min(8, self.arm_ch_var.get()))
        self.arm_ch_var.set(ch)
        aux = f"AUX{ch - 4}" if ch >= 5 else f"CH{ch}"
        if self.pipeline is not None:
            self.pipeline.set_arm_channel(ch - 1)
        self.info(f"ARM 채널 = CH{ch} ({aux}, 인덱스 {ch - 1})")

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
            self.arm_btn.config(text="ARM? 한 번 더", bg="#c07000", fg="white")
            self.info("ARM 확인: 3초 안에 ARM 을 한 번 더 누르세요 (프롭 주의)")
            return
        self._arm_confirm_t = 0.0
        self.arm_btn.config(text="ARM", bg="SystemButtonFace", fg="black")
        ch = self.arm_ch_var.get()
        state = self.pipeline.arm()
        if state and state["verifiable"]:
            self.info(f"ARM 명령 전송 (CH{ch}=1900) · FC 응답 확인 중")
        else:
            self.info(f"ARM 명령 전송 (CH{ch}=1900). 실물은 조종기 트레이너가 CH{ch}까지 넘겨야 "
                      f"기체에 도달합니다 (기본 설정은 CH1~4만) — ARM 은 조종기 SA 스위치 권장")

    def disarm(self):
        self._arm_confirm_t = 0.0
        if hasattr(self, "arm_btn"):
            self.arm_btn.config(text="ARM", bg="SystemButtonFace", fg="black")
        if self.pipeline is not None:
            self.pipeline.disarm()
            self.set_mode(Mode.STANDBY)
        elif self.backend is not None:
            self.backend.neutral()
            self.backend.set_channel_us(4, 1000)
        self.info("DISARM (AUX1=1000) + 스로틀 최소")

    def nudge_trim(self, delta):
        var = self.tune_vars["hover_throttle"]
        var.set(round(max(-1.0, min(1.0, var.get() + delta)), 3))
        self._on_tune("hover_throttle")

    def adopt_trim(self):
        if self.pipeline is None:
            return
        value = self.pipeline.adopt_trim()
        self._syncing = True
        self.tune_vars["hover_throttle"].set(round(value, 3))
        self._syncing = False
        self.info(f"학습값 반영: 호버 스로틀 = {value:+.3f}")

    def reset_trim(self):
        if self.pipeline is not None:
            self.pipeline.reset_trim()
            self.info("트림 학습값 초기화")

    def _collect_cfg(self):
        for key, var in self.tune_vars.items():
            setattr(self.cfg, key, float(var.get()))
        for key, var in self.toggle_vars.items():
            setattr(self.cfg, key, bool(var.get()))
        for key, var in self.combo_vars.items():
            setattr(self.cfg, key, var.get())
        return self.cfg

    def _on_tune(self, _key):
        if self._syncing:
            return
        self._collect_cfg()
        if self.pipeline is not None:
            self.pipeline.apply_config(self.cfg)
        self.panic_btn.config(text="PANIC (Space) — 오프셋 0" if self.cfg.offset_mode
                              else "PANIC (Space) — 스로틀 최소")

    def _on_auto_session(self):
        if self.pipeline is not None:
            self.pipeline.set_auto_session(self.auto_session_mode())
        self.info(f"자동 기록: {self.auto_session_var.get()}")

    def _push_cfg_to_ui(self):
        self._syncing = True
        for key, var in self.tune_vars.items():
            var.set(getattr(self.cfg, key))
        for key, var in self.toggle_vars.items():
            var.set(getattr(self.cfg, key))
        for key, var in self.combo_vars.items():
            var.set(getattr(self.cfg, key))
        self._syncing = False

    def save_config(self):
        path = self._collect_cfg().save(self.args.config)
        self.info(f"설정 저장: {path}")

    def reload_config(self):
        self.cfg = FollowConfig.load(self.args.config)
        self._push_cfg_to_ui()
        if self.pipeline is not None:
            self.pipeline.apply_config(self.cfg)
        self.info(f"설정 불러옴: {self.args.config}")

    def toggle_session(self):
        if self.pipeline is None:
            return
        if self.pipeline.session_active:
            result = self.pipeline.stop_session(manual=True)
            self.rec_btn.config(text="세션 기록 시작 (R)")
            if result:
                self.info(f"세션 종료: {result[0].name} ({result[1]} frames) — 자동 기록은 R 로 다시 켤 때까지 멈춤")
        else:
            path = self.pipeline.start_session(manual=True)
            if path:
                self.rec_btn.config(text="세션 기록 중지 (R)")
                self.info(f"세션 시작: {path.name}")

    def snapshot(self):
        if self.pipeline is None:
            return
        path = self.pipeline.snapshot()
        if path:
            self.info(f"스냅샷: {path}")

    def open_rec_dir(self):
        target = self.rec_dir
        if self.pipeline is not None and (self.pipeline.session_dir or self.pipeline.last_session_dir):
            target = self.pipeline.session_dir or self.pipeline.last_session_dir
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
        self.root.update_idletasks()
        proc = subprocess.run([sys.executable, str(REPORT_TOOL), str(target), "--sheet", "--plot"],
                              capture_output=True, text=True, encoding="utf-8", errors="replace")
        tail = (proc.stdout or proc.stderr or "").strip().splitlines()[-3:]
        self.info("리포트: " + (" | ".join(tail) if tail else f"exit {proc.returncode}"))
        if proc.returncode == 0 and sys.platform == "win32":
            os.startfile(str(target))

    def _refresh_arm(self, arm):
        label = arm.get("label") or "—"
        colors = {"ARMED": "#1e8020", "DISARMED": "#606060", "ARM FAILED": "#c00020",
                  "DISARM FAILED": "#c00020", "ARM?": "#c07000", "DISARM?": "#c07000"}
        color = colors.get(label, "#b07000")
        suffix = ""
        if arm.get("label") in ("ARM SENT", "DISARM SENT") and not arm.get("verifiable"):
            suffix = " · 확인 불가"
        self.arm_status.config(text=label + suffix, fg=color)
        reasons = arm.get("reasons") or []
        if arm.get("result") == "failed" and reasons:
            self.arm_reason.config(text="막힌 이유: " + ", ".join(reasons))
        elif arm.get("error"):
            self.arm_reason.config(text="FC 확인 불가: " + arm["error"])
        else:
            self.arm_reason.config(text="")

    def on_canvas_click(self, event):
        if self.pipeline is None or self.pipeline.frame_size is None:
            return
        cw, ch = self.display_size
        fw, fh = self.pipeline.frame_size
        scale = min(cw / fw, ch / fh)
        dw, dh = fw * scale, fh * scale
        ox, oy = (cw - dw) / 2, (ch - dh) / 2
        x = (event.x - ox) / dw
        y = (event.y - oy) / dh
        if 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0:
            self.pipeline.select_target(x, y)
            self.info(f"타깃 선택 요청: ({x:.2f}, {y:.2f})")

    def _refresh(self):
        try:
            self._refresh_once()
        finally:
            self.root.after(30, self._refresh)

    def _refresh_once(self):
        if self.pipeline is None:
            return
        import cv2
        from PIL import Image, ImageTk

        frame, tele = self.pipeline.latest()
        if frame is not None:
            cw, ch = self.display_size
            fh, fw = frame.shape[:2]
            scale = min(cw / fw, ch / fh)
            size = (max(1, int(fw * scale)), max(1, int(fh * scale)))
            small = cv2.resize(frame, size, interpolation=cv2.INTER_AREA)
            img = Image.fromarray(cv2.cvtColor(small, cv2.COLOR_BGR2RGB))
            self.photo = ImageTk.PhotoImage(img)
            self.canvas.delete("all")
            self.canvas.create_image(cw // 2, ch // 2, image=self.photo, anchor="center")
        status = f"{tele.get('mode')} · {tele.get('status')}"
        safe = tele.get("safe")
        if safe:
            status += f"   T {safe['throttle']:+.3f}"
        self.status_var.set(status)
        if "trim" in tele:
            us = tele.get("channels_us") or [0, 0, 0]
            line = f"trim {tele['trim']:+.3f}  learned {tele.get('trim_offset', 0.0):+.3f}  thr {us[2]}us"
            if tele.get("descend"):
                line += f"  descend -{tele['descend']:.3f}"
            line += f"  motion {tele.get('motion', 0.0):.3f}"
            if tele.get("rec"):
                line += "\n● " + tele["rec"]
            self.trim_var.set(line)
        self._refresh_arm(tele.get("arm") or {})
        if self.pipeline.session_active and self.rec_btn.cget("text").startswith("세션 기록 시작"):
            self.rec_btn.config(text="세션 기록 중지 (R)")
        elif not self.pipeline.session_active and self.rec_btn.cget("text").startswith("세션 기록 중지"):
            self.rec_btn.config(text="세션 기록 시작 (R)")
        if self.pipeline.errors:
            self.info(self.pipeline.errors.pop(0))

    def on_close(self):
        self._teardown_pipeline()
        if self.source is not None:
            self.source.release()
        if self.backend is not None:
            self.backend.neutral()
            self.backend.close()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def main():
    args = parse_args()
    if args.list:
        for i, name, probe in probe_devices(args.cap_backend):
            print(f"[{i}] {name} — {probe}")
        return
    App(args).run()


if __name__ == "__main__":
    main()
