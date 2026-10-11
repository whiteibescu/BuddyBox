import argparse
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

for _s in (sys.stdout, sys.stderr):
    if _s is not None and hasattr(_s, "reconfigure"):
        _s.reconfigure(errors="replace")

from buddybox.follow.controller import FollowConfig
from buddybox.follow.session import load_session
from session_replay import apply_overrides, replay


def parse_variant(spec):
    name, sep, rest = spec.partition(":")
    if not sep:
        name, rest = spec, ""
    sets = [s.strip() for s in rest.split(",") if s.strip()]
    return name.strip(), sets


def _mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else 0.0


def _rms(xs):
    xs = list(xs)
    return math.sqrt(_mean(x * x for x in xs)) if xs else 0.0


def _sign_flips(xs):
    flips = 0
    prev = 0
    for x in xs:
        s = 1 if x > 0 else (-1 if x < 0 else 0)
        if s and prev and s != prev:
            flips += 1
        if s:
            prev = s
    return flips


def metrics(trace, cfg):
    tracking = [r for r in trace if r["status"] == "TRACKING"]
    errs_y = [r["err"]["y"] for r in tracking if r["err"]]
    errs_x = [r["err"]["x"] for r in tracking if r["err"]]
    errs_s = [r["err"]["size"] for r in tracking if r["err"]]
    sat = [1 for r in tracking
           if abs(r["raw"]["throttle"] - r["trim"]) >= cfg.max_throttle_delta - 1e-6]
    return {
        "tracking_steps": len(tracking),
        "err_y_rms": round(_rms(errs_y), 3),
        "err_x_rms": round(_rms(errs_x), 3),
        "err_size_mean": round(_mean(errs_s), 3),
        "thr_sat_pct": round(100.0 * len(sat) / max(1, len(tracking)), 1),
        "err_y_flips": _sign_flips(errs_y),
        "err_x_flips": _sign_flips(errs_x),
        "thr_track_mean": round(_mean(r["safe"]["throttle"] for r in tracking), 3),
        "yaw_max": round(max((abs(r["safe"]["yaw"]) for r in tracking), default=0.0), 3),
        "pitch_max": round(max((abs(r["safe"]["pitch"]) for r in tracking), default=0.0), 3),
        "trim_end": round(trace[-1]["trim"], 3) if trace else None,
    }


COLUMNS = [
    ("tracking_steps", "추적 스텝"),
    ("err_y_rms", "err_y RMS"),
    ("err_x_rms", "err_x RMS"),
    ("err_size_mean", "err_size 평균"),
    ("thr_sat_pct", "스로틀 포화 %"),
    ("err_y_flips", "err_y 반전"),
    ("err_x_flips", "err_x 반전"),
    ("thr_track_mean", "스로틀 평균"),
    ("yaw_max", "|yaw| 최대"),
    ("pitch_max", "|pitch| 최대"),
    ("trim_end", "트림 끝"),
]


def plot_sweep(session, results, out_path):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return None
    frames = session["frames"]
    t = [f["t"] for f in frames]
    fig, axes = plt.subplots(3, 1, figsize=(13, 10), sharex=True)
    for i, k in enumerate(("throttle", "yaw", "pitch")):
        axes[i].plot(t, [f["safe"][k] if f.get("safe") else None for f in frames],
                     label="recorded", color="0.75", lw=2)
        for name, trace, _ in results:
            axes[i].plot(t, [r["safe"][k] for r in trace], label=name, lw=1)
        axes[i].set_ylabel(k)
        axes[i].legend(loc="upper right", fontsize=8)
    axes[2].set_xlabel("t (s)")
    fig.suptitle(f"{Path(session['dir']).name} — PID sweep (open loop)")
    fig.tight_layout()
    fig.savefig(out_path, dpi=110)
    plt.close(fig)
    return out_path


def main():
    ap = argparse.ArgumentParser(
        description="기록된 세션에 여러 설정 후보를 재생해 한 표로 비교한다 (개루프)")
    ap.add_argument("session", help="세션 폴더")
    ap.add_argument("--variant", action="append", default=[],
                    help='"이름: key=v,key=v" 형식, 여러 번 지정 가능. 예: --variant "kd up: throttle_kd=0.12"')
    ap.add_argument("--plot", action="store_true", help="sweep.png 오버레이 그래프 생성")
    args = ap.parse_args()

    session = load_session(Path(args.session))
    base_cfg = FollowConfig.from_dict(session["config"])

    variants = [("base", [])] + [parse_variant(v) for v in args.variant]
    results = []
    for name, sets in variants:
        cfg = apply_overrides(base_cfg, sets)
        trace = replay(session, cfg)
        results.append((name, trace, metrics(trace, cfg)))
        print(f"[{name}] 재생 완료 ({len(trace)} 스텝)")

    lines = [f"# PID 스윕 — {Path(args.session).name}", ""]
    header = "| 후보 | " + " | ".join(label for _, label in COLUMNS) + " |"
    lines += [header, "|" + "---|" * (len(COLUMNS) + 1)]
    for name, _, m in results:
        lines.append("| " + name + " | " + " | ".join(str(m[k]) for k, _ in COLUMNS) + " |")
    lines += ["", "설정 후보:", ""]
    for name, sets in variants:
        lines.append(f"- **{name}**: {', '.join(sets) or '(세션 설정 그대로)'}")

    out_md = Path(args.session) / "sweep_report.md"
    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print()
    print("\n".join(lines))
    print(f"\n저장: {out_md}")
    if args.plot:
        p = plot_sweep(session, results, Path(args.session) / "sweep.png")
        if p:
            print(f"그래프: {p}")


if __name__ == "__main__":
    main()
