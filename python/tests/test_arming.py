import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from buddybox import BuddyBox
from buddybox.follow.arming import AUX1, ArmController
from buddybox.msp import FcStatus


class FakeVerifier:
    def __init__(self):
        self.armed = False
        self.reasons = []

    def status(self):
        flags = 1 << 7 if "THROTTLE" in self.reasons else 0
        return FcStatus(armed=self.armed, flight_mode_flags=1 if self.armed else 0,
                        arming_disable_flags=flags, reasons=list(self.reasons))

    def close(self):
        pass


class NoThreadArm(ArmController):
    def __init__(self, backend, verifier=None, **kw):
        super().__init__(backend, verifier=None, **kw)
        self.verifier = verifier
        self.state.verifiable = verifier is not None


def test_arm_and_disarm_set_aux1_without_verifier():
    with BuddyBox("sim") as bb:
        ac = ArmController(bb)
        s = ac.arm()
        assert bb.get_channels_us()[AUX1] == 1900
        assert s["commanded"] is True and s["result"] == "unverified" and s["label"] == "ARM SENT"
        s = ac.disarm()
        assert bb.get_channels_us()[AUX1] == 1000
        assert s["commanded"] is False and s["label"] == "DISARM SENT"


def test_verified_arm_success():
    results = []
    with BuddyBox("sim") as bb:
        v = FakeVerifier()
        ac = NoThreadArm(bb, v, on_result=lambda *a: results.append(a))
        ac.arm(now=0.0)
        assert ac.snapshot()["pending"] and ac.snapshot()["label"] == "ARM?"
        ac.observe(v.status(), now=0.2)
        assert ac.snapshot()["pending"]
        v.armed = True
        s = ac.observe(v.status(), now=0.6)
        assert s["result"] == "ok" and s["armed"] is True and s["label"] == "ARMED"
        assert results == [("ok", True, [])]


def test_verified_arm_failure_reports_reasons():
    results = []
    with BuddyBox("sim") as bb:
        v = FakeVerifier()
        v.reasons = ["THROTTLE"]
        ac = NoThreadArm(bb, v, confirm_timeout_s=1.0, on_result=lambda *a: results.append(a))
        ac.arm(now=10.0)
        ac.observe(v.status(), now=10.5)
        assert ac.snapshot()["pending"] and ac.snapshot()["reasons"] == ["THROTTLE"]
        s = ac.observe(v.status(), now=11.5)
        assert s["result"] == "failed" and s["label"] == "ARM FAILED" and s["reasons"] == ["THROTTLE"]
        assert results == [("failed", True, ["THROTTLE"])]


def test_verified_disarm_and_error_path():
    with BuddyBox("sim") as bb:
        v = FakeVerifier()
        v.armed = True
        ac = NoThreadArm(bb, v, confirm_timeout_s=1.0)
        ac.observe(v.status(), now=0.0)
        assert ac.snapshot()["label"] == "ARMED"
        ac.disarm(now=1.0)
        v.armed = False
        s = ac.observe(v.status(), now=1.3)
        assert s["result"] == "ok" and s["label"] == "DISARMED"
        ac.arm(now=5.0)
        ac.observe_error(OSError("연결 거부"), now=5.5)
        assert ac.snapshot()["pending"] and "연결 거부" in ac.snapshot()["error"]
        ac.observe_error(OSError("연결 거부"), now=6.5)
        s = ac.snapshot()
        assert not s["pending"] and s["result"] == "unverified"
