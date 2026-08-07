"""Branch-recovery automation contract (improve-automate-branch-management).

Gap being closed: "manual intervention is required to recover missing
branches". The owner module is autopilot.recovery_agent — it must sweep
missing-branch / tested-but-unintegrated work autonomously via
integration_sweeper.sweep with run_train=True (so recovered work rides the
merge train without a human), honoring AUTOPILOT_SWEEP_LIMIT. This test
pins that wiring so a refactor can't silently reintroduce a manual step.
"""
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner"))

# Mock db before importing autopilot (module imports db at load time).
mock_db = types.ModuleType("db")
mock_db.select = lambda *a, **kw: []
mock_db.insert = lambda *a, **kw: None
mock_db.update = lambda *a, **kw: None
sys.modules.setdefault("db", mock_db)

import autopilot  # noqa: E402


class RecoveryAgentContractTest(unittest.TestCase):
    def _run_with_mock_sweeper(self):
        calls = []
        sweeper = types.ModuleType("integration_sweeper")
        sweeper.sweep = lambda **kw: calls.append(kw) or {"swept": 0}
        sys.modules["integration_sweeper"] = sweeper
        try:
            result = autopilot.recovery_agent()
        finally:
            sys.modules.pop("integration_sweeper", None)
        return calls, result

    def test_recovery_agent_sweeps_without_manual_intervention(self):
        calls, result = self._run_with_mock_sweeper()
        self.assertEqual(len(calls), 1, "recovery_agent must invoke integration_sweeper.sweep")
        self.assertTrue(calls[0].get("run_train"),
                        "recovered branches must ride the merge train automatically")
        self.assertEqual(result, {"swept": 0})

    def test_sweep_limit_comes_from_env(self):
        os.environ["AUTOPILOT_SWEEP_LIMIT"] = "7"
        try:
            calls, _ = self._run_with_mock_sweeper()
        finally:
            os.environ.pop("AUTOPILOT_SWEEP_LIMIT", None)
        self.assertEqual(calls[0].get("limit"), 7)

    def test_recovery_prefix_is_stable(self):
        # blocker_quarantine and backlog tooling key off this prefix; a rename
        # would orphan every queued recover-missing-branch task.
        self.assertEqual(autopilot.RECOVERY_PREFIX, "recover-missing-branch-")


if __name__ == "__main__":
    unittest.main()
