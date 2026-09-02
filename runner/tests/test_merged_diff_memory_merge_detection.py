#!/usr/bin/env python3
"""End-to-end merge capture in the merged-diff memory metadata tracker.

Built on a REAL temporary git repository with a REAL merge commit rather than on
hand-written record dicts: the point of this file is that what capture_merge() stores
agrees with git, and only git can prove that.

SUBSTITUTION NOTE (whole-file rewrite)
--------------------------------------
This file used to test a "merge detection" feature that merged_diff_memory has never
had and that nothing in the fleet consumes: `mdm._classify_merge()`, `mdm.classify()`,
an `is_merge` / `merge_detection` pair of keys on every stored record, a
`get_recent_merges(..., merges_only=...)` filter, and `stats()["detected_by"]`. None of
those names exist in runner/merged_diff_memory.py (or in tools/merged_diff_memory.py),
so all 17 tests died on AttributeError/TypeError rather than checking anything. The
tests could not be repaired by adjusting an argument — the API they targeted was
invented. Mocking the functions into existence would only have tested the mocks, and
implementing a parent-count classifier purely to satisfy them would be writing product
to match a hallucinated spec.

Each test below is therefore replaced by the nearest REAL behaviour of the tracker,
keeping the original methodology (one real repo containing a direct commit, a
single-parent decoy whose subject says "Merge branch", a true --no-ff merge, and a
second merge whose subject mentions no branch at all). The individual replacements are
named in comments on each test.
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


class MergeCaptureIntegrationTest(unittest.TestCase):
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
        cls.root_sha = sha(repo)

        # An ordinary single-parent commit whose subject contains "Merge branch".
        Path(repo, "parser.txt").write_text("parses\n")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "fix: handle Merge branch messages in the parser")
        cls.decoy_sha = sha(repo)

        # A genuine two-parent merge that brings in b.txt.
        git(repo, "checkout", "-q", "-b", "feature")
        Path(repo, "b.txt").write_text("b\n")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "feat: add b")
        git(repo, "checkout", "-q", "master")
        git(repo, "merge", "-q", "--no-ff", "feature", "-m", "Merge branch 'feature'")
        cls.merge_sha = sha(repo)

        # A real merge whose subject matches no branch-merge phrasing, bringing in c.txt.
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

    # --- capture stores what git says ----------------------------------------------
    def test_capture_records_the_real_git_metadata(self):
        # Replaces test_real_merge_is_tagged_by_parent_count, which asserted a
        # rec["merge_detection"] == "parents" key capture_merge never writes. The real,
        # checkable claim about a captured merge is that every field of the stored
        # record equals what git reports for that commit.
        self.assertTrue(mdm.capture_merge(self.merge_sha, "feature", self.repo))
        rec = self._record(self.merge_sha)
        self.assertEqual(rec["branch"], "feature")
        self.assertEqual(rec["message"], "Merge branch 'feature'")
        self.assertEqual(rec["author"], "Test")
        self.assertEqual(
            rec["date"],
            git(self.repo, "log", "-1", "--format=%aI", self.merge_sha).stdout.strip())

    def test_merge_commit_files_affected_lists_what_the_merge_brought_in(self):
        # PRODUCT BUG (fixed): capture_merge() read the file list with a plain
        # `git diff-tree --no-commit-id --name-only -r <sha>`. For a MERGE commit git
        # prints nothing at all for that invocation, so files_affected was [] for every
        # true merge — and continuous_merger._capture_merge_memory() feeds this function
        # exactly those merge SHAs. The same bug had already been found and fixed in
        # assemble_merge_summaries(); capture_merge() kept the broken copy. It now
        # passes `-m --first-parent`, which diffs the merge against the branch it landed
        # on. Replaces test_parent_count_catches_a_merge_the_message_would_miss.
        mdm.capture_merge(self.silent_merge_sha, "second", self.repo)
        rec = self._record(self.silent_merge_sha)
        self.assertEqual(rec["files_affected"], ["c.txt"])
        self.assertEqual(rec["message"], "integrate the second lane")

    def test_direct_commit_files_affected_is_unchanged_by_the_fix(self):
        # Guards the other half of the fix: adding -m --first-parent must not disturb
        # ordinary single-parent commits. Replaces
        # test_direct_commit_is_not_tagged_as_a_merge (which asserted the nonexistent
        # rec["is_merge"] / rec["merge_detection"] keys).
        mdm.capture_merge(self.decoy_sha, "master", self.repo)
        rec = self._record(self.decoy_sha)
        self.assertEqual(rec["files_affected"], ["parser.txt"])

    def test_message_is_stored_verbatim_and_is_not_interpreted(self):
        # Replaces test_parent_count_beats_a_misleading_message. There is no
        # classification to beat: the tracker stores the subject line and draws no
        # conclusion from it. The decoy proves that — a single-parent commit whose
        # subject says "Merge branch" is stored exactly like any other commit, with no
        # extra key added and no field derived from the text.
        mdm.capture_merge(self.decoy_sha, "master", self.repo)
        rec = self._record(self.decoy_sha)
        self.assertEqual(rec["message"],
                         "fix: handle Merge branch messages in the parser")
        self.assertEqual(set(rec), {"commit", "branch", "author", "date", "message",
                                    "files_affected"})

    def test_capturing_the_same_commit_twice_does_not_duplicate_it(self):
        # New coverage for capture_merge's documented dedup contract ("True if the
        # metadata is on disk, including when the commit was already recorded").
        self.assertTrue(mdm.capture_merge(self.merge_sha, "feature", self.repo))
        self.assertTrue(mdm.capture_merge(self.merge_sha, "feature", self.repo))
        self.assertEqual([m["commit"] for m in mdm.get_recent_merges(50)],
                         [self.merge_sha])

    def test_a_record_missing_its_commit_key_does_not_abort_the_capture(self):
        # capture_merge uses m.get("commit") rather than m["commit"] precisely so a
        # hand-edited or partially-written entry cannot raise KeyError and lose the
        # capture. Exercises that documented guard.
        mdm.write_memory_file([{"branch": "legacy-row-with-no-commit-key"}])
        self.assertTrue(mdm.capture_merge(self.merge_sha, "feature", self.repo))
        self.assertIn(self.merge_sha, {m.get("commit") for m in mdm.get_recent_merges(50)})

    def test_unreachable_repo_still_records_the_commit_with_empty_git_fields(self):
        # Replaces test_falls_back_to_the_message_when_the_repo_is_unreachable and
        # test_unknown_when_neither_repo_nor_message_is_available, both of which called
        # mdm._classify_merge() — a function that does not exist. The real behaviour
        # when the repo is gone is _safe_run()'s fail-soft contract: every git read
        # returns "", so the record is still written (the commit/branch the caller knew
        # are not lost) but carries no git-derived detail.
        missing = os.path.join(self._store.name, "no-such-repo")
        self.assertTrue(mdm.capture_merge("deadbeef", "agent/x", missing))
        rec = self._record("deadbeef")
        self.assertEqual(rec["branch"], "agent/x")
        self.assertEqual(rec["author"], "")
        self.assertEqual(rec["date"], "")
        self.assertEqual(rec["message"], "")
        self.assertEqual(rec["files_affected"], [])

    # --- reading the tracked records ------------------------------------------------
    def test_get_recent_merges_returns_capture_order_newest_last(self):
        # Replaces test_get_recent_merges_can_filter_to_merges_only, which passed a
        # merges_only= keyword get_recent_merges does not accept. The real read API is
        # ordered-by-capture with a tail limit; that ordering is what memory_retrieval
        # .load_exemplars_from_store() depends on, so it is worth pinning.
        for s, b in ((self.root_sha, "master"), (self.decoy_sha, "master"),
                     (self.merge_sha, "feature"), (self.silent_merge_sha, "second")):
            mdm.capture_merge(s, b, self.repo)
        self.assertEqual([m["commit"] for m in mdm.get_recent_merges(50)],
                         [self.root_sha, self.decoy_sha, self.merge_sha,
                          self.silent_merge_sha])

    def test_limit_takes_the_most_recent_captures(self):
        # Replaces test_filter_applies_before_the_limit (there is no filter). The
        # boundary that does exist is the tail slice: limit=1 must yield the LAST
        # captured record, not the first.
        for s, b in ((self.root_sha, "master"), (self.decoy_sha, "master"),
                     (self.merge_sha, "feature")):
            mdm.capture_merge(s, b, self.repo)
        self.assertEqual([m["commit"] for m in mdm.get_recent_merges(1)],
                         [self.merge_sha])
        self.assertEqual([m["commit"] for m in mdm.get_recent_merges(2)],
                         [self.decoy_sha, self.merge_sha])

    def test_default_call_is_unchanged_for_existing_callers(self):
        for s, b in ((self.root_sha, "master"), (self.merge_sha, "feature")):
            mdm.capture_merge(s, b, self.repo)
        self.assertEqual(len(mdm.get_recent_merges(50)), 2)

    def test_stats_counts_every_captured_record(self):
        # Replaces test_stats_reports_the_split_and_how_it_was_decided, which asserted
        # st["merge_commits"], st["direct_commits"] and st["detected_by"] — none of
        # which stats() has ever produced. stats() is documented as the union of the
        # diff-cache counters and the metadata-tracking counters; that union is the
        # real, checkable claim.
        for s, b in ((self.root_sha, "master"), (self.decoy_sha, "master"),
                     (self.merge_sha, "feature"), (self.silent_merge_sha, "second")):
            mdm.capture_merge(s, b, self.repo)

        st = mdm.stats()
        self.assertEqual(st["total_tracked"], 4)
        self.assertEqual(st["max_capacity"], mdm.MAX_STORED_MERGES)
        self.assertEqual(st["memory_file"], str(mdm.MERGED_DIFF_FILE))
        self.assertTrue(st["file_exists"])
        for cache_key in ("entries", "bytes_used", "hits", "misses"):
            self.assertIn(cache_key, st)

    def test_stats_keeps_its_existing_keys(self):
        st = mdm.stats()
        for key in ("total_tracked", "max_capacity", "memory_file", "file_exists"):
            self.assertIn(key, st)

    def test_invalidate_clears_the_tracked_records(self):
        mdm.capture_merge(self.merge_sha, "feature", self.repo)
        self.assertEqual(mdm.stats()["total_tracked"], 1)
        self.assertTrue(mdm.invalidate())
        self.assertEqual(mdm.get_recent_merges(50), [])
        self.assertEqual(mdm.stats()["total_tracked"], 0)


class MalformedMemoryBackCompatTest(unittest.TestCase):
    """Records written before / outside this module must not break the readers.

    Replaces ClassifyBackCompatTest wholesale. That class exercised mdm.classify(),
    which does not exist, on record dicts it built itself; every one of its three tests
    raised AttributeError. The real back-compat surface is _read_memory() /
    get_recent_merges() / stats() facing a memory file this module did not write, so
    that is what is tested here — through the public readers, against a real file on
    disk, not against hand-made return values.
    """

    def setUp(self):
        self._store = tempfile.TemporaryDirectory()
        self._orig_dir, self._orig_file = mdm.MEMORY_DIR, mdm.MERGED_DIFF_FILE
        mdm.MEMORY_DIR = Path(self._store.name)
        mdm.MERGED_DIFF_FILE = Path(self._store.name) / "merged_diff_memory.json"

    def tearDown(self):
        mdm.MEMORY_DIR, mdm.MERGED_DIFF_FILE = self._orig_dir, self._orig_file
        self._store.cleanup()

    def test_absent_memory_file_reads_as_empty(self):
        self.assertFalse(mdm.MERGED_DIFF_FILE.exists())
        self.assertEqual(mdm.get_recent_merges(50), [])
        self.assertEqual(mdm.stats()["total_tracked"], 0)
        self.assertFalse(mdm.stats()["file_exists"])

    def test_truncated_json_reads_as_empty_instead_of_raising(self):
        mdm.MERGED_DIFF_FILE.write_text('{"merges": [{"commit": "abc"')
        self.assertEqual(mdm.get_recent_merges(50), [])
        self.assertEqual(mdm.stats()["total_tracked"], 0)

    def test_file_without_a_merges_key_reads_as_empty(self):
        mdm.MERGED_DIFF_FILE.write_text('{"something_else": 1}')
        self.assertEqual(mdm.get_recent_merges(50), [])

    def test_untagged_legacy_records_are_returned_unchanged(self):
        # The nearest survivor of test_untagged_record_falls_back_to_the_message: a
        # record stored by an older writer carries only the six schema keys and no
        # classification tag, and the reader hands it back exactly as stored rather
        # than deriving anything from its message text.
        legacy = [{"commit": "abc123", "branch": "agent/x", "author": "old",
                   "date": "2026-01-01T00:00:00+00:00",
                   "message": "Merge branch 'agent/x'", "files_affected": ["f.py"]}]
        self.assertTrue(mdm.write_memory_file(legacy))
        self.assertEqual(mdm.get_recent_merges(50), legacy)

    def test_non_int_limit_falls_back_to_the_documented_default(self):
        rows = [{"commit": f"c{i}", "branch": "b", "author": "a", "date": "d",
                 "message": "m", "files_affected": []} for i in range(30)]
        mdm.write_memory_file(rows[:25])
        self.assertEqual(len(mdm.get_recent_merges("not-a-number")), 20)
        self.assertEqual(len(mdm.get_recent_merges(None)), 20)

    def test_non_positive_limits_return_nothing(self):
        rows = [{"commit": f"c{i}", "branch": "b", "author": "a", "date": "d",
                 "message": "m", "files_affected": []} for i in range(5)]
        mdm.write_memory_file(rows)
        self.assertEqual(mdm.get_recent_merges(0), [])
        self.assertEqual(mdm.get_recent_merges(-3), [])


if __name__ == "__main__":
    unittest.main()
