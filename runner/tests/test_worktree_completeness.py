#!/usr/bin/env python3
"""
Tests for worktree_completeness.

These build a REAL git repo and a REAL sparse worktree in a temp dir rather than mocking
subprocess. The bug being guarded against is precisely that git's own behaviour surprised
us -- a mock of git would just encode the assumption that was wrong in the first place.

Nothing here touches the operator's home directory or the surrounding repo.
"""
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import worktree_completeness as wc


def _run(cwd, *args):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=60)


def _make_repo(root):
    """A repo with files in a subdirectory -- the subdirectory is what sparse drops."""
    repo = os.path.join(root, "repo")
    os.makedirs(os.path.join(repo, "runner", "tests"))
    _run(repo, "git", "init", "-q", "-b", "master")
    _run(repo, "git", "config", "user.email", "t@example.com")
    _run(repo, "git", "config", "user.name", "t")
    _run(repo, "git", "config", "commit.gpgsign", "false")
    with open(os.path.join(repo, "top.txt"), "w") as f:
        f.write("top\n")
    with open(os.path.join(repo, "runner", "mod.py"), "w") as f:
        f.write("VALUE = 1\n")
    with open(os.path.join(repo, "runner", "tests", "test_mod.py"), "w") as f:
        f.write("def test_ok():\n    assert True\n")
    _run(repo, "git", "add", "-A")
    _run(repo, "git", "commit", "-q", "-m", "init")
    return repo


def _make_sparse_worktree(repo, name="wt"):
    """Reproduce the real defect: a worktree limited to top-level files only."""
    wt = os.path.join(os.path.dirname(repo), name)
    # --detach: master is already checked out in the source repo, and git refuses to have
    # one branch in two worktrees.
    _run(repo, "git", "worktree", "add", "-q", "--no-checkout", "--detach", wt, "master")
    _run(wt, "git", "sparse-checkout", "init")
    _run(wt, "git", "sparse-checkout", "set", "top.txt")
    _run(wt, "git", "checkout", "-q", "--detach", "master")
    return wt


class _TempRepo(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.repo = _make_repo(self.root)

    def tearDown(self):
        self._tmp.cleanup()


class TestAFullWorktreeIsLeftAlone(_TempRepo):
    def test_the_source_repo_itself_reads_complete(self):
        v = wc.inspect(self.repo)
        self.assertTrue(v["complete"])
        self.assertEqual(v["missing_count"], 0)

    def test_a_normal_worktree_reads_complete(self):
        wt = os.path.join(self.root, "full")
        _run(self.repo, "git", "worktree", "add", "-q", "--detach", wt, "master")
        v = wc.inspect(wt)
        self.assertTrue(v["complete"], v["reason"])
        self.assertTrue(os.path.exists(os.path.join(wt, "runner", "mod.py")))

    def test_ensure_complete_is_a_noop_on_a_good_worktree(self):
        wt = os.path.join(self.root, "full2")
        _run(self.repo, "git", "worktree", "add", "-q", "--detach", wt, "master")
        ok, _ = wc.ensure_complete(wt)
        self.assertTrue(ok)
        self.assertTrue(os.path.exists(os.path.join(wt, "runner", "tests", "test_mod.py")))


class TestTheDefectIsDetected(_TempRepo):
    def setUp(self):
        super().setUp()
        self.wt = _make_sparse_worktree(self.repo)

    def test_the_premise_the_files_really_are_missing_from_disk(self):
        """If this fails, the rest of the suite is testing nothing."""
        self.assertTrue(os.path.exists(os.path.join(self.wt, "top.txt")))
        self.assertFalse(os.path.exists(os.path.join(self.wt, "runner", "mod.py")))

    def test_but_the_index_still_lists_them(self):
        """The exact trap: git says the file is tracked while the disk has no such file."""
        out = _run(self.wt, "git", "ls-files")
        self.assertIn("runner/mod.py", out.stdout)

    def test_inspect_reports_incomplete(self):
        v = wc.inspect(self.wt)
        self.assertFalse(v["complete"])
        self.assertGreater(v["missing_count"], 0)

    def test_the_missing_paths_are_named_not_just_counted(self):
        v = wc.inspect(self.wt)
        self.assertTrue(any("runner/" in p for p in v["missing_sample"]), v["missing_sample"])

    def test_sparse_flag_is_seen(self):
        self.assertTrue(wc.sparse_enabled(self.wt))

    def test_skipped_paths_can_be_limited(self):
        self.assertLessEqual(len(wc.skipped_paths(self.wt, limit=1)), 1)


class TestRepair(_TempRepo):
    def setUp(self):
        super().setUp()
        self.wt = _make_sparse_worktree(self.repo, "wt_repair")

    def test_repair_materializes_the_missing_files(self):
        ok, log = wc.repair(self.wt)
        self.assertTrue(ok, log)
        self.assertTrue(os.path.exists(os.path.join(self.wt, "runner", "mod.py")))
        self.assertTrue(os.path.exists(os.path.join(self.wt, "runner", "tests", "test_mod.py")))

    def test_repair_clears_the_verdict(self):
        wc.repair(self.wt)
        self.assertTrue(wc.inspect(self.wt)["complete"])

    def test_ensure_complete_repairs_by_default(self):
        ok, _ = wc.ensure_complete(self.wt)
        self.assertTrue(ok)
        self.assertTrue(os.path.exists(os.path.join(self.wt, "runner", "mod.py")))

    def test_ensure_complete_can_refuse_without_repairing(self):
        ok, detail = wc.ensure_complete(self.wt, repair_if_sparse=False)
        self.assertFalse(ok)
        self.assertIn("index", detail)
        self.assertFalse(os.path.exists(os.path.join(self.wt, "runner", "mod.py")))


class TestFailSoft(unittest.TestCase):
    """Anything unreadable must be reported COMPLETE. A guard that blocks real work on a
    path it merely failed to understand is worse than the bug it is chasing."""

    def test_a_non_git_directory_is_not_flagged(self):
        with tempfile.TemporaryDirectory() as d:
            v = wc.inspect(d)
            self.assertTrue(v["complete"])
            self.assertFalse(v["checked"])

    def test_a_missing_path_is_not_flagged(self):
        v = wc.inspect("/nonexistent/path/that/does/not/exist")
        self.assertTrue(v["complete"])

    def test_empty_path_is_not_flagged(self):
        self.assertTrue(wc.inspect("")["complete"])

    def test_ensure_complete_allows_an_unreadable_path(self):
        ok, _ = wc.ensure_complete("/nonexistent/path/that/does/not/exist")
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()
