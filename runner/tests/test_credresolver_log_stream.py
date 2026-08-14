"""Regression guard: cred-resolver informational output must not go to stderr.

The credresolver job was reported as a crash loop -- "134 occurrences, 100%
dead, zero successful runs" -- while actually exiting 0 and doing its job.  The
cause was not a crash at all: ``logging.basicConfig`` defaults to STDERR, so
every INFO line, including successes like "auto-resolved 1/2 credential
requests", was written to ``.runtime/logs/credresolver.err``.  The crash-loop
detector reads that file, so a healthy job looked permanently broken.

These tests pin the fix at the two levels that matter: the configuration says
stdout, and a real subprocess run leaves stderr clean.
"""
import os
import subprocess
import sys
import unittest

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE = os.path.join(RUNNER, "credential_auto_resolver.py")


class TestLogStreamConfiguration(unittest.TestCase):
    def test_basic_config_targets_stdout_explicitly(self):
        source = open(MODULE, encoding="utf-8").read()
        self.assertIn("stream=sys.stdout", source,
                      "informational logging must be pinned to stdout; "
                      "logging.basicConfig defaults to stderr")

    def test_the_reason_is_recorded_next_to_the_call(self):
        """A bare stream= is easy to 'tidy away' without the why."""
        source = open(MODULE, encoding="utf-8").read()
        self.assertIn("crash-loop", source.lower())


class TestSubprocessStreams(unittest.TestCase):
    """The behaviour the detector actually observes."""

    def _run(self):
        return subprocess.run(
            [sys.executable, MODULE],
            capture_output=True, text=True, timeout=120,
            cwd=RUNNER,
            env={**os.environ, "PYTHONPATH": RUNNER},
        )

    def test_informational_output_goes_to_stdout(self):
        result = self._run()
        self.assertIn("[cred-resolver]", result.stdout)

    def test_stderr_stays_clean_on_a_successful_run(self):
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr.strip(), "",
                         "a job that exits 0 must not write to stderr; that is "
                         "what made the detector call this a crash loop")

    def test_the_job_exits_zero(self):
        self.assertEqual(self._run().returncode, 0)


if __name__ == "__main__":
    unittest.main()
