"""Tests for branch_lifecycle module."""
import os
import subprocess
import sys
import tempfile
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
import branch_lifecycle as bl


# ---------------------------------------------------------------------------
# validate_branch_name
# ---------------------------------------------------------------------------
class TestValidateBranchName:
    def test_valid_agent(self):
        ok, reason = bl.validate_branch_name("agent/my-task-slug")
        assert ok is True and reason == ""

    def test_valid_feature(self):
        ok, _ = bl.validate_branch_name("feature/proj-123")
        assert ok is True

    def test_empty(self):
        ok, reason = bl.validate_branch_name("")
        assert ok is False and "empty" in reason

    def test_none(self):
        ok, _ = bl.validate_branch_name(None)
        assert ok is False

    def test_too_long(self):
        ok, reason = bl.validate_branch_name("a" * 260)
        assert ok is False and "too long" in reason

    def test_double_dot(self):
        ok, reason = bl.validate_branch_name("agent/foo..bar")
        assert ok is False and ".." in reason

    def test_tilde(self):
        ok, reason = bl.validate_branch_name("agent/foo~1")
        assert ok is False

    def test_space(self):
        ok, reason = bl.validate_branch_name("agent/foo bar")
        assert ok is False

    def test_ends_with_lock(self):
        ok, reason = bl.validate_branch_name("agent/foo.lock")
        assert ok is False

    def test_ends_with_slash(self):
        ok, reason = bl.validate_branch_name("agent/foo/")
        assert ok is False

    def test_starts_with_dash(self):
        ok, reason = bl.validate_branch_name("-agent/foo")
        assert ok is False

    def test_consecutive_slashes(self):
        ok, reason = bl.validate_branch_name("agent//foo")
        assert ok is False

    def test_backslash(self):
        ok, reason = bl.validate_branch_name("agent\\foo")
        assert ok is False

    def test_caret(self):
        ok, reason = bl.validate_branch_name("agent/foo^bar")
        assert ok is False


# ---------------------------------------------------------------------------
# is_agent_branch / is_feature_branch
# ---------------------------------------------------------------------------
class TestBranchTypeChecks:
    def test_agent_branch(self):
        assert bl.is_agent_branch("agent/my-task") is True

    def test_not_agent(self):
        assert bl.is_agent_branch("feature/foo") is False

    def test_agent_empty_slug(self):
        assert bl.is_agent_branch("agent/") is False

    def test_agent_none(self):
        assert bl.is_agent_branch(None) is False

    def test_feature_branch(self):
        assert bl.is_feature_branch("feature/proj-123") is True

    def test_not_feature(self):
        assert bl.is_feature_branch("agent/foo") is False

    def test_feature_empty(self):
        assert bl.is_feature_branch("feature/") is False


# ---------------------------------------------------------------------------
# branch_exists (with real temp git repo)
# ---------------------------------------------------------------------------
class TestBranchExists:
    @pytest.fixture
    def git_repo(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=str(repo), capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(repo), capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=str(repo), capture_output=True)
        (repo / "f.txt").write_text("init")
        subprocess.run(["git", "add", "."], cwd=str(repo), capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(repo), capture_output=True)
        subprocess.run(["git", "checkout", "-b", "agent/test-task"], cwd=str(repo), capture_output=True)
        subprocess.run(["git", "checkout", "-"], cwd=str(repo), capture_output=True)
        return str(repo)

    def test_exists(self, git_repo):
        assert bl.branch_exists(git_repo, "agent/test-task") is True

    def test_not_exists(self, git_repo):
        assert bl.branch_exists(git_repo, "agent/nonexistent") is False

    def test_bad_repo(self):
        assert bl.branch_exists("/nonexistent/repo", "agent/foo") is None

    def test_none_repo(self):
        assert bl.branch_exists(None, "agent/foo") is None


# ---------------------------------------------------------------------------
# zero_spend_recovery_eligible
# ---------------------------------------------------------------------------
class TestZeroSpendRecovery:
    def test_no_task(self):
        result = bl.zero_spend_recovery_eligible(None, "/tmp")
        assert result["eligible"] is False

    def test_max_retries(self):
        task = {"slug": "foo", "state": "FAILED", "attempt": 99}
        result = bl.zero_spend_recovery_eligible(task, "/tmp")
        assert result["eligible"] is False
        assert "max retries" in result["reason"]

    def test_failed_no_branch(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=str(repo), capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=str(repo), capture_output=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=str(repo), capture_output=True)
        (repo / "f.txt").write_text("x")
        subprocess.run(["git", "add", "."], cwd=str(repo), capture_output=True)
        subprocess.run(["git", "commit", "-m", "i"], cwd=str(repo), capture_output=True)

        task = {"slug": "missing-task", "state": "FAILED", "attempt": 0}
        result = bl.zero_spend_recovery_eligible(task, str(repo))
        assert result["eligible"] is True
        assert result["strategy"] == "recreate_from_base"

    def test_failed_with_branch(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=str(repo), capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=str(repo), capture_output=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=str(repo), capture_output=True)
        (repo / "f.txt").write_text("x")
        subprocess.run(["git", "add", "."], cwd=str(repo), capture_output=True)
        subprocess.run(["git", "commit", "-m", "i"], cwd=str(repo), capture_output=True)
        subprocess.run(["git", "checkout", "-b", "agent/has-work"], cwd=str(repo), capture_output=True)
        subprocess.run(["git", "checkout", "-"], cwd=str(repo), capture_output=True)

        task = {"slug": "has-work", "state": "FAILED", "attempt": 1}
        result = bl.zero_spend_recovery_eligible(task, str(repo))
        assert result["eligible"] is True
        assert result["strategy"] == "requeue"

    def test_running_with_branch(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=str(repo), capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=str(repo), capture_output=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=str(repo), capture_output=True)
        (repo / "f.txt").write_text("x")
        subprocess.run(["git", "add", "."], cwd=str(repo), capture_output=True)
        subprocess.run(["git", "commit", "-m", "i"], cwd=str(repo), capture_output=True)
        subprocess.run(["git", "checkout", "-b", "agent/orphan"], cwd=str(repo), capture_output=True)
        subprocess.run(["git", "checkout", "-"], cwd=str(repo), capture_output=True)

        task = {"slug": "orphan", "state": "RUNNING", "attempt": 0}
        result = bl.zero_spend_recovery_eligible(task, str(repo))
        assert result["eligible"] is True
        assert result["strategy"] == "adopt_orphan"

    def test_unreachable_repo(self):
        task = {"slug": "foo", "state": "FAILED", "attempt": 0}
        result = bl.zero_spend_recovery_eligible(task, "/nonexistent")
        assert result["eligible"] is False


# ---------------------------------------------------------------------------
# list_cleanup_candidates
# ---------------------------------------------------------------------------
class TestListCleanupCandidates:
    def test_bad_repo(self):
        assert bl.list_cleanup_candidates("/nonexistent", {"merged-slug"}) == []

    def test_merged_branch(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=str(repo), capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=str(repo), capture_output=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=str(repo), capture_output=True)
        (repo / "f.txt").write_text("x")
        subprocess.run(["git", "add", "."], cwd=str(repo), capture_output=True)
        subprocess.run(["git", "commit", "-m", "i"], cwd=str(repo), capture_output=True)
        subprocess.run(["git", "checkout", "-b", "agent/done-task"], cwd=str(repo), capture_output=True)
        subprocess.run(["git", "checkout", "-"], cwd=str(repo), capture_output=True)

        candidates = bl.list_cleanup_candidates(str(repo), {"done-task"})
        assert len(candidates) == 1
        assert candidates[0]["reason"] == "merged"


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------
class TestStats:
    def test_stats_returns_dict(self):
        s = bl.stats()
        assert isinstance(s, dict)
        assert "validations" in s

    def test_reset(self):
        bl.reset_stats()
        s = bl.stats()
        assert all(v == 0 for v in s.values())
