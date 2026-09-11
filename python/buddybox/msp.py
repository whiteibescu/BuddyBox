import socket
import struct
import threading
from dataclasses import dataclass, field

MSP_STATUS = 101
MSP_STATUS_EX = 150
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


class MspClient:
    def __init__(self, host="127.0.0.1", port=SITL_MSP_PORT, timeout=1.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._sock = None
        self._lock = threading.Lock()
        self.description = f"msp://{host}:{port}"

    def _connect(self):
        if self._sock is None:
            self._sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
            self._sock.settimeout(self.timeout)
        return self._sock

    def _recv_exact(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self._sock.recv(n - len(buf))
            if not chunk:
                raise MspError("MSP 연결 종료")
            buf += chunk
        return buf

    def request(self, cmd, payload=b""):
        with self._lock:
            try:
                sock = self._connect()
                sock.sendall(encode(cmd, payload))
                hdr = self._recv_exact(5)
                rest = self._recv_exact(hdr[3] + 1)
                got_cmd, data = decode(hdr + rest)
                if got_cmd != cmd:
                    raise MspError(f"MSP 응답 명령 불일치: {got_cmd} != {cmd}")
                return data
            except (OSError, MspError):
                self.close()
                raise

    def status(self):
        return parse_status(self.request(MSP_STATUS))

    def close(self):
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
