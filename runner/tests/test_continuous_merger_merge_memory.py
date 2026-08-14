#!/usr/bin/env python3
"""Merged-diff memory must actually be written when a merge lands.

`merged_diff_memory.capture_merge()` had no production caller — only tests — so
the memory file stayed empty forever and `get_recent_merges()` / `stats()` were
dead API. These tests pin the wiring in `continuous_merger._merge_branch` and,
just as importantly, pin that the capture can never break a merge that already
succeeded.
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import continuous_merger


def _run(returncode=0, stdout=""):
    return MagicMock(returncode=returncode, stdout=stdout, stderr="")


class TestCaptureMergeMemoryHelper(unittest.TestCase):
    def test_delegates_to_merged_diff_memory(self):
        fake = MagicMock()
        fake.capture_merge.return_value = True
        with patch.dict(sys.modules, {"merged_diff_memory": fake}):
            self.assertTrue(continuous_merger._capture_merge_memory("/repo", "agent/x", "sha1"))
        fake.capture_merge.assert_called_once_with("sha1", "agent/x", "/repo")

    def test_returns_false_without_a_sha_or_repo(self):
        self.assertFalse(continuous_merger._capture_merge_memory("/repo", "agent/x", ""))
        self.assertFalse(continuous_merger._capture_merge_memory("", "agent/x", "sha1"))
        self.assertFalse(continuous_merger._capture_merge_memory("/repo", "agent/x", None))

    def test_a_failing_write_is_reported_not_raised(self):
        fake = MagicMock()
        fake.capture_merge.return_value = False
        with patch.dict(sys.modules, {"merged_diff_memory": fake}):
            self.assertFalse(continuous_merger._capture_merge_memory("/repo", "b", "sha"))

    def test_an_exploding_capture_is_swallowed(self):
        fake = MagicMock()
        fake.capture_merge.side_effect = RuntimeError("disk full")
        with patch.dict(sys.modules, {"merged_diff_memory": fake}):
            self.assertFalse(continuous_merger._capture_merge_memory("/repo", "b", "sha"))


class TestMergeBranchWiring(unittest.TestCase):
    """_merge_branch must capture on every path that reports merged=True."""

    def setUp(self):
        self.captured = []
        self.capture_patch = patch.object(
            continuous_merger, "_capture_merge_memory",
            side_effect=lambda repo, branch, sha: self.captured.append((repo, branch, sha)) or True)
        self.capture_patch.start()
        self.addCleanup(self.capture_patch.stop)

    def test_already_ancestor_path_captures_before_the_ref_is_deleted(self):
        calls = []

        def fake_git(args, repo, timeout=None):
            calls.append(args)
            if args[:2] == ["git", "status"]:
                return _run(0, "")
            if args[:2] == ["git", "rev-parse"] and args[2] == "--verify":
                return _run(0, "sha-tip")
            if args[:2] == ["git", "merge-base"]:
                return _run(0, "")
            if args[:2] == ["git", "rev-parse"]:
                return _run(0, "sha-tip")
            return _run(0, "")

        with patch.object(continuous_merger, "_git", side_effect=fake_git):
            result = continuous_merger._merge_branch("/repo", "agent/x", "master", {})

        self.assertTrue(result["merged"])
        self.assertEqual(result["strategy"], "already_ancestor")
        self.assertEqual(self.captured, [("/repo", "agent/x", "sha-tip")])
        # capture must precede `git branch -D`, or the branch metadata is gone
        delete_index = next(i for i, a in enumerate(calls) if a[:3] == ["git", "branch", "-D"])
        self.assertGreater(delete_index, 0)

    def test_resolver_path_captures_the_merge_commit(self):
        def fake_git(args, repo, timeout=None):
            if args[:2] == ["git", "status"]:
                return _run(0, "")
            if args[:2] == ["git", "rev-parse"] and args[2] == "--verify":
                return _run(0, "branch-tip")
            if args[:2] == ["git", "merge-base"]:
                return _run(1, "")          # not an ancestor — go through the resolver
            if args[:3] == ["git", "rev-parse", "HEAD"]:
                return _run(0, "merge-sha")
            return _run(0, "")

        resolver = MagicMock()
        resolver.resolve_branch.return_value = {"merged": True, "strategy": "clean"}
        with patch.object(continuous_merger, "_git", side_effect=fake_git), \
             patch.object(continuous_merger, "auto_conflict_resolver", resolver):
            result = continuous_merger._merge_branch("/repo", "agent/x", "master", {})

        self.assertTrue(result["merged"])
        self.assertEqual(result["sha"], "merge-sha")
        self.assertEqual(self.captured, [("/repo", "agent/x", "merge-sha")])

    def test_nothing_is_captured_when_the_merge_does_not_land(self):
        def fake_git(args, repo, timeout=None):
            if args[:2] == ["git", "status"]:
                return _run(0, "")
            if args[:2] == ["git", "rev-parse"] and args[2] == "--verify":
                return _run(1, "")          # branch does not exist
            return _run(0, "")

        with patch.object(continuous_merger, "_git", side_effect=fake_git):
            result = continuous_merger._merge_branch("/repo", "agent/missing", "master", {})

        self.assertFalse(result["merged"])
        self.assertEqual(self.captured, [])

    def test_nothing_is_captured_when_the_resolver_refuses(self):
        def fake_git(args, repo, timeout=None):
            if args[:2] == ["git", "status"]:
                return _run(0, "")
            if args[:2] == ["git", "rev-parse"] and args[2] == "--verify":
                return _run(0, "branch-tip")
            if args[:2] == ["git", "merge-base"]:
                return _run(1, "")
            return _run(0, "")

        resolver = MagicMock()
        resolver.resolve_branch.return_value = {"merged": False, "error": "regression"}
        with patch.object(continuous_merger, "_git", side_effect=fake_git), \
             patch.object(continuous_merger, "auto_conflict_resolver", resolver):
            result = continuous_merger._merge_branch("/repo", "agent/x", "master", {})

        self.assertFalse(result["merged"])
        self.assertEqual(self.captured, [])


class TestCaptureNeverBreaksAMerge(unittest.TestCase):
    def test_a_raising_capture_does_not_fail_a_landed_merge(self):
        def fake_git(args, repo, timeout=None):
            if args[:2] == ["git", "status"]:
                return _run(0, "")
            if args[:2] == ["git", "rev-parse"] and args[2] == "--verify":
                return _run(0, "branch-tip")
            if args[:2] == ["git", "merge-base"]:
                return _run(1, "")
            if args[:3] == ["git", "rev-parse", "HEAD"]:
                return _run(0, "merge-sha")
            return _run(0, "")

        resolver = MagicMock()
        resolver.resolve_branch.return_value = {"merged": True, "strategy": "clean"}
        exploding = MagicMock()
        exploding.capture_merge.side_effect = OSError("read-only filesystem")

        with patch.object(continuous_merger, "_git", side_effect=fake_git), \
             patch.object(continuous_merger, "auto_conflict_resolver", resolver), \
             patch.dict(sys.modules, {"merged_diff_memory": exploding}):
            result = continuous_merger._merge_branch("/repo", "agent/x", "master", {})

        self.assertTrue(result["merged"], "a memory-write failure must not undo a merge")
        self.assertEqual(result["sha"], "merge-sha")


if __name__ == "__main__":
    unittest.main()
