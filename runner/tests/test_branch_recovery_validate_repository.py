#!/usr/bin/env python3
"""Tests for branch_recovery.validate_repository (missing-branch recovery slice-3).

Covers the gap the slice names: recover_branch() could not tell a genuinely
lost branch apart from a repository it was never able to read (deleted repo,
expired/underscoped PAT, no remote), and reported both as
"all strategies exhausted".
"""
import os
import subprocess
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import branch_recovery


def _init_repo(path):
    """Create a git repo with one commit and no remote."""
    subprocess.run(["git", "init", "-q", path], capture_output=True)
    env = {**os.environ,
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    subprocess.run(["git", "-C", path, "commit", "--allow-empty", "-q", "-m", "init"],
                   capture_output=True, env=env)
    return path


class TestValidateRepository:
    def test_no_path(self):
        r = branch_recovery.validate_repository("")
        assert r["ok"] is False
        assert r["reason"] == "no_path"
        assert r["remediation"]

    def test_missing_directory(self):
        r = branch_recovery.validate_repository("/nonexistent/repo/path")
        assert r["ok"] is False
        assert r["reason"] == "missing_dir"
        assert "does not exist" in r["detail"]

    def test_directory_is_not_a_git_repo(self):
        with tempfile.TemporaryDirectory() as td:
            r = branch_recovery.validate_repository(td)
            assert r["ok"] is False
            assert r["reason"] == "not_a_repo"

    def test_repo_without_remote(self):
        with tempfile.TemporaryDirectory() as td:
            _init_repo(td)
            r = branch_recovery.validate_repository(td)
            assert r["ok"] is False
            assert r["reason"] == "no_remote"
            assert "remote add origin" in r["remediation"]

    def test_pat_denied_is_reported_as_unreachable(self):
        """A configured remote that refuses the credential is 'unreachable'."""
        with tempfile.TemporaryDirectory() as td:
            _init_repo(td)
            subprocess.run(["git", "-C", td, "remote", "add", "origin",
                            "https://github.com/example/private.git"],
                           capture_output=True)
            with patch.object(branch_recovery, "_git") as mock_git:
                def side_effect(repo, *args):
                    if args[0] == "rev-parse":
                        return 0, "true", ""
                    if args[0] == "remote":
                        return 0, "https://github.com/example/private.git", ""
                    if args[0] == "ls-remote":
                        return 128, "", "remote: Repository not found."
                    return -1, "", "unexpected"
                mock_git.side_effect = side_effect
                # Force the git fallback path so the assertion is about this module.
                with patch.dict(sys.modules, {"repo_access_healer": None}):
                    r = branch_recovery.validate_repository(td)
            assert r["ok"] is False
            assert r["reason"] == "unreachable"
            assert "PAT" in r["remediation"]

    def test_healthy_repo_ok(self):
        with tempfile.TemporaryDirectory() as td:
            _init_repo(td)
            subprocess.run(["git", "-C", td, "remote", "add", "origin", td],
                           capture_output=True)
            with patch("repo_access_healer.diagnose_repo") as mock_diag:
                mock_diag.return_value = (True, "repo accessible")
                r = branch_recovery.validate_repository(td)
            assert r["ok"] is True
            assert r["reason"] == "ok"
            assert r["remediation"] == ""

    def test_falls_back_when_healer_unimportable(self):
        """A broken/absent repo_access_healer must not break the preflight."""
        with tempfile.TemporaryDirectory() as td:
            _init_repo(td)
            subprocess.run(["git", "-C", td, "remote", "add", "origin", td],
                           capture_output=True)
            with patch.dict(sys.modules, {"repo_access_healer": None}):
                r = branch_recovery.validate_repository(td)
            # origin points at itself, so ls-remote succeeds
            assert r["ok"] is True


class TestRecoverBranchSurfacesRepoCause:
    def test_missing_repo_names_the_cause(self):
        r = branch_recovery.recover_branch("/nonexistent/repo", "agent/whatever")
        assert r["status"] == "unrecoverable"
        assert r["repo_reason"] == "missing_dir"
        assert r["remediation"]

    def test_unreachable_remote_not_reported_as_exhausted(self):
        """The regression: PAT failure used to read 'all strategies exhausted'."""
        with tempfile.TemporaryDirectory() as td:
            _init_repo(td)
            with patch.object(branch_recovery, "validate_repository") as mock_val:
                mock_val.return_value = {
                    "ok": False, "reason": "unreachable",
                    "detail": "remote: Repository not found.",
                    "remediation": "rotate the PAT",
                }
                r = branch_recovery.recover_branch(td, "agent/gone")
            assert r["status"] == "unrecoverable"
            assert r["repo_reason"] == "unreachable"
            assert "all strategies exhausted" not in r["action_taken"]
            assert "repository inaccessible" in r["action_taken"]

    def test_healthy_repo_still_reports_exhausted(self):
        """Behavior preserved: a readable repo with a truly lost branch is unchanged."""
        with tempfile.TemporaryDirectory() as td:
            _init_repo(td)
            with patch.object(branch_recovery, "validate_repository") as mock_val:
                mock_val.return_value = {"ok": True, "reason": "ok",
                                         "detail": "repo accessible", "remediation": ""}
                r = branch_recovery.recover_branch(td, "agent/genuinely-gone")
            assert r["status"] == "unrecoverable"
            assert "all strategies exhausted" in r["action_taken"]
            assert "repo_reason" not in r

    def test_repo_unreachable_counter_increments(self):
        before = branch_recovery.stats()["recover_repo_unreachable"]
        branch_recovery.recover_branch("/nonexistent/repo", "agent/x")
        assert branch_recovery.stats()["recover_repo_unreachable"] == before + 1


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
