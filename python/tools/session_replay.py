import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from buddybox.follow.controller import FollowConfig, FollowController
from buddybox.follow.state import FlightSupervisor, Mode
from buddybox.safety import SafetyLimiter
from buddybox.vision.tracker import TargetTracker
from buddybox.follow.session import RAW_VIDEO, load_session


def apply_overrides(cfg, sets):
    data = cfg.to_dict()
    for item in sets or []:
        key, _, value = item.partition("=")
        key = key.strip()
        if key not in data:
            sys.exit(f"알 수 없는 설정 키: {key}")
        cur = data[key]
        if isinstance(cur, bool):
            data[key] = value.strip().lower() in ("1", "true", "yes", "on")
        elif isinstance(cur, (int, float)):
            data[key] = float(value)
        else:
            data[key] = value.strip()
    return FollowConfig.from_dict(data)


def redetect(session, model, conf, every, threads=None):
    import cv2

    from buddybox.vision.detector import OnnxDetector

    det = OnnxDetector(model, threads=threads)
    det.warmup()
    cap = cv2.VideoCapture(str(session["dir"] / RAW_VIDEO))
    per_seq = {}
    last_index = None
    counter = 0
    for rec in session["frames"]:
        if not rec.get("new"):
            continue
        counter += 1
        if counter % max(1, every) != 0:
            continue
        idx = rec.get("rec_frame", 0)
        if idx != last_index:
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            last_index = idx
        ok, frame = cap.read()
        if not ok:
            continue
        H, W = frame.shape[:2]
        people = [d for d in det(frame, conf) if d.label == "person"]
        per_seq[rec["seq"]] = [(d.conf, d.x1 / W, d.y1 / H, d.x2 / W, d.y2 / H) for d in people]
    cap.release()
    return per_seq


def replay(session, cfg, redetected=None):
    tracker = TargetTracker(lost_after_s=cfg.lost_after_s)
    controller = FollowController(cfg)
    supervisor = FlightSupervisor(controller)
    limiter = SafetyLimiter(max_tilt=cfg.max_tilt, max_yaw=cfg.max_yaw, max_throttle=cfg.max_throttle,
                            max_rate_per_s=cfg.max_rate_per_s, max_throttle_rate_per_s=cfg.max_throttle_rate_per_s)
    trace = []
    last_det = None
    for rec in session["frames"]:
        t = rec["t"]
        mode = rec.get("mode") or Mode.STANDBY.value
        if supervisor.mode.value != mode:
            supervisor.set_mode(mode)
        if redetected is not None:
            boxes = redetected.get(rec["seq"]) if rec.get("new") else None
            if boxes is not None:
                track = tracker.update([tuple(b) for b in boxes], t)
            else:
                track = tracker.peek(t)
        else:
            det_seq = rec.get("det_seq")
            if det_seq is not None and det_seq != last_det:
                last_det = det_seq
                track = tracker.update([tuple(p) for p in rec.get("persons") or []], t)
            else:
                track = tracker.peek(t)
        raw, status = supervisor.step(track, bool(rec.get("video_ok", True)), t)
        safe = limiter.apply(raw, t)
        err = controller.last_error if status.value == "TRACKING" else None
        trace.append({
            "t": t, "mode": mode, "status": status.value,
            "track": None if track is None else {"cx": track.cx, "cy": track.cy, "w": track.w, "h": track.h,
                                                 "lost": track.lost},
            "err": None if err is None else {"x": err.x, "y": err.y, "size": err.size},
            "raw": {"roll": raw.roll, "pitch": raw.pitch, "yaw": raw.yaw, "throttle": raw.throttle},
            "safe": safe,
            "trim": controller.effective_trim, "trim_offset": controller.trim_offset,
            "descend": supervisor.descend,
        })
    return trace


def _mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else 0.0


def compare(frames, trace):
    keys = ("throttle", "yaw", "pitch")
    out = {}
    for k in keys:
        diffs = []
        for rec, rep in zip(frames, trace):
            if rec.get("safe") and rep.get("safe"):
                diffs.append(rep["safe"][k] - rec["safe"][k])
        out[k] = {"mean_diff": round(_mean(diffs), 4), "max_abs_diff": round(max((abs(d) for d in diffs), default=0.0), 4),
                  "rms": round(math.sqrt(_mean(d * d for d in diffs)), 4) if diffs else 0.0}
    status_same = sum(1 for rec, rep in zip(frames, trace) if rec.get("status") == rep.get("status"))
    out["status_agreement_pct"] = round(100.0 * status_same / max(1, len(trace)), 1)
    tracking = [rep for rep in trace if rep["status"] == "TRACKING"]
    out["replay_tracking_steps"] = len(tracking)
    out["replay_throttle"] = {
        "min": round(min((r["safe"]["throttle"] for r in trace), default=0.0), 3),
        "max": round(max((r["safe"]["throttle"] for r in trace), default=0.0), 3),
        "tracking_mean": round(_mean(r["safe"]["throttle"] for r in tracking), 3),
    }
    out["replay_trim_end"] = round(trace[-1]["trim"], 3) if trace else None
    out["replay_yaw_max_abs"] = round(max((abs(r["safe"]["yaw"]) for r in tracking), default=0.0), 3)
    out["replay_pitch_max_abs"] = round(max((abs(r["safe"]["pitch"]) for r in tracking), default=0.0), 3)
    return out


def plot_compare(session, trace, out_path, name):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return None
    frames = session["frames"]
    t = [f["t"] for f in frames]
    fig, axes = plt.subplots(3, 1, figsize=(12, 9), sharex=True)
    for i, k in enumerate(("throttle", "yaw", "pitch")):
        axes[i].plot(t, [f["safe"][k] if f.get("safe") else None for f in frames], label=f"recorded {k}", color="tab:gray")
        axes[i].plot(t, [r["safe"][k] for r in trace], label=f"replay {k} ({name})", color="tab:red")
        axes[i].set_ylabel(k)
        axes[i].legend(loc="upper right", fontsize=8)
    axes[0].plot(t, [r["trim"] for r in trace], label="replay trim", color="tab:orange", ls="--")
    axes[0].legend(loc="upper right", fontsize=8)
    axes[2].set_xlabel("t (s)")
    fig.suptitle(f"{Path(session['dir']).name} - replay '{name}' (open loop: same detections, controller output only)")
    fig.tight_layout()
    fig.savefig(out_path, dpi=110)
    plt.close(fig)
    return out_path


def main():
    ap = argparse.ArgumentParser(
        description="기록된 세션의 검출 결과에 다른 설정(PID 등)으로 컨트롤러를 다시 돌려 비교 (개루프)")
    ap.add_argument("session", help="세션 폴더")
    ap.add_argument("--config", default=None, help="대체 설정 JSON (기본: 세션의 config.json)")
    ap.add_argument("--set", action="append", default=[], help="설정 덮어쓰기, 예: --set throttle_kp=0.15")
    ap.add_argument("--name", default="replay", help="출력 이름")
    ap.add_argument("--plot", action="store_true")
    ap.add_argument("--redetect", action="store_true", help="raw.mp4 로 검출을 다시 수행 (느림)")
    ap.add_argument("--model", default=None)
    ap.add_argument("--conf", type=float, default=None)
    ap.add_argument("--every", type=int, default=None)
    args = ap.parse_args()

    session = load_session(args.session)
    base = FollowConfig.load(args.config) if args.config else FollowConfig.from_dict(session["config"])
    cfg = apply_overrides(base, args.set)

    redetected = None
    if args.redetect:
        from buddybox.vision.detector import find_default_model

        model = Path(args.model) if args.model else find_default_model()
        det_info = session["meta"].get("detector", {})
        conf = args.conf if args.conf is not None else float(det_info.get("conf", 0.5))
        every = args.every if args.every is not None else int(det_info.get("every", 2))
        print(f"재검출: {model.name} conf={conf} every={every} …")
        redetected = redetect(session, model, conf, every)

    trace = replay(session, cfg, redetected)
    result = compare(session["frames"], trace)
    out_dir = Path(args.session)
    (out_dir / f"replay_{args.name}.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in trace) + "\n", encoding="utf-8")
    (out_dir / f"replay_{args.name}.config.json").write_text(
        json.dumps(cfg.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    print("주의: 개루프 비교입니다. 같은 검출 입력에 대해 컨트롤러 출력만 달라지며, 기체 움직임은 반영되지 않습니다.")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.plot:
        p = plot_compare(session, trace, out_dir / f"replay_{args.name}.png", args.name)
        print("plot:", p or "(matplotlib 없음)")


if __name__ == "__main__":
    main()
