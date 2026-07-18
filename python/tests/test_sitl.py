"""Betaflight SITL rc_packet 인코딩 테스트 — 하드웨어/SITL 불필요."""

import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from buddybox import CH_MAX, CH_MID, CH_MIN
from buddybox.sitl import BuddyBoxSitl, build_rc_packet


def test_rc_packet_is_40_bytes():
    assert len(build_rc_packet([CH_MID] * 8, 0.0)) == 40


def test_rc_packet_layout():
    channels = [988, 1200, 1500, 1800, 2012, 1000, 1100, 1300]
    packet = build_rc_packet(channels, 12.5)
    ts, *chans = struct.unpack("<d16H", packet)
    assert ts == 12.5
    assert chans[:8] == channels


def test_missing_channels_padded_with_mid():
    packet = build_rc_packet([1000] * 8, 0.0)
    _, *chans = struct.unpack("<d16H", packet)
    assert chans[8:] == [CH_MID] * 8


def test_out_of_range_clamped():
    packet = build_rc_packet([0, 9999, 1500, 1500, 1500, 1500, 1500, 1500], 0.0)
    _, *chans = struct.unpack("<d16H", packet)
    assert chans[0] == CH_MIN
    assert chans[1] == CH_MAX


def test_sitl_backend_sends_udp_packets():
    import socket

    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx.bind(("127.0.0.1", 0))
    rx.settimeout(2.0)
    port = rx.getsockname()[1]

    with BuddyBoxSitl(host="127.0.0.1", port=port) as bb:
        bb.set_sticks(roll=1.0)
        data, _ = rx.recvfrom(64)

    assert len(data) == 40
    _, *chans = struct.unpack("<d16H", data)
    assert chans[2] == CH_MIN  # 스로틀은 최소로 시작
    rx.close()
