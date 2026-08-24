"""A requeue must be grounded in real repo state, not assumed.

apply_recovery_action records `repo_ok` and `branch_exists` on a requeue so a
missing worktree or a lost agent branch is RECORDED rather than assumed — the
difference between "requeue and reuse the existing branch" and "requeue and
silently start from nothing". That grounding had no test at all: the existing
suite covers the fail-soft return value and the stats counters, but never
asserts what a requeue actually observes about the repo.

Every test builds a throwaway git repo under tmp_path. Nothing runs git against
this checkout.
"""
import os
import subprocess
import sys

import pytest

_RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _RUNNER not in sys.path:
    sys.path.insert(0, _RUNNER)

import stale_backlog_recovery as sbr  # noqa: E402


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo)] + list(args),
                          capture_output=True, text=True, timeout=30)


@pytest.fixture()
def repo(tmp_path):
    """A one-commit repo carrying the branch agent/live-slug."""
    _git(tmp_path, "init", "-b", "master")
    _git(tmp_path, "config", "user.name", "t")
    _git(tmp_path, "config", "user.email", "t@t")
    (tmp_path / "f.txt").write_text("x\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "seed")
    _git(tmp_path, "branch", "agent/live-slug")
    return tmp_path


@pytest.fixture(autouse=True)
def clean_state():
    sbr.invalidate()
    yield
    sbr.invalidate()


def _last_applied():
    return sbr._applied[-1]


def _requeue(slug):
    return {"task_id": "t-1", "slug": slug, "action": "requeue"}


class TestRequeueGrounding:
    def test_surviving_branch_is_recorded_as_existing(self, repo):
        assert sbr.apply_recovery_action(_requeue("live-slug"), str(repo)) is True
        record = _last_applied()
        assert record["repo_ok"] is True
        assert record["branch_exists"] is True

    def test_lost_branch_is_recorded_as_missing(self, repo):
        """The case that matters: requeue must not assume the work survived."""
        assert sbr.apply_recovery_action(_requeue("vanished-slug"), str(repo)) is True
        record = _last_applied()
        assert record["repo_ok"] is True
        assert record["branch_exists"] is False

    def test_branch_lookup_is_namespaced_under_agent(self, repo):
        """A bare branch of the same name must not be mistaken for agent/<slug>."""
        _git(repo, "branch", "bare-slug")
        sbr.apply_recovery_action(_requeue("bare-slug"), str(repo))
        assert _last_applied()["branch_exists"] is False

    def test_non_git_directory_is_recorded_as_not_ok(self, tmp_path):
        plain = tmp_path / "not-a-repo"
        plain.mkdir()
        assert sbr.apply_recovery_action(_requeue("live-slug"), str(plain)) is True
        record = _last_applied()
        assert record["repo_ok"] is False
        # No branch claim is made when the repo could not be read at all.
        assert "branch_exists" not in record

    def test_slugless_requeue_makes_no_branch_claim(self, repo):
        sbr.apply_recovery_action({"task_id": "t-1", "action": "requeue"}, str(repo))
        record = _last_applied()
        assert record["repo_ok"] is True
        assert "branch_exists" not in record

    def test_the_original_action_is_not_mutated(self, repo):
        action = _requeue("live-slug")
        sbr.apply_recovery_action(action, str(repo))
        assert "repo_ok" not in action
        assert "branch_exists" not in action


class TestNonRequeueActions:
    @pytest.mark.parametrize("kind", ["mark_stale", "cancel"])
    def test_no_repo_probe_is_made(self, repo, kind):
        """Only a requeue depends on repo state; the others must not pay for it."""
        action = {"task_id": "t-1", "slug": "live-slug", "action": kind}
        assert sbr.apply_recovery_action(action, str(repo)) is True
        record = _last_applied()
        assert "repo_ok" not in record
        assert "branch_exists" not in record

    def test_non_requeue_works_without_a_repo_at_all(self):
        action = {"task_id": "t-1", "slug": "s", "action": "cancel"}
        assert sbr.apply_recovery_action(action, "/nonexistent-path-xyz") is True


class TestRejectionAndFailSoft:
    @pytest.mark.parametrize("action", [
        None, "requeue", 7, {}, {"action": "explode"}, {"task_id": "t"},
    ])
    def test_invalid_actions_are_rejected_without_recording(self, action):
        assert sbr.apply_recovery_action(action) is False
        assert sbr.stats()["applied_total"] == 0

    def test_a_broken_git_is_fail_soft_not_an_exception(self, repo, monkeypatch):
        def boom(*a, **k):
            raise OSError("git not found")

        monkeypatch.setattr(sbr.subprocess, "run", boom)
        assert sbr.apply_recovery_action(_requeue("live-slug"), str(repo)) is False
        assert sbr.stats()["applied_total"] == 0

    def test_a_git_timeout_is_fail_soft(self, repo, monkeypatch):
        def slow(*a, **k):
            raise subprocess.TimeoutExpired(cmd="git", timeout=15)

        monkeypatch.setattr(sbr.subprocess, "run", slow)
        assert sbr.apply_recovery_action(_requeue("live-slug"), str(repo)) is False
