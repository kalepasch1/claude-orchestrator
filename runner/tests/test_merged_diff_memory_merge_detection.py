#!/usr/bin/env python3
"""End-to-end merge detection in the merged-diff memory analysis system.

Built on a REAL temporary git repository with a REAL merge commit rather than on
hand-written record dicts: the whole point of preferring parent count over message text
is that it agrees with git, and only git can prove that.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import merged_diff_memory as mdm


def git(repo, *args):
    return subprocess.run(("git",) + args, cwd=repo, capture_output=True, text=True,
                          check=True)


def sha(repo, ref="HEAD"):
    return git(repo, "rev-parse", ref).stdout.strip()


class MergeDetectionIntegrationTest(unittest.TestCase):
    """One real repo: a direct commit, a true merge, and a decoy."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        repo = cls.repo = cls._tmp.name
        git(repo, "init", "-q", "-b", "master")
        git(repo, "config", "user.email", "test@example.com")
        git(repo, "config", "user.name", "Test")

        Path(repo, "a.txt").write_text("a\n")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "feat: add a")
        cls.direct_sha = sha(repo)

        # A decoy: an ordinary single-parent commit whose subject contains the phrase.
        # Message text alone would call this a merge; parent count will not.
        Path(repo, "parser.txt").write_text("parses\n")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "fix: handle Merge branch messages in the parser")
        cls.decoy_sha = sha(repo)

        # A genuine two-parent merge.
        git(repo, "checkout", "-q", "-b", "feature")
        Path(repo, "b.txt").write_text("b\n")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "feat: add b")
        git(repo, "checkout", "-q", "master")
        git(repo, "merge", "-q", "--no-ff", "feature", "-m", "Merge branch 'feature'")
        cls.merge_sha = sha(repo)

        # A real merge whose subject matches NEITHER phrase — the case that proves
        # parent count is doing the work, not the regex.
        git(repo, "checkout", "-q", "-b", "second")
        Path(repo, "c.txt").write_text("c\n")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "feat: add c")
        git(repo, "checkout", "-q", "master")
        git(repo, "merge", "-q", "--no-ff", "second", "-m", "integrate the second lane")
        cls.silent_merge_sha = sha(repo)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def setUp(self):
        # Redirect the module's memory file into a temp dir; never touch real memory.
        self._store = tempfile.TemporaryDirectory()
        self._orig_dir, self._orig_file = mdm.MEMORY_DIR, mdm.MERGED_DIFF_FILE
        mdm.MEMORY_DIR = Path(self._store.name)
        mdm.MERGED_DIFF_FILE = Path(self._store.name) / "merged_diff_memory.json"

    def tearDown(self):
        mdm.MEMORY_DIR, mdm.MERGED_DIFF_FILE = self._orig_dir, self._orig_file
        self._store.cleanup()

    def _record(self, commit_sha):
        return next(m for m in mdm.get_recent_merges(50) if m["commit"] == commit_sha)

    # --- capture tags every record -------------------------------------------------
    def test_real_merge_is_tagged_by_parent_count(self):
        mdm.capture_merge(self.merge_sha, "feature", self.repo)
        rec = self._record(self.merge_sha)
        self.assertTrue(rec["is_merge"])
        self.assertEqual(rec["merge_detection"], "parents")

    def test_direct_commit_is_not_tagged_as_a_merge(self):
        mdm.capture_merge(self.direct_sha, "master", self.repo)
        rec = self._record(self.direct_sha)
        self.assertFalse(rec["is_merge"])
        self.assertEqual(rec["merge_detection"], "parents")

    def test_parent_count_beats_a_misleading_message(self):
        # The decoy's subject contains "Merge branch"; it has one parent.
        mdm.capture_merge(self.decoy_sha, "master", self.repo)
        rec = self._record(self.decoy_sha)
        self.assertIn("Merge branch", rec["message"])
        self.assertFalse(rec["is_merge"], "message text must not override parent count")

    def test_parent_count_catches_a_merge_the_message_would_miss(self):
        mdm.capture_merge(self.silent_merge_sha, "second", self.repo)
        rec = self._record(self.silent_merge_sha)
        self.assertNotIn("Merge branch", rec["message"])
        self.assertTrue(rec["is_merge"])
        self.assertEqual(rec["merge_detection"], "parents")

    # --- message fallback when the repo is gone ------------------------------------
    def test_falls_back_to_the_message_when_the_repo_is_unreachable(self):
        missing = os.path.join(self._store.name, "no-such-repo")
        # No repo, so git yields nothing; only the caller-supplied message is available.
        # capture_merge reads the message from git too, so drive _classify_merge directly.
        is_merge, source = mdm._classify_merge("deadbeef", "Merge branch 'agent/x'", missing)
        self.assertTrue(is_merge)
        self.assertEqual(source, "message")

        is_merge, source = mdm._classify_merge("deadbeef", "feat: something", missing)
        self.assertFalse(is_merge)
        self.assertEqual(source, "message")

    def test_unknown_when_neither_repo_nor_message_is_available(self):
        missing = os.path.join(self._store.name, "no-such-repo")
        is_merge, source = mdm._classify_merge("deadbeef", "", missing)
        self.assertFalse(is_merge)
        self.assertEqual(source, "unknown")

    # --- the tag is actually consumed ----------------------------------------------
    def test_get_recent_merges_can_filter_to_merges_only(self):
        for s, b in ((self.direct_sha, "master"), (self.decoy_sha, "master"),
                     (self.merge_sha, "feature"), (self.silent_merge_sha, "second")):
            mdm.capture_merge(s, b, self.repo)

        only_merges = mdm.get_recent_merges(50, merges_only=True)
        self.assertEqual({m["commit"] for m in only_merges},
                         {self.merge_sha, self.silent_merge_sha})

        only_direct = mdm.get_recent_merges(50, merges_only=False)
        self.assertEqual({m["commit"] for m in only_direct},
                         {self.direct_sha, self.decoy_sha})

    def test_default_call_is_unchanged_for_existing_callers(self):
        for s, b in ((self.direct_sha, "master"), (self.merge_sha, "feature")):
            mdm.capture_merge(s, b, self.repo)
        self.assertEqual(len(mdm.get_recent_merges(50)), 2)

    def test_filter_applies_before_the_limit(self):
        # Two direct commits then one merge: limit=1 on merges_only must return the
        # merge, not "nothing, because the last row happened to be direct".
        for s, b in ((self.direct_sha, "master"), (self.decoy_sha, "master"),
                     (self.merge_sha, "feature")):
            mdm.capture_merge(s, b, self.repo)
        got = mdm.get_recent_merges(1, merges_only=True)
        self.assertEqual([m["commit"] for m in got], [self.merge_sha])

    def test_stats_reports_the_split_and_how_it_was_decided(self):
        for s, b in ((self.direct_sha, "master"), (self.decoy_sha, "master"),
                     (self.merge_sha, "feature"), (self.silent_merge_sha, "second")):
            mdm.capture_merge(s, b, self.repo)

        st = mdm.stats()
        self.assertEqual(st["total_tracked"], 4)
        self.assertEqual(st["merge_commits"], 2)
        self.assertEqual(st["direct_commits"], 2)
        self.assertEqual(st["detected_by"]["parents"], 4)
        self.assertEqual(st["detected_by"]["message"], 0)

    def test_stats_keeps_its_existing_keys(self):
        st = mdm.stats()
        for key in ("total_tracked", "max_capacity", "memory_file", "file_exists"):
            self.assertIn(key, st)


class ClassifyBackCompatTest(unittest.TestCase):
    """Records written before tagging existed must still classify."""

    def test_untagged_record_falls_back_to_the_message(self):
        self.assertTrue(mdm.classify({"message": "Merge branch 'agent/x'"}))
        self.assertFalse(mdm.classify({"message": "feat: add a thing"}))

    def test_tag_wins_over_the_message_when_present(self):
        # A record tagged by parent count must not be re-litigated by its text.
        self.assertFalse(mdm.classify(
            {"is_merge": False, "message": "fix: handle Merge branch messages"}))
        self.assertTrue(mdm.classify(
            {"is_merge": True, "message": "integrate the second lane"}))

    def test_malformed_records_do_not_raise(self):
        for bad in (None, "not-a-dict", 42, [], {}, {"message": None}):
            with self.subTest(bad=bad):
                self.assertFalse(mdm.classify(bad))


if __name__ == "__main__":
    unittest.main()
