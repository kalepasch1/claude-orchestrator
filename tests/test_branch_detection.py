"""
test_branch_detection.py — unit tests for branch_detection module.

Tests cover:
  - detect_orphaned_branches: finds branches with no task
  - detect_missing_branches: finds tasks with no branch
  - classify_branch_state: single-branch state classifier
  - Edge cases: empty inputs, missing repo, None values
"""
import os
import sys
import pytest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "runner"))
import branch_detection as bd


# ---------------------------------------------------------------------------
# detect_orphaned_branches
# ---------------------------------------------------------------------------
class TestDetectOrphaned:
    def test_finds_orphan(self):
        with mock.patch.object(bd, "_list_agent_branches", return_value={"task-a", "task-b", "orphan-x"}):
            with mock.patch("os.path.isdir", return_value=True):
                result = bd.detect_orphaned_branches("/repo", {"task-a", "task-b"})
        assert result == ["orphan-x"]

    def test_no_orphans(self):
        with mock.patch.object(bd, "_list_agent_branches", return_value={"task-a"}):
            with mock.patch("os.path.isdir", return_value=True):
                result = bd.detect_orphaned_branches("/repo", {"task-a"})
        assert result == []

    def test_empty_known_slugs(self):
        with mock.patch.object(bd, "_list_agent_branches", return_value={"x", "y"}):
            with mock.patch("os.path.isdir", return_value=True):
                result = bd.detect_orphaned_branches("/repo", set())
        assert sorted(result) == ["x", "y"]

    def test_missing_repo_returns_empty(self):
        result = bd.detect_orphaned_branches("", {"a"})
        assert result == []

    def test_none_repo_returns_empty(self):
        result = bd.detect_orphaned_branches(None, {"a"})
        assert result == []


# ---------------------------------------------------------------------------
# detect_missing_branches
# ---------------------------------------------------------------------------
class TestDetectMissing:
    def test_finds_missing(self):
        tasks = [
            {"slug": "exists", "state": "RUNNING"},
            {"slug": "gone", "state": "RUNNING"},
        ]
        with mock.patch.object(bd, "_list_agent_branches", return_value={"exists"}):
            with mock.patch("os.path.isdir", return_value=True):
                result = bd.detect_missing_branches("/repo", tasks)
        assert len(result) == 1
        assert result[0]["slug"] == "gone"

    def test_ignores_completed_tasks(self):
        tasks = [{"slug": "done-task", "state": "DONE"}]
        with mock.patch.object(bd, "_list_agent_branches", return_value=set()):
            with mock.patch("os.path.isdir", return_value=True):
                result = bd.detect_missing_branches("/repo", tasks)
        assert result == []

    def test_empty_tasks(self):
        with mock.patch("os.path.isdir", return_value=True):
            result = bd.detect_missing_branches("/repo", [])
        assert result == []

    def test_none_tasks(self):
        with mock.patch("os.path.isdir", return_value=True):
            result = bd.detect_missing_branches("/repo", None)
        assert result == []


# ---------------------------------------------------------------------------
# classify_branch_state
# ---------------------------------------------------------------------------
class TestClassify:
    def test_healthy(self):
        with mock.patch.object(bd, "_git", return_value=(0, "", "")):
            r = bd.classify_branch_state("/repo", "my-slug", known_slugs={"my-slug"})
        assert r["state"] == "healthy"

    def test_orphaned(self):
        with mock.patch.object(bd, "_git", return_value=(0, "", "")):
            r = bd.classify_branch_state("/repo", "orphan", known_slugs=set())
        assert r["state"] == "orphaned"

    def test_missing(self):
        with mock.patch.object(bd, "_git", return_value=(128, "", "not found")):
            tasks = [{"slug": "missing-slug", "state": "RUNNING"}]
            r = bd.classify_branch_state("/repo", "missing-slug", tasks=tasks)
        assert r["state"] == "missing"

    def test_unknown(self):
        with mock.patch.object(bd, "_git", return_value=(128, "", "not found")):
            r = bd.classify_branch_state("/repo", "mystery", known_slugs=set())
        assert r["state"] == "unknown"


# ---------------------------------------------------------------------------
# _list_agent_branches
# ---------------------------------------------------------------------------
class TestListAgentBranches:
    def test_parses_output(self):
        fake_output = "  agent/task-a\n  agent/task-b\n* agent/current"
        with mock.patch.object(bd, "_git", return_value=(0, fake_output, "")):
            result = bd._list_agent_branches("/repo")
        assert result == {"task-a", "task-b", "current"}

    def test_empty_on_error(self):
        with mock.patch.object(bd, "_git", return_value=(1, "", "error")):
            result = bd._list_agent_branches("/repo")
        assert result == set()

    def test_empty_on_no_branches(self):
        with mock.patch.object(bd, "_git", return_value=(0, "", "")):
            result = bd._list_agent_branches("/repo")
        assert result == set()
