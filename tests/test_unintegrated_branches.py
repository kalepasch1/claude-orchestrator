"""A branch the merge train silently skips must be reported, not averaged away.

merge_stall_monitor's only signal was fleet-wide: 0 MERGED in N hours. A single
agent branch that reaches origin and is never landed -- the failure behind every
`recover-missing-branch` card in the queue -- kept the monitor green, because
other branches were still merging. `unintegrated_agent_branches` adds the
per-branch check. These tests run against a real throwaway git repo; nothing is
mocked, because the bug being guarded is in the git reachability question.
"""
import os
import subprocess
import sys
import time

import pytest

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner")
)


@pytest.fixture()
def monitor(monkeypatch):
    """Import the module with db stubbed -- these tests never touch Supabase."""
    import types

    stub = types.ModuleType("db")
    stub.select = lambda *a, **k: []
    stub.insert = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "db", stub)
    import importlib
    import merge_stall_monitor
    return importlib.reload(merge_stall_monitor)


def _run(args, cwd):
    subprocess.check_call(["git"] + args, cwd=cwd, stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL)


def _commit(repo, name, message, age_days=0):
    (repo / name).write_text(message)
    _run(["add", "-A"], repo)
    env = os.environ.copy()
    if age_days:
        stamp = time.strftime(
            "%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - age_days * 86400)
        )
        env["GIT_AUTHOR_DATE"] = stamp
        env["GIT_COMMITTER_DATE"] = stamp
    subprocess.check_call(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid",
         "commit", "--no-verify", "-m", message],
        cwd=repo, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


@pytest.fixture()
def repo(tmp_path):
    """A clone with an origin remote, an orchestrator/dev, and agent branches."""
    bare = tmp_path / "origin.git"
    _run(["init", "--bare", "-b", "master", str(bare)], tmp_path)

    work = tmp_path / "work"
    work.mkdir()
    _run(["init", "-b", "master"], work)
    _run(["remote", "add", "origin", str(bare)], work)
    _commit(work, "README", "base")
    _run(["push", "-q", "origin", "master"], work)
    _run(["push", "-q", "origin", "master:orchestrator/dev"], work)
    _run(["fetch", "-q", "origin"], work)
    return work


def test_no_agent_branches_is_not_a_stall(monitor, repo):
    assert monitor.unintegrated_agent_branches(str(repo), min_age_hours=0) == []


def test_landed_branch_is_not_reported(monitor, repo):
    """A branch already reachable from orchestrator/dev has been integrated."""
    _run(["checkout", "-q", "-b", "agent/landed"], repo)
    _commit(repo, "a.txt", "landed work", age_days=3)
    _run(["push", "-q", "origin", "HEAD:agent/landed"], repo)
    _run(["push", "-q", "origin", "HEAD:orchestrator/dev"], repo)
    _run(["fetch", "-q", "origin"], repo)

    assert monitor.unintegrated_agent_branches(str(repo), min_age_hours=0) == []


def test_skipped_branch_is_reported(monitor, repo):
    _run(["checkout", "-q", "-b", "agent/skipped"], repo)
    _commit(repo, "b.txt", "work the train never took", age_days=3)
    _run(["push", "-q", "origin", "HEAD:agent/skipped"], repo)
    _run(["fetch", "-q", "origin"], repo)

    stalled = monitor.unintegrated_agent_branches(str(repo), min_age_hours=0)

    assert [b["branch"] for b in stalled] == ["origin/agent/skipped"]
    assert stalled[0]["age_hours"] > 70          # ~3 days


def test_a_recent_branch_is_given_time_to_land(monitor, repo):
    """The train is asynchronous; a just-pushed branch is not yet a problem."""
    _run(["checkout", "-q", "-b", "agent/fresh"], repo)
    _commit(repo, "c.txt", "just pushed")
    _run(["push", "-q", "origin", "HEAD:agent/fresh"], repo)
    _run(["fetch", "-q", "origin"], repo)

    assert monitor.unintegrated_agent_branches(str(repo), min_age_hours=6) == []
    assert monitor.unintegrated_agent_branches(str(repo), min_age_hours=0)


def test_results_are_sorted_oldest_first(monitor, repo):
    for name, age in (("agent/old", 10), ("agent/newer", 2), ("agent/middle", 5)):
        _run(["checkout", "-q", "master"], repo)
        _run(["checkout", "-q", "-b", name], repo)
        _commit(repo, f"{name.replace('/', '_')}.txt", name, age_days=age)
        _run(["push", "-q", "origin", f"HEAD:{name}"], repo)
    _run(["fetch", "-q", "origin"], repo)

    stalled = monitor.unintegrated_agent_branches(str(repo), min_age_hours=0)
    assert [b["branch"] for b in stalled] == [
        "origin/agent/old", "origin/agent/middle", "origin/agent/newer",
    ]


def test_only_agent_branches_are_scanned(monitor, repo):
    _run(["checkout", "-q", "-b", "hotfix/not-an-agent-branch"], repo)
    _commit(repo, "d.txt", "hotfix", age_days=9)
    _run(["push", "-q", "origin", "HEAD:hotfix/not-an-agent-branch"], repo)
    _run(["fetch", "-q", "origin"], repo)

    assert monitor.unintegrated_agent_branches(str(repo), min_age_hours=0) == []


# --- fail-soft ------------------------------------------------------------

def test_missing_integration_branch_returns_empty_not_raise(monitor, repo):
    assert monitor.unintegrated_agent_branches(
        str(repo), integration_branch="does/not/exist", min_age_hours=0
    ) == []


def test_a_non_repo_path_returns_empty_not_raise(monitor, tmp_path):
    assert monitor.unintegrated_agent_branches(str(tmp_path), min_age_hours=0) == []


def test_git_helper_is_fail_soft(monitor, tmp_path):
    assert monitor._git(["rev-parse", "--verify", "nope"], str(tmp_path), quiet=True) is None


# --- wiring ---------------------------------------------------------------

def test_check_reports_branches_even_when_the_fleet_is_not_stalled(monitor, repo, monkeypatch):
    """The case that used to read as a clean 'ok'."""
    _run(["checkout", "-q", "-b", "agent/skipped"], repo)
    _commit(repo, "e.txt", "orphan", age_days=4)
    _run(["push", "-q", "origin", "HEAD:agent/skipped"], repo)
    _run(["fetch", "-q", "origin"], repo)

    monkeypatch.setattr(monitor, "_backlog_size", lambda: 0)
    monkeypatch.setattr(monitor, "UNINTEGRATED_ALERT_HOURS", 0.0)

    result = monitor.check(repo=str(repo))

    assert result["status"] == "ok"
    assert [b["branch"] for b in result["unintegrated_branches"]] == ["origin/agent/skipped"]


def test_check_stays_fail_soft(monitor, monkeypatch):
    def boom():
        raise RuntimeError("supabase down")

    monkeypatch.setattr(monitor, "_backlog_size", boom)
    result = monitor.check(repo=".")
    assert result["status"] == "error"
    assert "supabase down" in result["error"]
