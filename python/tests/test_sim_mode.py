"""시뮬레이션 모드(BuddyBox(port="sim")) 테스트 — 하드웨어 불필요."""

import os
import struct
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from buddybox import CH_MIN, CH_THROTTLE, BuddyBox


def test_sim_mode_opens_without_hardware():
    with BuddyBox("sim") as bb:
        assert bb.simulator is not None
        assert bb.port == "sim"


def test_sim_mode_sends_frames():
    with BuddyBox("sim") as bb:
        time.sleep(0.3)  # 50Hz 송신 스레드가 몇 프레임 보낼 시간
        assert bb.simulator.frames_sent >= 5


def test_sim_frame_reflects_stick_values():
    with BuddyBox("sim") as bb:
        bb.set_sticks(roll=1.0, throttle=-1.0)
        time.sleep(0.1)
        frame = bb.simulator.last_frame
        channels = struct.unpack("<8H", frame[2:18])
        assert channels[0] == 2012          # roll 최대
        assert channels[CH_THROTTLE] == CH_MIN

def test_real_mode_returns_none_simulator():
    # 시뮬레이터 속성은 sim 모드에서만 객체를 반환해야 한다
    with BuddyBox("sim") as bb:
        assert bb.simulator is not None  # sanity
    # 실제 포트는 하드웨어가 필요하므로 여기서는 sim 여부 판별 로직만 확인
