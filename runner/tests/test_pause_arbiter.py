"""Tests for pause_arbiter — typed pauses, TTL, escalation after consecutive trips."""
import json
import os
import sys
import tempfile
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Stub kill_switch
_real_modules = {name: sys.modules.get(name) for name in ("kill_switch", "db", "subscription_guard")}
_paused = {"v": False}
_ks = types.ModuleType("kill_switch")
_ks.pause = lambda **kw: None
_ks.resume = lambda **kw: None
_ks.is_paused = lambda *a: _paused["v"]

# Stub db for escalation approval filing
_approvals = []
_db = types.ModuleType("db")
_db.insert = lambda table, row: _approvals.append(row)
_db.select = lambda *a, **kw: []

# Stub subscription_guard
_sg = types.ModuleType("subscription_guard")
_sg.audit = lambda: {"api_keys_present": False}

# WAS three bare `sys.modules[...] = ...` assignments followed by a hand-rolled
# restore loop over _real_modules. The restore was correct -- this file was one
# of the few that put things back -- but it is exactly what
# env_during_import.modules_during_import() does, including the "the name was
# absent before" case, and doing it by hand in every file is how the other
# thirteen got it wrong. See runner/tests/test_sys_modules_shadowing.py.
from env_during_import import modules_during_import

with modules_during_import(kill_switch=_ks, db=_db, subscription_guard=_sg):
    import pause_arbiter

# Bind the test doubles explicitly as well as through import injection. This
# keeps the suite hermetic when another test imported pause_arbiter first.
pause_arbiter.kill_switch = _ks
pause_arbiter.db = _db
pause_arbiter.subscription_guard = _sg


class TestPauseArbiterBasic(unittest.TestCase):
    def setUp(self):
        sys.modules.update({"kill_switch": _ks, "db": _db, "subscription_guard": _sg})
        self._tmpdir = tempfile.mkdtemp()
        pause_arbiter.STATE_FILE = os.path.join(self._tmpdir, "state.json")
        _paused["v"] = False
        _approvals.clear()

    def tearDown(self):
        for name, module in _real_modules.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module

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
        sys.modules.update({"kill_switch": _ks, "db": _db, "subscription_guard": _sg})
        self._tmpdir = tempfile.mkdtemp()
        pause_arbiter.STATE_FILE = os.path.join(self._tmpdir, "state.json")
        _paused["v"] = False
        _approvals.clear()

    def tearDown(self):
        for name, module in _real_modules.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module

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


class TestRecheckNeverLiftsWhatItDoesNotOwn(unittest.TestCase):
    """The interlock: recheck() may only lift pauses it can account for.

    An operator's manual STOP, a pre-arbiter pause, an unregistered reason code, a
    checker that raises — in every one of those the arbiter is looking at a pause it
    cannot reason about, and the only safe move is to leave it alone. These paths carried
    no tests, and they are the ones where a wrong answer resumes a fleet somebody
    deliberately stopped.
    """

    def setUp(self):
        sys.modules.update({"kill_switch": _ks, "db": _db, "subscription_guard": _sg})
        self._tmpdir = tempfile.mkdtemp()
        pause_arbiter.STATE_FILE = os.path.join(self._tmpdir, "state.json")
        _paused["v"] = False
        _approvals.clear()
        self._saved_audit = _sg.audit

    def tearDown(self):
        _sg.audit = self._saved_audit
        for name, module in _real_modules.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module

    def test_a_pause_with_no_arbiter_metadata_is_left_alone(self):
        # A manual STOP. Nothing in the state file describes it, so the arbiter has no
        # basis for deciding it is safe to resume — and resuming it would silently undo
        # a human decision.
        _paused["v"] = True
        result = pause_arbiter.recheck()
        self.assertTrue(result["paused"])
        self.assertEqual(result["action"], "none")
        self.assertIn("no arbiter metadata", result.get("reason", ""))

    def test_an_unregistered_reason_code_is_never_lifted(self):
        # Typed, but by a producer this arbiter does not know how to clear. Without a
        # clear_check there is no evidence the condition ended.
        pause_arbiter.pause("some_future_reason", "tripped", ttl_s=0)
        _paused["v"] = True
        result = pause_arbiter.recheck()
        self.assertEqual(result["action"], "none")

    def test_a_checker_that_raises_does_not_lift_without_an_expired_ttl(self):
        # An error is not evidence the condition cleared. Treating it as one would make a
        # broken checker the fastest way to resume the fleet.
        def _boom():
            raise RuntimeError("probe unavailable")

        pause_arbiter.register("flaky_probe", _boom, auto_expirable=True)
        pause_arbiter.pause("flaky_probe", "tripped", ttl_s=99999)
        _paused["v"] = True
        result = pause_arbiter.recheck()
        self.assertEqual(result["action"], "none")
        self.assertIn("errored", result.get("reason", ""))

    def test_a_checker_that_raises_lifts_only_once_the_ttl_has_expired(self):
        # The deliberate exception: an auto-expirable pause whose checker is broken must
        # not become permanent. The TTL is the fallback, and it has to have elapsed.
        def _boom():
            raise RuntimeError("probe unavailable")

        pause_arbiter.register("flaky_probe_expired", _boom, auto_expirable=True)
        pause_arbiter.pause("flaky_probe_expired", "tripped", ttl_s=0)
        _paused["v"] = True
        result = pause_arbiter.recheck()
        self.assertEqual(result["action"], "lifted")
        self.assertIn("TTL", result.get("reason", ""))

    def test_a_non_expirable_pause_is_not_lifted_by_its_ttl(self):
        # auto_expirable=False means time alone is never enough.
        def _boom():
            raise RuntimeError("probe unavailable")

        pause_arbiter.register("manual_only", _boom, auto_expirable=False)
        pause_arbiter.pause("manual_only", "tripped", ttl_s=0)
        _paused["v"] = True
        result = pause_arbiter.recheck()
        self.assertEqual(result["action"], "none")

    def test_an_is_paused_failure_reports_an_error_rather_than_resuming(self):
        # If the arbiter cannot even tell whether the fleet is paused, it must not act.
        original = _ks.is_paused
        _ks.is_paused = lambda *a: (_ for _ in ()).throw(RuntimeError("kill switch unreachable"))
        try:
            result = pause_arbiter.recheck()
        finally:
            _ks.is_paused = original
        self.assertEqual(result["action"], "none")
        self.assertIn("is_paused failed", result.get("error", ""))

    def test_stale_metadata_is_dropped_when_the_fleet_is_not_paused(self):
        # Housekeeping: the state file must not accumulate entries for pauses that no
        # longer exist, or a later trip would inherit a stale streak and escalate early.
        pause_arbiter.pause("billing_key_presence", "trip 1", by="billing_guard")
        _paused["v"] = False
        result = pause_arbiter.recheck()
        self.assertFalse(result["paused"])
        self.assertEqual(pause_arbiter._load_state().get("global:"), None)
