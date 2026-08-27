#!/usr/bin/env python3
"""Tests for tools/focused_conflict_triage.py.

The properties that matter here are the ones a recovery tool can get wrong in
the dangerous direction:

  * it must never mutate evidence (the git allowlist has to actually refuse)
  * an empty file in base must not read as a deleted file, or every hunk
    against it is misfiled as PATH_GONE and real work is discarded
  * a hunk whose content already landed must not be reported as missing, or
    the follow-up task overwrites current code with older content
  * a hunk that genuinely applies and is absent must be reported as missing,
    or the recovery silently loses work

The last two are the whole point of the module, so both directions are pinned.
"""

import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import focused_conflict_triage as fct  # noqa: E402


DIFF_TWO_FILES = """diff --git a/alpha.txt b/alpha.txt
index 1111111..2222222 100644
--- a/alpha.txt
+++ b/alpha.txt
@@ -1,3 +1,4 @@
 one
 two
+two-and-a-half
 three
@@ -10,2 +11,3 @@
 ten
+ten-and-a-half
 eleven
diff --git a/beta.txt b/beta.txt
new file mode 100644
index 0000000..3333333
--- /dev/null
+++ b/beta.txt
@@ -0,0 +1,2 @@
+brand
+new
"""


def _run(args, cwd):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True)


class TestDiffDecomposition(unittest.TestCase):
    def test_splits_into_one_block_per_file(self):
        blocks = fct.split_file_diffs(DIFF_TWO_FILES)
        self.assertEqual([p for p, _ in blocks], ["alpha.txt", "beta.txt"])

    def test_splits_a_block_into_preamble_and_hunks(self):
        blocks = dict(fct.split_file_diffs(DIFF_TWO_FILES))
        preamble, hunks = fct.split_hunks(blocks["alpha.txt"])
        self.assertEqual(len(hunks), 2)
        self.assertTrue(preamble[0].startswith("diff --git"))
        self.assertTrue(all(h[0].startswith("@@") for h in hunks))

    def test_single_hunk_diff_keeps_the_file_header(self):
        blocks = dict(fct.split_file_diffs(DIFF_TWO_FILES))
        preamble, hunks = fct.split_hunks(blocks["alpha.txt"])
        one = fct.single_hunk_diff(preamble, hunks[1])
        self.assertIn("--- a/alpha.txt", one)
        self.assertIn("+++ b/alpha.txt", one)
        self.assertEqual(one.count("@@ -"), 1)

    def test_added_and_removed_lines_ignore_the_file_headers(self):
        blocks = dict(fct.split_file_diffs(DIFF_TWO_FILES))
        _, hunks = fct.split_hunks(blocks["alpha.txt"])
        self.assertEqual(fct.added_lines(hunks[0]), ["two-and-a-half"])
        self.assertEqual(fct.removed_lines(hunks[0]), [])

    def test_new_file_mode_is_detected(self):
        blocks = dict(fct.split_file_diffs(DIFF_TWO_FILES))
        preamble, _ = fct.split_hunks(blocks["beta.txt"])
        self.assertTrue(fct.is_new_file(preamble))
        preamble_a, _ = fct.split_hunks(blocks["alpha.txt"])
        self.assertFalse(fct.is_new_file(preamble_a))


class TestReadOnlyEnforcement(unittest.TestCase):
    def test_mutating_subcommands_are_refused_by_name(self):
        for sub in ("checkout", "reset", "clean", "apply", "update-ref", "push",
                    "commit", "stash", "worktree", "fetch"):
            with self.assertRaises(fct.ReadOnlyViolation, msg=sub):
                fct._git(sub, "--help")

    def test_branch_listing_is_allowed_but_branch_delete_is_not(self):
        with self.assertRaises(fct.ReadOnlyViolation):
            fct._git("branch", "-D", "something")
        with self.assertRaises(fct.ReadOnlyViolation):
            fct._git("branch", "--delete", "something")
        # The listing form must survive, or callers lose ownership detection.
        self.assertNotIn("branch", [])  # allowlist membership, not execution
        self.assertIn("branch", fct.READ_ONLY_GIT)

    def test_empty_invocation_is_refused(self):
        with self.assertRaises(fct.ReadOnlyViolation):
            fct._git()


class TestBlockContainment(unittest.TestCase):
    def test_contiguous_block_is_found(self):
        self.assertTrue(fct._contains_block(["a", "b", "c", "d"], ["b", "c"]))

    def test_non_contiguous_block_is_not_found(self):
        self.assertFalse(fct._contains_block(["a", "b", "x", "c"], ["b", "c"]))

    def test_empty_needle_is_trivially_contained(self):
        self.assertTrue(fct._contains_block(["a"], []))


class TestAgainstARealRepo(unittest.TestCase):
    """Everything below runs against a throwaway git repo, never the caller's."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="fct-test-")
        _run(["git", "init", "-q", "-b", "main"], self.dir)
        _run(["git", "config", "user.email", "t@example.com"], self.dir)
        _run(["git", "config", "user.name", "t"], self.dir)

    def _write(self, name, text):
        with open(os.path.join(self.dir, name), "w") as fh:
            fh.write(text)

    def _commit(self, msg):
        _run(["git", "add", "-A"], self.dir)
        _run(["git", "commit", "-q", "--no-verify", "-m", msg], self.dir)

    def test_empty_file_in_base_is_not_reported_as_deleted(self):
        self._write("empty.txt", "")
        self._commit("add empty file")
        self.assertEqual(fct.base_file_lines("HEAD", "empty.txt", cwd=self.dir), [])
        self.assertIsNone(fct.base_file_lines("HEAD", "nope.txt", cwd=self.dir))

    def test_hunk_whose_content_already_landed_is_already_present(self):
        self._write("a.txt", "one\ntwo\ntwo-and-a-half\nthree\n")
        self._commit("content already landed")
        diff = (
            "diff --git a/a.txt b/a.txt\n"
            "--- a/a.txt\n"
            "+++ b/a.txt\n"
            "@@ -1,3 +1,4 @@\n"
            " one\n"
            " two\n"
            "+two-and-a-half\n"
            " three\n"
        )
        preamble, hunks = fct.split_hunks(dict(fct.split_file_diffs(diff))["a.txt"])
        verdict = fct.classify_hunk(
            hunks[0], preamble, "a.txt", "HEAD", 0, cwd=self.dir
        )
        self.assertEqual(verdict.verdict, fct.HUNK_ALREADY_PRESENT)

    def test_hunk_that_applies_and_is_absent_is_missing(self):
        self._write("a.txt", "one\ntwo\nthree\n")
        self._commit("content not landed")
        diff = (
            "diff --git a/a.txt b/a.txt\n"
            "--- a/a.txt\n"
            "+++ b/a.txt\n"
            "@@ -1,3 +1,4 @@\n"
            " one\n"
            " two\n"
            "+two-and-a-half\n"
            " three\n"
        )
        preamble, hunks = fct.split_hunks(dict(fct.split_file_diffs(diff))["a.txt"])
        verdict = fct.classify_hunk(
            hunks[0], preamble, "a.txt", "HEAD", 0, cwd=self.dir
        )
        self.assertEqual(verdict.verdict, fct.HUNK_MISSING)

    def test_hunk_against_a_vanished_path_is_path_gone(self):
        self._write("keep.txt", "x\n")
        self._commit("base without the target path")
        diff = (
            "diff --git a/gone.txt b/gone.txt\n"
            "--- a/gone.txt\n"
            "+++ b/gone.txt\n"
            "@@ -1,2 +1,2 @@\n"
            " head\n"
            "-old\n"
            "+new\n"
        )
        preamble, hunks = fct.split_hunks(dict(fct.split_file_diffs(diff))["gone.txt"])
        verdict = fct.classify_hunk(
            hunks[0], preamble, "gone.txt", "HEAD", 0, cwd=self.dir
        )
        self.assertEqual(verdict.verdict, fct.HUNK_PATH_GONE)

    def test_new_file_hunk_against_absent_path_is_missing_not_path_gone(self):
        self._write("keep.txt", "x\n")
        self._commit("base without the new file")
        preamble, hunks = fct.split_hunks(
            dict(fct.split_file_diffs(DIFF_TWO_FILES))["beta.txt"]
        )
        verdict = fct.classify_hunk(
            hunks[0], preamble, "beta.txt", "HEAD", 0, cwd=self.dir
        )
        self.assertEqual(verdict.verdict, fct.HUNK_MISSING)

    def test_a_pure_deletion_of_live_lines_is_never_missing(self):
        """The bug that made the first real run useless.

        13,992 of 14,300 hunks came back HUNK_MISSING, and every one was a
        deletion whose lines are still in base. Acting on that would have
        deleted most of the repository in the name of recovering it.
        """
        self._write("a.txt", "one\ntwo\nthree\n")
        self._commit("base still has the line")
        diff = (
            "diff --git a/a.txt b/a.txt\n"
            "--- a/a.txt\n"
            "+++ b/a.txt\n"
            "@@ -1,3 +1,2 @@\n"
            " one\n"
            "-two\n"
            " three\n"
        )
        preamble, hunks = fct.split_hunks(dict(fct.split_file_diffs(diff))["a.txt"])
        verdict = fct.classify_hunk(
            hunks[0], preamble, "a.txt", "HEAD", 0, cwd=self.dir
        )
        self.assertEqual(verdict.verdict, fct.HUNK_DELETION_ONLY)
        self.assertNotEqual(verdict.verdict, fct.HUNK_MISSING)

    def test_a_deletion_only_ref_is_fully_accounted_for_not_reimplement(self):
        self._write("a.txt", "one\ntwo\nthree\n")
        self._write("b.txt", "keep\n")
        self._commit("base")
        base = _run(["git", "rev-parse", "HEAD"], self.dir).stdout.strip()
        self._write("a.txt", "one\nthree\n")
        self._commit("sweep snapshot that only removes")
        sweep = _run(["git", "rev-parse", "HEAD"], self.dir).stdout.strip()

        result = fct.triage_ref("refs/orch-rescue/d", sweep, base, 0, cwd=self.dir)
        self.assertEqual(result.counts.get(fct.HUNK_MISSING, 0), 0)
        self.assertGreater(result.counts.get(fct.HUNK_DELETION_ONLY, 0), 0)
        self.assertEqual(result.outcome, "FULLY_ACCOUNTED_FOR")
        self.assertIn("does not remove live code", result.disposition)

    def test_deletion_already_carried_out_is_already_present(self):
        self._write("a.txt", "one\nthree\n")
        self._commit("line already removed")
        diff = (
            "diff --git a/a.txt b/a.txt\n"
            "--- a/a.txt\n"
            "+++ b/a.txt\n"
            "@@ -1,3 +1,2 @@\n"
            " one\n"
            "-two\n"
            " three\n"
        )
        preamble, hunks = fct.split_hunks(dict(fct.split_file_diffs(diff))["a.txt"])
        verdict = fct.classify_hunk(
            hunks[0], preamble, "a.txt", "HEAD", 0, cwd=self.dir
        )
        self.assertEqual(verdict.verdict, fct.HUNK_ALREADY_PRESENT)

    def test_triage_ref_reports_partial_reimplement_and_names_the_hunks(self):
        # Base: one file, missing the line the rescue ref adds.
        self._write("a.txt", "one\ntwo\nthree\n")
        self._commit("base")
        base = _run(["git", "rev-parse", "HEAD"], self.dir).stdout.strip()

        # A rescue-shaped commit: adds a line to a.txt and creates beta.txt.
        self._write("a.txt", "one\ntwo\ntwo-and-a-half\nthree\n")
        self._write("beta.txt", "brand\nnew\n")
        self._commit("rescue snapshot")
        rescue = _run(["git", "rev-parse", "HEAD"], self.dir).stdout.strip()

        result = fct.triage_ref("refs/orch-rescue/x", rescue, base, 0, cwd=self.dir)
        self.assertEqual(result.outcome, "PARTIAL_REIMPLEMENT")
        self.assertGreater(result.counts.get(fct.HUNK_MISSING, 0), 0)
        self.assertEqual(len(result.missing), result.counts[fct.HUNK_MISSING])
        self.assertIn("a.txt", [m["path"] for m in result.missing])

    def test_triage_ref_reports_fully_accounted_for_when_content_landed(self):
        self._write("a.txt", "one\ntwo\nthree\n")
        self._commit("base")
        self._write("a.txt", "one\ntwo\ntwo-and-a-half\nthree\n")
        self._commit("rescue snapshot")
        rescue = _run(["git", "rev-parse", "HEAD"], self.dir).stdout.strip()

        # Base is now the rescue commit itself: every hunk already landed.
        result = fct.triage_ref("refs/orch-rescue/y", rescue, rescue, 0, cwd=self.dir)
        self.assertEqual(result.outcome, "FULLY_ACCOUNTED_FOR")
        self.assertEqual(result.counts.get(fct.HUNK_MISSING, 0), 0)


class TestLedgerSelection(unittest.TestCase):
    def test_only_conflicted_rescue_refs_are_selected(self):
        ledger = {
            "kind": "orchestrator_rescue_refs",
            "items": [
                {"ref": "refs/orch-rescue/a", "classification": "RECOVERABLE_VALUE"},
                {"ref": "refs/orch-rescue/b", "classification": fct.CONFLICTED},
                {"ref": "refs/orch-rescue/c", "classification": "ALREADY_PRESENT"},
            ],
        }
        picked = fct.conflicted_items(ledger)
        self.assertEqual([i["ref"] for i in picked], ["refs/orch-rescue/b"])

    def test_a_conflicted_item_of_another_kind_is_excluded(self):
        ledger = {
            "kind": "orchestrator_rescue_refs",
            "items": [
                {
                    "ref": "/tmp/some.patch",
                    "classification": fct.CONFLICTED,
                    "kind": "chatgpt_bridge",
                },
                {"ref": "refs/orch-rescue/b", "classification": fct.CONFLICTED},
            ],
        }
        picked = fct.conflicted_items(ledger)
        self.assertEqual([i["ref"] for i in picked], ["refs/orch-rescue/b"])

    def test_legacy_class_key_is_accepted(self):
        ledger = {
            "kind": "orchestrator_rescue_refs",
            "items": [{"ref": "refs/orch-rescue/b", "class": fct.CONFLICTED}],
        }
        self.assertEqual(len(fct.conflicted_items(ledger)), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
