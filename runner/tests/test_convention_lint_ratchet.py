"""The convention lint must be gateable, and the gate must still be able to fail.

tools/convention_lint.py works — it compiles and runs — but it exits 1 because the
repo carries accumulated convention debt. A gate that is red on day one and stays
red is the same as having no gate, so CI cannot adopt it. The --baseline ratchet
(the pattern preflight.yml already uses for tsc via .tsc-error-baseline) makes the
useful half enforceable now.

The risk with a ratchet is that it silently tolerates everything, so these tests
assert BOTH directions: at/below baseline exits 0, above baseline exits non-zero.
"""
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LINT = REPO / "tools" / "convention_lint.py"


def _run(*args, cwd=None):
    # Bounded on purpose: this repo warns on unbounded subprocess.run() in tests,
    # and a lint that hangs should fail the test rather than the whole suite.
    return subprocess.run([sys.executable, str(LINT), *args],
                          cwd=str(cwd or REPO), capture_output=True, text=True,
                          timeout=120)


class TestConventionLintRatchet(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.pkg = self.dir / "sample"
        self.pkg.mkdir()
        # One known FAIL_SOFT_ERROR: a public function that raises on bad input.
        (self.pkg / "clean.py").write_text(textwrap.dedent('''\
            def safe(value):
                """Fail-soft: never raises."""
                try:
                    return int(value)
                except (TypeError, ValueError):
                    return 0
            '''))
        self.baseline = self.dir / "baseline"

    def tearDown(self):
        self.tmp.cleanup()

    def _add_violation(self):
        (self.pkg / "dirty.py").write_text(textwrap.dedent('''\
            def risky(value):
                """Raises on bad input, which the FAIL_SOFT_ERROR rule forbids."""
                if not value:
                    raise ValueError("bad input")
                return value
            '''))

    def test_write_baseline_records_the_current_count_and_exits_zero(self):
        r = _run("sample", "--write-baseline", str(self.baseline), cwd=self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(self.baseline.exists())
        self.assertGreaterEqual(int(self.baseline.read_text().strip()), 0)

    def test_at_baseline_exits_zero(self):
        _run("sample", "--write-baseline", str(self.baseline), cwd=self.dir)
        r = _run("sample", "--baseline", str(self.baseline), cwd=self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("at baseline", r.stdout)

    def test_a_new_violation_above_baseline_fails(self):
        # The whole point: the ratchet must still be able to go red.
        _run("sample", "--write-baseline", str(self.baseline), cwd=self.dir)
        self._add_violation()
        r = _run("sample", "--baseline", str(self.baseline), cwd=self.dir)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("new violation", r.stdout)

    def test_below_baseline_exits_zero_and_says_to_lower_it(self):
        self._add_violation()
        _run("sample", "--write-baseline", str(self.baseline), cwd=self.dir)
        (self.pkg / "dirty.py").unlink()
        r = _run("sample", "--baseline", str(self.baseline), cwd=self.dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("below baseline", r.stdout)

    def test_a_missing_baseline_file_is_fail_soft_not_a_crash(self):
        r = _run("sample", "--baseline", str(self.dir / "nope"), cwd=self.dir)
        self.assertIn("treating as 0", r.stdout)
        self.assertNotIn("Traceback", r.stderr)

    def test_a_garbage_baseline_file_is_fail_soft_not_a_crash(self):
        self.baseline.write_text("not-a-number\n")
        r = _run("sample", "--baseline", str(self.baseline), cwd=self.dir)
        self.assertIn("treating as 0", r.stdout)
        self.assertNotIn("Traceback", r.stderr)

    def test_default_behaviour_is_unchanged_without_the_flags(self):
        # Existing callers (pre-commit hook) must keep failing on violations.
        self._add_violation()
        r = _run("sample", cwd=self.dir)
        self.assertEqual(r.returncode, 1)
        self.assertNotIn("Traceback", r.stderr)


class TestConventionLintRunsOnThisRepo(unittest.TestCase):
    def test_the_tool_runs_without_a_traceback(self):
        # The task premise was that the tool had syntax/runtime errors. It does not:
        # it runs and reports real violations. Pin that so a future edit cannot
        # regress it into a crash unnoticed.
        r = _run("runner", "tools")
        self.assertNotIn("Traceback", r.stderr)
        self.assertIn(r.returncode, (0, 1))


if __name__ == "__main__":
    unittest.main()
