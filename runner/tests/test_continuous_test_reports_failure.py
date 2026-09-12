#!/usr/bin/env python3
"""continuous_test must be able to report a failing suite.

_run_cmd derives `passed` from `returncode == 0`, and run_unit_tests reports
`failed: 0 if passed else 1`. Every pytest branch of _detect_test_cmd used to end in
`2>&1 || true`, which forces returncode 0 — so for any pytest-based project this
module was structurally incapable of reporting a failure. It did not hide failures;
it could not see them.

Same defect, same session, as package.json's `npm test`, which ended in `|| true`
and made the fleet's merge gate unfailable.
"""
import json
import os
import sys
import tempfile
import shutil
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import continuous_test as ct


class DetectedCommandsCannotSwallowFailure(unittest.TestCase):

    SWALLOWS = ("|| true", "||true", "| true", "; true", "|| exit 0")

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self._saved = ct.UNIT_TEST_CMD
        ct.UNIT_TEST_CMD = ""
        self.addCleanup(lambda: setattr(ct, "UNIT_TEST_CMD", self._saved))

    def _assert_no_swallow(self, cmd):
        for swallow in self.SWALLOWS:
            self.assertNotIn(swallow, cmd,
                             f"detected command {cmd!r} can never report a failure")

    def test_a_pyproject_project_gets_a_command_that_can_fail(self):
        open(os.path.join(self.tmp, "pyproject.toml"), "w").close()
        self._assert_no_swallow(ct._detect_test_cmd(self.tmp))

    def test_a_pytest_ini_project_gets_a_command_that_can_fail(self):
        open(os.path.join(self.tmp, "pytest.ini"), "w").close()
        self._assert_no_swallow(ct._detect_test_cmd(self.tmp))

    def test_a_runner_tests_project_gets_a_command_that_can_fail(self):
        os.makedirs(os.path.join(self.tmp, "runner", "tests"))
        self._assert_no_swallow(ct._detect_test_cmd(self.tmp))

    def test_no_detected_command_anywhere_swallows_its_exit_code(self):
        """Covers every branch at once, including any added later."""
        open(os.path.join(self.tmp, "pyproject.toml"), "w").close()
        os.makedirs(os.path.join(self.tmp, "runner", "tests"), exist_ok=True)
        with open(os.path.join(self.tmp, "package.json"), "w") as handle:
            json.dump({"scripts": {"test": "pytest"}}, handle)
        self._assert_no_swallow(ct._detect_test_cmd(self.tmp))

    def test_an_explicit_override_is_returned_untouched(self):
        """The operator's TEST_CMD is theirs; this module must not rewrite it."""
        ct.UNIT_TEST_CMD = "make check"
        self.assertEqual(ct._detect_test_cmd(self.tmp), "make check")

    def test_a_project_with_no_tests_yields_no_command(self):
        self.assertEqual(ct._detect_test_cmd(self.tmp), "")


class FailureIsActuallyReported(unittest.TestCase):
    """End to end through _run_cmd: a failing suite must come back failed."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self._saved = ct.UNIT_TEST_CMD
        self.addCleanup(lambda: setattr(ct, "UNIT_TEST_CMD", self._saved))

    def test_a_failing_command_is_reported_as_failed(self):
        ct.UNIT_TEST_CMD = f"{sys.executable} -c 'import sys; sys.exit(1)'"
        out = ct.run_unit_tests(self.tmp)
        self.assertFalse(out["ok"])
        self.assertEqual(out["failed"], 1)

    def test_a_passing_command_is_reported_as_passed(self):
        ct.UNIT_TEST_CMD = f"{sys.executable} -c 'import sys; sys.exit(0)'"
        out = ct.run_unit_tests(self.tmp)
        self.assertTrue(out["ok"])
        self.assertEqual(out["failed"], 0)

    def test_a_swallowed_failure_would_be_caught_here(self):
        """The regression, stated as the behaviour rather than the string: appending
        the old swallow to a failing command must NOT produce a pass."""
        ct.UNIT_TEST_CMD = f"{sys.executable} -c 'import sys; sys.exit(1)' 2>&1 || true"
        out = ct.run_unit_tests(self.tmp)
        self.assertTrue(out["ok"], "sanity: the swallow does force a pass")
        # ...which is exactly why no command this module BUILDS may contain one.
        open(os.path.join(self.tmp, "pyproject.toml"), "w").close()
        ct.UNIT_TEST_CMD = ""
        self.assertNotIn("|| true", ct._detect_test_cmd(self.tmp))


if __name__ == "__main__":
    unittest.main()
