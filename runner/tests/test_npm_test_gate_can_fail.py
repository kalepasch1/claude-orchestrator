#!/usr/bin/env python3
"""`npm test` is the fleet's merge gate. It must be able to fail.

TEST_CMD defaults to "npm test" in merge_train.py, approval_merge.py,
autonomous_test_runner.py, continuous_test_runner.py and cade_tournaments.py — so
whatever package.json calls "test" is what decides whether agent work merges.

It was:

    python3 -m pytest runner/tests/ -x --tb=short -q 2>&1 || true

`|| true` makes the command exit 0 unconditionally. The gate that decides what
reaches the release train could not fail, on any input, ever — a branch with a
syntax error passed it exactly as cleanly as a branch with none. `2>&1` without a
redirect target also folded stderr into stdout, so the failure text it was
discarding did not even reach the log separately.

These tests pin the two properties that make it a gate: the command propagates a
non-zero exit, and it runs a scope that is actually green so enforcing it does not
halt the fleet on debt it did not create.
"""
import json
import os
import subprocess
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PACKAGE_JSON = os.path.join(REPO, "package.json")


def _scripts():
    with open(PACKAGE_JSON, encoding="utf-8") as handle:
        return json.load(handle).get("scripts", {})


class NpmTestIsARealGate(unittest.TestCase):

    def test_the_test_script_exists(self):
        self.assertIn("test", _scripts())

    def test_the_test_script_cannot_swallow_its_exit_code(self):
        """The whole defect in one assertion."""
        command = _scripts()["test"]
        for swallow in ("|| true", "||true", "| true", "; true", "|| exit 0"):
            self.assertNotIn(swallow, command,
                             f"npm test ends in {swallow!r}; the merge gate cannot fail")

    def test_the_test_script_does_not_misdirect_stderr(self):
        """`2>&1` with no target folds stderr into stdout and loses the distinction
        between a failure message and ordinary output."""
        self.assertNotIn("2>&1", _scripts()["test"])

    def test_a_failing_command_in_this_shape_reports_non_zero(self):
        """Guards the shape, not just the string: `A && B` must propagate A's failure.
        A future edit that reintroduces a swallow in another spelling fails here."""
        command = _scripts()["test"].replace(
            "python3 -m pytest runner/tests/test_ci_offline.py -q --no-header",
            f"{sys.executable} -c 'import sys; sys.exit(3)'", 1)
        result = subprocess.run(command, shell=True, cwd=REPO,
                                capture_output=True, text=True, timeout=180)
        self.assertNotEqual(result.returncode, 0,
                            "the gate returned 0 for a command that failed")

    def test_the_gated_scope_is_green_so_enforcing_it_does_not_halt_the_fleet(self):
        """Making a gate real is only safe if it passes today. This is the same
        scope .github/workflows/ci.yml already blocks on, deliberately."""
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "runner/tests/test_ci_offline.py",
             "-q", "--no-header"],
            cwd=REPO, capture_output=True, text=True, timeout=600,
            env={**os.environ, "SUPABASE_URL": "", "SUPABASE_SERVICE_KEY": ""})
        self.assertEqual(result.returncode, 0, result.stdout[-2000:])

    def test_the_full_suite_is_still_reachable(self):
        """Narrowing the blocking gate must not hide the wider suite. It is not green
        today (~41 pre-existing failures), which is exactly why it is not the gate."""
        scripts = _scripts()
        self.assertIn("test:full", scripts)
        self.assertIn("runner/tests/", scripts["test:full"])
        self.assertNotIn("-x", scripts["test:full"],
                         "the full run should report every failure, not stop at the first")


if __name__ == "__main__":
    unittest.main()
