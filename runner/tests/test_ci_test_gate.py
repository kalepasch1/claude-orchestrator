#!/usr/bin/env python3
"""ci_test_gate decides whether a branch may merge. It had no tests.

Two of its documented controls did nothing before this change, and nothing would
have noticed:

  * ORCH_CI_PASS_THRESHOLD was declared and never read. An operator setting 0.9 to
    tolerate a flaky suite got 1.0 behaviour, silently.
  * the `duration_s > MAX_DURATION` check was unreachable — MAX_DURATION is the
    subprocess timeout, so an overrun raises TimeoutExpired and returns passed=False,
    and the `not passed` branch returns first. "tests too slow" could never be said.

These tests pin what the gate actually does, so the next knob that stops working is
caught by a red test rather than by an incident.
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import ci_test_gate as gate


PY = sys.executable


class RunTests(unittest.TestCase):

    def test_a_passing_command_passes(self):
        out = gate.run_tests(".", f"{PY} -c 'import sys; sys.exit(0)'")
        self.assertTrue(out["passed"])
        self.assertEqual(out["exit_code"], 0)

    def test_a_failing_command_fails_and_keeps_its_exit_code(self):
        out = gate.run_tests(".", f"{PY} -c 'import sys; sys.exit(7)'")
        self.assertFalse(out["passed"])
        self.assertEqual(out["exit_code"], 7)

    def test_a_timeout_is_a_failure_not_a_pass(self):
        """This is where MAX_DURATION is really enforced."""
        out = gate.run_tests(".", f"{PY} -c 'import time; time.sleep(30)'", timeout=1)
        self.assertFalse(out["passed"])
        self.assertIn("timed out", out["stderr"])

    def test_a_command_that_cannot_run_is_a_failure(self):
        """Fail closed: an unlaunchable command must not read as a green suite."""
        with mock.patch.object(gate.subprocess, "run", side_effect=OSError("no shell")):
            out = gate.run_tests(".", "anything")
        self.assertFalse(out["passed"])


class GateMerge(unittest.TestCase):

    def setUp(self):
        self._db = mock.patch.object(gate.db, "insert", return_value=None)
        self._db.start()
        self.addCleanup(self._db.stop)
        for name, value in (("ENABLED", True), ("DRY_RUN", False), ("AUTO_BLOCK", False)):
            patcher = mock.patch.object(gate, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _gate(self, cmd):
        return gate.gate_merge("p", "slug", ".", cmd)

    def test_a_passing_suite_allows_the_merge(self):
        out = self._gate(f"{PY} -c 'import sys; sys.exit(0)'")
        self.assertTrue(out["allow"])
        self.assertEqual(out["reason"], "tests passed")

    def test_a_failing_suite_blocks_the_merge(self):
        out = self._gate(f"{PY} -c 'import sys; sys.exit(1)'")
        self.assertFalse(out["allow"])
        self.assertIn("tests failed", out["reason"])

    def test_a_disabled_gate_allows_and_says_so(self):
        with mock.patch.object(gate, "ENABLED", False):
            out = self._gate(f"{PY} -c 'import sys; sys.exit(1)'")
        self.assertTrue(out["allow"])
        self.assertEqual(out["reason"], "ci_test_gate disabled")

    def test_dry_run_allows_a_failing_suite_but_records_the_real_verdict(self):
        """Dry-run is the safe default. It must still tell the truth in the record —
        an advisory gate that reports a pass is indistinguishable from a broken one."""
        with mock.patch.object(gate, "DRY_RUN", True):
            out = self._gate(f"{PY} -c 'import sys; sys.exit(1)'")
        self.assertTrue(out["allow"])
        self.assertEqual(out["reason"], "dry-run mode")
        self.assertFalse(out["test_result"]["passed"])

    def test_auto_block_marks_the_task_blocked_on_failure(self):
        with mock.patch.object(gate, "AUTO_BLOCK", True), \
             mock.patch.object(gate.db, "update") as update:
            self._gate(f"{PY} -c 'import sys; sys.exit(1)'")
        update.assert_called_once()
        self.assertEqual(update.call_args.args[1]["state"], "BLOCKED")

    def test_a_db_outage_does_not_turn_a_failure_into_a_pass(self):
        """Recording the verdict and enforcing it are separate concerns."""
        with mock.patch.object(gate.db, "insert", side_effect=RuntimeError("db down")):
            out = self._gate(f"{PY} -c 'import sys; sys.exit(1)'")
        self.assertFalse(out["allow"])


class RemovedKnobsStayRemoved(unittest.TestCase):
    """Both were documented controls that did nothing. Re-adding either without an
    implementation puts the lie back."""

    def test_there_is_no_unread_pass_threshold_constant(self):
        self.assertFalse(hasattr(gate, "PASS_THRESHOLD"),
                         "PASS_THRESHOLD is back; implement a pass RATE or leave it out")

    def test_the_unreachable_duration_verdict_is_gone(self):
        source = open(gate.__file__, encoding="utf-8").read()
        body = source.split('"""', 2)[-1]  # skip the module docstring, which explains it
        self.assertNotIn('duration_s"] > MAX_DURATION', body,
                         "unreachable: MAX_DURATION is the subprocess timeout")

    def test_the_duration_bound_is_still_enforced_as_a_timeout(self):
        self.assertGreater(gate.MAX_DURATION, 0)
        out = gate.run_tests(".", f"{PY} -c 'import time; time.sleep(30)'", timeout=1)
        self.assertFalse(out["passed"])


if __name__ == "__main__":
    unittest.main()
