import os
import struct
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from buddybox.msp import MSP_STATUS, MspError, arming_disable_names, decode, encode, parse_status


def status_payload(armed, disable_flags=0, extra_flag_bytes=0):
    flags = 1 if armed else 0
    payload = struct.pack("<HHHIBHH", 125, 0, 0b100001, flags, 0, 12, 0)
    payload += bytes([extra_flag_bytes]) + bytes(extra_flag_bytes)
    payload += bytes([26]) + struct.pack("<I", disable_flags) + bytes([0])
    return payload


def frame(cmd, payload, direction=b">"):
    body = bytes([len(payload), cmd]) + payload
    ck = 0
    for b in body:
        ck ^= b
    return b"$M" + direction + body + bytes([ck])


def test_encode_request_matches_msp_v1():
    assert encode(MSP_STATUS) == b"$M<\x00\x65\x65"
    req = encode(200, b"\x01\x02")
    assert req[:3] == b"$M<" and req[3] == 2 and req[4] == 200 and req[-1] == (2 ^ 200 ^ 1 ^ 2)


def test_decode_roundtrip_and_checksum():
    payload = status_payload(True)
    cmd, data = decode(frame(MSP_STATUS, payload))
    assert cmd == MSP_STATUS and data == payload
    bad = bytearray(frame(MSP_STATUS, payload))
    bad[-1] ^= 0xFF
    with pytest.raises(MspError):
        decode(bytes(bad))
    with pytest.raises(MspError):
        decode(frame(MSP_STATUS, b"", direction=b"!"))


def test_parse_status_armed_flag_and_disable_reasons():
    st = parse_status(status_payload(True))
    assert st.armed and st.arming_disable_flags == 0 and st.reasons == []
    flags = (1 << 7) | (1 << 25)
    st = parse_status(status_payload(False, disable_flags=flags))
    assert not st.armed
    assert st.reasons == ["THROTTLE", "ARMSWITCH"]
    st = parse_status(status_payload(False, disable_flags=1 << 8, extra_flag_bytes=2))
    assert st.reasons == ["ANGLE"]


def test_parse_status_tolerates_short_payload():
    st = parse_status(status_payload(True)[:10] + b"\x00")
    assert st.armed and st.arming_disable_flags == 0
    with pytest.raises(MspError):
        parse_status(b"\x00" * 5)


def test_arming_disable_names_unknown_bits():
    assert arming_disable_names(1 << 30) == ["bit30"]
