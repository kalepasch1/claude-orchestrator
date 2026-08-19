"""self_deploy.reconcile_origin: merged-on-origin must become running-here.

The failure this locks down: self_deploy only ever compared the RUNNING commit to the
LOCAL head. The fleet commits directly to its own master, so local kept advancing while
PRs merged on origin were never pulled — self_deploy said "up-to-date" forever and every
merged PR sat on origin without executing. These tests pin the four outcomes, and in
particular that a conflicting divergence is REPORTED rather than force-resolved.
"""
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import self_deploy  # noqa: E402


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                          text=True, check=True)


def _cfg(repo):
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "commit.gpgsign", "false")


def _head(repo):
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def _commit(repo, name, body, message):
    (repo / name).write_text(body)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", message)


@pytest.fixture
def repos(tmp_path, monkeypatch):
    """A bare origin, a `seed` clone that publishes to it, and the `node` under test."""
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", "-b", "master", str(origin)],
                   check=True, capture_output=True)
    seed = tmp_path / "seed"
    subprocess.run(["git", "clone", str(origin), str(seed)], check=True, capture_output=True)
    _cfg(seed)
    _commit(seed, "base.txt", "base\n", "seed")
    _git(seed, "push", "-u", "origin", "master")
    node = tmp_path / "node"
    subprocess.run(["git", "clone", str(origin), str(node)], check=True, capture_output=True)
    _cfg(node)
    monkeypatch.setattr(self_deploy, "TRACK_ORIGIN", True)
    monkeypatch.setattr(self_deploy, "ORIGIN_REMOTE", "origin")
    monkeypatch.setattr(self_deploy, "ORIGIN_BRANCH", "master")
    return seed, node


def test_already_current_is_a_noop(repos):
    seed, node = repos
    before = _head(node)
    result = self_deploy.reconcile_origin(str(node))
    assert result["action"] == "already_current"
    assert result["ok"] is True
    assert result["behind"] == 0
    assert _head(node) == before


def test_node_purely_behind_fast_forwards_to_origin(repos):
    seed, node = repos
    _commit(seed, "merged_pr.txt", "shipped\n", "merged PR")
    _git(seed, "push", "origin", "master")

    result = self_deploy.reconcile_origin(str(node))

    assert result["action"] == "fast_forward"
    assert result["behind"] == 1
    # The whole point: the merged file is now present in the tree that self-deploy deploys.
    assert (node / "merged_pr.txt").exists()
    assert _head(node) == _head(seed)


def test_diverged_but_clean_absorbs_origin_without_losing_local_work(repos):
    seed, node = repos
    _commit(seed, "merged_pr.txt", "shipped\n", "merged PR")
    _git(seed, "push", "origin", "master")
    _commit(node, "local_work.txt", "direct-to-master\n", "fleet commit")
    local_head = _head(node)

    result = self_deploy.reconcile_origin(str(node))

    assert result["action"] == "merged"
    assert result["behind"] == 1
    assert (node / "merged_pr.txt").exists(), "origin work must arrive"
    assert (node / "local_work.txt").exists(), "local work must survive"
    for sha in (local_head, _head(seed)):
        subprocess.run(["git", "merge-base", "--is-ancestor", sha, _head(node)],
                       cwd=str(node), check=True, capture_output=True)


def test_conflicting_divergence_is_reported_never_force_resolved(repos, monkeypatch):
    seed, node = repos
    _commit(seed, "base.txt", "origin side\n", "origin edit")
    _git(seed, "push", "origin", "master")
    _commit(node, "base.txt", "node side\n", "node edit")
    before = _head(node)
    cards = []
    monkeypatch.setattr(self_deploy.db, "insert", lambda *a, **k: cards.append((a, k)))

    result = self_deploy.reconcile_origin(str(node))

    assert result["action"] == "conflicted"
    assert result["ok"] is False
    assert _head(node) == before, "the live head must not move on a conflict"
    assert (node / "base.txt").read_text() == "node side\n"
    assert "<<<<<<<" not in (node / "base.txt").read_text()
    assert _git(node, "status", "--porcelain").stdout.strip() == "", "no half-merged state"
    assert cards, "a conflicting divergence must be surfaced, not swallowed"


def test_tracking_can_be_disabled_and_then_touches_nothing(repos, monkeypatch):
    seed, node = repos
    _commit(seed, "merged_pr.txt", "shipped\n", "merged PR")
    _git(seed, "push", "origin", "master")
    before = _head(node)
    monkeypatch.setattr(self_deploy, "TRACK_ORIGIN", False)

    result = self_deploy.reconcile_origin(str(node))

    assert result["action"] == "disabled"
    assert _head(node) == before
    assert not (node / "merged_pr.txt").exists()


def test_maybe_deploy_reconciles_origin_before_judging_staleness(repos, monkeypatch):
    seed, node = repos
    _commit(seed, "merged_pr.txt", "shipped\n", "merged PR")
    _git(seed, "push", "origin", "master")
    monkeypatch.delenv("ORCH_BOOT_COMMIT", raising=False)

    result = self_deploy.maybe_deploy(str(node))

    assert result["origin"]["action"] == "fast_forward"
    assert (node / "merged_pr.txt").exists()
    # No boot marker in a scratch clone -> staleness is unknown, not falsely "healthy".
    assert result["reason"] == "up-to-date"
    assert result["unknown"] is True
