"""Betaflight SITL용 UDP RC 백엔드 — BuddyBox와 동일한 API.

Betaflight SITL은 UDP 포트 9004로 RC 입력(rc_packet)을 받는다:

    double timestamp(초) + 16 × uint16 채널 펄스폭(µs)   (little-endian, 40바이트)

사용 예 (실물 코드에서 BuddyBox만 갈아끼우면 됨):
    from buddybox.sitl import BuddyBoxSitl

    with BuddyBoxSitl() as bb:              # SITL이 같은 PC에서 실행 중일 때
        bb.set_sticks(roll=0.0, pitch=0.0, yaw=0.0, throttle=-1.0)

채널 순서는 실물과 동일한 AETR: CH1=Roll, CH2=Pitch, CH3=Throttle, CH4=Yaw.
전송 주기도 실물 시리얼 경로와 같은 50Hz로 맞춰 타이밍 특성 차이를 줄인다.
"""

import socket
import struct
import threading
import time

from . import (
    CH_MID,
    CH_MIN,
    CH_PITCH,
    CH_ROLL,
    CH_THROTTLE,
    CH_YAW,
    clamp_us,
    norm_to_us,
)

SITL_RC_PORT = 9004
_SEND_HZ = 50
_NUM_CH = 16  # rc_packet은 항상 16채널


def build_rc_packet(channels_us, timestamp):
    """8(이상)채널 µs 리스트 → 40바이트 SITL rc_packet. 부족한 채널은 중립으로 채운다."""
    chans = [clamp_us(us) for us in channels_us]
    chans += [CH_MID] * (_NUM_CH - len(chans))
    return struct.pack("<d16H", timestamp, *chans[:_NUM_CH])


class BuddyBoxSitl:
    """Betaflight SITL로 RC 패킷을 50Hz 전송하는 백그라운드 송신기.

    공개 API는 BuddyBox(시리얼)와 동일하다.
    """

    def __init__(self, host="127.0.0.1", port=SITL_RC_PORT):
        self._addr = (host, port)
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.port = f"udp://{host}:{port}"

        self._lock = threading.Lock()
        self._channels = [CH_MID] * 8
        self._channels[CH_THROTTLE] = CH_MIN

        self._running = True
        self._thread = threading.Thread(target=self._tx_loop, daemon=True)
        self._thread.start()

    # ---- 값 설정 (BuddyBox와 동일) ----

    def set_channel_us(self, index, us):
        with self._lock:
            self._channels[index] = clamp_us(us)

    def set_channel(self, index, value):
        self.set_channel_us(index, norm_to_us(value))

    def set_sticks(self, roll=None, pitch=None, yaw=None, throttle=None):
        if roll is not None:
            self.set_channel(CH_ROLL, roll)
        if pitch is not None:
            self.set_channel(CH_PITCH, pitch)
        if yaw is not None:
            self.set_channel(CH_YAW, yaw)
        if throttle is not None:
            self.set_channel(CH_THROTTLE, throttle)

    def neutral(self):
        self.set_sticks(roll=0.0, pitch=0.0, yaw=0.0, throttle=-1.0)

    def get_channels_us(self):
        with self._lock:
            return list(self._channels)

    @property
    def simulator(self):
        return None  # BuddyBox와의 인터페이스 호환용

    # ---- 전송 ----

    def _tx_loop(self):
        interval = 1.0 / _SEND_HZ
        while self._running:
            with self._lock:
                packet = build_rc_packet(self._channels, time.time())
            try:
                self._sock.sendto(packet, self._addr)
            except OSError:
                break
            time.sleep(interval)

    # ---- 종료 ----

    def close(self):
        self._running = False
        self._thread.join(timeout=1.0)
        self._sock.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
