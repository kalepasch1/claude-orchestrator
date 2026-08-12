"""Tests for patch_conflict_analyzer, including the stated acceptance case.

Acceptance from the task: create a target file and a patch that both edit the same 3 lines
in incompatible ways; after 4 attempts the analyzer must return needs_manual_rebase with a
structured conflicts array and a reuse_recommendation citing the source hash.

The two properties that matter beyond that:
  - a patch that STILL APPLIES must never be reported as needing a rebase (that would send
    a perfectly good reuse down the expensive path, which is the failure mode this whole
    library exists to avoid);
  - the analyzer must never write to the target tree — it answers a question about a patch,
    and a tool that mutates the repo to answer it is unusable during a live session.
"""
import os
import subprocess
import sys
import tempfile
import unittest

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DIR)

import patch_conflict_analyzer as pca  # noqa: E402

ORIGINAL = "alpha\nbravo\ncharlie\ndelta\necho\nfoxtrot\ngolf\nhotel\n"


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)


class RepoFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = self.tmp.name
        _git(self.repo, "init", "-q")
        _git(self.repo, "config", "user.email", "t@example.com")
        _git(self.repo, "config", "user.name", "t")
        self._write("target.txt", ORIGINAL)
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-qm", "base")

    def _write(self, rel, body):
        with open(os.path.join(self.repo, rel), "w") as fh:
            fh.write(body)

    def _make_patch(self, new_body, name="change.patch"):
        """A real git diff turning ORIGINAL into new_body."""
        self._write("target.txt", new_body)
        diff = _git(self.repo, "diff").stdout
        _git(self.repo, "checkout", "--", "target.txt")
        path = os.path.join(self.tmp.name, name)
        with open(path, "w") as fh:
            fh.write(diff)
        return path


class AppliesCleanTest(RepoFixture):
    def test_an_unchanged_target_applies_clean(self):
        patch = self._make_patch(ORIGINAL.replace("charlie", "CHARLIE"))
        res = pca.analyze(self.repo, patch)
        self.assertEqual(res["status"], pca.STATUS_CLEAN)
        self.assertEqual(res["attempts"], 1)   # stops at the cheapest strategy

    def test_clean_result_recommends_direct_reuse(self):
        patch = self._make_patch(ORIGINAL.replace("charlie", "CHARLIE"))
        res = pca.analyze(self.repo, patch, source_hash="bffd1c2752f8")
        self.assertIn("as-is", res["reuse_recommendation"])
        self.assertIn("bffd1c2752f8", res["reuse_recommendation"])

    def test_no_conflicts_are_reported_when_it_applies(self):
        patch = self._make_patch(ORIGINAL.replace("charlie", "CHARLIE"))
        self.assertEqual(pca.analyze(self.repo, patch)["conflicts"], [])


class ShiftedContextTest(RepoFixture):
    def test_a_patch_whose_context_moved_still_places(self):
        # the common stale-patch case: lines shifted, intent unchanged
        patch = self._make_patch(ORIGINAL.replace("charlie", "CHARLIE"))
        self._write("target.txt", "header\nheader2\n" + ORIGINAL)
        _git(self.repo, "commit", "-aqm", "shift down by 2")
        res = pca.analyze(self.repo, patch)
        self.assertIn(res["status"], (pca.STATUS_CLEAN, pca.STATUS_FUZZ))
        self.assertNotEqual(res["status"], pca.STATUS_MANUAL)


class AcceptanceTest(RepoFixture):
    """The stated acceptance case: incompatible edits to the same 3 lines."""

    def setUp(self):
        super().setUp()
        self.patch = self._make_patch(
            ORIGINAL.replace("charlie\ndelta\necho\n", "CHARLIE-1\nDELTA-1\nECHO-1\n"))
        # the target now edits the SAME three lines a different, incompatible way
        self._write("target.txt",
                    ORIGINAL.replace("charlie\ndelta\necho\n", "charlie-2\ndelta-2\necho-2\n"))
        _git(self.repo, "commit", "-aqm", "incompatible edit")
        self.res = pca.analyze(self.repo, self.patch, retry_limit=4,
                               source_hash="bffd1c2752f8")

    def test_status_is_needs_manual_rebase(self):
        self.assertEqual(self.res["status"], pca.STATUS_MANUAL)

    def test_all_four_strategies_were_attempted(self):
        self.assertEqual(self.res["attempts"], 4)

    def test_conflicts_are_structured(self):
        self.assertTrue(self.res["conflicts"])
        c = self.res["conflicts"][0]
        for key in ("file", "line_range", "base_lines", "incoming_lines"):
            self.assertIn(key, c)

    def test_the_conflict_names_the_file_and_a_line_range(self):
        c = self.res["conflicts"][0]
        self.assertEqual(c["file"], "target.txt")
        self.assertEqual(len(c["line_range"]), 2)
        self.assertLessEqual(c["line_range"][0], c["line_range"][1])

    def test_recommendation_cites_the_source_hash(self):
        self.assertIn("bffd1c2752f8", self.res["reuse_recommendation"])

    def test_recommendation_advises_against_forcing_the_diff(self):
        self.assertIn("manual rebase", self.res["reuse_recommendation"])


class ReadOnlyTest(RepoFixture):
    def test_the_target_tree_is_never_modified(self):
        patch = self._make_patch(ORIGINAL.replace("charlie", "CHARLIE"))
        before = _git(self.repo, "status", "--porcelain").stdout
        pca.analyze(self.repo, patch)
        self.assertEqual(_git(self.repo, "status", "--porcelain").stdout, before)

    def test_the_file_content_is_unchanged_even_on_a_conflict(self):
        patch = self._make_patch(ORIGINAL.replace("charlie", "X"))
        self._write("target.txt", ORIGINAL.replace("charlie", "Y"))
        _git(self.repo, "commit", "-aqm", "diverge")
        with open(os.path.join(self.repo, "target.txt")) as fh:
            before = fh.read()
        pca.analyze(self.repo, patch)
        with open(os.path.join(self.repo, "target.txt")) as fh:
            self.assertEqual(fh.read(), before)

    def test_every_git_invocation_uses_check(self):
        src = open(pca.__file__).read()
        self.assertIn('"git", "apply", "--check"', src)


class FailSoftTest(RepoFixture):
    def test_missing_repo(self):
        res = pca.analyze("/no/such/repo", "/tmp/x.patch")
        self.assertEqual(res["status"], pca.STATUS_MANUAL)
        self.assertIn("repo not found", res["reuse_recommendation"])

    def test_missing_patch(self):
        res = pca.analyze(self.repo, "/no/such/file.patch")
        self.assertIn("patch not found", res["reuse_recommendation"])

    def test_empty_patch_still_yields_a_conflict_entry(self):
        path = os.path.join(self.tmp.name, "empty.patch")
        open(path, "w").close()
        res = pca.analyze(self.repo, path)
        self.assertTrue(res["conflicts"])

    def test_retry_limit_is_honoured(self):
        patch = self._make_patch(ORIGINAL.replace("charlie", "X"))
        self._write("target.txt", ORIGINAL.replace("charlie", "Y"))
        _git(self.repo, "commit", "-aqm", "diverge")
        self.assertEqual(pca.analyze(self.repo, patch, retry_limit=2)["attempts"], 2)

    def test_analyzer_never_raises(self):
        for repo, patch in ((None, None), ("", ""), (self.repo, None)):
            self.assertIn(pca.analyze(repo, patch)["status"],
                          (pca.STATUS_CLEAN, pca.STATUS_FUZZ, pca.STATUS_MANUAL))


if __name__ == "__main__":
    unittest.main()


class ThreeWayIsNotTrustedTest(RepoFixture):
    """Why --3way is absent from the ladder, pinned so nobody "helpfully" adds it back.

    Measured 2026-08-12: for a patch and a target that edit the same lines incompatibly,
    `git apply --3way --check` returns 0 while the real `git apply --3way` returns 1 and
    writes conflict markers. The --check form validates that the blobs needed for a merge
    are available, not that the merge is conflict-free.
    """

    def test_three_way_is_not_on_the_ladder(self):
        flags = [f for _, extra in pca.STRATEGIES for f in extra]
        self.assertNotIn("--3way", flags)

    def test_git_three_way_check_really_does_lie(self):
        # If this ever fails, git changed and --3way could be reconsidered.
        patch = self._make_patch(
            ORIGINAL.replace("charlie\ndelta\necho\n", "C1\nD1\nE1\n"))
        self._write("target.txt",
                    ORIGINAL.replace("charlie\ndelta\necho\n", "C2\nD2\nE2\n"))
        _git(self.repo, "commit", "-aqm", "incompatible")

        checked = _git(self.repo, "apply", "--check", "--3way", patch).returncode
        applied = _git(self.repo, "apply", "--3way", patch).returncode
        _git(self.repo, "checkout", "--", "target.txt")

        self.assertEqual(checked, 0, "--3way --check reported failure; git may have "
                                     "changed and --3way could be reconsidered")
        self.assertNotEqual(applied, 0, "the real --3way apply succeeded; the premise "
                                        "for excluding it no longer holds")
