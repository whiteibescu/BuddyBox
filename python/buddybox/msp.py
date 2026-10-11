"""MSP(MultiWii Serial Protocol) v1 클라이언트 — Betaflight FC 상태·센서 판독.

전송 경로 두 가지를 같은 API로 지원한다.

- MspClient  : TCP (Betaflight SITL, 기본 포트 5761)
- MspSerial  : USB-VCP 시리얼 (실기 FC, 벤치)

    client = open_msp("COM7")            # 또는 open_msp("sitl", host="172.x.x.x")
    client.status().armed
    client.sonar_altitude_m()            # MTF-02P 레인지파인더, m (None = 범위 밖)
    client.debug()                       # debug[0..7] (debug_mode = OPTICALFLOW 등)
"""

import socket
import struct
import threading
import time
from dataclasses import dataclass, field

MSP_STATUS = 101
MSP_ATTITUDE = 108
MSP_ALTITUDE = 109
MSP_STATUS_EX = 150
MSP_SONAR_ALTITUDE = 58
MSP_DEBUG = 254
SITL_MSP_PORT = 5761

ARMING_DISABLE_NAMES = [
    "NOGYRO", "FAILSAFE", "RXLOSS", "BADRX", "BOXFAILSAFE", "RUNAWAY", "CRASH", "THROTTLE", "ANGLE",
    "BOOTGRACE", "NOPREARM", "LOAD", "CALIB", "CLI", "CMS", "BST", "MSP", "PARALYZE", "GPS", "RESC",
    "RPMFILTER", "REBOOT_REQD", "DSHOT_BBANG", "NO_ACC_CAL", "MOTOR_PROTO", "ARMSWITCH",
]


class MspError(Exception):
    pass


@dataclass
class FcStatus:
    armed: bool
    flight_mode_flags: int
    arming_disable_flags: int
    cycle_time_us: int = 0
    sensors: int = 0
    reasons: list = field(default_factory=list)


@dataclass
class Attitude:
    roll_deg: float
    pitch_deg: float
    yaw_deg: float


@dataclass
class Altitude:
    alt_m: float
    vario_m_s: float


def encode(cmd, payload=b""):
    body = bytes([len(payload), cmd]) + bytes(payload)
    ck = 0
    for b in body:
        ck ^= b
    return b"$M<" + body + bytes([ck])


def decode(frame):
    if len(frame) < 6 or frame[:2] != b"$M":
        raise MspError("잘못된 MSP 프레임")
    direction = frame[2:3]
    size = frame[3]
    cmd = frame[4]
    if len(frame) < 6 + size:
        raise MspError("MSP 프레임 길이 부족")
    payload = frame[5:5 + size]
    ck = 0
    for b in frame[3:5 + size]:
        ck ^= b
    if ck != frame[5 + size]:
        raise MspError("MSP 체크섬 오류")
    if direction == b"!":
        raise MspError(f"MSP 명령 {cmd} 오류 응답")
    return cmd, payload


def arming_disable_names(flags):
    return [name for i, name in enumerate(ARMING_DISABLE_NAMES) if flags & (1 << i)] + \
           [f"bit{i}" for i in range(len(ARMING_DISABLE_NAMES), 32) if flags & (1 << i)]


def parse_status(payload):
    if len(payload) < 11:
        raise MspError("MSP_STATUS 페이로드가 짧습니다")
    cycle, _i2c, sensors = struct.unpack("<HHH", payload[0:6])
    flags = struct.unpack("<I", payload[6:10])[0]
    disable = 0
    if len(payload) > 15:
        extra = payload[15] & 0x0F
        off = 16 + extra
        if len(payload) >= off + 5:
            disable = struct.unpack("<I", payload[off + 1:off + 5])[0]
    return FcStatus(armed=bool(flags & 1), flight_mode_flags=flags, arming_disable_flags=disable,
                    cycle_time_us=cycle, sensors=sensors, reasons=arming_disable_names(disable))


def parse_sonar_altitude(payload):
    """MSP_SONAR_ALTITUDE(58): int32 cm (기울기 보정). 음수 = 범위 밖/측정 실패 → None."""
    if len(payload) < 4:
        raise MspError("MSP_SONAR_ALTITUDE 페이로드가 짧습니다")
    cm = struct.unpack("<i", payload[0:4])[0]
    return None if cm < 0 else cm / 100.0


def parse_debug(payload):
    """MSP_DEBUG(254): int16 × 8 (2026.x). 구버전은 4개만 올 수 있어 0으로 채운다."""
    n = min(8, len(payload) // 2)
    if n == 0:
        raise MspError("MSP_DEBUG 페이로드가 짧습니다")
    vals = list(struct.unpack(f"<{n}h", payload[:2 * n]))
    return vals + [0] * (8 - n)


def parse_attitude(payload):
    """MSP_ATTITUDE(108): int16 roll, pitch (0.1°), int16 yaw (°)."""
    if len(payload) < 6:
        raise MspError("MSP_ATTITUDE 페이로드가 짧습니다")
    r, p, y = struct.unpack("<hhh", payload[0:6])
    return Attitude(roll_deg=r / 10.0, pitch_deg=p / 10.0, yaw_deg=float(y))


def parse_altitude(payload):
    """MSP_ALTITUDE(109): int32 추정 고도 cm, int16 수직 속도 cm/s."""
    if len(payload) < 6:
        raise MspError("MSP_ALTITUDE 페이로드가 짧습니다")
    alt_cm, vario = struct.unpack("<ih", payload[0:6])
    return Altitude(alt_m=alt_cm / 100.0, vario_m_s=vario / 100.0)


class _MspBase:
    """요청/응답 한 쌍을 락으로 직렬화하는 공통 로직. 하위 클래스가 전송 계층을 제공한다."""

    description = "msp"

    def __init__(self, timeout=1.0):
        self.timeout = timeout
        self._lock = threading.Lock()

    # --- 전송 계층 (하위 클래스 구현) ---
    def _open(self):
        raise NotImplementedError

    def _write(self, data):
        raise NotImplementedError

    def _read(self, n):
        """최대 n바이트를 읽어 반환. 타임아웃이면 b''."""
        raise NotImplementedError

    def close(self):
        raise NotImplementedError

    # --- 공통 ---
    def _recv_exact(self, n, deadline):
        buf = b""
        while len(buf) < n:
            if time.monotonic() > deadline:
                raise MspError("MSP 응답 타임아웃")
            chunk = self._read(n - len(buf))
            if not chunk:
                continue
            buf += chunk
        return buf

    def _read_frame(self, deadline):
        """'$M' 헤더까지 재동기화한 뒤 프레임 한 개를 읽는다 (CLI 잔여 출력 등 잡음 무시)."""
        window = b""
        while True:
            window = (window + self._recv_exact(1, deadline))[-3:]
            if len(window) == 3 and window[:2] == b"$M" and window[2:3] in (b">", b"!"):
                break
        rest = self._recv_exact(2, deadline)
        size = rest[0]
        payload_ck = self._recv_exact(size + 1, deadline)
        return decode(window + rest + payload_ck)

    def request(self, cmd, payload=b""):
        with self._lock:
            try:
                self._open()
                self._write(encode(cmd, payload))
                deadline = time.monotonic() + self.timeout
                while True:
                    got_cmd, data = self._read_frame(deadline)
                    if got_cmd == cmd:
                        return data
                    # 다른 명령의 지연 응답이 섞여 들어오면 버리고 계속 읽는다
            except (OSError, MspError):
                self.close()
                raise

    def status(self):
        return parse_status(self.request(MSP_STATUS))

    def sonar_altitude_m(self):
        return parse_sonar_altitude(self.request(MSP_SONAR_ALTITUDE))

    def debug(self):
        return parse_debug(self.request(MSP_DEBUG))

    def attitude(self):
        return parse_attitude(self.request(MSP_ATTITUDE))

    def altitude(self):
        return parse_altitude(self.request(MSP_ALTITUDE))


class MspClient(_MspBase):
    """TCP 전송 (Betaflight SITL)."""

    def __init__(self, host="127.0.0.1", port=SITL_MSP_PORT, timeout=1.0):
        super().__init__(timeout)
        self.host = host
        self.port = port
        self._sock = None
        self.description = f"msp://{host}:{port}"

    def _open(self):
        if self._sock is None:
            self._sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
            self._sock.settimeout(self.timeout)

    def _write(self, data):
        self._sock.sendall(data)

    def _read(self, n):
        try:
            chunk = self._sock.recv(n)
        except socket.timeout:
            return b""
        if not chunk:
            raise MspError("MSP 연결 종료")
        return chunk

    def close(self):
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None


class MspSerial(_MspBase):
    """시리얼 전송 (FC USB-VCP). pyserial 필요. `ser`에 pyserial 호환 객체를 직접 넘겨도 된다."""

    def __init__(self, port, baud=115200, timeout=1.0, ser=None):
        super().__init__(timeout)
        self.port = port
        self.baud = baud
        self._ser = ser
        self.description = f"msp://{port}@{baud}"

    def _open(self):
        if self._ser is None:
            import serial
            self._ser = serial.Serial(self.port, self.baud, timeout=0.05, write_timeout=self.timeout)
            self._ser.reset_input_buffer()

    def _write(self, data):
        self._ser.write(data)

    def _read(self, n):
        return self._ser.read(n) or b""

    def close(self):
        if self._ser is not None:
            try:
                self._ser.close()
            except OSError:
                pass
            self._ser = None


def open_msp(spec, host="127.0.0.1", port=SITL_MSP_PORT, baud=115200, timeout=1.0):
    """'sitl' → MspClient(TCP), 'COMx'/'/dev/tty…' → MspSerial, 빈 값/'none'/'sim' → None."""
    spec = (spec or "").strip()
    if not spec or spec.lower() in ("none", "sim", "off"):
        return None
    if spec.lower() == "sitl":
        return MspClient(host=host, port=port, timeout=timeout)
    return MspSerial(spec, baud=baud, timeout=timeout)
