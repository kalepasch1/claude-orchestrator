#!/usr/bin/env python3
"""Tests for runner/tools/adjudicate_evidence_snapshot.py.

Builds a throwaway git repo per case so the assertions are about the
adjudicator's logic, not about whatever the fleet repo happens to look like.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
)

import adjudicate_evidence_snapshot as ade  # noqa: E402


def _run(repo, *args):
    subprocess.run(
        ["git", "-C", repo] + list(args), check=True, capture_output=True, text=True
    )


def _commit(repo, message):
    _run(repo, "add", "-A")
    _run(
        repo,
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@example.com",
        "commit",
        "-q",
        "-m",
        message,
    )
    return subprocess.run(
        ["git", "-C", repo, "rev-parse", "HEAD"], capture_output=True, text=True
    ).stdout.strip()


def _write(repo, path, text):
    full = os.path.join(repo, path)
    os.makedirs(os.path.dirname(full) or repo, exist_ok=True)
    with open(full, "w", encoding="utf-8") as handle:
        handle.write(text)


class TestAdjudicateEvidenceSnapshot(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = self._tmp.name
        _run(self.repo, "init", "-q", "-b", "main")

    def tearDown(self):
        self._tmp.cleanup()

    def test_identical_path_is_identical(self):
        _write(self.repo, "a.py", "x = 1\n")
        snap = _commit(self.repo, "snap")
        entry = ade.adjudicate_path(self.repo, snap, "HEAD", "a.py")
        self.assertEqual(entry["verdict"], ade.IDENTICAL)

    def test_pure_addition_by_base_is_superseded(self):
        _write(self.repo, "a.py", "x = 1\n")
        snap = _commit(self.repo, "snap")
        _write(self.repo, "a.py", "x = 1\ny = 2\nz = 3\n")
        _commit(self.repo, "base moves on")
        entry = ade.adjudicate_path(self.repo, snap, "HEAD", "a.py")
        self.assertEqual(entry["verdict"], ade.SUPERSEDED_BY_NEWER)
        self.assertEqual(entry["snapshot_to_base"]["deleted"], 0)

    def test_two_sided_change_is_diverged(self):
        _write(self.repo, "a.py", "x = 1\nkeep = 0\n")
        _commit(self.repo, "root")
        _write(self.repo, "a.py", "x = 1\nsnapshot_only = 1\n")
        snap = _commit(self.repo, "snap")
        _run(self.repo, "checkout", "-q", "HEAD~1", "--", "a.py")
        _write(self.repo, "a.py", "x = 1\nbase_only = 1\n")
        _commit(self.repo, "base")
        entry = ade.adjudicate_path(self.repo, snap, "HEAD", "a.py")
        self.assertEqual(entry["verdict"], ade.DIVERGED)

    def test_missing_path_is_evidence_absent(self):
        _write(self.repo, "a.py", "x = 1\n")
        snap = _commit(self.repo, "snap")
        entry = ade.adjudicate_path(self.repo, snap, "HEAD", "nope.py")
        self.assertEqual(entry["verdict"], ade.EVIDENCE_ABSENT)

    def test_conflict_markers_are_reported(self):
        _write(self.repo, "a.py", "x = 1\n")
        _commit(self.repo, "root")
        _write(self.repo, "a.py", "<<<<<<< HEAD\nx = 1\n=======\nx = 2\n>>>>>>> other\n")
        snap = _commit(self.repo, "abandoned mid-merge")
        _write(self.repo, "a.py", "x = 2\nresolved = True\n")
        _commit(self.repo, "base resolved it")
        entry = ade.adjudicate_path(self.repo, snap, "HEAD", "a.py")
        self.assertTrue(entry["conflict_markers"])

    def test_rollup_flags_nothing_recoverable(self):
        _write(self.repo, "a.py", "x = 1\n")
        snap = _commit(self.repo, "snap")
        _write(self.repo, "a.py", "x = 1\ny = 2\n")
        _commit(self.repo, "base")
        report = ade.adjudicate(self.repo, snap, "HEAD", ["a.py"])
        self.assertTrue(report["nothing_recoverable"])
        self.assertEqual(report["needs_human_review"], [])

    def test_bad_rev_fails_soft(self):
        _write(self.repo, "a.py", "x = 1\n")
        _commit(self.repo, "snap")
        entry = ade.adjudicate_path(self.repo, "deadbeefdeadbeef", "HEAD", "a.py")
        self.assertEqual(entry["verdict"], ade.EVIDENCE_ABSENT)

    def test_changed_paths_lists_differing_files(self):
        _write(self.repo, "a.py", "x = 1\n")
        _write(self.repo, "b.py", "y = 1\n")
        snap = _commit(self.repo, "snap")
        _write(self.repo, "b.py", "y = 1\ny2 = 2\n")
        _commit(self.repo, "base")
        self.assertEqual(ade.changed_paths(self.repo, snap, "HEAD"), ["b.py"])

    def test_report_is_json_serialisable(self):
        _write(self.repo, "a.py", "x = 1\n")
        snap = _commit(self.repo, "snap")
        report = ade.adjudicate(self.repo, snap, "HEAD", ["a.py"])
        self.assertIn("counts", json.loads(json.dumps(report)))


if __name__ == "__main__":
    unittest.main()
