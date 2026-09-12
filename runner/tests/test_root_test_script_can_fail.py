"""The repo's `npm test` must be able to report failure.

WHY THIS FILE EXISTS. The root package.json's test script read

    python3 -m pytest runner/tests/ -x --tb=short -q 2>&1 || true

and `|| true` makes the exit status 0 no matter what pytest found. That script is
not decoration:

  · production_push_guard.verify_tests() runs it to earn the "green suite" proof
    it refuses production pushes without. Observed directly on 2026-08-25: the
    guard printed "TESTS GREEN — full suite green for d2b3a549b9fd" on a tree
    that a separate run of the same suite, at the same commit, reported as
    2 failed. The verdict was not connected to the result.

  · it is also the default TEST_CMD (`npm test`) that merge_train, approval_merge,
    release_train, cade_tournaments, queue_elimination and pipeline_fusion fall
    back to, so it is what gates merges of orchestrator self-changes.

A gate whose command cannot fail is not a gate. merge_train.py's own comment says
as much about an earlier version of this exact problem: "('npm test'), which is
precisely what made the old gate meaningless."

This test asserts the property rather than the string, so reformatting the script
or changing pytest's flags is fine and re-introducing a swallow is not.
"""
import json
import os
import re
import subprocess
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

#: Shell constructs that force success regardless of what the command found.
_SWALLOWS = (
    re.compile(r"\|\|\s*true\b"),
    re.compile(r"\|\|\s*:\s*$"),
    re.compile(r"\|\|\s*exit\s+0\b"),
    re.compile(r";\s*exit\s+0\b"),
    re.compile(r"\btrue\s*$"),
)


def _root_scripts():
    with open(os.path.join(REPO, "package.json"), encoding="utf-8") as fh:
        return json.load(fh).get("scripts", {})


class RootTestScriptTest(unittest.TestCase):
    def test_the_test_script_exists_and_runs_the_suite(self):
        script = _root_scripts().get("test", "")
        self.assertTrue(script, "root package.json has no test script to gate on")
        self.assertIn("pytest", script,
                      f"the gate's test command does not run the suite: {script!r}")

    def test_the_test_script_does_not_swallow_its_exit_status(self):
        script = _root_scripts().get("test", "")
        for pattern in _SWALLOWS:
            self.assertIsNone(
                pattern.search(script),
                f"root `npm test` forces success ({pattern.pattern!r} in {script!r}). "
                "production_push_guard and every TEST_CMD fallback read this exit "
                "code as the verdict on the suite; with a swallow they cannot tell "
                "a green run from a red one.")

    def test_a_failing_pytest_invocation_really_does_exit_nonzero(self):
        """Asserted by running it, not by reading it.

        A regex can be satisfied by a script that still cannot fail for some
        other reason. This runs the script's own shape against a deliberately
        failing test file and requires a nonzero status.
        """
        script = _root_scripts().get("test", "")
        # Same shell, same flags, one file that fails on purpose.
        probe = script.replace("runner/tests/", "runner/tests/_gate_probe_tmp.py")
        path = os.path.join(REPO, "runner", "tests", "_gate_probe_tmp.py")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("def test_this_must_fail():\n    assert False\n")
        self.addCleanup(lambda: os.path.exists(path) and os.unlink(path))

        result = subprocess.run(probe, cwd=REPO, shell=True,
                                capture_output=True, text=True, timeout=300)
        self.assertNotEqual(
            result.returncode, 0,
            "a failing suite exited 0 — the production push guard would record it "
            f"as green.\nstdout: {result.stdout[-800:]}")


if __name__ == "__main__":
    unittest.main()
