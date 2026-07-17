"""프레임 인코딩 규격 테스트 — 펌웨어(promicro_ppm.ino)의 파서와 일치해야 한다."""

import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from buddybox import CH_MAX, CH_MID, CH_MIN, build_frame, clamp_us, norm_to_us

NEUTRAL = [CH_MID] * 8


def test_frame_length_is_19_bytes():
    assert len(build_frame(NEUTRAL)) == 19


def test_frame_header():
    frame = build_frame(NEUTRAL)
    assert frame[0] == 0xA5
    assert frame[1] == 0x5A


def test_payload_is_little_endian_uint16():
    channels = [988, 1200, 1500, 1800, 2012, 1000, 1100, 1300]
    frame = build_frame(channels)
    assert list(struct.unpack("<8H", frame[2:18])) == channels


def test_checksum_is_xor_of_payload():
    frame = build_frame([1234, 1500, 988, 2012, 1500, 1500, 1500, 1500])
    expected = 0
    for b in frame[2:18]:
        expected ^= b
    assert frame[18] == expected


def test_out_of_range_values_are_clamped():
    frame = build_frame([0, 5000, 1500, 1500, 1500, 1500, 1500, 1500])
    decoded = struct.unpack("<8H", frame[2:18])
    assert decoded[0] == CH_MIN
    assert decoded[1] == CH_MAX


def test_clamp_us_bounds():
    assert clamp_us(0) == CH_MIN
    assert clamp_us(99999) == CH_MAX
    assert clamp_us(1500) == 1500


def test_norm_to_us_endpoints():
    assert norm_to_us(-1.0) == CH_MIN
    assert norm_to_us(0.0) == CH_MID
    assert norm_to_us(1.0) == CH_MAX


def test_norm_to_us_clips_overrange_input():
    assert norm_to_us(-5.0) == CH_MIN
    assert norm_to_us(5.0) == CH_MAX
