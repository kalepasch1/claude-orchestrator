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


def _declare_resolved_file_gate_green(case):
    """Stub _merge_branch's resolved-file gate for the duration of one test case.

    The resolver path in _merge_branch calls _resolved_file_gate_blocked(), which
    delegates to resolved_file_gate.promotion_blocked() — a REAL scan of a real
    working tree, fail-closed by design. These tests hand it the fictional "/repo",
    so the gate scans whatever checkout the suite happens to run from, finds the
    conflict-marker strings that live in this repo's own fixtures, and refuses. The
    merge then reports merged=False and the memory-capture assertions fail — an
    outcome decided by the contents of the developer's checkout rather than by the
    capture wiring these tests are named for.

    The gate is fail-closed on purpose and owns its own test file
    (test_resolved_file_gate.py); declaring it green here keeps this file about
    _merge_branch's capture wiring.
    """
    p = patch.object(continuous_merger, "_resolved_file_gate_blocked",
                     return_value=(False, ""))
    p.start()
    case.addCleanup(p.stop)


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
        _declare_resolved_file_gate_green(self)

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
        # The resolved-file gate (added 2026-08-12, after this file was written)
        # sits between resolve_branch and the capture, and it does its own
        # filesystem work rather than going through the mocked _git -- so
        # against a "/repo" that does not exist it correctly fails closed and
        # no merge is reported. That behaviour has its own test below; here the
        # subject is the capture wiring, so the gate is stubbed open.
        with patch.object(continuous_merger, "_git", side_effect=fake_git), \
             patch.object(continuous_merger, "auto_conflict_resolver", resolver), \
             patch.object(continuous_merger, "_resolved_file_gate_blocked",
                          return_value=(False, "")):
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
    def setUp(self):
        _declare_resolved_file_gate_green(self)

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
             patch.object(continuous_merger, "_resolved_file_gate_blocked",
                          return_value=(False, "")), \
             patch.dict(sys.modules, {"merged_diff_memory": exploding}):
            result = continuous_merger._merge_branch("/repo", "agent/x", "master", {})

        self.assertTrue(result["merged"], "a memory-write failure must not undo a merge")
        self.assertEqual(result["sha"], "merge-sha")


class TestTheResolvedFileGateIsInThePath(unittest.TestCase):
    """The gate the two tests above have to stub open must really be there.

    It was added to _merge_branch in 2026-08-12, after this file was written,
    and its arrival is what turned those two green tests red: it reaches the
    filesystem directly rather than through the mocked _git, so a repo path that
    does not exist enumerates to nothing and it fails closed. Stubbing it open
    to test the capture wiring is only safe while these hold.
    """

    def _fake_git(self, args, repo, timeout=None):
        if args[:2] == ["git", "status"]:
            return _run(0, "")
        if args[:2] == ["git", "rev-parse"] and args[2] == "--verify":
            return _run(0, "branch-tip")
        if args[:2] == ["git", "merge-base"]:
            return _run(1, "")
        if args[:3] == ["git", "rev-parse", "HEAD"]:
            return _run(0, "merge-sha")
        return _run(0, "")

    def _merge(self, gate_return):
        resolver = MagicMock()
        resolver.resolve_branch.return_value = {"merged": True, "strategy": "clean",
                                                "resolved_files": ["a.py"]}
        captured = []
        memory = MagicMock()
        memory.capture_merge.side_effect = lambda sha, br, repo: captured.append(sha) or True
        with patch.object(continuous_merger, "_git", side_effect=self._fake_git), \
             patch.object(continuous_merger, "auto_conflict_resolver", resolver), \
             patch.object(continuous_merger, "_resolved_file_gate_blocked",
                          return_value=gate_return) as gate, \
             patch.dict(sys.modules, {"merged_diff_memory": memory}):
            result = continuous_merger._merge_branch("/repo", "agent/x", "master", {})
        return result, gate, captured

    def test_a_blocking_gate_refuses_the_merge(self):
        result, _, captured = self._merge((True, "markers in three files"))
        self.assertFalse(result["merged"])
        self.assertEqual(result["strategy"], "gate-blocked")
        self.assertIn("markers in three files", result["error"])
        self.assertIsNone(result["sha"])
        self.assertEqual(captured, [],
                         "a blocked merge must not be written to merge memory")

    def test_the_gate_is_handed_the_files_the_resolver_touched(self):
        _, gate, _ = self._merge((False, ""))
        gate.assert_called_once_with("/repo", ["a.py"])

    def test_an_unreadable_repo_fails_closed_for_real(self):
        """Not stubbed: the real gate, against a path that does not exist."""
        blocked, reason = continuous_merger._resolved_file_gate_blocked(
            "/nonexistent/repo", [])
        self.assertTrue(blocked)
        self.assertTrue(reason)


if __name__ == "__main__":
    unittest.main()
