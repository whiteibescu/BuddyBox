import os
import struct
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from buddybox.msp import (MSP_DEBUG, MSP_SONAR_ALTITUDE, MSP_STATUS, MspClient, MspError, MspSerial,
                          arming_disable_names, decode, encode, open_msp, parse_altitude, parse_attitude,
                          parse_debug, parse_sonar_altitude, parse_status)


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


# ---- 센서 페이로드 ----

def test_parse_sonar_altitude_cm_to_m_and_negative_is_none():
    assert parse_sonar_altitude(struct.pack("<i", 123)) == 1.23
    assert parse_sonar_altitude(struct.pack("<i", -1)) is None
    with pytest.raises(MspError):
        parse_sonar_altitude(b"\x01")


def test_parse_debug_eight_int16_and_pads_short():
    vals = [1, -2, 3, -4, 5, -6, 700, -800]
    assert parse_debug(struct.pack("<8h", *vals)) == vals
    assert parse_debug(struct.pack("<4h", 1, 2, 3, 4)) == [1, 2, 3, 4, 0, 0, 0, 0]


def test_parse_attitude_and_altitude():
    att = parse_attitude(struct.pack("<hhh", -123, 45, 270))
    assert att.roll_deg == -12.3 and att.pitch_deg == 4.5 and att.yaw_deg == 270.0
    alt = parse_altitude(struct.pack("<ih", 250, -30))
    assert alt.alt_m == 2.5 and alt.vario_m_s == -0.3


# ---- 시리얼 전송 (가짜 포트) ----

class FakeSerial:
    """요청 명령별 응답을 미리 넣어두고, 쓰기마다 해당 응답을 읽기 버퍼에 쌓는다."""

    def __init__(self, responses, noise=b""):
        self.responses = responses
        self.rx = bytearray(noise)
        self.tx = []
        self.closed = False

    def write(self, data):
        self.tx.append(bytes(data))
        cmd = data[4]
        resp = self.responses.get(cmd)
        if resp is not None:
            self.rx += resp
        return len(data)

    def read(self, n):
        out = bytes(self.rx[:n])
        del self.rx[:n]
        return out

    def reset_input_buffer(self):
        self.rx.clear()

    def close(self):
        self.closed = True


def test_msp_serial_requests_and_resyncs_past_noise():
    fake = FakeSerial({MSP_SONAR_ALTITUDE: frame(MSP_SONAR_ALTITUDE, struct.pack("<i", 88))},
                      noise=b"# cli garbage\r\n$M")
    client = MspSerial("COMX", ser=fake, timeout=0.5)
    assert client.sonar_altitude_m() == 0.88
    assert fake.tx[0] == encode(MSP_SONAR_ALTITUDE)
    assert client.description == "msp://COMX@115200"


def test_msp_serial_skips_mismatched_frames_and_times_out():
    stale = frame(MSP_STATUS, status_payload(False))
    fake = FakeSerial({MSP_DEBUG: stale + frame(MSP_DEBUG, struct.pack("<8h", *range(8)))})
    client = MspSerial("COMX", ser=fake, timeout=0.5)
    assert client.debug() == list(range(8))
    silent = FakeSerial({})
    client = MspSerial("COMX", ser=silent, timeout=0.05)
    with pytest.raises(MspError):
        client.sonar_altitude_m()
    assert silent.closed


def test_msp_serial_error_response_raises_and_closes():
    fake = FakeSerial({MSP_DEBUG: frame(MSP_DEBUG, b"", direction=b"!")})
    client = MspSerial("COMX", ser=fake, timeout=0.5)
    with pytest.raises(MspError):
        client.debug()
    assert fake.closed


def test_open_msp_dispatch():
    assert open_msp("") is None and open_msp("sim") is None and open_msp("none") is None
    assert isinstance(open_msp("sitl", host="1.2.3.4"), MspClient)
    ser = open_msp("COM9", baud=57600)
    assert isinstance(ser, MspSerial) and ser.port == "COM9" and ser.baud == 57600


def test_sensor_poller_read_once_builds_sample():
    from buddybox.follow.sensors import SensorPoller
    debug = [0] * 8
    debug[6], debug[7] = 100, 300
    fake = FakeSerial({MSP_SONAR_ALTITUDE: frame(MSP_SONAR_ALTITUDE, struct.pack("<i", 200)),
                       MSP_DEBUG: frame(MSP_DEBUG, struct.pack("<8h", *debug))})
    poller = SensorPoller(MspSerial("COMX", ser=fake, timeout=0.5))
    s = poller.read_once(now=5.0)
    assert s is poller.latest() and s.t == 5.0 and s.alt_m == 2.0
    assert abs(s.vx - 0.2) < 1e-9 and abs(s.vy - 0.6) < 1e-9 and s.seq == 1
    # 실패하면 None 을 돌려주고 오류 카운트
    poller2 = SensorPoller(MspSerial("COMX", ser=FakeSerial({}), timeout=0.05))
    assert poller2.read_once(now=1.0) is None and poller2.errors == 1 and poller2.latest() is None
