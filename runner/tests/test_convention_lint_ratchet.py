#!/usr/bin/env python3
"""The convention lint must be a ratchet, not a cliff.

`tools/lint_conventions.py` is the linter the pre-commit hook actually runs
(.pre-commit-config.yaml). It exited 1 on ANY violation, and the tree carries thousands
of them — so the hook failed on every commit and the only way to work was `--no-verify`,
which disables every other hook too. A gate that is always red is not a gate; it is a
thing people learn to skip.

The ratchet makes it enforceable today: a rule's count may not RISE above the recorded
baseline. Existing violations are counted and can only go down. Same shape as the repo's
.tsc-error-baseline.

These pin the properties that make that safe — above all that a corrupt or missing
baseline fails STRICT rather than silently disabling the gate.

Note on the end-to-end cases below: `.convention-lint-baseline.json` is a snapshot of a
whole-tree scan of `runner tools scripts`, so it has to be regenerated
(`--update-baseline` over those same three directories) whenever the tree's counts move
for a legitimate reason. If test_the_committed_tree_passes goes red, read the per-rule
"rose to" lines first: they say whether someone added violations or the snapshot is
merely stale.
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load_linter(module_path, module_name):
    """Load the hook's linter from its path, WITHOUT touching sys.path/sys.modules.

    This file used to do `sys.path.insert(REPO/tools)` + `import lint_conventions`. The
    repo has a SECOND module of that name, runner/tools/lint_conventions.py, and its own
    test files import it the same way — so whichever ran first owned the name for the
    session. Run alone, this file got the hook's linter and passed; run in the same
    session as the runner/tools secret tests, `lint` was the other module and all 12
    unit-level tests here died on AttributeError (no load_baseline/regressions), which
    reads like a broken ratchet rather than a broken import.
    """
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


lint = _load_linter(os.path.join(REPO, "tools", "lint_conventions.py"),
                    "tools_lint_conventions_ratchet")


class TestRegressionArithmetic(unittest.TestCase):
    def test_a_rising_count_is_a_regression(self):
        self.assertEqual(lint.regressions({"A": 5}, {"A": 4}), [("A", 5, 4)])

    def test_an_equal_count_is_not(self):
        self.assertEqual(lint.regressions({"A": 4}, {"A": 4}), [])

    def test_a_falling_count_is_not(self):
        self.assertEqual(lint.regressions({"A": 2}, {"A": 4}), [])

    def test_a_brand_new_rule_is_a_regression_against_an_implicit_zero(self):
        # A rule added later must not be grandfathered by omission — that is how a new
        # check lands already disabled.
        self.assertEqual(lint.regressions({"NEW": 1}, {"A": 4}), [("NEW", 1, 0)])

    def test_multiple_regressions_are_reported_together_and_sorted(self):
        self.assertEqual(lint.regressions({"B": 2, "A": 9}, {"A": 1, "B": 1}),
                         [("A", 9, 1), ("B", 2, 1)])


class TestBaselineLoading(unittest.TestCase):
    def _write(self, text):
        fh = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        fh.write(text)
        fh.close()
        self.addCleanup(os.unlink, fh.name)
        return fh.name

    def test_missing_file_reads_as_empty_not_as_permissive(self):
        # Empty baseline == nothing grandfathered == strict. Failing the other way would
        # let deleting the file silently switch the gate off.
        self.assertEqual(lint.load_baseline("/nonexistent/baseline.json"), {})

    def test_corrupt_file_reads_as_empty(self):
        self.assertEqual(lint.load_baseline(self._write("{not json")), {})

    def test_counts_are_read(self):
        path = self._write(json.dumps({"counts": {"A": 3}}))
        self.assertEqual(lint.load_baseline(path), {"A": 3})

    def test_non_numeric_entries_are_ignored(self):
        path = self._write(json.dumps({"counts": {"A": 3, "B": "lots"}}))
        self.assertEqual(lint.load_baseline(path), {"A": 3})

    def test_a_corrupt_baseline_makes_everything_a_regression(self):
        # The composition that matters: unreadable baseline -> strict gate.
        self.assertTrue(lint.regressions({"A": 1}, lint.load_baseline("/nope.json")))


class TestTheRealGate(unittest.TestCase):
    """End-to-end through the CLI, against the committed baseline."""

    def _run(self, *args):
        return subprocess.run(
            [sys.executable, os.path.join(REPO, "tools", "lint_conventions.py"), *args],
            capture_output=True, text=True, cwd=REPO, timeout=900)

    def test_the_committed_tree_passes(self):
        result = self._run("runner", "tools", "scripts")
        self.assertEqual(result.returncode, 0,
                         f"the gate must be green on the tree it was baselined against:\n"
                         f"{result.stderr[-2000:]}")

    def test_a_new_violation_fails_the_gate(self):
        """The whole point: grandfathering must not disable the rule.

        A fresh silent swallow in a new file pushes FAIL_SOFT_ERROR above its baseline.
        """
        path = os.path.join(REPO, "runner", "_ratchet_probe_tmp.py")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("def f():\n    try:\n        g()\n    except Exception:\n        pass\n")
        self.addCleanup(lambda: os.path.exists(path) and os.unlink(path))
        result = self._run("runner", "tools", "scripts")
        self.assertEqual(result.returncode, 1, "a NEW violation must fail the gate")
        self.assertIn("FAIL_SOFT_ERROR", result.stderr)
        self.assertIn("rose to", result.stderr)

    def test_failure_output_names_only_the_offending_rule(self):
        # A dump of every grandfathered violation buries the handful of lines the
        # author must actually fix.
        path = os.path.join(REPO, "runner", "_ratchet_probe_tmp2.py")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("def f():\n    try:\n        g()\n    except Exception:\n        pass\n")
        self.addCleanup(lambda: os.path.exists(path) and os.unlink(path))
        result = self._run("runner", "tools", "scripts")
        printed = [ln for ln in result.stdout.splitlines() if ": " in ln]
        self.assertTrue(printed)
        self.assertTrue(all("FAIL_SOFT_ERROR" in ln for ln in printed),
                        "only the regressed rule's violations should be printed")

    def test_baseline_file_is_committed_and_well_formed(self):
        with open(os.path.join(REPO, ".convention-lint-baseline.json"), encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertIn("counts", data)
        self.assertGreater(data["total"], 0)
        self.assertEqual(data["total"], sum(data["counts"].values()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
