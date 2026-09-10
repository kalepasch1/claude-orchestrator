#!/usr/bin/env python3
"""Tests for merged_diff_memory._extract_patterns_from_commit.

Every git read and every collaborator (quality_gate, _changed_files,
_frameworks) is stubbed, so each case asserts unconditionally. The previous
version of this suite wrapped its assertions in `if result is not None:` —
which meant the whole file passed even when the function returned None for
everything, i.e. exactly the regression the suite exists to catch.
"""
import os
import subprocess
import sys
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# `db` opens a connection at import time; the function under test never uses it.
_DB_STUB = patch.dict("sys.modules", {"db": MagicMock()})
_DB_STUB.start()
import merged_diff_memory  # noqa: E402

EXTRACT = merged_diff_memory._extract_patterns_from_commit

MSG_WITH_RULES = (
    "feat: add caching\n\n"
    "- DO use TTL-based expiry\n"
    "- AVOID global mutable state\n"
)
STAT = " runner/cache.py | 50 ++++\n 1 file changed, 50 insertions(+)\n"


class _Base(unittest.TestCase):
    """Stubs the two git reads plus every collaborator the function imports."""

    files = ["runner/cache.py"]
    frameworks = ["pytest"]
    gate = (True, "ok")

    def setUp(self):
        self.git = patch("subprocess.check_output").start()
        self.git.side_effect = [MSG_WITH_RULES, STAT]
        self.changed_files = patch(
            "merged_diff_library._changed_files", return_value=list(self.files)
        ).start()
        self.frameworks_fn = patch(
            "merged_diff_library._frameworks", return_value=list(self.frameworks)
        ).start()
        self.quality_gate = patch.object(
            merged_diff_memory.learn_from_merges, "quality_gate", return_value=self.gate
        ).start()
        self.log_error = patch.object(merged_diff_memory, "_log_error").start()
        self.addCleanup(patch.stopall)


class TestSuccessfulExtraction(_Base):
    def test_returns_the_documented_record_shape(self):
        result = EXTRACT("/tmp/repo", "abc123")
        self.assertIsNotNone(result)
        self.assertEqual(
            set(result), {"commit", "rules", "frameworks", "files", "timestamp"}
        )

    def test_commit_hash_is_echoed_back(self):
        self.assertEqual(EXTRACT("/tmp/repo", "abc123")["commit"], "abc123")

    def test_rules_come_from_the_do_avoid_bullets(self):
        self.assertEqual(
            EXTRACT("/tmp/repo", "abc123")["rules"],
            ["DO use TTL-based expiry", "AVOID global mutable state"],
        )

    def test_frameworks_and_files_come_from_merged_diff_library(self):
        result = EXTRACT("/tmp/repo", "abc123")
        self.assertEqual(result["frameworks"], ["pytest"])
        self.assertEqual(result["files"], ["runner/cache.py"])
        self.changed_files.assert_called_once_with("/tmp/repo", "abc123^", "abc123")

    def test_timestamp_is_an_iso_8601_string(self):
        stamp = EXTRACT("/tmp/repo", "abc123")["timestamp"]
        self.assertIsInstance(stamp, str)
        datetime.fromisoformat(stamp)  # raises if not ISO-8601

    def test_reads_the_message_and_the_stat_from_the_given_repo(self):
        EXTRACT("/tmp/repo", "abc123")
        self.assertEqual(self.git.call_count, 2)
        msg_call, stat_call = self.git.call_args_list
        self.assertEqual(msg_call.args[0], ["git", "log", "-1", "--format=%B", "abc123"])
        self.assertEqual(stat_call.args[0], ["git", "show", "--stat", "abc123"])
        for call in (msg_call, stat_call):
            self.assertEqual(call.kwargs["cwd"], "/tmp/repo")

    def test_the_gate_grades_the_distilled_rules_not_the_raw_commit(self):
        """Regression: the gate used to be fed `message + git show --stat`,
        which it rejects by definition as a raw dump — 447/447 commits over a
        14-day window. It must see the bullet list built from the rules."""
        EXTRACT("/tmp/repo", "abc123")
        graded = self.quality_gate.call_args.args[0]
        self.assertEqual(
            graded, "- DO use TTL-based expiry\n- AVOID global mutable state"
        )
        self.assertNotIn("1 file changed", graded)


class TestNothingLearnable(_Base):
    files: list = []
    frameworks: list = []

    def test_returns_none_when_there_are_no_rules_frameworks_or_files(self):
        self.git.side_effect = ["chore: bump version\n", ""]
        self.assertIsNone(EXTRACT("/tmp/repo", "abc123"))

    def test_returns_a_record_when_only_rules_were_found(self):
        result = EXTRACT("/tmp/repo", "abc123")
        self.assertIsNotNone(result)
        self.assertEqual(result["files"], [])
        self.assertEqual(result["frameworks"], [])
        self.assertTrue(result["rules"])


class TestQualityGate(_Base):
    def test_rejected_rules_are_dropped_but_the_record_survives(self):
        self.quality_gate.return_value = (False, "fewer than 2 bullet lines")
        result = EXTRACT("/tmp/repo", "abc123")
        self.assertIsNotNone(result)
        self.assertEqual(result["rules"], [])
        self.assertEqual(result["files"], ["runner/cache.py"])
        self.assertEqual(result["frameworks"], ["pytest"])
        self.log_error.assert_called_once()

    def test_gate_is_not_consulted_when_the_commit_has_no_rules(self):
        self.git.side_effect = ["chore: retitle a heading\n", STAT]
        result = EXTRACT("/tmp/repo", "abc123")
        self.assertIsNotNone(result)
        self.assertEqual(result["rules"], [])
        self.quality_gate.assert_not_called()


class TestFailSoft(_Base):
    def _assert_none_and_logged(self, repo="/tmp/repo", commit="abc123"):
        self.assertIsNone(EXTRACT(repo, commit))
        self.log_error.assert_called_once()

    def test_git_returning_non_zero_yields_none(self):
        self.git.side_effect = subprocess.CalledProcessError(1, "git")
        self._assert_none_and_logged(commit="bad_hash")

    def test_git_timeout_yields_none(self):
        self.git.side_effect = subprocess.TimeoutExpired("git", 10)
        self._assert_none_and_logged(commit="slow_hash")

    def test_a_none_repo_path_yields_none_instead_of_raising(self):
        self.git.side_effect = TypeError("cwd must be a path")
        self._assert_none_and_logged(repo=None)

    def test_a_none_commit_hash_yields_none_instead_of_raising(self):
        self.git.side_effect = TypeError("bad ref")
        self._assert_none_and_logged(commit=None)

    def test_an_empty_commit_hash_yields_none_instead_of_raising(self):
        self.git.side_effect = subprocess.CalledProcessError(128, "git")
        self._assert_none_and_logged(commit="")

    def test_a_collaborator_blowing_up_yields_none_instead_of_raising(self):
        self.changed_files.side_effect = OSError("git not on PATH")
        self._assert_none_and_logged()

    def test_the_gate_blowing_up_yields_none_instead_of_raising(self):
        self.quality_gate.side_effect = RuntimeError("grader unavailable")
        self._assert_none_and_logged()


if __name__ == "__main__":
    unittest.main()
