"""Unit tests for the dirty/broken-worktree reconciler.

Run: python3 -m unittest discover -s tools -p 'test_*.py'

Real git repos, not mocks: the classifier's whole job is reading git state
correctly, and a mock would happily agree with a wrong command.

Regression under test: an untracked path is untracked relative to the worktree's
own checkout, not to the base branch. A worktree parked on an older commit
reports files the base has since started tracking, and those were classified
RECOVERABLE_VALUE — dropped work that was never dropped.
"""

import os
import subprocess
import tempfile
import unittest

import reconcile_worktree_evidence as r


def run(repo, *args):
    subprocess.run(["git", "-C", repo, *args], check=True,
                   capture_output=True, text=True)


def write(repo, rel, body):
    path = os.path.join(repo, rel)
    os.makedirs(os.path.dirname(path) or repo, exist_ok=True)
    with open(path, "w") as fh:
        fh.write(body)
    return path


def commit(repo, message):
    run(repo, "add", "-A")
    run(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-m", message)


class SplitUntrackedAgainstBase(unittest.TestCase):
    """base_blob / worktree_blob / split_untracked_against_base."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = self.tmp.name
        run(self.repo, "init", "-q", "-b", "main")
        write(self.repo, "kept.txt", "one\n")
        commit(self.repo, "base")
        self.addCleanup(self.tmp.cleanup)

    def test_path_absent_from_base_is_new(self):
        write(self.repo, "brand-new.txt", "fresh\n")
        new, same, differs = r.split_untracked_against_base(
            ["brand-new.txt"], self.repo, "main", self.repo)
        self.assertEqual((new, same, differs), (["brand-new.txt"], [], []))

    def test_identical_to_base_is_not_new(self):
        # The exact case that produced a false RECOVERABLE_VALUE: the worktree
        # holds a byte-identical copy of a file the base already tracks.
        new, same, differs = r.split_untracked_against_base(
            ["kept.txt"], self.repo, "main", self.repo)
        self.assertEqual((new, same, differs), ([], ["kept.txt"], []))

    def test_diverged_from_base_is_neither_new_nor_same(self):
        write(self.repo, "kept.txt", "two\n")
        new, same, differs = r.split_untracked_against_base(
            ["kept.txt"], self.repo, "main", self.repo)
        self.assertEqual((new, same, differs), ([], [], ["kept.txt"]))

    def test_missing_file_is_not_treated_as_matching(self):
        new, same, differs = r.split_untracked_against_base(
            ["kept.txt"], os.path.join(self.repo, "nope"), "main", self.repo)
        self.assertEqual(differs, ["kept.txt"])

    def test_base_blob_failsoft_on_bad_ref(self):
        self.assertEqual(r.base_blob("no-such-ref", "kept.txt", self.repo), "")

    def test_worktree_blob_failsoft_on_missing_path(self):
        self.assertEqual(r.worktree_blob(self.repo, "absent.txt"), "")
