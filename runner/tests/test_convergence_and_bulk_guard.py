#!/usr/bin/env python3
"""Regression tests for the two invariants added by the anti-self-work re-architecture:

  1. THE CONVERGENCE GATE — nothing that cannot reach DEPLOYED_AND_VERIFIED may spawn children.
  2. THE BULK-UPDATE GUARD — no silent >100-row state transition (9,236 tasks were once
     flipped to MERGED this way, making every downstream metric untrue).
"""
import os
import sys
import types
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_RUNNER = os.path.dirname(_HERE)
sys.path.insert(0, _RUNNER)

# Stub db before importing the modules under test so no test touches the network.
if "db" not in sys.modules:
    _db = types.ModuleType("db")
    _db.select = lambda *a, **k: []
    _db.insert = lambda *a, **k: None
    _db.update = lambda *a, **k: None
    _db.count = lambda *a, **k: 0
    sys.modules["db"] = _db

import bulk_update_guard
import deployment_terminal


class ConvergenceGateTest(unittest.TestCase):
    def setUp(self):
        os.environ["ORCH_CONVERGENCE_GATE"] = "1"
        os.environ["ORCH_RELEASE_BACKPRESSURE"] = "0"   # isolate the gate from release state

    def test_blocked_tasks_may_still_be_decomposed(self):
        """BLOCKED is recoverable, not dead: auto_remediate decomposes blocked tasks to unblock
        them. Gating BLOCKED would stall the remediation path that lets work reach production."""
        ok, why = deployment_terminal.can_spawn_children({"slug": "big-feature", "state": "BLOCKED"})
        self.assertTrue(ok, why)

    def test_dead_states_cannot_spawn_children(self):
        for state in ("CLOSED", "QUARANTINED", "SHELVED", "SUPERSEDED"):
            ok, why = deployment_terminal.can_spawn_children({"slug": "t", "state": state})
            self.assertFalse(ok, f"{state} must not be allowed to spawn children")
            self.assertIn(state, why)

    def test_shadow_task_cannot_spawn_children(self):
        ok, why = deployment_terminal.can_spawn_children(
            {"slug": "shadow-abc", "state": "QUEUED", "shadow_only": True})
        self.assertFalse(ok)
        self.assertIn("shadow_only", why)

    def test_already_terminal_task_cannot_spawn_children(self):
        ok, _ = deployment_terminal.can_spawn_children(
            {"slug": "t", "state": deployment_terminal.DEPLOYED_AND_VERIFIED})
        self.assertFalse(ok)

    def test_live_task_may_spawn_children(self):
        ok, why = deployment_terminal.can_spawn_children({"slug": "t", "state": "RUNNING"})
        self.assertTrue(ok, why)

    def test_gate_is_reversible(self):
        os.environ["ORCH_CONVERGENCE_GATE"] = "0"
        ok, _ = deployment_terminal.can_spawn_children({"slug": "t", "state": "CLOSED"})
        self.assertTrue(ok, "gate must be disableable for emergency operation")


class BackPressureTest(unittest.TestCase):
    def setUp(self):
        os.environ["ORCH_RELEASE_BACKPRESSURE"] = "1"
        self._orig = deployment_terminal.blocking_release
        deployment_terminal.blocking_release = lambda project: (
            {"deploy_status": "failed", "to_sha": "deadbeefcafe"} if project == "red-app" else None)

    def tearDown(self):
        # restore, or the stub leaks into every later test in this process
        deployment_terminal.blocking_release = self._orig
        os.environ["ORCH_RELEASE_BACKPRESSURE"] = "0"

    def test_red_project_refuses_new_work(self):
        ok, why = deployment_terminal.project_accepts_work("red-app", "improve-something")
        self.assertFalse(ok)
        self.assertIn("RED", why)

    def test_green_project_accepts_work(self):
        ok, _ = deployment_terminal.project_accepts_work("green-app", "improve-something")
        self.assertTrue(ok)

    def test_healing_work_is_never_blocked(self):
        """If these were blocked a red project could never go green again — permanent deadlock.
        The prefixes must match what production actually emits (deployfix-, relfix-)."""
        for slug in ("deployfix-red-app-08041200", "relfix-red-app-4fa4039b",
                     "recover-missing-branch-foo", "hotfix-x", "rollback-y"):
            ok, why = deployment_terminal.project_accepts_work("red-app", slug)
            self.assertTrue(ok, f"{slug} must be exempt from back-pressure, got: {why}")


class BulkUpdateGuardTest(unittest.TestCase):
    def setUp(self):
        os.environ["ORCH_BULK_GUARD_ENABLED"] = "1"
        os.environ["ORCH_BULK_STATE_MAX"] = "100"
        os.environ.pop("ORCH_ALLOW_BULK_STATE_CHANGE", None)

    def test_small_state_change_allowed(self):
        self.assertTrue(bulk_update_guard.check("tasks", {"state": "MERGED"}, 100))

    def test_the_historical_9236_row_flip_is_refused(self):
        with self.assertRaises(bulk_update_guard.BulkStateChangeRefused):
            bulk_update_guard.check("tasks", {"state": "MERGED"}, 9236)

    def test_non_state_patch_is_never_blocked(self):
        self.assertTrue(bulk_update_guard.check("tasks", {"note": "hello"}, 50000))

    def test_override_allows_and_audits(self):
        audited = {}
        original = bulk_update_guard._audit
        bulk_update_guard._audit = lambda *a, **k: audited.setdefault("called", True)
        try:
            os.environ["ORCH_ALLOW_BULK_STATE_CHANGE"] = "intentional backfill"
            self.assertTrue(bulk_update_guard.check("tasks", {"state": "MERGED"}, 9236))
            self.assertTrue(audited.get("called"), "an allowed bulk change MUST be audited")
        finally:
            bulk_update_guard._audit = original

    def test_status_and_deploy_status_are_also_guarded(self):
        for field in ("status", "deploy_status"):
            with self.assertRaises(bulk_update_guard.BulkStateChangeRefused):
                bulk_update_guard.check("releases", {field: "success"}, 500)

    def test_unknown_row_count_is_refused(self):
        """An undeterminable row count is NOT permission — it is exactly when the guard matters
        most, since the write may be unbounded. db.update retries the count before giving up."""
        with self.assertRaises(bulk_update_guard.BulkStateChangeRefused):
            bulk_update_guard.check("tasks", {"state": "MERGED"}, None)

    def test_unknown_row_count_allowed_with_explicit_override(self):
        os.environ["ORCH_ALLOW_BULK_STATE_CHANGE"] = "operator confirmed"
        try:
            self.assertTrue(bulk_update_guard.check("tasks", {"state": "MERGED"}, None))
        finally:
            os.environ.pop("ORCH_ALLOW_BULK_STATE_CHANGE", None)


class SelfWorkGateTest(unittest.TestCase):
    def test_self_target_blocked_by_default(self):
        import self_work_gate
        os.environ.pop("ORCH_SELF_IMPROVEMENT_ENABLED", None)
        self.assertFalse(self_work_gate.allow_self_target("beethoven"))
        self.assertTrue(self_work_gate.allow_self_target("apparently"))

    def test_self_target_reversible(self):
        import self_work_gate
        os.environ["ORCH_SELF_IMPROVEMENT_ENABLED"] = "1"
        try:
            self.assertTrue(self_work_gate.allow_self_target("beethoven"))
        finally:
            os.environ.pop("ORCH_SELF_IMPROVEMENT_ENABLED", None)

    def test_all_synthetic_generators_default_off(self):
        import self_work_gate
        for flag in ("ORCH_CODER_CANARIES", "ORCH_DEPLOY_CANARIES",
                     "ORCH_SHADOW_TRIALS", "ORCH_SESSION_AUTOCONTINUE"):
            os.environ.pop(flag, None)
            self.assertFalse(self_work_gate.enabled(flag), f"{flag} must default OFF")


class HotReloadDrainTest(unittest.TestCase):
    def test_code_swap_refused_while_tasks_in_flight(self):
        import hot_reload
        os.environ["ORCH_HOT_RELOAD_REQUIRE_IDLE"] = "1"
        self.assertFalse(hot_reload._idle_enough(["task-a"]))
        self.assertFalse(hot_reload._idle_enough(None), "unknown in-flight count must be unsafe")
        self.assertTrue(hot_reload._idle_enough([]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
