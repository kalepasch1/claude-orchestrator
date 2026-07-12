"""Tests for pause_arbiter — typed pauses, TTL, escalation after consecutive trips."""
import json
import os
import sys
import tempfile
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Stub kill_switch
_paused = {"v": False}
_ks = types.ModuleType("kill_switch")
_ks.pause = lambda **kw: None
_ks.resume = lambda **kw: None
_ks.is_paused = lambda *a: _paused["v"]
sys.modules["kill_switch"] = _ks

# Stub db for escalation approval filing
_approvals = []
_db = types.ModuleType("db")
_db.insert = lambda table, row: _approvals.append(row)
_db.select = lambda *a, **kw: []
sys.modules["db"] = _db

# Stub subscription_guard
_sg = types.ModuleType("subscription_guard")
_sg.audit = lambda: {"api_keys_present": False}
sys.modules["subscription_guard"] = _sg

import pause_arbiter


class TestPauseArbiterBasic(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        pause_arbiter.STATE_FILE = os.path.join(self._tmpdir, "state.json")
        _paused["v"] = False
        _approvals.clear()

    def test_pause_writes_state(self):
        pause_arbiter.pause("test_cause", "something broke", by="test")
        state = pause_arbiter._load_state()
        self.assertIn("global:", state)
        self.assertEqual(state["global:"]["reason_code"], "test_cause")

    def test_resume_clears_state(self):
        pause_arbiter.pause("test_cause", "broke", by="test")
        pause_arbiter.resume(by="test")
        state = pause_arbiter._load_state()
        self.assertNotIn("global:", state)

    def test_streak_increments_on_same_reason(self):
        pause_arbiter.pause("flaky", "flap", by="test")
        self.assertEqual(pause_arbiter._load_state()["global:"]["streak"], 1)
        pause_arbiter.pause("flaky", "flap again", by="test")
        self.assertEqual(pause_arbiter._load_state()["global:"]["streak"], 2)

    def test_streak_resets_on_different_reason(self):
        pause_arbiter.pause("cause_a", "a", by="test")
        pause_arbiter.pause("cause_b", "b", by="test")
        self.assertEqual(pause_arbiter._load_state()["global:"]["streak"], 1)


class TestEscalationAfterConsecutiveTrips(unittest.TestCase):
    """The core escalation feature: after ESCALATE_AFTER consecutive identical trips,
    pause_arbiter stops auto-lifting and files a material approval."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        pause_arbiter.STATE_FILE = os.path.join(self._tmpdir, "state.json")
        _paused["v"] = False
        _approvals.clear()

    def test_escalation_at_threshold(self):
        """After 3 consecutive identical trips, the pause is marked escalated."""
        for i in range(pause_arbiter.ESCALATE_AFTER):
            pause_arbiter.pause("billing_key_presence", f"trip {i+1}", by="billing_guard")
        state = pause_arbiter._load_state()
        entry = state["global:"]
        self.assertTrue(entry["escalated"])
        self.assertEqual(entry["streak"], pause_arbiter.ESCALATE_AFTER)

    def test_no_escalation_below_threshold(self):
        """Below ESCALATE_AFTER, pause is not escalated."""
        for i in range(pause_arbiter.ESCALATE_AFTER - 1):
            pause_arbiter.pause("billing_key_presence", f"trip {i+1}", by="billing_guard")
        state = pause_arbiter._load_state()
        self.assertFalse(state["global:"]["escalated"])

    def test_escalation_files_approval(self):
        """Escalation must file a material approval so a human sees it."""
        for i in range(pause_arbiter.ESCALATE_AFTER):
            pause_arbiter.pause("billing_key_presence", f"trip {i+1}", by="billing_guard")
        self.assertTrue(len(_approvals) > 0, "must file an approval on escalation")
        self.assertEqual(_approvals[0]["kind"], "material")
        self.assertIn("re-tripped", _approvals[0]["title"])

    def test_recheck_refuses_to_lift_escalated(self):
        """Once escalated, recheck() must NOT auto-lift even if clear_check passes."""
        for i in range(pause_arbiter.ESCALATE_AFTER):
            pause_arbiter.pause("billing_key_presence", f"trip {i+1}", by="billing_guard")
        _paused["v"] = True
        result = pause_arbiter.recheck()
        self.assertEqual(result["action"], "none")
        self.assertIn("escalated", result.get("reason", ""))

    def test_recheck_lifts_non_escalated(self):
        """Non-escalated pause with a passing clear_check should be lifted."""
        pause_arbiter.pause("billing_key_presence", "trip 1", by="billing_guard")
        _paused["v"] = True
        _sg.audit = lambda: {"api_keys_present": False}
        result = pause_arbiter.recheck()
        self.assertEqual(result["action"], "lifted")


if __name__ == "__main__":
    unittest.main()
