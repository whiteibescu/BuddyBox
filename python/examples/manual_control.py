"""수동 조종 테스트 GUI (tkinter 슬라이더 + 키보드).

실행:
    python manual_control.py [COM포트]

키보드:
    W/S  : Throttle 증감        방향키 ↑/↓ : Pitch
    A/D  : Yaw 좌/우            방향키 ←/→ : Roll
    Space: 즉시 중립 (스로틀 최소)
"""

import sys
import tkinter as tk

sys.path.insert(0, "..")  # buddybox 패키지 (python/ 기준)
from buddybox import BuddyBox, CH_ROLL, CH_PITCH, CH_THROTTLE, CH_YAW

STEP = 0.05  # 키 1회당 변화량

AXES = [
    ("Roll",     CH_ROLL),
    ("Pitch",    CH_PITCH),
    ("Throttle", CH_THROTTLE),
    ("Yaw",      CH_YAW),
]


def main():
    port = sys.argv[1] if len(sys.argv) > 1 else None
    bb = BuddyBox(port)
    print(f"연결됨: {bb.port} — 50Hz 송신 중")

    root = tk.Tk()
    root.title(f"BuddyBox manual control ({bb.port})")

    sliders = {}
    labels = {}

    def on_slide(ch):
        def handler(value):
            bb.set_channel(ch, float(value))
        return handler

    for row, (name, ch) in enumerate(AXES):
        tk.Label(root, text=name, width=9, anchor="w").grid(row=row, column=0, padx=6)
        s = tk.Scale(
            root, from_=-1.0, to=1.0, resolution=0.01, orient="horizontal",
            length=320, showvalue=False, command=on_slide(ch),
        )
        s.set(-1.0 if ch == CH_THROTTLE else 0.0)
        s.grid(row=row, column=1, pady=3)
        lbl = tk.Label(root, text="", width=8)
        lbl.grid(row=row, column=2, padx=6)
        sliders[ch] = s
        labels[ch] = lbl

    def nudge(ch, delta):
        sliders[ch].set(max(-1.0, min(1.0, sliders[ch].get() + delta)))

    def panic(_event=None):
        for _, ch in AXES:
            sliders[ch].set(-1.0 if ch == CH_THROTTLE else 0.0)
        bb.neutral()

    tk.Label(
        root, text="W/S=Thr  A/D=Yaw  화살표=Roll/Pitch  Space=중립", fg="gray"
    ).grid(row=len(AXES), column=0, columnspan=3, pady=(4, 8))

    root.bind("w", lambda e: nudge(CH_THROTTLE, +STEP))
    root.bind("s", lambda e: nudge(CH_THROTTLE, -STEP))
    root.bind("a", lambda e: nudge(CH_YAW, -STEP))
    root.bind("d", lambda e: nudge(CH_YAW, +STEP))
    root.bind("<Up>",    lambda e: nudge(CH_PITCH, +STEP))
    root.bind("<Down>",  lambda e: nudge(CH_PITCH, -STEP))
    root.bind("<Left>",  lambda e: nudge(CH_ROLL, -STEP))
    root.bind("<Right>", lambda e: nudge(CH_ROLL, +STEP))
    root.bind("<space>", panic)

    def refresh():
        us = bb.get_channels_us()
        for _, ch in AXES:
            labels[ch].config(text=f"{us[ch]} µs")
        root.after(100, refresh)

    refresh()

    def on_close():
        bb.neutral()
        bb.close()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
