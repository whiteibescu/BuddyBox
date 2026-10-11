"""MTF-02P 하방 센서(레인지파인더 + 옵티컬 플로우) 판독 — Betaflight MSP 경유.

FC가 센서를 읽고(UART2 MSP) 처리한 값을 PC가 다시 MSP로 가져온다.

- 거리: MSP_SONAR_ALTITUDE(58) → 기울기 보정 고도 m. 범위 밖/실패는 None.
- 플로우: MSP_DEBUG(254), `debug_mode = OPTICALFLOW`일 때 debug[6], [7] = 필터링된 플로우 X, Y
  (0.001 rad/s). 지면 속도 = 플로우(rad/s) × 고도(m).

    poller = SensorPoller(open_msp("COM7"), hz=20)
    poller.start()
    s = poller.latest()          # RangeFlowSample 또는 None
    s.alt_m, s.vx, s.vy, s.fresh(now)
"""

import time
from dataclasses import asdict, dataclass
from threading import Lock, Thread

FLOW_SCALE = 0.001            # debug 단위 → rad/s
FLOW_SLOT_X = 6               # 필터링된 플로우 X (좌우)
FLOW_SLOT_Y = 7               # 필터링된 플로우 Y (앞뒤) — 앞으로 밀면 증가해야 함


@dataclass
class RangeFlowSample:
    t: float                  # time.monotonic() 수신 시각
    seq: int
    alt_m: object = None      # None = 범위 밖 / 측정 실패
    flow_x: float = 0.0       # rad/s
    flow_y: float = 0.0       # rad/s
    vx: float = 0.0           # m/s (좌우, +X = 오른쪽; 부호는 설정으로 보정)
    vy: float = 0.0           # m/s (앞뒤, +Y = 앞)
    debug: tuple = ()
    error: str = ""

    @property
    def alt_valid(self):
        return self.alt_m is not None

    def fresh(self, now, timeout_s):
        return (now - self.t) <= timeout_s

    def to_dict(self):
        d = asdict(self)
        d["debug"] = list(self.debug)
        d["alt_valid"] = self.alt_valid
        return d


def compute_sample(t, seq, alt_m, debug, flow_x_slot=FLOW_SLOT_X, flow_y_slot=FLOW_SLOT_Y,
                   invert_x=False, invert_y=False, flow_scale=FLOW_SCALE):
    """원시 MSP 값 → RangeFlowSample. 고도가 없으면 속도는 0으로 두고 alt_m=None."""
    debug = list(debug or [])
    fx = (debug[flow_x_slot] if flow_x_slot < len(debug) else 0) * flow_scale
    fy = (debug[flow_y_slot] if flow_y_slot < len(debug) else 0) * flow_scale
    if invert_x:
        fx = -fx
    if invert_y:
        fy = -fy
    vx = vy = 0.0
    if alt_m is not None:
        vx = fx * alt_m
        vy = fy * alt_m
    return RangeFlowSample(t=t, seq=seq, alt_m=alt_m, flow_x=fx, flow_y=fy, vx=vx, vy=vy,
                           debug=tuple(debug))


class OsdSensorSource:
    """영상 OSD 판독으로 샘플을 만드는 센서 소스 (SensorPoller 와 같은 latest() 인터페이스).

    파이프라인이 새 프레임마다 feed(frame, now) 를 호출한다. 다운링크 하드웨어 없이
    비행 중 값을 받는 경로 — buddybox.vision.osd 참고.
    """

    def __init__(self, reader, invert_x=False, invert_y=False, every=1):
        self.reader = reader
        self.invert_x = invert_x
        self.invert_y = invert_y
        self.every = max(1, int(every))
        self._lock = Lock()
        self._latest = None
        self._seq = 0
        self._frames = 0
        self.errors = 0
        self.last_error = ""
        self.last_reading = None

    @property
    def description(self):
        return "osd"

    def start(self):
        pass

    def stop(self):
        pass

    def latest(self):
        with self._lock:
            return self._latest

    def feed(self, frame, now=None):
        self._frames += 1
        if (self._frames - 1) % self.every:
            return None
        now = time.monotonic() if now is None else now
        try:
            r = self.reader.read(frame)
        except Exception as exc:
            self.errors += 1
            self.last_error = str(exc)
            return None
        self.last_reading = r
        if not r.ok:
            self.errors += 1
            self.last_error = r.error
            with self._lock:
                if self._latest is not None:
                    self._latest.error = r.error
            return None
        self._seq += 1
        sample = compute_sample(now, self._seq, r.alt_m, r.debug, invert_x=self.invert_x,
                                invert_y=self.invert_y)
        with self._lock:
            self._latest = sample
        return sample


class SensorPoller:
    """백그라운드 스레드로 거리+플로우를 주기 폴링해 최신 샘플을 보관한다.

    MSP 클라이언트는 ArmController(상태 폴링)와 공유해도 된다 — 요청은 클라이언트 락으로 직렬화된다.
    """

    def __init__(self, client, hz=20.0, invert_x=False, invert_y=False,
                 flow_x_slot=FLOW_SLOT_X, flow_y_slot=FLOW_SLOT_Y, read_flow=True):
        self.client = client
        self.hz = hz
        self.invert_x = invert_x
        self.invert_y = invert_y
        self.flow_x_slot = flow_x_slot
        self.flow_y_slot = flow_y_slot
        self.read_flow = read_flow
        self._lock = Lock()
        self._latest = None
        self._seq = 0
        self.errors = 0
        self.last_error = ""
        self._running = False
        self._thread = None

    @property
    def description(self):
        return getattr(self.client, "description", "msp")

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def latest(self):
        with self._lock:
            return self._latest

    def read_once(self, now=None):
        """한 번 폴링해 샘플을 갱신하고 반환한다 (테스트·벤치 도구용)."""
        now = time.monotonic() if now is None else now
        try:
            alt = self.client.sonar_altitude_m()
            debug = self.client.debug() if self.read_flow else []
        except Exception as exc:
            self.errors += 1
            self.last_error = str(exc)
            with self._lock:
                if self._latest is not None:
                    self._latest.error = self.last_error
            return None
        self._seq += 1
        sample = compute_sample(now, self._seq, alt, debug, self.flow_x_slot, self.flow_y_slot,
                                self.invert_x, self.invert_y)
        with self._lock:
            self._latest = sample
        return sample

    def _loop(self):
        interval = 1.0 / max(1.0, self.hz)
        while self._running:
            t0 = time.monotonic()
            sample = self.read_once(t0)
            # 실패 시 잠깐 쉬어 포트를 독점하지 않도록
            wait = interval - (time.monotonic() - t0)
            time.sleep(max(0.005, wait) if sample is not None else max(0.2, interval))
