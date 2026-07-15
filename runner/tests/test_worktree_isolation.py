import os
import subprocess
import sys

import pytest

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RUNNER not in sys.path:
    sys.path.insert(0, RUNNER)

import repo_lock
import worktree_isolation


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "app"
    path.mkdir()
    git(path, "init", "-b", "main")
    git(path, "config", "user.email", "test@example.com")
    git(path, "config", "user.name", "Test")
    (path / "kept.txt").write_text("primary\n")
    git(path, "add", "kept.txt")
    git(path, "commit", "-m", "initial")
    return path


def test_setup_failure_never_returns_primary_checkout(repo, tmp_path):
    broken = tmp_path / "broken.sh"
    broken.write_text("#!/bin/sh\nexit 9\n")
    broken.chmod(0o755)

    with pytest.raises(worktree_isolation.WorktreeIsolationError, match="setup failed"):
        worktree_isolation.ensure_task_worktree(str(repo), "task-1", "main", str(broken))

    assert (repo / "kept.txt").read_text() == "primary\n"
    assert not (repo.parent / "app-wt" / "task-1").exists()


def test_valid_worktree_is_reused_without_cleaning_partial_work(repo, tmp_path):
    wt = repo.parent / "app-wt" / "task-2"
    wt.parent.mkdir()
    git(repo, "worktree", "add", "-b", "agent/task-2", str(wt), "main")
    (wt / "partial.txt").write_text("recover me\n")

    result = worktree_isolation.ensure_task_worktree(
        str(repo), "task-2", "main", str(tmp_path / "not-called")
    )

    assert result == os.path.realpath(wt)
    assert (wt / "partial.txt").read_text() == "recover me\n"


def test_validation_rejects_wrong_branch(repo):
    wt = repo.parent / "app-wt" / "task-3"
    wt.parent.mkdir()
    git(repo, "worktree", "add", "-b", "wrong-branch", str(wt), "main")

    with pytest.raises(worktree_isolation.WorktreeIsolationError, match="branch mismatch"):
        worktree_isolation.validate_task_worktree(str(repo), "task-3", str(wt))


def test_repo_lock_fails_closed_when_lock_directory_is_unavailable(repo, monkeypatch):
    monkeypatch.setattr(repo_lock, "LOCK_DIR", str(repo / "kept.txt" / "locks"))
    with repo_lock.hold(str(repo), timeout=0.01) as acquired:
        assert acquired is False
