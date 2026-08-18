#!/usr/bin/env python3
"""
Tests for branch_manager base-branch detection.

The old detector probed local `master`, returned `main` on anything else, and
only caught CalledProcessError. It therefore: raised on timeout/missing-git,
misread fresh clones that have origin/master but no local master, and could
never return a non-generic default such as darwn's `medicalOnly`.

These tests build real throwaway git repos rather than mocking subprocess, so
they exercise the actual ref resolution.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RUNNER not in sys.path:
    sys.path.insert(0, RUNNER)

import branch_manager  # noqa: E402


def _mkrepo(tmp, branch):
    """Create a git repo whose only branch is `branch`, with one commit."""
    subprocess.run(["git", "init", "-q", "-b", branch, tmp], check=True)
    subprocess.run(["git", "-C", tmp, "config", "user.email", "t@t.t"], check=True)
    subprocess.run(["git", "-C", tmp, "config", "user.name", "t"], check=True)
    open(os.path.join(tmp, "f"), "w").write("x")
    subprocess.run(["git", "-C", tmp, "add", "."], check=True)
    subprocess.run(["git", "-C", tmp, "commit", "-q", "-m", "init"], check=True)
    return tmp


class RefExistsTest(unittest.TestCase):
    def test_true_for_a_real_ref(self):
        with tempfile.TemporaryDirectory() as tmp:
            _mkrepo(tmp, "master")
            self.assertTrue(branch_manager._ref_exists(tmp, "master"))

    def test_false_for_a_missing_ref(self):
        with tempfile.TemporaryDirectory() as tmp:
            _mkrepo(tmp, "master")
            self.assertFalse(branch_manager._ref_exists(tmp, "main"))

    def test_false_and_no_raise_for_a_nonexistent_path(self):
        self.assertFalse(branch_manager._ref_exists("/nonexistent/repo/xyz", "master"))

    def test_false_and_no_raise_on_timeout(self):
        with mock.patch.object(branch_manager.subprocess, "call",
                               side_effect=subprocess.TimeoutExpired("git", 5)):
            self.assertFalse(branch_manager._ref_exists("/tmp", "master"))

    def test_false_and_no_raise_when_git_is_missing(self):
        with mock.patch.object(branch_manager.subprocess, "call",
                               side_effect=FileNotFoundError("git")):
            self.assertFalse(branch_manager._ref_exists("/tmp", "master"))


class DetectBaseBranchTest(unittest.TestCase):
    def setUp(self):
        # Default: no project row matches, so detection falls to repo state.
        self._p = mock.patch.object(branch_manager.db, "select", return_value=[])
        self._p.start()

    def tearDown(self):
        self._p.stop()

    def test_master_repo_detected_as_master(self):
        with tempfile.TemporaryDirectory() as tmp:
            _mkrepo(tmp, "master")
            self.assertEqual(branch_manager._detect_base_branch(tmp), "master")

    def test_main_repo_detected_as_main(self):
        """The regression: a main-only repo used to work by accident, but only
        because the master probe raised CalledProcessError."""
        with tempfile.TemporaryDirectory() as tmp:
            _mkrepo(tmp, "main")
            self.assertEqual(branch_manager._detect_base_branch(tmp), "main")

    def test_configured_default_base_wins_when_it_resolves(self):
        with tempfile.TemporaryDirectory() as tmp:
            _mkrepo(tmp, "medicalOnly")
            with mock.patch.object(branch_manager.db, "select", return_value=[
                {"repo_path": tmp, "default_base": "medicalOnly"},
            ]):
                self.assertEqual(branch_manager._detect_base_branch(tmp), "medicalOnly")

    def test_configured_default_base_ignored_when_it_does_not_resolve(self):
        """Naming a branch that is not in the checkout is the failure this
        prevents — fall through to observed repo state instead."""
        with tempfile.TemporaryDirectory() as tmp:
            _mkrepo(tmp, "master")
            with mock.patch.object(branch_manager.db, "select", return_value=[
                {"repo_path": tmp, "default_base": "does-not-exist"},
            ]):
                self.assertEqual(branch_manager._detect_base_branch(tmp), "master")

    def test_a_db_failure_does_not_raise(self):
        with tempfile.TemporaryDirectory() as tmp:
            _mkrepo(tmp, "main")
            with mock.patch.object(branch_manager.db, "select",
                                   side_effect=RuntimeError("db down")):
                self.assertEqual(branch_manager._detect_base_branch(tmp), "main")

    def test_remote_only_master_is_detected(self):
        """A fresh clone / agent worktree may carry origin/master and no local
        master. The old probe reported that repo as `main`."""
        with tempfile.TemporaryDirectory() as up, tempfile.TemporaryDirectory() as down:
            _mkrepo(up, "master")
            clone = os.path.join(down, "c")
            subprocess.run(["git", "clone", "-q", up, clone], check=True)
            subprocess.run(["git", "-C", clone, "checkout", "-q", "-b", "agent/x"], check=True)
            subprocess.run(["git", "-C", clone, "branch", "-q", "-D", "master"], check=True)
            self.assertEqual(branch_manager._detect_base_branch(clone), "master")

    def test_empty_and_bogus_paths_fall_back_to_master_without_raising(self):
        for path in ("/nonexistent/repo/xyz", "", "/tmp"):
            self.assertIn(branch_manager._detect_base_branch(path),
                          ("master", "main"))

    def test_never_raises_even_when_every_git_call_explodes(self):
        with mock.patch.object(branch_manager.subprocess, "call",
                               side_effect=OSError("boom")), \
             mock.patch.object(branch_manager.subprocess, "check_output",
                               side_effect=OSError("boom")):
            self.assertEqual(branch_manager._detect_base_branch("/tmp"), "master")


class OriginHeadTest(unittest.TestCase):
    def test_strips_the_origin_prefix(self):
        with mock.patch.object(branch_manager.subprocess, "check_output",
                               return_value="origin/develop\n"):
            self.assertEqual(branch_manager._origin_head("/tmp"), "develop")

    def test_empty_when_origin_head_is_unset(self):
        with mock.patch.object(branch_manager.subprocess, "check_output",
                               side_effect=subprocess.CalledProcessError(1, "git")):
            self.assertEqual(branch_manager._origin_head("/tmp"), "")

    def test_empty_when_the_ref_is_not_origin_prefixed(self):
        with mock.patch.object(branch_manager.subprocess, "check_output",
                               return_value="HEAD\n"):
            self.assertEqual(branch_manager._origin_head("/tmp"), "")


if __name__ == "__main__":
    unittest.main()
