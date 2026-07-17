"""BuddyBox — PC에서 Pro Micro를 통해 PPM 트레이너 신호를 보내는 라이브러리.

사용 예:
    from buddybox import BuddyBox

    with BuddyBox("COM5") as bb:
        bb.set_sticks(roll=0.0, pitch=0.0, yaw=0.0, throttle=-1.0)
        ...

채널 순서 (AETR): CH1=Roll, CH2=Pitch, CH3=Throttle, CH4=Yaw
"""

import struct
import threading
import time

import serial
from serial.tools import list_ports

CH_MIN = 988
CH_MID = 1500
CH_MAX = 2012

CH_ROLL = 0
CH_PITCH = 1
CH_THROTTLE = 2
CH_YAW = 3

_HEADER = b"\xa5\x5a"
_SEND_HZ = 50


def clamp_us(us):
    """펄스폭을 펌웨어와 동일한 범위(988~2012µs)로 제한한다."""
    return max(CH_MIN, min(CH_MAX, int(us)))


def norm_to_us(value):
    """정규화 값 -1.0~+1.0 → 펄스폭 µs."""
    value = max(-1.0, min(1.0, float(value)))
    span = (CH_MAX - CH_MIN) / 2
    return round(CH_MID + value * span)


def build_frame(channels_us):
    """8채널 µs 리스트 → 19바이트 시리얼 프레임 (헤더 + payload + XOR 체크섬)."""
    payload = struct.pack("<8H", *(clamp_us(us) for us in channels_us))
    checksum = 0
    for b in payload:
        checksum ^= b
    return _HEADER + payload + bytes([checksum])


def find_promicro_port():
    """Pro Micro(ATmega32U4, VID 0x2341/0x1B4F)로 보이는 첫 포트를 반환. 없으면 None."""
    for p in list_ports.comports():
        if p.vid in (0x2341, 0x1B4F):
            return p.device
    return None


class BuddyBox:
    """Pro Micro로 8채널 값을 50Hz로 전송하는 백그라운드 송신기.

    스틱 값은 -1.0(최소) ~ +1.0(최대) 정규화 값으로 지정한다.
    시작 시 스로틀은 최소, 나머지는 중립이다.
    """

    def __init__(self, port=None, baud=115200):
        if port is None:
            port = find_promicro_port()
            if port is None:
                raise RuntimeError(
                    "Pro Micro 포트를 찾지 못했습니다. port='COM5' 식으로 직접 지정하세요."
                )
        self._ser = serial.Serial(port, baud, timeout=0.1)
        self.port = port

        self._lock = threading.Lock()
        self._channels = [CH_MID] * 8
        self._channels[CH_THROTTLE] = CH_MIN

        self._running = True
        self._thread = threading.Thread(target=self._tx_loop, daemon=True)
        self._thread.start()

    # ---- 값 설정 ----

    def set_channel_us(self, index, us):
        """채널(0~7) 펄스폭을 µs(988~2012)로 직접 설정."""
        with self._lock:
            self._channels[index] = clamp_us(us)

    def set_channel(self, index, value):
        """채널(0~7)을 정규화 값 -1.0~+1.0으로 설정."""
        self.set_channel_us(index, norm_to_us(value))

    def set_sticks(self, roll=None, pitch=None, yaw=None, throttle=None):
        """스틱 4채널을 정규화 값으로 설정. None인 축은 유지.

        throttle은 -1.0(정지) ~ +1.0(최대)이다.
        """
        if roll is not None:
            self.set_channel(CH_ROLL, roll)
        if pitch is not None:
            self.set_channel(CH_PITCH, pitch)
        if yaw is not None:
            self.set_channel(CH_YAW, yaw)
        if throttle is not None:
            self.set_channel(CH_THROTTLE, throttle)

    def neutral(self):
        """스틱 중립 + 스로틀 최소로 되돌린다."""
        self.set_sticks(roll=0.0, pitch=0.0, yaw=0.0, throttle=-1.0)

    def get_channels_us(self):
        with self._lock:
            return list(self._channels)

    # ---- 전송 ----

    def _frame(self):
        with self._lock:
            return build_frame(self._channels)

    def _tx_loop(self):
        interval = 1.0 / _SEND_HZ
        while self._running:
            try:
                self._ser.write(self._frame())
            except serial.SerialException:
                break
            time.sleep(interval)

    # ---- 종료 ----

    def close(self):
        """전송을 멈추고 포트를 닫는다. Pro Micro는 500ms 후 PPM을 정지한다."""
        self._running = False
        self._thread.join(timeout=1.0)
        self._ser.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
