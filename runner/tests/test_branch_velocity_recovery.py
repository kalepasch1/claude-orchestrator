#!/usr/bin/env python3
"""Tests: queue_velocity PID shelving is consecutive-gated, integral-clamped,
env-tunable, and runs a zero-spend branch-recovery check before shelving.

Covers the four required behaviours:
  1. a single low-EV / high-integral sample is NOT shelved
  2. sustained high integral triggers the clamp and then shelving/recovery
  3. tasks whose branch is missing but reconstructable are recovered, not shelved
  4. lease/RPC/infra errors during the recovery check are fail-soft (no shelve)
"""
import importlib
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import queue_velocity as qv

TASK = {"id": "t-1", "slug": "fix-widget", "confidence": 0.1, "project_id": "proj-1"}
PROJECT_ROW = {"id": "proj-1", "repo_path": "/fake/repo", "default_base": "main"}


class ControllerTestBase(unittest.TestCase):
    """Isolate controller state files and thresholds per test."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._patches = [
            patch.object(qv, "STATE_FILE", os.path.join(self._tmp.name, "state.json")),
            patch.object(qv, "GENERATOR_PAUSE_FILE",
                         os.path.join(self._tmp.name, "pause.json")),
        ]
        for p in self._patches:
            p.start()
        self.addCleanup(self._tmp.cleanup)
        for p in self._patches:
            self.addCleanup(p.stop)

    def run_with_depths(self, depths, **overrides):
        """Run the controller once per depth sample; return list of decisions."""
        results = []
        ctx = [patch.object(qv, k, v) for k, v in overrides.items()]
        for c in ctx:
            c.start()
        try:
            for d in depths:
                with patch.object(qv.db, "count", return_value=d):
                    results.append(qv.run())
        finally:
            for c in ctx:
                c.stop()
        return results


# ---------------------------------------------------------------------------
# 1. Consecutive-sample gating: a single high-integral sample never shelves
# ---------------------------------------------------------------------------

class SingleLowEvSampleNotShelvedTest(ControllerTestBase):
    def test_single_over_threshold_sample_builds_pressure_only(self):
        with patch.object(qv, "_shelve_lowest_ev", return_value=0) as shelve:
            results = self.run_with_depths(
                [100, 200],  # velocity +100 on 2nd sample -> integral 100 > 10
                INTEGRAL_SHELVE_THRESHOLD=10, SHELVE_MIN_DEPTH=0,
                SHELVE_CONSECUTIVE_REQUIRED=2)
        shelve.assert_not_called()
        self.assertFalse(results[-1]["i_action"])
        self.assertEqual(results[-1]["shelve_pressure"], 1)

    def test_pressure_resets_when_integral_drops(self):
        with patch.object(qv, "_shelve_lowest_ev", return_value=0) as shelve:
            # 2nd sample builds pressure; 3rd drains the queue and resets it
            results = self.run_with_depths(
                [100, 200, 50],
                INTEGRAL_SHELVE_THRESHOLD=50, SHELVE_MIN_DEPTH=0,
                SHELVE_CONSECUTIVE_REQUIRED=2)
        shelve.assert_not_called()
        self.assertEqual(results[-1]["shelve_pressure"], 0)

    def test_consecutive_over_threshold_samples_do_shelve(self):
        with patch.object(qv, "_shelve_lowest_ev", return_value=5) as shelve:
            results = self.run_with_depths(
                [100, 200, 300],  # integral 100 then 200, both > 10
                INTEGRAL_SHELVE_THRESHOLD=10, SHELVE_MIN_DEPTH=0,
                SHELVE_CONSECUTIVE_REQUIRED=2)
        shelve.assert_called_once()
        self.assertTrue(results[-1]["i_action"])
        self.assertEqual(results[-1]["shelved"], 5)
        # Pressure resets after acting
        self.assertEqual(results[-1]["shelve_pressure"], 0)

    def test_decision_state_is_observable(self):
        results = self.run_with_depths([100], SHELVE_CONSECUTIVE_REQUIRED=99)
        self.assertEqual(qv.last_decision(), results[-1])
        for key in ("depth", "velocity", "integral", "integral_clamped",
                    "shelve_pressure", "i_action", "shelved"):
            self.assertIn(key, results[-1])


# ---------------------------------------------------------------------------
# 2. Integral anti-windup clamp
# ---------------------------------------------------------------------------

class IntegralClampTest(ControllerTestBase):
    def test_integral_is_clamped_at_max(self):
        results = self.run_with_depths(
            [100, 200, 300, 400],  # raw integral would reach 300
            INTEGRAL_MAX=150, SHELVE_CONSECUTIVE_REQUIRED=99)
        self.assertEqual(results[-1]["integral"], 150)
        self.assertTrue(results[-1]["integral_clamped"])

    def test_integral_below_max_is_not_flagged(self):
        results = self.run_with_depths(
            [100, 200], INTEGRAL_MAX=10_000, SHELVE_CONSECUTIVE_REQUIRED=99)
        self.assertEqual(results[-1]["integral"], 100)
        self.assertFalse(results[-1]["integral_clamped"])

    def test_measurement_failure_preserves_state(self):
        with patch.object(qv.db, "count", side_effect=RuntimeError("db down")):
            result = qv.run()
        self.assertFalse(result["ok"])
        self.assertFalse(result["measurement_valid"])


# ---------------------------------------------------------------------------
# 3. Zero-spend recovery hook: reconstructable branches are kept, not shelved
# ---------------------------------------------------------------------------

class RecoveryBeforeShelveTest(ControllerTestBase):
    def _shelve_one(self, detect, recover_result=None, recover_side_effect=None):
        """Run _shelve_lowest_ev over one task with mocked recovery plumbing."""
        with patch.object(qv.db, "select") as sel, \
             patch.object(qv.db, "update") as upd, \
             patch("os.path.isdir", return_value=True), \
             patch("patch_recovery.detect_branch", **detect), \
             patch("patch_recovery.recover",
                   return_value=recover_result,
                   side_effect=recover_side_effect) as rec:
            sel.side_effect = lambda table, *a, **k: (
                [dict(TASK)] if table == "tasks" else [dict(PROJECT_ROW)])
            shelved = qv._shelve_lowest_ev(1)
        return shelved, upd, rec

    def test_branch_present_is_not_shelved(self):
        shelved, upd, rec = self._shelve_one(
            {"return_value": {"found": True, "location": "worktree",
                              "branch": "agent/fix-widget", "path": "/wt"}})
        self.assertEqual(shelved, 0)
        upd.assert_not_called()
        rec.assert_not_called()

    def test_missing_branch_reconstructed_instead_of_shelved(self):
        shelved, upd, rec = self._shelve_one(
            {"return_value": {"found": False, "location": None,
                              "branch": "agent/fix-widget", "path": None}},
            recover_result={"ok": True, "method": "patch_replay",
                            "branch": "agent/fix-widget"})
        self.assertEqual(shelved, 0)
        upd.assert_not_called()
        rec.assert_called_once_with("/fake/repo", "fix-widget", "main",
                                    project="proj-1")

    def test_unrecoverable_task_is_shelved(self):
        """Empty patch library / no cache hit: shelving proceeds normally."""
        shelved, upd, _ = self._shelve_one(
            {"return_value": {"found": False, "location": None,
                              "branch": "agent/fix-widget", "path": None}},
            recover_result={"ok": False, "method": "none",
                            "reason": "all mechanical recovery methods exhausted"})
        self.assertEqual(shelved, 1)
        upd.assert_called_once()
        self.assertEqual(upd.call_args[0][2]["state"], "SHELVED")

    def test_recovery_disabled_shelves_without_checking(self):
        with patch.object(qv, "RECOVERY_ENABLED", False), \
             patch.object(qv.db, "select", return_value=[dict(TASK)]), \
             patch.object(qv.db, "update") as upd, \
             patch("patch_recovery.detect_branch") as det:
            shelved = qv._shelve_lowest_ev(1)
        self.assertEqual(shelved, 1)
        det.assert_not_called()
        upd.assert_called_once()

    def test_task_without_repo_on_disk_is_shelved(self):
        with patch.object(qv.db, "select") as sel, \
             patch.object(qv.db, "update") as upd, \
             patch("os.path.isdir", return_value=False):
            sel.side_effect = lambda table, *a, **k: (
                [dict(TASK)] if table == "tasks" else [dict(PROJECT_ROW)])
            shelved = qv._shelve_lowest_ev(1)
        self.assertEqual(shelved, 1)
        upd.assert_called_once()

    def test_mixed_batch_only_unrecoverable_shelved(self):
        tasks = [
            {"id": "t-1", "slug": "has-branch", "confidence": 0.1, "project_id": "proj-1"},
            {"id": "t-2", "slug": "recoverable", "confidence": 0.2, "project_id": "proj-1"},
            {"id": "t-3", "slug": "gone", "confidence": 0.3, "project_id": "proj-1"},
        ]
        detections = {
            "has-branch": {"found": True, "location": "local",
                           "branch": "agent/has-branch", "path": None},
            "recoverable": {"found": False, "location": None,
                            "branch": "agent/recoverable", "path": None},
            "gone": {"found": False, "location": None,
                     "branch": "agent/gone", "path": None},
        }
        recoveries = {
            "recoverable": {"ok": True, "method": "reflog", "branch": "agent/recoverable"},
            "gone": {"ok": False, "method": "none", "reason": "exhausted"},
        }
        with patch.object(qv.db, "select") as sel, \
             patch.object(qv.db, "update") as upd, \
             patch("os.path.isdir", return_value=True), \
             patch("patch_recovery.detect_branch",
                   side_effect=lambda repo, slug: detections[slug]), \
             patch("patch_recovery.recover",
                   side_effect=lambda repo, slug, base, **kw: recoveries[slug]):
            sel.side_effect = lambda table, *a, **k: (
                [dict(t) for t in tasks] if table == "tasks" else [dict(PROJECT_ROW)])
            shelved = qv._shelve_lowest_ev(3)
        self.assertEqual(shelved, 1)
        upd.assert_called_once()
        self.assertEqual(upd.call_args[0][1], {"id": "t-3"})


# ---------------------------------------------------------------------------
# 4. Fail-soft on infra errors (branch_lease pattern): outage != unrecoverable
# ---------------------------------------------------------------------------

class InfraErrorFailSoftTest(ControllerTestBase):
    def test_recovery_infra_error_does_not_shelve(self):
        with patch.object(qv.db, "select") as sel, \
             patch.object(qv.db, "update") as upd, \
             patch("os.path.isdir", return_value=True), \
             patch("patch_recovery.detect_branch",
                   side_effect=RuntimeError("lease RPC unreachable")):
            sel.side_effect = lambda table, *a, **k: (
                [dict(TASK)] if table == "tasks" else [dict(PROJECT_ROW)])
            shelved = qv._shelve_lowest_ev(1)
        self.assertEqual(shelved, 0)
        upd.assert_not_called()

    def test_recover_rpc_error_does_not_shelve(self):
        shelved = None
        with patch.object(qv.db, "select") as sel, \
             patch.object(qv.db, "update") as upd, \
             patch("os.path.isdir", return_value=True), \
             patch("patch_recovery.detect_branch",
                   return_value={"found": False, "location": None,
                                 "branch": "agent/fix-widget", "path": None}), \
             patch("patch_recovery.recover",
                   side_effect=OSError("db rpc 503")):
            sel.side_effect = lambda table, *a, **k: (
                [dict(TASK)] if table == "tasks" else [dict(PROJECT_ROW)])
            shelved = qv._shelve_lowest_ev(1)
        self.assertEqual(shelved, 0)
        upd.assert_not_called()

    def test_project_lookup_error_is_fail_soft_shelve_path(self):
        """_get_project swallows db errors and returns None -> no repo -> shelve
        proceeds (a missing project row is a data condition, not an outage)."""
        def sel(table, *a, **k):
            if table == "tasks":
                return [dict(TASK)]
            raise RuntimeError("projects table unavailable")
        with patch.object(qv.db, "select", side_effect=sel), \
             patch.object(qv.db, "update") as upd:
            shelved = qv._shelve_lowest_ev(1)
        self.assertEqual(shelved, 1)
        upd.assert_called_once()

    def test_task_query_error_returns_zero(self):
        with patch.object(qv.db, "select", side_effect=RuntimeError("db down")):
            self.assertEqual(qv._shelve_lowest_ev(10), 0)

    def test_update_error_is_swallowed(self):
        with patch.object(qv.db, "select", return_value=[dict(TASK)]), \
             patch.object(qv.db, "update", side_effect=RuntimeError("db down")), \
             patch.object(qv, "RECOVERY_ENABLED", False):
            self.assertEqual(qv._shelve_lowest_ev(1), 0)


# ---------------------------------------------------------------------------
# Env-var tunables
# ---------------------------------------------------------------------------

class EnvTunableTest(unittest.TestCase):
    ENV_KEYS = ("ORCH_QV_INTEGRAL_SHELVE", "ORCH_QV_SHELVE_CONSECUTIVE",
                "ORCH_QV_INTEGRAL_MAX", "ORCH_QV_SHELVE_PCT",
                "ORCH_QV_SHELVE_MIN_DEPTH", "ORCH_QV_RECOVERY_ENABLED")

    def _reload_with(self, env):
        saved = {k: os.environ.get(k) for k in self.ENV_KEYS}
        try:
            for k in self.ENV_KEYS:
                os.environ.pop(k, None)
            os.environ.update(env)
            return importlib.reload(qv)
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def tearDown(self):
        importlib.reload(qv)  # restore defaults for other tests

    def test_thresholds_come_from_env(self):
        mod = self._reload_with({
            "ORCH_QV_INTEGRAL_SHELVE": "123",
            "ORCH_QV_SHELVE_CONSECUTIVE": "5",
            "ORCH_QV_INTEGRAL_MAX": "999",
            "ORCH_QV_SHELVE_PCT": "0.5",
            "ORCH_QV_SHELVE_MIN_DEPTH": "42",
            "ORCH_QV_RECOVERY_ENABLED": "false",
        })
        self.assertEqual(mod.INTEGRAL_SHELVE_THRESHOLD, 123)
        self.assertEqual(mod.SHELVE_CONSECUTIVE_REQUIRED, 5)
        self.assertEqual(mod.INTEGRAL_MAX, 999)
        self.assertEqual(mod.SHELVE_PCT, 0.5)
        self.assertEqual(mod.SHELVE_MIN_DEPTH, 42)
        self.assertFalse(mod.RECOVERY_ENABLED)

    def test_bad_env_values_fall_back_to_defaults(self):
        mod = self._reload_with({
            "ORCH_QV_INTEGRAL_SHELVE": "not-a-number",
            "ORCH_QV_SHELVE_PCT": "also-bad",
        })
        self.assertEqual(mod.INTEGRAL_SHELVE_THRESHOLD, 5000)
        self.assertEqual(mod.SHELVE_PCT, 0.20)

    def test_defaults_without_env(self):
        mod = self._reload_with({})
        self.assertEqual(mod.INTEGRAL_SHELVE_THRESHOLD, 5000)
        self.assertEqual(mod.SHELVE_CONSECUTIVE_REQUIRED, 2)
        self.assertEqual(mod.INTEGRAL_MAX, 15000)
        self.assertTrue(mod.RECOVERY_ENABLED)


if __name__ == "__main__":
    unittest.main()
