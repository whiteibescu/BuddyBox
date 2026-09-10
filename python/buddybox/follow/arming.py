import time
from dataclasses import asdict, dataclass, field
from threading import Lock, Thread

AUX1 = 4
ARM_US = 1900
DISARM_US = 1000


@dataclass
class ArmState:
    commanded: object = None
    armed: object = None
    verifiable: bool = False
    pending: bool = False
    result: str = ""
    reasons: list = field(default_factory=list)
    error: str = ""
    command_t: float = 0.0
    updated_t: float = 0.0
    disable_flags: int = 0

    @property
    def label(self):
        if self.pending:
            return "ARM?" if self.commanded else "DISARM?"
        if self.result == "failed":
            return "ARM FAILED" if self.commanded else "DISARM FAILED"
        if self.armed is True:
            return "ARMED"
        if self.armed is False:
            return "DISARMED"
        if self.commanded is True:
            return "ARM SENT"
        if self.commanded is False:
            return "DISARM SENT"
        return ""

    def to_dict(self):
        d = asdict(self)
        d["label"] = self.label
        return d


class ArmController:
    def __init__(self, backend, verifier=None, channel=AUX1, arm_us=ARM_US, disarm_us=DISARM_US,
                 confirm_timeout_s=3.0, poll_s=0.5, fast_poll_s=0.15, on_result=None):
        self.backend = backend
        self.verifier = verifier
        self.channel = channel
        self.arm_us = arm_us
        self.disarm_us = disarm_us
        self.confirm_timeout_s = confirm_timeout_s
        self.poll_s = poll_s
        self.fast_poll_s = fast_poll_s
        self.on_result = on_result
        self._lock = Lock()
        self.state = ArmState(verifiable=verifier is not None)
        self._running = False
        self._thread = None
        if verifier is not None:
            self._running = True
            self._thread = Thread(target=self._loop, daemon=True)
            self._thread.start()

    def _command(self, armed, now=None):
        now = time.monotonic() if now is None else now
        self.backend.set_channel_us(self.channel, self.arm_us if armed else self.disarm_us)
        with self._lock:
            self.state.commanded = armed
            self.state.command_t = now
            self.state.updated_t = now
            self.state.reasons = []
            if self.verifier is not None:
                self.state.pending = True
                self.state.result = ""
            else:
                self.state.pending = False
                self.state.result = "unverified"
        return self.snapshot()

    def arm(self, now=None):
        return self._command(True, now)

    def disarm(self, now=None):
        return self._command(False, now)

    def snapshot(self):
        with self._lock:
            return self.state.to_dict()

    def observe(self, status, now=None):
        now = time.monotonic() if now is None else now
        fired = None
        with self._lock:
            st = self.state
            st.armed = bool(status.armed)
            st.disable_flags = int(status.arming_disable_flags)
            st.error = ""
            st.updated_t = now
            if st.pending:
                if st.armed == st.commanded:
                    st.pending = False
                    st.result = "ok"
                    st.reasons = []
                    fired = ("ok", st.commanded, [])
                elif now - st.command_t > self.confirm_timeout_s:
                    st.pending = False
                    st.result = "failed"
                    st.reasons = list(status.reasons)
                    fired = ("failed", st.commanded, st.reasons)
                else:
                    st.reasons = list(status.reasons)
        if fired and self.on_result:
            self.on_result(*fired)
        return self.snapshot()

    def observe_error(self, exc, now=None):
        now = time.monotonic() if now is None else now
        fired = None
        with self._lock:
            st = self.state
            st.error = str(exc)
            st.updated_t = now
            if st.pending and now - st.command_t > self.confirm_timeout_s:
                st.pending = False
                st.result = "unverified"
                fired = ("unverified", st.commanded, [st.error])
        if fired and self.on_result:
            self.on_result(*fired)

    def _loop(self):
        while self._running:
            try:
                status = self.verifier.status()
                self.observe(status)
            except Exception as exc:
                self.observe_error(exc)
            with self._lock:
                pending = self.state.pending
            time.sleep(self.fast_poll_s if pending else self.poll_s)

    def stop(self):
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        if self.verifier is not None and hasattr(self.verifier, "close"):
            self.verifier.close()
