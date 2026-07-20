import contextlib
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
import integration_runtime
import approval_merge


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "canonical"
    root.mkdir()
    git(root, "init", "-b", "main")
    git(root, "config", "user.email", "test@example.com")
    git(root, "config", "user.name", "Test")
    (root / "tracked.txt").write_text("one\n")
    git(root, "add", "tracked.txt")
    git(root, "commit", "-m", "initial")
    return root


def test_isolated_repo_is_detached_and_preserves_canonical(repo, tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_ORCH_HOME", str(tmp_path / "runtime"))
    before = integration_runtime.canonical_snapshot(str(repo))
    with integration_runtime.isolated_repo(str(repo), "test") as worktree:
        assert os.path.realpath(worktree) != os.path.realpath(repo)
        assert subprocess.run(
            ["git", "symbolic-ref", "-q", "HEAD"], cwd=worktree, capture_output=True
        ).returncode != 0
        git(worktree, "branch", "integration-test-ref")
    assert integration_runtime.canonical_snapshot(str(repo)) == before


def test_canonical_mutation_is_detected(repo, tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_ORCH_HOME", str(tmp_path / "runtime"))
    with pytest.raises(integration_runtime.CanonicalCheckoutMutationError):
        with integration_runtime.isolated_repo(str(repo), "test"):
            (repo / "tracked.txt").write_text("changed\n")


def test_dirty_persistent_slot_is_preserved_and_bypassed(repo, tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_ORCH_HOME", str(tmp_path / "runtime"))
    with integration_runtime.isolated_repo(str(repo), "first") as persistent:
        pass
    (Path(persistent) / "tracked.txt").write_text("interrupted integration\n")
    git(persistent, "add", "tracked.txt")

    with integration_runtime.isolated_repo(str(repo), "second") as replacement:
        assert os.path.realpath(replacement) != os.path.realpath(persistent)
        assert subprocess.run(
            ["git", "status", "--porcelain=v1"], cwd=replacement,
            capture_output=True, text=True, check=True,
        ).stdout == ""
        replacement_path = replacement

    # The evidence remains available for recovery, while the temporary bypass
    # is cleaned after the successful pass.
    assert (Path(persistent) / "tracked.txt").read_text() == "interrupted integration\n"
    assert not Path(replacement_path).exists()


def test_merge_and_release_share_one_global_lease(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_ORCH_HOME", str(tmp_path / "runtime"))
    entered = threading.Event()
    release = threading.Event()

    def holder():
        with integration_runtime.global_lease("merge_train") as acquired:
            assert acquired
            entered.set()
            release.wait(5)

    thread = threading.Thread(target=holder)
    thread.start()
    assert entered.wait(5)
    with integration_runtime.global_lease("release_train") as acquired:
        assert not acquired
    release.set()
    thread.join(5)
    assert not thread.is_alive()


def test_global_lease_does_not_mask_body_oserror(tmp_path, monkeypatch):
    """A transient DB error must escape normally and release the train lease."""
    monkeypatch.setenv("CLAUDE_ORCH_HOME", str(tmp_path / "runtime"))
    with pytest.raises(OSError, match="temporary database outage"):
        with integration_runtime.global_lease("merge_train") as acquired:
            assert acquired
            raise OSError("temporary database outage")

    with integration_runtime.global_lease("next_train") as acquired:
        assert acquired


def test_merge_is_global_but_release_is_project_isolated():
    runner = Path(__file__).parents[1]
    merge = (runner / "merge_train.py").read_text()
    release = (runner / "release_train.py").read_text()
    assert 'global_lease("merge_train"' in merge
    assert 'isolated_repo(repo_path, "merge_train")' in merge
    assert 'isolated_repo(repo, "release_train")' in release
    assert "ThreadPoolExecutor" in release
    assert 'global_lease("release_train"' not in release


def test_free_branch_never_removes_primary_when_called_from_linked_worktree(
    repo, tmp_path
):
    git(repo, "branch", "agent/stale")
    linked = tmp_path / "linked"
    git(repo, "worktree", "add", "--detach", str(linked), "main")
    git(repo, "checkout", "agent/stale")
    assert approval_merge._free_branch(str(linked), "agent/stale") is False
    assert repo.exists()
    assert git(repo, "branch", "--show-current").stdout.strip() == "agent/stale"
