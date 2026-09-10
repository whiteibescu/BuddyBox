import argparse
import csv
import json
import math
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from buddybox.follow.controller import FollowConfig
from buddybox.follow.session import RAW_VIDEO, load_session

STATUS_ORDER = ["TRACKING", "LOST", "NO TARGET", "NO VIDEO", "HOVER", "STANDBY"]


def _mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else 0.0


def _std(xs):
    xs = list(xs)
    if len(xs) < 2:
        return 0.0
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def _minmax(xs):
    xs = list(xs)
    return (min(xs), max(xs)) if xs else (0.0, 0.0)


def segments(frames, key="status"):
    out = []
    for f in frames:
        v = f.get(key)
        if out and out[-1]["value"] == v:
            out[-1]["end"] = f["t"]
            out[-1]["steps"] += 1
        else:
            out.append({"value": v, "start": f["t"], "end": f["t"], "steps": 1})
    return out


MOTION_THRESHOLD = 0.015
MOTION_HOLD_S = 2.0


def active_segments(frames, threshold=None, hold_s=MOTION_HOLD_S):
    if threshold is None:
        threshold = MOTION_THRESHOLD
    segs = []
    cur = None
    last_hot = None
    for f in frames:
        if not f.get("new"):
            continue
        t = f["t"]
        hot = f.get("motion", 0.0) >= threshold
        if hot:
            last_hot = t
            if cur is None:
                cur = {"start": t, "end": t}
            else:
                cur["end"] = t
        elif cur is not None and last_hot is not None and t - last_hot > hold_s:
            segs.append(cur)
            cur = None
    if cur is not None:
        segs.append(cur)
    return [{"start": round(s["start"], 2), "end": round(s["end"], 2)} for s in segs if s["end"] - s["start"] >= 1.0]


def zero_crossings(values, times):
    crossings = []
    prev = None
    for v, t in zip(values, times):
        if v == 0.0:
            continue
        s = v > 0
        if prev is not None and s != prev:
            crossings.append(t)
        prev = s
    if len(crossings) < 2:
        return len(crossings), None
    gaps = [b - a for a, b in zip(crossings, crossings[1:])]
    return len(crossings), 2.0 * _mean(gaps)


def summarize(session):
    frames = session["frames"]
    cfg = session["config"]
    meta = session["meta"]
    if not frames:
        return {"error": "frames.jsonl 이 비어 있습니다"}
    duration = frames[-1]["t"] - frames[0]["t"]
    by_status = {}
    for f in frames:
        by_status[f["status"]] = by_status.get(f["status"], 0) + 1
    tracking = [f for f in frames if f["status"] == "TRACKING" and f.get("err")]
    times = [f["t"] for f in tracking]
    err_x = [f["err"]["x"] for f in tracking]
    err_y = [f["err"]["y"] for f in tracking]
    err_s = [f["err"]["size"] for f in tracking]
    raw_y = [f["err"]["raw_y"] for f in tracking]
    thr = [f["safe"]["throttle"] for f in frames if f.get("safe")]
    thr_track = [f["safe"]["throttle"] for f in tracking if f.get("safe")]
    yaw = [f["safe"]["yaw"] for f in tracking if f.get("safe")]
    pitch = [f["safe"]["pitch"] for f in tracking if f.get("safe")]
    delta_lim = float(cfg.get("max_throttle_delta", 0.12))
    sat = 0
    for f in tracking:
        if f.get("raw") and abs(f["raw"]["throttle"] - f.get("trim", 0.0)) >= delta_lim - 1e-6:
            sat += 1
    zc_y, period_y = zero_crossings(err_y, times)
    zc_x, period_x = zero_crossings(err_x, times)
    trims = [f.get("trim", 0.0) for f in frames]
    offsets = [f.get("trim_offset", 0.0) for f in frames]
    descends = [f.get("descend", 0.0) for f in frames]
    persons = [len(f.get("persons") or []) for f in frames if f.get("new")]
    infer = [f["infer_ms"] for f in frames if f.get("infer_ms")]
    fps = [f["fps"] for f in frames if f.get("fps")]
    motion = [f.get("motion", 0.0) for f in frames if f.get("new")]
    active = active_segments(frames)
    return {
        "motion": {"mean": round(_mean(motion), 4), "max": round(max(motion), 4) if motion else 0.0,
                   "active_pct": round(100.0 * sum(s["end"] - s["start"] for s in active) / duration, 1) if duration > 0 else 0.0},
        "active_segments": active,
        "dir": str(session["dir"]),
        "started": meta.get("started"),
        "source": meta.get("source"),
        "detector": meta.get("detector", {}),
        "frame_size": meta.get("frame_size"),
        "duration_s": round(duration, 2),
        "steps": len(frames),
        "control_hz": round(len(frames) / duration, 1) if duration > 0 else 0.0,
        "video_fps_mean": round(_mean(fps), 1),
        "infer_ms_mean": round(_mean(infer), 1),
        "status_share": {k: round(100.0 * v / len(frames), 1) for k, v in sorted(by_status.items())},
        "persons_mean": round(_mean(persons), 2),
        "persons_zero_pct": round(100.0 * sum(1 for p in persons if p == 0) / len(persons), 1) if persons else 0.0,
        "tracking_steps": len(tracking),
        "err_x": {"mean": round(_mean(err_x), 3), "std": round(_std(err_x), 3)},
        "err_y": {"mean": round(_mean(err_y), 3), "std": round(_std(err_y), 3),
                  "raw_mean": round(_mean(raw_y), 3)},
        "err_size": {"mean": round(_mean(err_s), 3), "std": round(_std(err_s), 3)},
        "throttle": {"min": round(_minmax(thr)[0], 3), "max": round(_minmax(thr)[1], 3),
                     "tracking_mean": round(_mean(thr_track), 3)},
        "yaw": {"mean_abs": round(_mean(abs(v) for v in yaw), 3), "max_abs": round(max((abs(v) for v in yaw), default=0.0), 3)},
        "pitch": {"mean": round(_mean(pitch), 3), "max_abs": round(max((abs(v) for v in pitch), default=0.0), 3)},
        "throttle_saturation_pct": round(100.0 * sat / len(tracking), 1) if tracking else 0.0,
        "osc_y": {"zero_crossings": zc_y, "period_s": None if period_y is None else round(period_y, 2)},
        "osc_x": {"zero_crossings": zc_x, "period_s": None if period_x is None else round(period_x, 2)},
        "trim": {"start": round(trims[0], 3), "end": round(trims[-1], 3),
                 "offset_end": round(offsets[-1], 3), "offset_min": round(min(offsets), 3),
                 "offset_max": round(max(offsets), 3)},
        "descend_max": round(max(descends), 3),
        "config": {k: cfg.get(k) for k in ("hover_throttle", "throttle_mode", "altitude_reference", "target_y",
                                           "target_height", "throttle_kp", "throttle_ki", "throttle_kd",
                                           "lateral_kp", "lateral_kd", "pitch_kp", "pitch_kd",
                                           "max_throttle_delta", "trim_learning", "trim_learn_rate",
                                           "lost_descend_rate", "altitude_assist", "distance_hold")},
        "events": [e for e in session["events"] if e.get("kind") != "config"],
        "segments": [s for s in segments(frames) if s["end"] - s["start"] >= 0.2 or s["steps"] >= 3],
    }


def render_markdown(s):
    if "error" in s:
        return f"# 세션 리포트\n\n{s['error']}\n"
    lines = [f"# 세션 리포트 — {Path(s['dir']).name}", ""]
    lines += [f"- 시작: {s['started']}  소스: `{s['source']}`  프레임: {s['frame_size']}",
              f"- 검출기: {s['detector'].get('name')} ({s['detector'].get('provider')}, threads={s['detector'].get('threads')}, conf={s['detector'].get('conf')}, every={s['detector'].get('every')})",
              f"- 길이 {s['duration_s']}s · 제어 스텝 {s['steps']} ({s['control_hz']} Hz) · 영상 {s['video_fps_mean']} fps · 추론 {s['infer_ms_mean']} ms",
              f"- 사람 검출 평균 {s['persons_mean']}명, 0명 프레임 {s['persons_zero_pct']}%",
              f"- 화면 움직임 평균 {s['motion']['mean']} / 최대 {s['motion']['max']} · 움직임 구간 {s['motion']['active_pct']}%: "
              + (", ".join(f"{a['start']}~{a['end']}s" for a in s["active_segments"]) or "없음"), ""]
    lines += ["## 상태 비율", "", "| 상태 | % |", "|---|---|"]
    for k in STATUS_ORDER:
        if k in s["status_share"]:
            lines.append(f"| {k} | {s['status_share'][k]} |")
    lines += ["", "## 추적 구간 통계 (TRACKING 만)", ""]
    if s["tracking_steps"] == 0:
        lines.append("추적 구간 없음")
    else:
        lines += ["| 항목 | 값 |", "|---|---|",
                  f"| 스텝 수 | {s['tracking_steps']} |",
                  f"| err_x 평균/표준편차 | {s['err_x']['mean']:+.3f} / {s['err_x']['std']:.3f} |",
                  f"| err_y 평균/표준편차 (raw 평균) | {s['err_y']['mean']:+.3f} / {s['err_y']['std']:.3f} ({s['err_y']['raw_mean']:+.3f}) |",
                  f"| err_size 평균/표준편차 | {s['err_size']['mean']:+.3f} / {s['err_size']['std']:.3f} |",
                  f"| 스로틀 min / max / 추적중 평균 | {s['throttle']['min']:+.3f} / {s['throttle']['max']:+.3f} / {s['throttle']['tracking_mean']:+.3f} |",
                  f"| 스로틀 보정 포화 비율 | {s['throttle_saturation_pct']}% |",
                  f"| yaw 평균 절댓값 / 최대 | {s['yaw']['mean_abs']:.3f} / {s['yaw']['max_abs']:.3f} |",
                  f"| pitch 평균 / 최대 절댓값 | {s['pitch']['mean']:+.3f} / {s['pitch']['max_abs']:.3f} |",
                  f"| err_y 부호 전환 / 추정 주기 | {s['osc_y']['zero_crossings']} / {s['osc_y']['period_s']} s |",
                  f"| err_x 부호 전환 / 추정 주기 | {s['osc_x']['zero_crossings']} / {s['osc_x']['period_s']} s |"]
    lines += ["", "## 호버 트림", "",
              f"- trim 시작 {s['trim']['start']:+.3f} → 끝 {s['trim']['end']:+.3f} (학습 오프셋 끝 {s['trim']['offset_end']:+.3f}, 범위 {s['trim']['offset_min']:+.3f}~{s['trim']['offset_max']:+.3f})",
              f"- LOST 하강 최대 {s['descend_max']:.3f}", ""]
    lines += ["## 설정 (주요)", "", "```json", json.dumps(s["config"], indent=2, ensure_ascii=False), "```", ""]
    lines += ["## 상태 타임라인", "", "| 시작(s) | 끝(s) | 상태 | 스텝 |", "|---|---|---|---|"]
    for seg in s["segments"]:
        lines.append(f"| {seg['start']:.1f} | {seg['end']:.1f} | {seg['value']} | {seg['steps']} |")
    lines += ["", "## 이벤트", ""]
    for e in s["events"]:
        extra = {k: v for k, v in e.items() if k not in ("t", "kind")}
        lines.append(f"- {e['t']:.1f}s `{e['kind']}` {json.dumps(extra, ensure_ascii=False) if extra else ''}")
    lines.append("")
    return "\n".join(lines)


def _track_ns(rec):
    t = rec.get("track")
    if not t:
        return None
    return SimpleNamespace(**t)


def frame_at(cap, index, cache):
    if cache.get("index") == index:
        return cache["frame"]
    import cv2

    cap.set(cv2.CAP_PROP_POS_FRAMES, index)
    ok, frame = cap.read()
    if not ok:
        return None
    cache["index"], cache["frame"] = index, frame
    return frame


def render_frame(session, rec, cap, cache, cfg):
    import cv2

    from buddybox.follow.overlay import draw_boxes, draw_hud

    frame = frame_at(cap, rec.get("rec_frame", 0), cache)
    if frame is None:
        return None
    img = frame.copy()
    persons = [tuple(p) for p in rec.get("persons") or []]
    draw_boxes(img, persons, _track_ns(rec), cfg)
    err = rec.get("err")
    tele = {
        "mode": rec.get("mode"), "status": rec.get("status"), "fps": rec.get("fps", 0.0),
        "infer_ms": rec.get("infer_ms", 0.0), "detector": "",
        "error": SimpleNamespace(**err) if err else None,
        "safe": rec.get("safe"), "channels_us": rec.get("us"),
        "trim": rec.get("trim", 0.0), "trim_offset": rec.get("trim_offset", 0.0), "descend": rec.get("descend", 0.0),
    }
    draw_hud(img, tele)
    cv2.putText(img, f"t={rec['t']:.2f}s  seq={rec.get('seq')}  rec_frame={rec.get('rec_frame')}",
                (12, img.shape[0] - 12), cv2.FONT_HERSHEY_SIMPLEX, max(0.45, img.shape[0] / 1400.0),
                (255, 255, 255), 1, cv2.LINE_AA)
    return img


def pick_frames(frames, n, statuses=None):
    pool = [f for f in frames if f.get("new")]
    if statuses:
        chosen = [f for f in pool if f["status"] in statuses]
        if not chosen:
            active = active_segments(frames)
            chosen = [f for f in pool if any(a["start"] <= f["t"] <= a["end"] for a in active)]
        if chosen:
            pool = chosen
    if not pool:
        return []
    if n >= len(pool):
        return pool
    step = (len(pool) - 1) / float(n - 1) if n > 1 else 0
    return [pool[int(round(i * step))] for i in range(n)]


def contact_sheet(session, out_path, n=12, cols=4, tile_w=480, statuses=("TRACKING", "LOST")):
    import cv2
    import numpy as np

    raw = session["dir"] / RAW_VIDEO
    cap = cv2.VideoCapture(str(raw))
    if not cap.isOpened():
        raise RuntimeError(f"raw 영상을 열 수 없습니다: {raw}")
    cfg = FollowConfig.from_dict(session["config"])
    picks = pick_frames(session["frames"], n, statuses)
    cache = {}
    tiles = []
    for rec in picks:
        img = render_frame(session, rec, cap, cache, cfg)
        if img is None:
            continue
        h, w = img.shape[:2]
        tile_h = int(tile_w * h / w)
        tile = cv2.resize(img, (tile_w, tile_h), interpolation=cv2.INTER_AREA)
        cv2.rectangle(tile, (0, 0), (tile_w - 1, tile_h - 1), (80, 80, 80), 1)
        tiles.append(tile)
    cap.release()
    if not tiles:
        return None
    tile_h = tiles[0].shape[0]
    rows = int(math.ceil(len(tiles) / float(cols)))
    sheet = np.zeros((rows * tile_h, cols * tile_w, 3), dtype=np.uint8)
    for i, tile in enumerate(tiles):
        r, c = divmod(i, cols)
        sheet[r * tile_h:(r + 1) * tile_h, c * tile_w:(c + 1) * tile_w] = tile
    cv2.imwrite(str(out_path), sheet)
    return out_path


def export_frames(session, times, out_dir):
    import cv2

    raw = session["dir"] / RAW_VIDEO
    cap = cv2.VideoCapture(str(raw))
    cfg = FollowConfig.from_dict(session["config"])
    cache = {}
    paths = []
    frames = [f for f in session["frames"] if f.get("new")]
    for t in times:
        rec = min(frames, key=lambda f: abs(f["t"] - t))
        img = render_frame(session, rec, cap, cache, cfg)
        if img is None:
            continue
        p = Path(out_dir) / f"frame_{rec['t']:07.2f}s.png"
        cv2.imwrite(str(p), img)
        paths.append(p)
    cap.release()
    return paths


def plot(session, out_path):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return None
    frames = session["frames"]
    t = [f["t"] for f in frames]
    thr = [f["safe"]["throttle"] if f.get("safe") else None for f in frames]
    trim = [f.get("trim") for f in frames]
    err_y = [f["err"]["y"] if f.get("err") else None for f in frames]
    err_x = [f["err"]["x"] if f.get("err") else None for f in frames]
    err_s = [f["err"]["size"] if f.get("err") else None for f in frames]
    yaw = [f["safe"]["yaw"] if f.get("safe") else None for f in frames]
    pitch = [f["safe"]["pitch"] if f.get("safe") else None for f in frames]
    motion = [f.get("motion", 0.0) if f.get("new") else None for f in frames]
    fig, axes = plt.subplots(4, 1, figsize=(12, 11), sharex=True,
                             gridspec_kw={"height_ratios": [3, 2, 2, 1]})
    colors = {"TRACKING": "#c8f7c5", "LOST": "#fff3b0", "NO TARGET": "#ffd8a8", "NO VIDEO": "#ffb3b3",
              "HOVER": "#cfe8ff", "STANDBY": "#e0e0e0"}
    for seg in segments(frames):
        for ax in axes:
            ax.axvspan(seg["start"], seg["end"], color=colors.get(seg["value"], "#eeeeee"), alpha=0.6, lw=0)
    axes[0].plot(t, thr, label="throttle (safe)", color="tab:red")
    axes[0].plot(t, trim, label="trim (learned)", color="tab:orange", ls="--")
    axes[0].plot(t, err_y, label="err_y", color="tab:blue")
    axes[0].set_ylabel("throttle / err_y")
    axes[0].legend(loc="upper right", fontsize=8)
    axes[1].plot(t, yaw, label="yaw", color="tab:red")
    axes[1].plot(t, err_x, label="err_x", color="tab:blue")
    axes[1].set_ylabel("yaw / err_x")
    axes[1].legend(loc="upper right", fontsize=8)
    axes[2].plot(t, pitch, label="pitch", color="tab:red")
    axes[2].plot(t, err_s, label="err_size", color="tab:blue")
    axes[2].set_ylabel("pitch / err_size")
    axes[2].legend(loc="upper right", fontsize=8)
    axes[3].plot(t, motion, label="motion", color="tab:purple")
    axes[3].axhline(MOTION_THRESHOLD, color="tab:purple", ls=":", lw=0.8)
    axes[3].set_ylabel("motion")
    axes[3].set_xlabel("t (s)")
    axes[3].legend(loc="upper right", fontsize=8)
    for e in session["events"]:
        if e.get("kind") in ("mode", "panic", "trim_adopt", "trim_reset", "arm", "disarm", "arm_result"):
            for ax in axes:
                ax.axvline(e["t"], color="k", lw=0.6, alpha=0.5)
            axes[0].text(e["t"], axes[0].get_ylim()[1], e.get("mode", e["kind"]), fontsize=7, rotation=90, va="top")
    fig.suptitle(Path(session["dir"]).name)
    fig.tight_layout()
    fig.savefig(out_path, dpi=110)
    plt.close(fig)
    return out_path


def export_csv(session, out_path):
    frames = session["frames"]
    cols = ["t", "seq", "det_seq", "new", "rec_frame", "mode", "status", "fps", "infer_ms", "video_ok", "motion",
            "arm", "n_persons", "track_cx", "track_cy", "track_w", "track_h", "track_conf", "track_age", "track_lost",
            "err_x", "err_y", "err_size", "raw_x", "raw_y", "raw_size",
            "raw_roll", "raw_pitch", "raw_yaw", "raw_throttle", "roll", "pitch", "yaw", "throttle",
            "trim", "trim_offset", "descend", "ch1", "ch2", "ch3", "ch4", "ch5"]
    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for f in frames:
            tr = f.get("track") or {}
            err = f.get("err") or {}
            raw = f.get("raw") or {}
            safe = f.get("safe") or {}
            us = f.get("us") or [None] * 5
            w.writerow([f.get("t"), f.get("seq"), f.get("det_seq"), f.get("new"), f.get("rec_frame"), f.get("mode"),
                        f.get("status"), f.get("fps"), f.get("infer_ms"), f.get("video_ok"), f.get("motion"),
                        f.get("arm"), len(f.get("persons") or []), tr.get("cx"), tr.get("cy"), tr.get("w"), tr.get("h"),
                        tr.get("conf"), tr.get("age"), tr.get("lost"),
                        err.get("x"), err.get("y"), err.get("size"), err.get("raw_x"), err.get("raw_y"), err.get("raw_size"),
                        raw.get("roll"), raw.get("pitch"), raw.get("yaw"), raw.get("throttle"),
                        safe.get("roll"), safe.get("pitch"), safe.get("yaw"), safe.get("throttle"),
                        f.get("trim"), f.get("trim_offset"), f.get("descend"),
                        us[0], us[1], us[2], us[3], us[4] if len(us) > 4 else None])
    return out_path


def latest_session(root):
    sessions = sorted(Path(root).glob("session_*"))
    return sessions[-1] if sessions else None


def main():
    global MOTION_THRESHOLD
    ap = argparse.ArgumentParser(description="BuddyBox 세션 리포트 (요약 + 프레임 격자 + 그래프 + CSV)")
    ap.add_argument("session", nargs="?", default=None, help="세션 폴더 (생략 시 python/recordings 의 최신 세션)")
    ap.add_argument("--sheet", nargs="?", const=12, type=int, default=None, help="프레임 격자 이미지 (N장, 기본 12)")
    ap.add_argument("--sheet-status", default="TRACKING,LOST", help="격자에 우선 담을 상태 (쉼표), all=전부")
    ap.add_argument("--frames", default=None, help="내보낼 시각(초) 목록, 예: 3.5,12,40.2")
    ap.add_argument("--plot", action="store_true", help="plot.png 생성 (matplotlib 필요)")
    ap.add_argument("--csv", action="store_true", help="frames.csv 생성")
    ap.add_argument("--json", action="store_true", help="요약을 JSON 으로 stdout 출력")
    ap.add_argument("--out", default=None, help="출력 폴더 (기본: 세션 폴더)")
    ap.add_argument("--motion-threshold", type=float, default=MOTION_THRESHOLD,
                    help="움직임 구간 판정 임계값 (VRX 실측: 정지 0.0003, 비행 ~0.02)")
    args = ap.parse_args()
    MOTION_THRESHOLD = args.motion_threshold

    root = Path(__file__).resolve().parent.parent / "recordings"
    session_dir = Path(args.session) if args.session else latest_session(root)
    if session_dir is None or not session_dir.exists():
        sys.exit(f"세션 폴더가 없습니다: {session_dir or root}")
    session = load_session(session_dir)
    out_dir = Path(args.out) if args.out else session_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    summary = summarize(session)
    md = render_markdown(summary)
    (out_dir / "report.md").write_text(md, encoding="utf-8")
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    else:
        print(md)
    made = [out_dir / "report.md"]
    if args.sheet:
        statuses = None if args.sheet_status == "all" else tuple(s.strip() for s in args.sheet_status.split(","))
        p = contact_sheet(session, out_dir / "sheet.png", n=args.sheet, statuses=statuses)
        if p:
            made.append(p)
    if args.frames:
        times = [float(x) for x in args.frames.split(",") if x.strip()]
        made += export_frames(session, times, out_dir)
    if args.plot:
        p = plot(session, out_dir / "plot.png")
        made.append(p if p else "(matplotlib 없음 → plot 생략)")
    if args.csv:
        made.append(export_csv(session, out_dir / "frames.csv"))
    print("생성:", ", ".join(str(m) for m in made))


if __name__ == "__main__":
    main()
