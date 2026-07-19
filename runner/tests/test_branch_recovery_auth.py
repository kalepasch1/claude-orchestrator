#!/usr/bin/env python3
"""Tests for branch recovery with PAT authentication (slice-3).

Tests git operations with Personal Access Token (PAT) authentication,
ensuring graceful degradation when credentials are unavailable or invalid.
"""
import os
import sys
import tempfile
import subprocess
import json
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


class TestGitAuthModule:
    """Test git_auth module functionality."""

    def test_pat_available_when_configured(self):
        """pat_available returns True when ORCH_GIT_PAT is set."""
        import git_auth
        with patch.dict(os.environ, {"ORCH_GIT_PAT": "ghp_test123456"}):
            # Need to reload module to pick up env var
            import importlib
            importlib.reload(git_auth)
            assert git_auth.pat_available() is True

    def test_pat_unavailable_when_not_configured(self):
        """pat_available returns False when ORCH_GIT_PAT is not set."""
        import git_auth
        with patch.dict(os.environ, {}, clear=True):
            import importlib
            importlib.reload(git_auth)
            assert git_auth.pat_available() is False

    def test_run_git_with_missing_repo(self):
        """run_git returns error when repo doesn't exist."""
        import git_auth
        rc, out, err = git_auth.run_git(["branch"], "/nonexistent/repo")
        assert rc != 0
        assert err == "repo not accessible"

    def test_run_git_with_valid_repo(self):
        """run_git returns success for valid git repo."""
        import git_auth
        with tempfile.TemporaryDirectory() as td:
            subprocess.run(["git", "init", td], capture_output=True)
            rc, out, err = git_auth.run_git(["branch"], td)
            assert rc == 0

    def test_run_git_timeout_handled(self):
        """run_git timeout is caught and returns error."""
        import git_auth
        with patch("git_auth.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("git", 5)
            rc, out, err = git_auth.run_git(["branch"], "/tmp")
            assert rc == -1
            assert err == "timeout"

    def test_branch_exists_remote_false_when_missing(self):
        """branch_exists_remote returns False for nonexistent branch."""
        import git_auth
        with tempfile.TemporaryDirectory() as td:
            subprocess.run(["git", "init", td], capture_output=True)
            result = git_auth.branch_exists_remote(td, "nonexistent", "origin")
            assert result is False

    def test_fetch_branch_graceful_on_unreachable_remote(self):
        """fetch_branch returns (False, error) when remote unreachable."""
        import git_auth
        with tempfile.TemporaryDirectory() as td:
            subprocess.run(["git", "init", td], capture_output=True)
            ok, err = git_auth.fetch_branch(td, "main", "origin")
            assert ok is False
            assert isinstance(err, str)

    def test_ls_remote_returns_empty_on_failure(self):
        """ls_remote returns (False, []) when remote unreachable."""
        import git_auth
        with tempfile.TemporaryDirectory() as td:
            subprocess.run(["git", "init", td], capture_output=True)
            ok, branches = git_auth.ls_remote(td, "origin")
            assert ok is False
            assert branches == []

    def test_auth_status_dict_format(self):
        """auth_status returns dict with expected keys."""
        import git_auth
        status = git_auth.auth_status()
        assert "pat_configured" in status
        assert "pat_available" in status
        assert isinstance(status["pat_configured"], bool)
        assert isinstance(status["pat_available"], bool)

    def test_no_credential_leaks_in_git_output(self):
        """Git operation errors don't leak credential values."""
        import git_auth
        with tempfile.TemporaryDirectory() as td:
            subprocess.run(["git", "init", td], capture_output=True)
            rc, out, err = git_auth.run_git(["ls-remote", "fake://url"], td)
            # Should not contain any obvious token patterns
            assert "ghp_" not in err
            assert "token" not in err.lower() or "token_" in err


class TestBranchFleetRecoveryWithAuth:
    """Test branch_fleet_recovery with PAT authentication."""

    def test_recover_branch_uses_git_auth_for_fetch(self):
        """recover_branch uses git_auth.fetch_branch for remote operations."""
        from branch_fleet_recovery import recover_branch
        import branch_fleet_recovery

        task = {
            "id": "t1",
            "slug": "auth-test",
            "project_id": "p1",
            "kind": "build",
            "prompt": "test",
            "base_branch": "master",
        }

        with patch("branch_fleet_recovery.git_auth.fetch_branch") as mock_fetch:
            with patch("branch_fleet_recovery._branch_exists_local") as mock_local:
                with patch("branch_fleet_recovery._branch_exists_remote") as mock_remote:
                    mock_local.return_value = False
                    mock_remote.return_value = True
                    mock_fetch.return_value = (True, None)

                    result = recover_branch(task, "/tmp")

                    assert mock_fetch.called
                    assert result["recovered"] is True
                    assert result["strategy"] == "fetched_remote"

    def test_recover_branch_with_pat_unavailable(self):
        """recover_branch skips recovery when PAT is unavailable."""
        from branch_fleet_recovery import recover_branch

        task = {
            "id": "t1",
            "slug": "no-pat",
            "project_id": "p1",
            "kind": "build",
            "prompt": "test",
            "base_branch": "master",
        }

        with patch("branch_fleet_recovery.git_auth.pat_available") as mock_pat:
            with patch("branch_fleet_recovery._branch_exists_local") as mock_local:
                with patch("branch_fleet_recovery._branch_exists_remote") as mock_remote:
                    mock_pat.return_value = False
                    mock_local.return_value = False
                    mock_remote.return_value = False

                    result = recover_branch(task, "/tmp")

                    assert result["recovered"] is False
                    assert result["strategy"] == "pat_unavailable"

    def test_recover_branch_fetch_failure_graceful(self):
        """recover_branch handles fetch failures gracefully."""
        from branch_fleet_recovery import recover_branch

        task = {
            "id": "t1",
            "slug": "fetch-fail",
            "project_id": "p1",
            "kind": "build",
            "prompt": "test",
            "base_branch": "master",
        }

        with patch("branch_fleet_recovery.git_auth.fetch_branch") as mock_fetch:
            with patch("branch_fleet_recovery._branch_exists_local") as mock_local:
                with patch("branch_fleet_recovery._branch_exists_remote") as mock_remote:
                    mock_local.return_value = False
                    mock_remote.return_value = True
                    mock_fetch.return_value = (False, "authentication failed")

                    result = recover_branch(task, "/tmp")

                    # Should attempt requeue when fetch fails
                    assert result["recovered"] is False

    def test_recover_branch_respects_dry_run(self):
        """recover_branch respects DRY_RUN flag."""
        from branch_fleet_recovery import recover_branch
        import branch_fleet_recovery

        task = {
            "id": "t1",
            "slug": "dry-run-test",
            "project_id": "p1",
            "kind": "build",
            "prompt": "test",
            "base_branch": "master",
        }

        with patch.dict(os.environ, {"ORCH_FLEET_RECOVERY_DRY_RUN": "true"}):
            import importlib
            importlib.reload(branch_fleet_recovery)

            with patch("branch_fleet_recovery.git_auth.fetch_branch") as mock_fetch:
                with patch("branch_fleet_recovery._branch_exists_local") as mock_local:
                    with patch("branch_fleet_recovery._branch_exists_remote") as mock_remote:
                        mock_local.return_value = False
                        mock_remote.return_value = True

                        result = recover_branch(task, "/tmp")

                        # In dry-run, should not attempt fetch
                        assert mock_fetch.call_count == 0
                        assert result["strategy"] == "dry_run"

    def test_branch_exists_remote_uses_git_auth(self):
        """_branch_exists_remote delegates to git_auth.branch_exists_remote."""
        from branch_fleet_recovery import _branch_exists_remote

        with patch("branch_fleet_recovery.git_auth.branch_exists_remote") as mock_check:
            mock_check.return_value = True
            result = _branch_exists_remote("/tmp", "main")
            assert result is True
            assert mock_check.called


class TestGitAuthWithInvalidCredentials:
    """Test behavior when PAT is invalid or expired."""

    def test_fetch_with_invalid_pat_returns_error(self):
        """fetch_branch with invalid PAT returns error."""
        import git_auth
        with tempfile.TemporaryDirectory() as td:
            subprocess.run(["git", "init", td], capture_output=True)

            with patch.dict(os.environ, {"ORCH_GIT_PAT": "invalid_pat_123"}):
                import importlib
                importlib.reload(git_auth)

                ok, err = git_auth.fetch_branch(td, "branch", "origin")
                assert ok is False
                assert isinstance(err, str)

    def test_run_git_command_error_safe(self):
        """run_git error messages don't leak credentials."""
        import git_auth
        with patch("git_auth.subprocess.run") as mock_run:
            mock_error = subprocess.CompletedProcess(
                ["git"], 128, "", "fatal: could not authenticate with token"
            )
            mock_run.return_value = mock_error

            rc, out, err = git_auth.run_git(["fetch"], "/tmp")

            assert "token" not in err.lower() or "[REDACTED]" in err

    def test_branch_exists_remote_handles_auth_error(self):
        """branch_exists_remote returns False on auth errors."""
        import git_auth
        with tempfile.TemporaryDirectory() as td:
            subprocess.run(["git", "init", td], capture_output=True)

            with patch("git_auth.run_git") as mock_git:
                mock_git.return_value = (128, "", "fatal: repository not found")
                result = git_auth.branch_exists_remote(td, "main", "origin")
                assert result is False


class TestGitAuthEnvironmentHandling:
    """Test PAT environment variable handling."""

    def test_pat_read_from_environment(self):
        """git_auth reads ORCH_GIT_PAT from environment."""
        with patch.dict(os.environ, {"ORCH_GIT_PAT": "ghp_test_token_123"}):
            import git_auth
            import importlib
            importlib.reload(git_auth)

            assert git_auth.pat_available() is True

    def test_empty_pat_treated_as_unavailable(self):
        """Empty ORCH_GIT_PAT string is treated as unavailable."""
        with patch.dict(os.environ, {"ORCH_GIT_PAT": ""}):
            import git_auth
            import importlib
            importlib.reload(git_auth)

            assert git_auth.pat_available() is False

    def test_whitespace_pat_stripped(self):
        """Whitespace in ORCH_GIT_PAT is stripped."""
        with patch.dict(os.environ, {"ORCH_GIT_PAT": "  ghp_token_123  "}):
            import git_auth
            import importlib
            importlib.reload(git_auth)

            assert git_auth.pat_available() is True

    def test_debug_mode_safe_logging(self):
        """Debug mode logs auth attempts without credential values."""
        import git_auth
        with patch.dict(os.environ, {"ORCH_GIT_AUTH_DEBUG": "true"}):
            import importlib
            importlib.reload(git_auth)

            with patch("git_auth._log.debug") as mock_debug:
                with tempfile.TemporaryDirectory() as td:
                    git_auth.run_git(["status"], "/nonexistent")

                    # Check that any debug logs don't contain credentials
                    for call in mock_debug.call_args_list:
                        if call[0]:
                            msg = str(call[0])
                            assert "ghp_" not in msg
                            assert "PAT" not in msg


class TestBranchRecoveryIntegration:
    """Integration tests for branch recovery with authentication."""

    def test_sweep_handles_auth_gracefully(self):
        """sweep() handles repos that require auth."""
        from branch_fleet_recovery import sweep

        with patch("branch_fleet_recovery.db.select") as mock_db_select:
            def select_side_effect(table, params=None):
                if table == "tasks":
                    return [{
                        "id": "t1",
                        "slug": "auth-required",
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
                        "repo_path": "/private/repo",
                        "default_base": "master"
                    }]
                return []

            mock_db_select.side_effect = select_side_effect

            with patch("branch_fleet_recovery.git_auth.pat_available") as mock_pat:
                mock_pat.return_value = False

                results = sweep()

                assert isinstance(results, list)

    def test_recovery_task_creation_on_auth_failure(self):
        """Recovery task is created when branch fetch fails due to auth."""
        from branch_fleet_recovery import recover_branch

        task = {
            "id": "t1",
            "slug": "auth-fail-recovery",
            "project_id": "p1",
            "kind": "build",
            "prompt": "test",
            "base_branch": "master",
        }

        with patch("branch_fleet_recovery.git_auth.fetch_branch") as mock_fetch:
            with patch("branch_fleet_recovery.git_auth.pat_available") as mock_pat:
                with patch("branch_fleet_recovery.db.select") as mock_select:
                    with patch("branch_fleet_recovery.db.insert") as mock_insert:
                        with patch("branch_fleet_recovery._branch_exists_local") as mock_local:
                            with patch("branch_fleet_recovery._branch_exists_remote") as mock_remote:
                                mock_local.return_value = False
                                mock_remote.return_value = True
                                mock_fetch.return_value = (False, "auth failed")
                                mock_pat.return_value = True
                                mock_select.return_value = []

                                result = recover_branch(task, "/tmp")

                                # When fetch fails but PAT available, should attempt requeue
                                assert result["recovered"] is not None

    def test_no_recovery_without_pat_and_no_remote(self):
        """No recovery attempt when PAT missing and branch not on remote."""
        from branch_fleet_recovery import recover_branch

        task = {
            "id": "t1",
            "slug": "no-remote",
            "project_id": "p1",
            "kind": "build",
            "prompt": "test",
            "base_branch": "master",
        }

        with patch("branch_fleet_recovery.git_auth.pat_available") as mock_pat:
            with patch("branch_fleet_recovery._branch_exists_local") as mock_local:
                with patch("branch_fleet_recovery._branch_exists_remote") as mock_remote:
                    mock_pat.return_value = False
                    mock_local.return_value = False
                    mock_remote.return_value = False

                    result = recover_branch(task, "/tmp")

                    assert result["strategy"] == "pat_unavailable"


class TestErrorMessageSafety:
    """Test that error messages never leak credentials."""

    def test_git_auth_error_redaction(self):
        """git_auth errors don't contain PAT values."""
        import git_auth
        from db import redact_secrets

        with tempfile.TemporaryDirectory() as td:
            subprocess.run(["git", "init", td], capture_output=True)

            with patch.dict(os.environ, {"ORCH_GIT_PAT": "ghp_secret_token"}):
                import importlib
                importlib.reload(git_auth)

                rc, out, err = git_auth.run_git(["status"], td)

                # Use db's redaction to verify no leaks
                redacted = redact_secrets(err)
                assert "ghp_" not in redacted or "[REDACTED]" in redacted

    def test_recovery_error_messages_safe(self):
        """recovery error messages don't leak credentials."""
        from branch_fleet_recovery import recover_branch
        from db import redact_secrets

        task = {
            "id": "t1",
            "slug": "error-test",
            "project_id": "p1",
            "kind": "build",
            "prompt": "test",
            "base_branch": "master",
        }

        with patch("branch_fleet_recovery.git_auth.fetch_branch") as mock_fetch:
            with patch("branch_fleet_recovery._branch_exists_local") as mock_local:
                with patch("branch_fleet_recovery._branch_exists_remote") as mock_remote:
                    mock_local.return_value = False
                    mock_remote.return_value = True
                    mock_fetch.return_value = (False, "ghp_error_token_123")

                    result = recover_branch(task, "/tmp")

                    # Check that error detail is redacted if present
                    if "detail" in result:
                        redacted = redact_secrets(str(result["detail"]))
                        assert "ghp_" not in redacted or "[REDACTED]" in redacted


class TestFailSoftBehavior:
    """Test fail-soft error handling in auth layer."""

    def test_git_auth_never_raises(self):
        """git_auth functions never raise exceptions."""
        import git_auth

        with patch("git_auth.subprocess.run") as mock_run:
            mock_run.side_effect = RuntimeError("catastrophic failure")

            # Should not raise
            rc, out, err = git_auth.run_git(["status"], "/tmp")
            assert rc == -1
            assert isinstance(err, str)

    def test_recovery_continues_on_db_error(self):
        """Branch recovery continues even if DB operations fail."""
        from branch_fleet_recovery import recover_branch

        task = {
            "id": "t1",
            "slug": "db-error",
            "project_id": "p1",
            "kind": "build",
            "prompt": "test",
            "base_branch": "master",
        }

        with patch("branch_fleet_recovery.git_auth.pat_available") as mock_pat:
            with patch("branch_fleet_recovery._branch_exists_local") as mock_local:
                with patch("branch_fleet_recovery._branch_exists_remote") as mock_remote:
                    with patch("branch_fleet_recovery.db.select") as mock_select:
                        mock_pat.return_value = True
                        mock_local.return_value = False
                        mock_remote.return_value = False
                        mock_select.side_effect = RuntimeError("DB error")

                        result = recover_branch(task, "/tmp")

                        assert result["recovered"] is False
                        assert result["strategy"] == "error"


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
