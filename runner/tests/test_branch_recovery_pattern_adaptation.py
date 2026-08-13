#!/usr/bin/env python3
"""
Tests for pattern-adaptation recovery in the fleet-wide missing-branch sweep.

branch_recovery.recover_missing_branches (merged-diff library, similarity
threshold) was written and tested and then left at zero callers, so the
periodic sweep only ever had branch_fleet_recovery's git strategies: fetch
from remote, or requeue the whole task and pay for a fresh agent run.

Also covers _resolve_base, which replaced
`project.get("default_base", "master")` — dict.get's default does not fire
when the key is present and None, which it usually is.
"""
import os
import sys
import unittest
from unittest import mock

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RUNNER not in sys.path:
    sys.path.insert(0, RUNNER)

import branch_recovery_periodic as brp  # noqa: E402


class ResolveBaseTest(unittest.TestCase):
    def test_task_base_wins(self):
        self.assertEqual(
            brp._resolve_base({"default_base": "master"}, {"base_branch": "medicalOnly"}),
            "medicalOnly")

    def test_project_default_used_when_task_has_none(self):
        self.assertEqual(brp._resolve_base({"default_base": "main"}, {}), "main")

    def test_present_but_none_falls_through_instead_of_returning_none(self):
        """The original bug: dict.get(k, 'master') returns None when the key
        exists with a None value, which is what a selected-but-null column is."""
        with mock.patch.dict(sys.modules, {
            "branch_manager": mock.Mock(_detect_base_branch=lambda p: "master"),
        }):
            out = brp._resolve_base({"default_base": None, "repo_path": "/tmp"},
                                    {"base_branch": None})
        self.assertEqual(out, "master")

    def test_falls_back_to_repo_detection(self):
        with mock.patch.dict(sys.modules, {
            "branch_manager": mock.Mock(_detect_base_branch=lambda p: "develop"),
        }):
            out = brp._resolve_base({"repo_path": "/tmp"}, {})
        self.assertEqual(out, "develop")

    def test_whitespace_only_values_are_not_treated_as_a_base(self):
        with mock.patch.dict(sys.modules, {
            "branch_manager": mock.Mock(_detect_base_branch=lambda p: "master"),
        }):
            out = brp._resolve_base({"default_base": "   "}, {"base_branch": ""})
        self.assertEqual(out, "master")

    def test_detection_failure_falls_back_to_master_without_raising(self):
        with mock.patch.dict(sys.modules, {
            "branch_manager": mock.Mock(
                _detect_base_branch=mock.Mock(side_effect=RuntimeError("boom"))),
        }):
            self.assertEqual(brp._resolve_base({}, {}), "master")


class PatternAdaptTest(unittest.TestCase):
    def setUp(self):
        self._prev = brp.PATTERN_ADAPT
        brp.PATTERN_ADAPT = True

    def tearDown(self):
        brp.PATTERN_ADAPT = self._prev

    def _with_library(self, result):
        return mock.patch.dict(sys.modules, {
            "branch_recovery": mock.Mock(
                recover_missing_branches=mock.Mock(return_value=result)),
        })

    def test_returns_the_result_when_the_library_merged_something(self):
        with self._with_library({"merged": 1, "details": [{"slug": "s"}]}):
            out = brp._pattern_adapt({"slug": "s"}, {"repo_path": "/tmp", "name": "p"}, "master")
        self.assertIsNotNone(out)
        self.assertEqual(out["merged"], 1)

    def test_returns_none_when_nothing_merged(self):
        with self._with_library({"merged": 0, "quarantined": 1}):
            out = brp._pattern_adapt({"slug": "s"}, {"repo_path": "/tmp", "name": "p"}, "master")
        self.assertIsNone(out)

    def test_passes_project_isolation_and_the_resolved_base(self):
        lib = mock.Mock(return_value={"merged": 1})
        with mock.patch.dict(sys.modules, {
            "branch_recovery": mock.Mock(recover_missing_branches=lib),
        }):
            brp._pattern_adapt({"slug": "s"}, {"repo_path": "/r", "name": "beethoven"}, "medicalOnly")
        entries, kwargs = lib.call_args[0][0], lib.call_args[1]
        self.assertEqual(entries[0]["base"], "medicalOnly")
        self.assertEqual(entries[0]["project"], "beethoven")
        self.assertEqual(kwargs["project"], "beethoven")

    def test_disabled_by_flag_is_a_no_op(self):
        brp.PATTERN_ADAPT = False
        lib = mock.Mock(return_value={"merged": 1})
        with mock.patch.dict(sys.modules, {
            "branch_recovery": mock.Mock(recover_missing_branches=lib),
        }):
            self.assertIsNone(brp._pattern_adapt({"slug": "s"}, {}, "master"))
        lib.assert_not_called()

    def test_library_exception_is_fail_soft(self):
        with mock.patch.dict(sys.modules, {
            "branch_recovery": mock.Mock(
                recover_missing_branches=mock.Mock(side_effect=RuntimeError("down"))),
        }):
            self.assertIsNone(
                brp._pattern_adapt({"slug": "s"}, {"repo_path": "/tmp", "name": "p"}, "master"))


class RecoverProjectTest(unittest.TestCase):
    def setUp(self):
        self._dry = brp.DRY_RUN
        self._pa = brp.PATTERN_ADAPT
        brp.DRY_RUN = False
        brp.PATTERN_ADAPT = True

    def tearDown(self):
        brp.DRY_RUN = self._dry
        brp.PATTERN_ADAPT = self._pa

    def _run(self, git_result, pattern_result):
        with mock.patch.dict(sys.modules, {
            "branch_fleet_recovery": mock.Mock(
                recover_branch=mock.Mock(return_value=git_result)),
        }), mock.patch.object(brp, "_pattern_adapt", return_value=pattern_result), \
                mock.patch.object(brp, "_resolve_base", return_value="master"):
            return brp._recover_project(
                {"repo_path": "/tmp", "name": "p"}, [{"slug": "s"}])

    def test_git_recovery_short_circuits_pattern_adaptation(self):
        with mock.patch.dict(sys.modules, {
            "branch_fleet_recovery": mock.Mock(
                recover_branch=mock.Mock(return_value={"recovered": True, "strategy": "fetched_remote"})),
        }), mock.patch.object(brp, "_pattern_adapt") as pa, \
                mock.patch.object(brp, "_resolve_base", return_value="master"):
            detected, recovered = brp._recover_project(
                {"repo_path": "/tmp", "name": "p"}, [{"slug": "s"}])
        self.assertEqual((detected, recovered), (1, 1))
        pa.assert_not_called()

    def test_pattern_adaptation_runs_when_git_recovery_fails(self):
        detected, recovered = self._run(
            {"recovered": False, "strategy": "pat_unavailable"}, {"merged": 1})
        self.assertEqual((detected, recovered), (1, 1))

    def test_neither_strategy_succeeding_reports_zero_recovered(self):
        detected, recovered = self._run({"recovered": False, "strategy": "x"}, None)
        self.assertEqual((detected, recovered), (1, 0))

    def test_git_strategy_raising_still_reaches_pattern_adaptation(self):
        with mock.patch.dict(sys.modules, {
            "branch_fleet_recovery": mock.Mock(
                recover_branch=mock.Mock(side_effect=RuntimeError("git down"))),
        }), mock.patch.object(brp, "_pattern_adapt", return_value={"merged": 1}), \
                mock.patch.object(brp, "_resolve_base", return_value="master"):
            detected, recovered = brp._recover_project(
                {"repo_path": "/tmp", "name": "p"}, [{"slug": "s"}])
        self.assertEqual((detected, recovered), (1, 1))

    def test_dry_run_attempts_nothing(self):
        brp.DRY_RUN = True
        with mock.patch.dict(sys.modules, {
            "branch_fleet_recovery": mock.Mock(recover_branch=mock.Mock()),
        }) , mock.patch.object(brp, "_pattern_adapt") as pa, \
                mock.patch.object(brp, "_resolve_base", return_value="master"):
            detected, recovered = brp._recover_project(
                {"repo_path": "/tmp", "name": "p"}, [{"slug": "s"}])
        self.assertEqual((detected, recovered), (1, 0))
        pa.assert_not_called()

    def test_stats_expose_both_strategies(self):
        self.assertIn("recovered_git", brp.stats())
        self.assertIn("recovered_pattern", brp.stats())


if __name__ == "__main__":
    unittest.main()
