import os
import sys
import json
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import importlib
import pause_arbiter


class PauseArbiterTest(unittest.TestCase):
    def setUp(self):
        # isolate state file per test
        fd, self._tmp = tempfile.mkstemp(prefix="pause_arbiter_state_test_", suffix=".json")
        os.close(fd)
        os.remove(self._tmp)
        pause_arbiter.STATE_FILE = self._tmp
        pause_arbiter._REGISTRY.clear()

    def tearDown(self):
        try:
            os.remove(self._tmp)
        except OSError:
            pass

    def test_pause_writes_state_and_calls_kill_switch(self):
        kill_switch = types.SimpleNamespace(pause=MagicMock(return_value="PAUSED global"), resume=MagicMock())
        with patch.dict(sys.modules, {"kill_switch": kill_switch}):
            pause_arbiter.pause("test_reason", "something broke", by="tester", ttl_s=60)
        kill_switch.pause.assert_called_once()
        with open(self._tmp) as f:
            state = json.load(f)
        self.assertEqual(state["global:"]["reason_code"], "test_reason")
        self.assertEqual(state["global:"]["ttl_s"], 60)

    def test_recheck_lifts_when_registered_check_clears(self):
        pause_arbiter.register("clears_immediately", lambda: True, auto_expirable=True)
        kill_switch = types.SimpleNamespace(
            pause=MagicMock(), resume=MagicMock(),
            is_paused=MagicMock(return_value=True),
        )
        with patch.dict(sys.modules, {"kill_switch": kill_switch}):
            pause_arbiter.pause("clears_immediately", "transient", by="tester")
            result = pause_arbiter.recheck(scope="global")
        self.assertEqual(result["action"], "lifted")
        kill_switch.resume.assert_called_once()

    def test_recheck_leaves_manual_pause_alone(self):
        kill_switch = types.SimpleNamespace(
            pause=MagicMock(), resume=MagicMock(),
            is_paused=MagicMock(return_value=True),
        )
        # paused, but with no arbiter metadata (e.g. a manual dashboard STOP)
        with patch.dict(sys.modules, {"kill_switch": kill_switch}):
            result = pause_arbiter.recheck(scope="global")
        self.assertEqual(result["action"], "none")
        kill_switch.resume.assert_not_called()

    def test_recheck_never_auto_lifts_unregistered_reason_without_ttl(self):
        kill_switch = types.SimpleNamespace(
            pause=MagicMock(), resume=MagicMock(),
            is_paused=MagicMock(return_value=True),
        )
        with patch.dict(sys.modules, {"kill_switch": kill_switch}):
            pause_arbiter.pause("billing_real_spend_or_audit_failure", "real $ spend", by="tester", ttl_s=None)
            result = pause_arbiter.recheck(scope="global")
        self.assertEqual(result["action"], "none")
        kill_switch.resume.assert_not_called()

    def test_recheck_lifts_on_ttl_expiry_for_registered_reason(self):
        pause_arbiter.register("slow_clear", lambda: False, auto_expirable=True)
        kill_switch = types.SimpleNamespace(
            pause=MagicMock(), resume=MagicMock(),
            is_paused=MagicMock(return_value=True),
        )
        with patch.dict(sys.modules, {"kill_switch": kill_switch}):
            pause_arbiter.pause("slow_clear", "still not clear", by="tester", ttl_s=0)
            import time as _t
            _t.sleep(0.01)
            result = pause_arbiter.recheck(scope="global")
        self.assertEqual(result["action"], "lifted")
        kill_switch.resume.assert_called_once()

    def test_streak_resets_when_a_different_reason_trips(self):
        kill_switch = types.SimpleNamespace(pause=MagicMock(), resume=MagicMock())
        db = types.SimpleNamespace(insert=MagicMock())
        with patch.dict(sys.modules, {"kill_switch": kill_switch, "db": db}):
            pause_arbiter.pause("reason_a", "first", by="tester")
            pause_arbiter.pause("reason_a", "second", by="tester")
            pause_arbiter.pause("reason_b", "different cause", by="tester")
        with open(self._tmp) as f:
            state = json.load(f)
        self.assertEqual(state["global:"]["streak"], 1)
        self.assertFalse(state["global:"]["escalated"])
        db.insert.assert_not_called()

    def test_third_consecutive_identical_trip_escalates_and_files_approval(self):
        kill_switch = types.SimpleNamespace(pause=MagicMock(), resume=MagicMock())
        db = types.SimpleNamespace(insert=MagicMock())
        with patch.dict(sys.modules, {"kill_switch": kill_switch, "db": db}):
            pause_arbiter.pause("flappy_cause", "trip 1", by="tester")
            pause_arbiter.pause("flappy_cause", "trip 2", by="tester")
            pause_arbiter.pause("flappy_cause", "trip 3", by="tester")
        with open(self._tmp) as f:
            state = json.load(f)
        self.assertEqual(state["global:"]["streak"], 3)
        self.assertTrue(state["global:"]["escalated"])
        db.insert.assert_called_once()
        self.assertEqual(db.insert.call_args[0][0], "approvals")
        # a 4th trip while still escalated must not file a second approval
        with patch.dict(sys.modules, {"kill_switch": kill_switch, "db": db}):
            pause_arbiter.pause("flappy_cause", "trip 4", by="tester")
        db.insert.assert_called_once()

    def test_escalated_pause_is_never_auto_lifted_even_if_check_clears(self):
        pause_arbiter.register("flappy_cause", lambda: True, auto_expirable=True)
        kill_switch = types.SimpleNamespace(
            pause=MagicMock(), resume=MagicMock(),
            is_paused=MagicMock(return_value=True),
        )
        db = types.SimpleNamespace(insert=MagicMock())
        with patch.dict(sys.modules, {"kill_switch": kill_switch, "db": db}):
            pause_arbiter.pause("flappy_cause", "trip 1", by="tester")
            pause_arbiter.pause("flappy_cause", "trip 2", by="tester")
            pause_arbiter.pause("flappy_cause", "trip 3", by="tester")
            result = pause_arbiter.recheck(scope="global")
        self.assertEqual(result["action"], "none")
        kill_switch.resume.assert_not_called()


if __name__ == "__main__":
    unittest.main()
