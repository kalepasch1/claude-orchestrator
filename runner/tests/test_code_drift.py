#!/usr/bin/env python3
"""Regression tests for the 2026-07-31 stale-process incident class:

1. _pull_safe must NOT count untracked files as dirty (they blocked auto-pull
   forever on any machine with intake/processed/*.md droppings).
2. code_drift_restart must fire when disk HEAD moves past the in-memory startup
   HEAD with runner/*.py changes — and must NOT fire on same-HEAD, non-runner
   changes, insufficient uptime, or when disabled.
"""
import os
import sys
import time
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import fleet_control  # noqa: E402


def _git_result(stdout="", returncode=0, stderr=""):
    r = types.SimpleNamespace()
    r.stdout, r.returncode, r.stderr = stdout, returncode, stderr
    return r


class PullSafeUntrackedTest(unittest.TestCase):
    def _run(self, porcelain, branch="master"):
        def fake_git(*args):
            if args[0] == "status":
                return _git_result(porcelain)
            if args[:2] == ("rev-parse", "--abbrev-ref"):
                return _git_result(branch + "\n")
            return _git_result("")
        with patch.object(fleet_control, "_git", side_effect=fake_git):
            return fleet_control._pull_safe()

    def test_untracked_only_is_safe(self):
        ok, reason = self._run("?? intake/processed/a.md\n?? intake/processed/b.md\n")
        self.assertTrue(ok, reason)

    def test_tracked_modification_blocks(self):
        ok, reason = self._run(" M runner/runner.py\n?? intake/processed/a.md\n")
        self.assertFalse(ok)
        self.assertIn("dirty tracked", reason)

    def test_clean_is_safe(self):
        ok, _ = self._run("")
        self.assertTrue(ok)

    def test_wrong_branch_blocks(self):
        ok, reason = self._run("", branch="agent/foo")
        self.assertFalse(ok)
        self.assertIn("agent/foo", reason)


class CodeDriftRestartTest(unittest.TestCase):
    def setUp(self):
        self._head = fleet_control._STARTUP_HEAD
        self._started = fleet_control._STARTED_AT
        fleet_control._STARTUP_HEAD = "aaaa1111"
        fleet_control._STARTED_AT = time.time() - 3600  # uptime satisfied
        os.environ.pop("ORCH_CODE_DRIFT_RESTART", None)

    def tearDown(self):
        fleet_control._STARTUP_HEAD = self._head
        fleet_control._STARTED_AT = self._started
        os.environ.pop("ORCH_CODE_DRIFT_RESTART", None)

    def _drift(self, head, changed, restart_calls):
        def fake_git(*args):
            if args[0] == "rev-parse":
                return _git_result(head + "\n")
            if args[0] == "diff":
                return _git_result(changed)
            return _git_result("")
        with patch.object(fleet_control, "_git", side_effect=fake_git), \
             patch.object(fleet_control, "_restart",
                          side_effect=lambda: restart_calls.append(1)):
            return fleet_control.code_drift_restart()

    def test_restarts_on_runner_py_drift(self):
        calls = []
        self._drift("bbbb2222", "runner/verify.py\nrunner/fleet_control.py\n", calls)
        self.assertEqual(len(calls), 1)

    def test_no_restart_same_head(self):
        calls = []
        self._drift("aaaa1111", "", calls)
        self.assertEqual(calls, [])

    def test_no_restart_non_runner_changes(self):
        calls = []
        self._drift("bbbb2222", "docs/README.md\nweb/app.vue\n", calls)
        self.assertEqual(calls, [])

    def test_no_restart_under_min_uptime(self):
        fleet_control._STARTED_AT = time.time()  # just started
        calls = []
        self._drift("bbbb2222", "runner/verify.py\n", calls)
        self.assertEqual(calls, [])

    def test_disabled_by_env(self):
        os.environ["ORCH_CODE_DRIFT_RESTART"] = "false"
        calls = []
        self._drift("bbbb2222", "runner/verify.py\n", calls)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
