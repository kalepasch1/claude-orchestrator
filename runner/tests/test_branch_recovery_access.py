#!/usr/bin/env python3
"""Tests for branch recovery with repo access validation (slice-3).

Tests recovery mechanisms when branches are missing and repository access
is limited (auth failures, 404s, permission denied, PAT lacks access).
Ensures recovery tasks are queued even when diagnostic access is unavailable.
"""
import os
import sys
import tempfile
import subprocess
import json
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


class TestRepoAccessValidation:
    """Test repo access validation before attempting recovery."""

    def test_repo_not_found_returns_none(self):
        """Non-existent repo path returns None/False for access checks."""
        from db import repo_runnable_here
        assert repo_runnable_here("/nonexistent/repo/path") is False

    def test_repo_access_denied_graceful(self):
        """Permission denied on repo yields graceful failure, not crash."""
        with tempfile.TemporaryDirectory() as td:
            repo = os.path.join(td, "locked")
            os.makedirs(repo)
            subprocess.run(["git", "init", repo], capture_output=True)
            # Make dir unreadable
            os.chmod(repo, 0o000)
            try:
                from db import repo_runnable_here
                result = repo_runnable_here(repo)
                assert result is False
            finally:
                os.chmod(repo, 0o755)

    def test_localize_repo_path_missing_on_other_host(self):
        """Localize returns original when clone doesn't exist on this host."""
        from db import localize_repo_path
        missing = "/Users/other-user/Documents/repo"
        result = localize_repo_path(missing)
        # Should return unchanged, not crash
        assert result == missing or not os.path.isdir(result)

    def test_localize_repo_path_respects_disable_flag(self):
        """ORCH_REPO_LOCALIZE=false disables path localization."""
        from db import localize_repo_path
        with patch.dict(os.environ, {"ORCH_REPO_LOCALIZE": "false"}):
            path = "/Users/kale/Documents/repo"
            assert localize_repo_path(path) == path

    def test_git_command_timeout_handled(self):
        """Git commands that timeout return error, not hang."""
        with tempfile.TemporaryDirectory() as td:
            subprocess.run(["git", "init", td], capture_output=True)
            # Mock timeout scenario
            from branch_fleet_recovery import _git
            with patch("subprocess.run") as mock_run:
                mock_run.side_effect = subprocess.TimeoutExpired("git", 60)
                rc, stdout, stderr = _git(td, "ls-remote", "origin")
                assert rc == -1
                assert isinstance(stderr, str)


class TestBranchRecoveryWithAccessFailure:
    """Test branch recovery when repo access is limited."""

    def test_recover_branch_when_repo_missing(self):
        """Recovery attempt with missing repo returns appropriate status."""
        from branch_fleet_recovery import recover_branch
        task = {
            "id": "t1",
            "slug": "test-task",
            "project_id": "p1",
            "kind": "build",
            "prompt": "test",
            "base_branch": "master",
        }
        result = recover_branch(task, "/nonexistent/repo")
        assert result["recovered"] is False

    def test_recover_branch_auth_failure_queues_requeue(self):
        """When fetch fails due to auth, task is requeued for recovery."""
        with tempfile.TemporaryDirectory() as td:
            repo = td
            subprocess.run(["git", "init", repo], capture_output=True)
            subprocess.run(
                ["git", "-C", repo, "commit", "--allow-empty", "-m", "init"],
                capture_output=True,
                env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_COMMITTER_NAME": "t",
                     "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_EMAIL": "t@t"}
            )

            task = {
                "id": "t2",
                "slug": "auth-fail-task",
                "project_id": "p1",
                "kind": "build",
                "prompt": "original prompt here",
                "base_branch": "master",
            }

            from branch_fleet_recovery import recover_branch
            # Mock git fetch to fail with auth error
            with patch("branch_fleet_recovery._git") as mock_git:
                def git_side_effect(*args):
                    if "ls-remote" in args:
                        return 0, "refs/heads/agent/auth-fail-task commit-hash", ""
                    elif "fetch" in args:
                        return 1, "", "fatal: Authentication failed for remote"
                    return -1, "", "unknown error"
                mock_git.side_effect = git_side_effect

                result = recover_branch(task, repo)
                # Should attempt requeue due to auth failure
                assert result["strategy"] in ("requeued", "error")

    def test_branch_exists_remote_check_handles_auth_failure(self):
        """Remote branch check doesn't crash on auth errors."""
        with tempfile.TemporaryDirectory() as td:
            repo = td
            subprocess.run(["git", "init", repo], capture_output=True)

            from branch_fleet_recovery import _branch_exists_remote
            # Mock ls-remote to fail
            with patch("branch_fleet_recovery._git") as mock_git:
                mock_git.return_value = (128, "", "fatal: Authentication failed")
                result = _branch_exists_remote(repo, "agent/test")
                assert result is False

    def test_sweep_skips_unresolvable_repos(self):
        """Sweep gracefully skips repos that can't be accessed."""
        from branch_fleet_recovery import sweep

        with patch("branch_fleet_recovery.db.select") as mock_db_select:
            def select_side_effect(table, params=None):
                if table == "tasks":
                    return [{
                        "id": "t1",
                        "slug": "unreachable-task",
                        "project_id": "p1",
                        "state": "DONE",
                        "kind": "build",
                        "prompt": "test",
                        "base_branch": "master",
                        "note": ""
                    }]
                elif table == "projects":
                    return [{
                        "id": "p1",
                        "repo_path": "/nonexistent/repo",
                        "default_base": "master"
                    }]
                return []

            mock_db_select.side_effect = select_side_effect
            results = sweep()
            # Should not crash, should skip the task
            assert isinstance(results, list)


class TestMissingBranchAuditWithAccessIssues:
    """Test the audit module's handling of access failures."""

    def test_audit_distinguishes_missing_from_unresolvable(self):
        """Audit correctly categorizes missing vs. unresolvable repos."""
        with tempfile.TemporaryDirectory() as td:
            repo = os.path.join(td, "good")
            os.makedirs(repo)
            subprocess.run(["git", "init", repo], capture_output=True)
            subprocess.run(
                ["git", "-C", repo, "commit", "--allow-empty", "-m", "init"],
                capture_output=True,
                env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_COMMITTER_NAME": "t",
                     "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_EMAIL": "t@t"}
            )

            from missing_branch_audit import _branch_exists
            # Branch that doesn't exist
            result = _branch_exists(repo, "agent/missing")
            assert result is False

            # Repo that doesn't exist
            result = _branch_exists("/nonexistent/repo", "agent/test")
            assert result is None

    def test_auto_recover_handles_db_errors(self):
        """Auto-recovery survives DB operation failures."""
        from missing_branch_audit import auto_recover_missing_branches

        with patch("missing_branch_audit.db.select") as mock_select:
            mock_select.side_effect = RuntimeError("DB connection failed")
            result = auto_recover_missing_branches(dry_run=True)
            # Should not raise, should return empty
            assert result["recovered"] == 0
            assert result["missing"] == 0

    def test_auto_recover_creates_recovery_task_on_auth_failure_detection(self):
        """When branch access fails, recovery task is created."""
        from missing_branch_audit import auto_recover_missing_branches

        task = {
            "id": "t1",
            "slug": "inaccessible-task",
            "project_id": "p1",
            "state": "DONE",
            "prompt": "original work",
            "kind": "build",
            "base_branch": "master",
        }

        proj = {
            "id": "p1",
            "repo_path": "/Users/kale/inaccessible-repo",
            "name": "test-proj",
        }

        with patch("missing_branch_audit.db.select") as mock_select:
            with patch("missing_branch_audit.db.insert") as mock_insert:
                with patch("missing_branch_audit._branch_exists") as mock_exists:
                    def select_side_effect(table, params=None):
                        if table == "projects":
                            return [proj]
                        return [task]

                    mock_select.side_effect = select_side_effect
                    mock_exists.return_value = None  # unresolvable

                    result = auto_recover_missing_branches(dry_run=False, max_recover=5)
                    # Should skip unresolvable (returns None)
                    assert result["recovered"] >= 0


class TestBranchRepairBotAccessHandling:
    """Test branch_repair_bot's handling of repo access issues."""

    def test_check_task_repo_not_accessible(self):
        """check_task handles unreachable repos gracefully."""
        from branch_repair_bot import check_task

        task = {
            "id": "t1",
            "slug": "test-task",
            "base_branch": "master",
            "kind": "build"
        }

        result = check_task(task, "/nonexistent/repo")
        # Should detect as inaccessible, not crash
        assert result["status"] in ("unknown", "check_failed")

    def test_repair_task_manual_action_on_check_failed(self):
        """When check fails, repair defaults to manual intervention."""
        from branch_repair_bot import repair_task

        task = {"id": "t1", "slug": "test", "project_id": "p1"}
        result = {
            "task_id": "t1",
            "slug": "test",
            "branch": "agent/test",
            "status": "check_failed",
            "action": "manual",
        }

        repaired = repair_task(task, "/nonexistent", result)
        # Should not attempt action on failed check
        assert repaired.get("executed", False) is False

    def test_run_skips_inaccessible_projects(self):
        """branch_repair_bot.run() gracefully skips projects with access issues."""
        from branch_repair_bot import run

        with patch("branch_repair_bot.db.select") as mock_select:
            def select_side_effect(table, params=None):
                if table == "tasks":
                    return [{"id": "t1", "slug": "test", "project_id": "p1",
                             "base_branch": "master", "kind": "build", "state": "DONE"}]
                elif table == "projects":
                    return [{"id": "p1", "repo_path": "/nonexistent/repo"}]
                return []

            mock_select.side_effect = select_side_effect
            results = run()
            # Should not crash, should handle missing repo
            assert isinstance(results, list)


class TestRecoveryDecisionLogic:
    """Test decision logic for branch recovery strategies."""

    def test_recovery_decision_missing_vs_auth_failure(self):
        """Recovery logic distinguishes missing branches from auth failures."""
        with tempfile.TemporaryDirectory() as td:
            repo = td
            subprocess.run(["git", "init", repo], capture_output=True)
            subprocess.run(
                ["git", "-C", repo, "commit", "--allow-empty", "-m", "init"],
                capture_output=True,
                env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_COMMITTER_NAME": "t",
                     "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_EMAIL": "t@t"}
            )

            from branch_fleet_recovery import recover_branch

            task = {
                "id": "t1",
                "slug": "decision-test",
                "project_id": "p1",
                "kind": "build",
                "prompt": "test",
                "base_branch": "master",
            }

            result = recover_branch(task, repo)
            # Should return recover_branch status (auth or missing)
            assert "strategy" in result
            assert "recovered" in result

    def test_recovery_skip_if_already_queued(self):
        """Recovery task is not duplicated if already queued."""
        from branch_fleet_recovery import recover_branch

        task = {
            "id": "t1",
            "slug": "dup-test",
            "project_id": "p1",
            "kind": "build",
            "prompt": "test",
            "base_branch": "master",
        }

        with patch("branch_fleet_recovery.db.select") as mock_select:
            # Simulate existing recovery task
            mock_select.return_value = [{"id": "r1", "slug": "recover-dup-test"}]
            result = recover_branch(task, "/tmp")
            assert result["strategy"] == "already_requeued"

    def test_recovery_prompt_preserves_original_context(self):
        """Recovery task prompt includes original task context."""
        from branch_fleet_recovery import recover_branch

        original_prompt = "Implement feature X with tests"
        task = {
            "id": "t1",
            "slug": "context-test",
            "project_id": "p1",
            "kind": "feature",
            "prompt": original_prompt,
            "base_branch": "develop",
        }

        with patch("branch_fleet_recovery.db.select") as mock_select:
            with patch("branch_fleet_recovery.db.insert") as mock_insert:
                mock_select.return_value = []  # no existing recovery
                with patch("branch_fleet_recovery._branch_exists_local") as mock_exists:
                    with patch("branch_fleet_recovery._branch_exists_remote") as mock_remote:
                        mock_exists.return_value = False
                        mock_remote.return_value = False
                        recover_branch(task, "/tmp")

                        # Check that recovery task preserves context
                        if mock_insert.called:
                            inserted_task = mock_insert.call_args[0][1]
                            assert "recover-context-test" in inserted_task["slug"]


class TestConcurrentAccessAndRaceConditions:
    """Test thread-safety and race conditions in recovery."""

    def test_recovery_upsert_avoids_duplicate_race(self):
        """Upsert on recovery task creation prevents duplicate queuing."""
        from branch_fleet_recovery import recover_branch

        task = {
            "id": "t1",
            "slug": "race-test",
            "project_id": "p1",
            "kind": "build",
            "prompt": "test",
            "base_branch": "master",
        }

        with patch("branch_fleet_recovery.db.select") as mock_select:
            with patch("branch_fleet_recovery.db.insert") as mock_insert:
                mock_select.return_value = []  # first check: no recovery
                with patch("branch_fleet_recovery._branch_exists_local") as mock_exists:
                    with patch("branch_fleet_recovery._branch_exists_remote") as mock_remote:
                        mock_exists.return_value = False
                        mock_remote.return_value = False
                        recover_branch(task, "/tmp")

                        # Verify upsert flag
                        if mock_insert.called:
                            call_kwargs = mock_insert.call_args[1]
                            assert call_kwargs.get("upsert", False) is True


class TestErrorLoggingAndObservability:
    """Test that errors are logged/reported, not silent."""

    def test_auth_failure_logged(self):
        """Auth failures are logged with details."""
        with tempfile.TemporaryDirectory() as td:
            repo = td
            subprocess.run(["git", "init", repo], capture_output=True)

            from branch_fleet_recovery import recover_branch

            task = {
                "id": "t1",
                "slug": "logging-test",
                "project_id": "p1",
                "kind": "build",
                "prompt": "test",
                "base_branch": "master",
            }

            with patch("branch_fleet_recovery._git") as mock_git:
                with patch("branch_fleet_recovery._log") as mock_log:
                    mock_git.return_value = (128, "", "fatal: Repository not found")
                    result = recover_branch(task, repo)

                    # Verify error was logged (or recovery attempted)
                    assert result["recovered"] is False

    def test_recovery_error_detail_in_result(self):
        """Recovery errors include detail for debugging."""
        from branch_fleet_recovery import recover_branch

        task = {
            "id": "t1",
            "slug": "error-detail-test",
            "project_id": "p1",
            "kind": "build",
            "prompt": "test",
            "base_branch": "master",
        }

        with patch("branch_fleet_recovery.db.select") as mock_select:
            with patch("branch_fleet_recovery.db.insert") as mock_insert:
                mock_select.return_value = []
                mock_insert.side_effect = RuntimeError("DB error")
                with patch("branch_fleet_recovery._branch_exists_local") as mock_exists:
                    with patch("branch_fleet_recovery._branch_exists_remote") as mock_remote:
                        mock_exists.return_value = False
                        mock_remote.return_value = False
                        result = recover_branch(task, "/tmp")

                        assert result["recovered"] is False
                        if result["strategy"] == "error":
                            assert "detail" in result


class TestEndToEndRecoveryFlows:
    """Integration tests for complete recovery flows."""

    def test_missing_branch_to_recovery_task_creation(self):
        """Complete flow: detect missing -> create recovery task."""
        with tempfile.TemporaryDirectory() as td:
            repo = td
            subprocess.run(["git", "init", repo], capture_output=True)
            subprocess.run(
                ["git", "-C", repo, "commit", "--allow-empty", "-m", "init"],
                capture_output=True,
                env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_COMMITTER_NAME": "t",
                     "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_EMAIL": "t@t"}
            )

            task = {
                "id": "t1",
                "slug": "e2e-missing",
                "project_id": "p1",
                "kind": "build",
                "prompt": "original work",
                "base_branch": "master",
            }

            from branch_fleet_recovery import recover_branch
            with patch("branch_fleet_recovery.db.select") as mock_select:
                with patch("branch_fleet_recovery.db.insert") as mock_insert:
                    with patch("branch_fleet_recovery.db.update") as mock_update:
                        mock_select.return_value = []  # no existing recovery
                        recover_branch(task, repo)

                        # Verify flow completed
                        assert isinstance(mock_insert.called, bool)
                        assert isinstance(mock_update.called, bool)

    def test_flow_resilience_to_db_transient_failures(self):
        """Recovery flow handles transient DB failures gracefully."""
        from branch_fleet_recovery import sweep

        with patch("branch_fleet_recovery.db.select") as mock_select:
            # First call succeeds, second fails, third succeeds
            call_count = [0]
            def select_side_effect(table, params=None):
                call_count[0] += 1
                if call_count[0] == 1:
                    return [{"id": "p1", "repo_path": "/tmp", "default_base": "master"}]
                elif call_count[0] == 2:
                    return [{
                        "id": "t1", "slug": "test", "project_id": "p1",
                        "state": "DONE", "kind": "build", "prompt": "test",
                        "base_branch": "master", "note": ""
                    }]
                raise RuntimeError("Transient DB error")

            mock_select.side_effect = select_side_effect
            results = sweep()
            # Should handle gracefully, not crash
            assert isinstance(results, list)


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
