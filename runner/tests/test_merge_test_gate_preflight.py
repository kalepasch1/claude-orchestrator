#!/usr/bin/env python3
"""Tests for the branch preflight in merge_test_gate.py.

Why these exist. The gate's first step was `git diff base...branch`, wrapped in
`_find_changed_modules`, which returns [] on *every* failure path — bad repo
path, non-zero exit, timeout, exception. `check_merge` read [] as
`{"passed": True, "reason": "no changed modules"}`.

So the three states below were indistinguishable to the gate, and all three
came back green:

    branch exists and changed nothing   -> []   -> passed
    branch does not exist at all        -> []   -> passed
    repo isn't checked out on this host -> []   -> passed

The middle one is the failure this gate exists to prevent: a task marked DONE
whose agent/ branch was never pushed sails through the merge gate. The first
and third must keep passing — an empty branch is legitimately mergeable, and a
host without the checkout must not stall the fleet.
"""
import os
import subprocess
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test")

import merge_test_gate as gate  # noqa: E402


def _git(repo, *args):
    """Run git with a clean env so inherited GIT_DIR can't redirect us."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.setdefault("HOME", repo)
    return subprocess.run(["git"] + list(args), cwd=repo, env=env,
                          capture_output=True, text=True, timeout=30)


@pytest.fixture(autouse=True)
def _no_shared_cache():
    """branch_availability_check memoises by (repo, branch) for 120s.

    Every test here builds a fresh tempdir so collisions are unlikely, but the
    cache is process-global and these tests assert on absence — clear it rather
    than depend on tempdir uniqueness.
    """
    try:
        import branch_availability_check as bac
        bac._cache.clear()
        yield
        bac._cache.clear()
    except Exception:
        yield


def _repo(base="master"):
    """A git repo with one commit on `base` and a runner/ dir."""
    d = tempfile.mkdtemp()
    _git(d, "init", "-q", "-b", base)
    _git(d, "config", "user.email", "t@example.com")
    _git(d, "config", "user.name", "t")
    os.makedirs(os.path.join(d, "runner"), exist_ok=True)
    with open(os.path.join(d, "runner", "widget.py"), "w") as fh:
        fh.write("VALUE = 1\n")
    _git(d, "add", "-A")
    _git(d, "commit", "-q", "-m", "init")
    return d


def _branch(repo, name, content=None, path="runner/widget.py"):
    """Create `name` off the current HEAD, optionally rewriting a file on it."""
    _git(repo, "checkout", "-q", "-b", name)
    if content is not None:
        with open(os.path.join(repo, path), "w") as fh:
            fh.write(content)
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", f"work on {name}")
    _git(repo, "checkout", "-q", "-")
    return name


# --- the regression -------------------------------------------------------

def test_missing_task_branch_blocks_the_merge():
    """The whole point. A branch that was never pushed must not gate green."""
    repo = _repo()
    task = {"slug": "never-pushed", "base_branch": "master"}

    result = gate.check_merge(task, repo)

    assert result["passed"] is False, (
        "a task branch that does not exist reported a passing merge gate; "
        "this is the exact hole the preflight was added to close"
    )
    assert result["reason"] == "task branch missing"
    assert "agent/never-pushed" in result["preflight"]


def test_missing_base_branch_blocks_the_merge():
    repo = _repo()
    _branch(repo, "agent/has-branch", content="VALUE = 2\n")
    task = {"slug": "has-branch", "base_branch": "no-such-base"}

    result = gate.check_merge(task, repo)

    assert result["passed"] is False
    assert result["reason"] == "base branch missing"


def test_conflicting_branch_blocks_the_merge():
    """`git merge-tree` reports the conflict without touching a worktree."""
    repo = _repo()
    _branch(repo, "agent/conflicting", content="VALUE = 'theirs'\n")
    # Move master over the same line so the two genuinely conflict.
    with open(os.path.join(repo, "runner", "widget.py"), "w") as fh:
        fh.write("VALUE = 'ours'\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "diverge master")

    task = {"slug": "conflicting", "base_branch": "master"}
    result = gate.check_merge(task, repo)

    if result.get("reason") == "merge conflict":
        assert result["passed"] is False
    else:
        # Older git without `merge-tree --write-tree` returns undetermined,
        # which must degrade to pass-through rather than a false block.
        assert result["passed"] is not False


# --- the states that must KEEP passing ------------------------------------

def test_existing_branch_with_no_changes_still_passes():
    """An empty branch is legitimately mergeable. Don't over-correct."""
    repo = _repo()
    _branch(repo, "agent/empty-but-real")
    task = {"slug": "empty-but-real", "base_branch": "master"}

    result = gate.check_merge(task, repo)

    assert result["passed"] is True
    assert result["reason"] == "no changed modules"


def test_absent_repo_checkout_degrades_to_pass_through():
    """Undetermined is not the same as bad. A host missing the clone must not
    block every merge in the fleet."""
    task = {"slug": "anything", "base_branch": "master"}

    result = gate.check_merge(task, "/nonexistent/repo/path")

    assert result["passed"] is True


def test_preflight_can_be_disabled_by_env(monkeypatch):
    """Kill switch, in case the preflight itself misbehaves in production."""
    repo = _repo()
    monkeypatch.setattr(gate, "PREFLIGHT_ENABLED", False)
    task = {"slug": "never-pushed", "base_branch": "master"}

    result = gate.check_merge(task, repo)

    assert result["passed"] is True


# --- helper-level tri-state contract --------------------------------------

def test_ref_exists_is_tristate():
    repo = _repo()
    assert gate._ref_exists(repo, "master") is True
    assert gate._ref_exists(repo, "definitely-not-a-ref") is False
    # No repo at all -> undetermined, NOT False. Collapsing this to False
    # would block every merge on a host without the checkout.
    assert gate._ref_exists("/nonexistent/repo/path", "master") is None


def test_blocked_merges_are_counted():
    repo = _repo()
    before = gate.stats()["blocked_missing_branch"]
    gate.check_merge({"slug": "never-pushed-2", "base_branch": "master"}, repo)
    assert gate.stats()["blocked_missing_branch"] == before + 1
