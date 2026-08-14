#!/usr/bin/env python3
"""Pattern extraction must actually extract, and the bool must mean what it says.

Contract under test: `capture_to_memory()` returns True **only** when a memory
file was written, False on any error — bad git refs, no diffs, write failure.

Three stacked defects made that contract vacuous; each is pinned below.

  1. `_extract_patterns_from_commit` fed a raw commit message + `git show --stat`
     to `learn_from_merges.quality_gate`, which grades *distilled* convention
     lists and rejects raw dumps. Measured before the fix: 447/447 commits
     rejected with "fewer than 2 bullet lines", so patterns_count was
     permanently 0 and the bool was permanently False.
  2. The same function called `learn_from_merges._extract_rules` and
     `._changed_files` — neither exists on that module. Those calls would raise
     AttributeError; defect 1 meant they were never reached.
  3. `capture_to_memory(dry_run=True)` returned True, because run() fills
     `memory_file` with the truthy string "[dry-run] would save N patterns".
     The docstring has always promised False. Also masked by defect 1.
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import learn_from_merges
import merged_diff_memory as mdm

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestHelpersExistWhereTheyAreCalled(unittest.TestCase):
    """Defect 2: the callee must live on the module it is called from."""

    def test_extract_rules_is_a_local_helper(self):
        self.assertTrue(callable(getattr(mdm, "_extract_rules", None)))

    def test_it_is_not_on_learn_from_merges(self):
        self.assertFalse(hasattr(learn_from_merges, "_extract_rules"))
        self.assertFalse(hasattr(learn_from_merges, "_changed_files"))

    def test_changed_files_is_taken_from_merged_diff_library(self):
        from merged_diff_library import _changed_files
        self.assertTrue(callable(_changed_files))


class TestExtractRules(unittest.TestCase):
    def test_picks_up_do_avoid_bullets(self):
        text = "- DO wire the caller\n* AVOID silent excepts\n1. NEVER push to master\n- unrelated line"
        rules = mdm._extract_rules(text)
        self.assertEqual(len(rules), 3)
        self.assertTrue(any(r.startswith("DO wire") for r in rules))

    def test_ignores_prose(self):
        self.assertEqual(mdm._extract_rules("just a normal commit message"), [])

    def test_fail_soft(self):
        self.assertEqual(mdm._extract_rules(None), [])
        self.assertEqual(mdm._extract_rules(""), [])


class TestExtractPatternsFromRealHistory(unittest.TestCase):
    """Defect 1: a real commit must yield a pattern, not be gated away."""

    @classmethod
    def setUpClass(cls):
        cls.commits = mdm._get_merged_commits(REPO, 14)
        if not cls.commits:
            raise unittest.SkipTest("no merge commits in the last 14 days")

    def test_real_commits_yield_patterns(self):
        sample = [c for c, _msg in self.commits[:30]]
        extracted = [p for p in (mdm._extract_patterns_from_commit(REPO, c) for c in sample) if p]
        self.assertGreater(len(extracted), 0,
                           "every commit was rejected — the raw-text quality gate is back")

    def test_a_pattern_carries_the_documented_keys(self):
        for commit, _msg in self.commits[:30]:
            p = mdm._extract_pattern_keys_probe(commit) if hasattr(mdm, "_extract_pattern_keys_probe") \
                else mdm._extract_patterns_from_commit(REPO, commit)
            if p:
                self.assertEqual(set(p), {"commit", "rules", "frameworks", "files", "timestamp"})
                self.assertIsInstance(p["rules"], list)
                self.assertIsInstance(p["frameworks"], list)
                self.assertIsInstance(p["files"], list)
                return
        self.fail("no commit produced a pattern")

    # `_log_error` appends to a machine-global JSONL that other suites read by
    # first line; a deliberately-bad ref here would pollute it. Silence it.
    def test_a_bad_git_ref_yields_none_not_an_exception(self):
        with patch.object(mdm, "_log_error", return_value=None):
            self.assertIsNone(mdm._extract_patterns_from_commit(REPO, "deadbeefdeadbeef"))

    def test_a_missing_repo_yields_none(self):
        with patch.object(mdm, "_log_error", return_value=None):
            self.assertIsNone(mdm._extract_patterns_from_commit("/no/such/repo", "HEAD"))


class TestCaptureBoolContract(unittest.TestCase):
    def test_dry_run_is_false_because_it_writes_nothing(self):
        """Defect 3."""
        self.assertIs(mdm.capture_to_memory(repo=REPO, dry_run=True), False)

    def test_true_only_when_a_file_was_written(self):
        with patch.object(mdm, "run", return_value={
                "success": True, "memory_file": "/tmp/merged_learning_x.md",
                "merged_count": 3, "patterns_count": 2, "error": None}):
            self.assertIs(mdm.capture_to_memory(repo=REPO), True)

    def test_false_when_nothing_was_written(self):
        with patch.object(mdm, "run", return_value={
                "success": True, "memory_file": None,
                "merged_count": 0, "patterns_count": 0, "error": None}):
            self.assertIs(mdm.capture_to_memory(repo=REPO), False)

    def test_false_on_a_reported_error(self):
        with patch.object(mdm, "run", return_value={
                "success": False, "memory_file": None, "error": "bad git ref"}):
            self.assertIs(mdm.capture_to_memory(repo=REPO), False)

    def test_false_when_run_raises(self):
        with patch.object(mdm, "run", side_effect=RuntimeError("boom")):
            self.assertIs(mdm.capture_to_memory(repo=REPO), False)

    def test_false_when_run_returns_a_non_dict(self):
        with patch.object(mdm, "run", return_value="oops"):
            self.assertIs(mdm.capture_to_memory(repo=REPO), False)

    def test_false_on_write_failure(self):
        with patch.object(mdm, "_write_memory", return_value=False), \
             patch.object(mdm, "_save_to_memory", return_value=(False, None)):
            self.assertIs(mdm.capture_to_memory(repo=REPO), False)


class TestRunCounts(unittest.TestCase):
    def test_dry_run_reports_a_nonzero_pattern_count_on_real_history(self):
        result = mdm.run(repo=REPO, dry_run=True)
        self.assertIsInstance(result, dict)
        if result.get("merged_count", 0) == 0:
            self.skipTest("no merge commits in the lookback window")
        self.assertGreater(result["patterns_count"], 0,
                           "patterns_count is 0 again — extraction is gated away")


if __name__ == "__main__":
    unittest.main()
