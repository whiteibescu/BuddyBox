import cv2

FONT = cv2.FONT_HERSHEY_SIMPLEX

C_WHITE = (255, 255, 255)
C_GRAY = (160, 160, 160)
C_GREEN = (0, 255, 0)
C_YELLOW = (0, 255, 255)
C_RED = (0, 0, 255)
C_CYAN = (255, 200, 0)
C_ORANGE = (0, 140, 255)
C_MAGENTA = (255, 0, 255)

STATUS_COLORS = {
    "STANDBY": C_GRAY,
    "HOVER": C_CYAN,
    "TRACKING": C_GREEN,
    "LOST": C_YELLOW,
    "NO TARGET": C_ORANGE,
    "NO VIDEO": C_RED,
}


def _text(img, text, org, scale, color, thick=1):
    cv2.putText(img, text, org, FONT, scale, (0, 0, 0), thick + 2, cv2.LINE_AA)
    cv2.putText(img, text, org, FONT, scale, color, thick, cv2.LINE_AA)


def _dashed_hline(img, y, x0, x1, color, dash=12):
    x = x0
    while x < x1:
        cv2.line(img, (x, y), (min(x1, x + dash), y), color, 1)
        x += dash * 2


def draw_boxes(frame, dets, track, cfg):
    H, W = frame.shape[:2]
    lw = max(1, H // 480)
    fs = max(0.45, H / 1400.0)

    for d in dets:
        if hasattr(d, "x1"):
            x1, y1, x2, y2, conf = d.x1, d.y1, d.x2, d.y2, d.conf
        else:
            conf, x1, y1, x2, y2 = d[0], int(d[1] * W), int(d[2] * H), int(d[3] * W), int(d[4] * H)
        cv2.rectangle(frame, (x1, y1), (x2, y2), C_GRAY, lw)
        _text(frame, f"{conf:.2f}", (x1, max(12, y1 - 4)), fs * 0.8, C_GRAY)

    cx, cy = W // 2, int(cfg.target_y * H)
    dzx, dzy = int(cfg.deadzone_x * W / 2), int(cfg.deadzone_y * H / 2)
    cv2.rectangle(frame, (cx - dzx, cy - dzy), (cx + dzx, cy + dzy), C_CYAN, 1)
    cv2.line(frame, (cx - 20, cy), (cx + 20, cy), C_CYAN, 1)
    cv2.line(frame, (cx, cy - 20), (cx, cy + 20), C_CYAN, 1)
    _dashed_hline(frame, cy, 0, W, C_CYAN)
    _text(frame, f"{cfg.altitude_reference} y={cfg.target_y:.2f}", (cx + dzx + 6, cy - 6), fs * 0.8, C_CYAN)
    th = int(cfg.target_height * H)
    mid = H // 2
    cv2.line(frame, (W - 30, mid - th // 2), (W - 30, mid + th // 2), C_CYAN, 2)
    cv2.line(frame, (W - 36, mid - th // 2), (W - 24, mid - th // 2), C_CYAN, 2)
    cv2.line(frame, (W - 36, mid + th // 2), (W - 24, mid + th // 2), C_CYAN, 2)

    if track is not None:
        lost = getattr(track, "lost", False)
        color = C_YELLOW if lost else C_GREEN
        tcx, tcy, tw, thh = track.cx, track.cy, track.w, track.h
        x1, y1 = int((tcx - tw / 2) * W), int((tcy - thh / 2) * H)
        x2, y2 = int((tcx + tw / 2) * W), int((tcy + thh / 2) * H)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, lw * 2)
        ref_y = y1 if cfg.altitude_reference == "head" else int(tcy * H)
        tx = int(tcx * W)
        cv2.circle(frame, (tx, int(tcy * H)), max(4, lw * 3), color, -1)
        cv2.circle(frame, (tx, ref_y), max(5, lw * 4), C_MAGENTA, 2)
        cv2.line(frame, (cx, cy), (tx, ref_y), color, lw)
        tag = "LOST" if lost else f"TARGET {track.conf:.2f}"
        _text(frame, tag, (x1, max(16, y1 - 8)), fs, color, 2)


def draw_hud(frame, tele):
    H, W = frame.shape[:2]
    fs = max(0.45, H / 1400.0)
    line_h = int(28 * fs * 1.6)
    status = tele.get("status", "")
    color = STATUS_COLORS.get(status, C_WHITE)
    y = line_h
    _text(frame, f"{tele.get('mode', '')} / {status}", (12, y), fs * 1.3, color, 2)
    y += line_h
    _text(frame, f"{tele.get('fps', 0.0):4.1f} fps  det {tele.get('infer_ms', 0.0):5.1f} ms  "
                 f"{tele.get('detector', '')}", (12, y), fs, C_WHITE)
    y += line_h
    err = tele.get("error")
    if err is not None:
        _text(frame, f"err x {err.x:+.2f}  y {err.y:+.2f}  size {err.size:+.2f}", (12, y), fs, C_WHITE)
        y += line_h
    cmd = tele.get("safe")
    if cmd is not None:
        _text(frame, f"R {cmd['roll']:+.2f}  P {cmd['pitch']:+.2f}  Y {cmd['yaw']:+.2f}  T {cmd['throttle']:+.2f}",
              (12, y), fs, C_WHITE)
        y += line_h
    if "trim" in tele:
        desc = tele.get("descend", 0.0)
        line = f"trim {tele['trim']:+.3f} (learned {tele.get('trim_offset', 0.0):+.3f})"
        if desc:
            line += f"  descend -{desc:.3f}"
        _text(frame, line, (12, y), fs, C_YELLOW if desc else C_WHITE)
        y += line_h
    us = tele.get("channels_us")
    if us:
        _text(frame, "us " + " ".join(str(v) for v in us[:5]), (12, y), fs * 0.9, C_GRAY)
        y += line_h
    rec = tele.get("rec")
    if rec:
        cv2.circle(frame, (W - 30, 30), 10, C_RED, -1)
        _text(frame, rec, (W - 60 - int(len(rec) * 12 * fs), 38), fs, C_RED, 2)
    arm = tele.get("arm") or {}
    label = arm.get("label")
    if label:
        colors = {"ARMED": C_GREEN, "DISARMED": C_GRAY, "ARM FAILED": C_RED, "DISARM FAILED": C_RED}
        color = colors.get(label, C_YELLOW)
        text = label if arm.get("verifiable") else f"{label} (unverified)"
        _text(frame, text, (W - 40 - int(len(text) * 14 * fs), 38 + line_h), fs * 1.1, color, 2)
    _draw_sticks(frame, cmd, W, H)


def draw_overlay(frame, dets, track, cfg, tele):
    draw_boxes(frame, dets, track, cfg)
    draw_hud(frame, tele)
    return frame


def _draw_sticks(frame, cmd, W, H):
    if cmd is None:
        return
    size = max(60, H // 8)
    margin = 16
    for k, (ax, ay) in enumerate((("yaw", "throttle"), ("roll", "pitch"))):
        x0 = margin + k * (size + margin)
        y0 = H - margin - size
        cv2.rectangle(frame, (x0, y0), (x0 + size, y0 + size), (90, 90, 90), 1)
        cv2.line(frame, (x0 + size // 2, y0), (x0 + size // 2, y0 + size), (60, 60, 60), 1)
        cv2.line(frame, (x0, y0 + size // 2), (x0 + size, y0 + size // 2), (60, 60, 60), 1)
        px = int(x0 + (cmd[ax] + 1.0) / 2.0 * size)
        py = int(y0 + (1.0 - (cmd[ay] + 1.0) / 2.0) * size)
        cv2.circle(frame, (px, py), max(3, size // 14), C_GREEN, -1)
