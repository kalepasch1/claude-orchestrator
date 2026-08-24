#!/usr/bin/env python3
"""The quality-gate entry point: `make lint` / `tools/quality_check.py`.

The checks existed and each ran on its own; there was no single command, so "run the
complete quality check suite end to end" had no suite to run. That gap let four files
reach master carrying merge-conflict markers — every one a SyntaxError, which took out
COLLECTION of three test modules, the most expensive kind of red because the tests inside
never run and are never counted as failures.

Two properties are load-bearing and both are tested here:

* THE HARD/ADVISORY SPLIT. Syntax errors and conflict markers fail the build; the ~200
  convention findings do not. A gate that fails on everything gets disabled within a week,
  and then catches nothing at all.
* DETERMINISM. The request specified "run checks multiple times to confirm stability", so
  every listing is sorted and no check depends on walk order.

Proof: python3 -m pytest runner/tests/test_quality_check.py -q
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "tools"))

import quality_check as qc  # noqa: E402


def _tree(**files):
    root = tempfile.mkdtemp()
    for name, body in files.items():
        path = os.path.join(root, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(body)
    return root


class TestSyntaxGate(unittest.TestCase):
    def test_a_clean_tree_passes(self):
        root = _tree(**{"a.py": "x = 1\n", "pkg/b.py": "def f():\n    return 2\n"})
        self.assertTrue(qc.check_syntax(root)["ok"])

    def test_a_syntax_error_fails(self):
        result = qc.check_syntax(_tree(**{"bad.py": "def (((\n"}))
        self.assertFalse(result["ok"])
        self.assertEqual(result["failures"][0]["file"], "bad.py")

    def test_a_conflict_marker_file_is_caught_as_a_syntax_error(self):
        """The exact shape that reached master four times."""
        body = "<<<<<<< HEAD\nx = 1\n=======\nx = 2\n>>>>>>> other\n"
        self.assertFalse(qc.check_syntax(_tree(**{"conflicted.py": body}))["ok"])

    def test_it_is_a_hard_gate(self):
        self.assertTrue(qc.check_syntax(_tree(**{"a.py": "x=1\n"}))["hard"])

    def test_skip_dirs_are_not_scanned(self):
        root = _tree(**{"node_modules/bad.py": "def (((\n", "ok.py": "x = 1\n"})
        self.assertTrue(qc.check_syntax(root)["ok"], "node_modules was scanned")

    def test_failures_are_sorted(self):
        root = _tree(**{"z.py": "def (((\n", "a.py": "def (((\n"})
        files = [f["file"] for f in qc.check_syntax(root)["failures"]]
        self.assertEqual(files, sorted(files))

    def test_an_empty_tree_passes(self):
        self.assertTrue(qc.check_syntax(_tree())["ok"])


class TestConflictMarkerGate(unittest.TestCase):
    def test_it_is_a_hard_gate(self):
        self.assertTrue(qc.check_conflict_markers(REPO)["hard"])

    def test_a_non_git_directory_does_not_raise(self):
        result = qc.check_conflict_markers(_tree(**{"a.py": "x = 1\n"}))
        self.assertIn("ok", result)

    def test_the_markers_are_anchored(self):
        """A markdown '=======' underline must not be treated as a conflict."""
        self.assertNotIn("^=======", qc.CONFLICT_MARKERS)


class TestConventionsAreAdvisory(unittest.TestCase):
    def test_conventions_never_fail_the_build(self):
        """~200 findings on master. Failing on them means nobody runs the suite."""
        result = qc.check_conventions(REPO)
        self.assertFalse(result["hard"])
        self.assertTrue(result["ok"])

    def test_the_count_is_reported_so_it_can_be_ratcheted(self):
        result = qc.check_conventions(REPO)
        self.assertTrue("findings" in result or "note" in result)

    def test_a_missing_linter_degrades_quietly(self):
        result = qc.check_conventions(_tree(**{"a.py": "x = 1\n"}))
        self.assertTrue(result["ok"])


class TestRunAndReport(unittest.TestCase):
    def test_a_clean_tree_reports_ok(self):
        report = qc.run(_tree(**{"a.py": "x = 1\n"}))
        self.assertTrue(report["ok"])
        self.assertEqual(report["hard_failures"], [])

    def test_a_hard_failure_is_named(self):
        report = qc.run(_tree(**{"bad.py": "def (((\n"}))
        self.assertFalse(report["ok"])
        self.assertIn("syntax", report["hard_failures"])

    def test_a_broken_gate_does_not_hide_the_others(self):
        original = qc.CHECKS

        def _boom(root):
            raise RuntimeError("gate exploded")

        qc.CHECKS = (_boom, qc.check_syntax)
        try:
            report = qc.run(_tree(**{"bad.py": "def (((\n"}))
        finally:
            qc.CHECKS = original
        self.assertIn("syntax", report["hard_failures"])

    def test_the_report_formats(self):
        text = qc.format_report(qc.run(_tree(**{"bad.py": "def (((\n"})))
        self.assertIn("HARD", text)
        self.assertIn("RESULT: FAIL", text)

    def test_a_clean_report_says_pass(self):
        self.assertIn("RESULT: PASS",
                      qc.format_report(qc.run(_tree(**{"a.py": "x = 1\n"}))))


class TestDeterminism(unittest.TestCase):
    """'Run checks multiple times to confirm stability' — the stated acceptance."""

    def test_the_same_tree_gives_byte_identical_output(self):
        root = _tree(**{"z.py": "def (((\n", "a.py": "x = 1\n", "p/b.py": "y = 2\n"})
        first = json.dumps(qc.run(root), sort_keys=True)
        for _ in range(3):
            self.assertEqual(json.dumps(qc.run(root), sort_keys=True), first)

    def test_file_discovery_is_sorted(self):
        root = _tree(**{"z.py": "x=1\n", "a.py": "x=1\n", "m.py": "x=1\n"})
        found = qc._python_files(root)
        self.assertEqual(found, sorted(found))


class TestCli(unittest.TestCase):
    def test_exit_zero_on_a_clean_tree(self):
        self.assertEqual(qc.main(["--root", _tree(**{"a.py": "x = 1\n"})]), 0)

    def test_exit_nonzero_on_a_hard_failure(self):
        self.assertEqual(qc.main(["--root", _tree(**{"bad.py": "def (((\n"})]), 1)

    def test_json_mode_emits_parseable_output(self):
        root = _tree(**{"a.py": "x = 1\n"})
        out = subprocess.run(
            [sys.executable, os.path.join(REPO, "tools", "quality_check.py"),
             "--json", "--root", root],
            capture_output=True, text=True, timeout=300)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertTrue(json.loads(out.stdout)["ok"])


class TestMakefileTarget(unittest.TestCase):
    def test_make_lint_exists(self):
        with open(os.path.join(REPO, "Makefile"), encoding="utf-8") as fh:
            body = fh.read()
        self.assertIn("\nlint:", body)
        self.assertIn("quality_check.py", body)

    def test_lint_is_declared_phony(self):
        with open(os.path.join(REPO, "Makefile"), encoding="utf-8") as fh:
            body = fh.read()
        phony = [ln for ln in body.splitlines() if ln.startswith(".PHONY:")]
        self.assertTrue(any("lint" in ln for ln in phony), phony)


if __name__ == "__main__":
    unittest.main()
