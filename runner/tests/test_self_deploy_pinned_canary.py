"""The release canary must verify the candidate commit, not the live tree.

Before this, canary_gate ran pytest in the working tree the fleet keeps committing to.
A four-minute gate therefore verified a moving target: files changed mid-run, uncommitted
cruft (conflict markers, a half-applied merge) was read as if it were the candidate, and
contention from that same tree's workers pushed per-test timeouts over the line. Observed
2026-08-18: the identical 11-file critical set took 233s in the live tree (one 120s
timeout, gate red) and 13s in a clean worktree (all green).
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


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A real repo with two commits and a DIRTY working tree."""
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q", "-b", "master")
    _git(r, "config", "user.email", "t@example.com")
    _git(r, "config", "user.name", "T")
    (r / "runner").mkdir()
    (r / "runner" / "mod.py").write_text("VALUE = 1\n")
    _git(r, "add", "-A"); _git(r, "commit", "-qm", "base")
    base = _git(r, "rev-parse", "HEAD").stdout.strip()
    (r / "runner" / "mod.py").write_text("VALUE = 2\n")
    _git(r, "add", "-A"); _git(r, "commit", "-qm", "candidate")
    head = _git(r, "rev-parse", "HEAD").stdout.strip()
    # ...and the fleet keeps writing while the gate runs:
    (r / "runner" / "mod.py").write_text("VALUE = 3   # uncommitted, mid-flight\n")
    (r / "runner" / "cruft.py").write_text("<<<<<<< HEAD\n")
    monkeypatch.setattr(self_deploy, "CANARY_PINNED", True)
    monkeypatch.setattr(self_deploy, "CANARY_WORKTREE_DIR", str(tmp_path / "pin"))
    return {"path": str(r), "base": base, "head": head}


def _record_stages(monkeypatch, results=None):
    """Replace the gate stages with recorders; return the list of (label, workdir)."""
    seen = []
    outcomes = list(results or [])

    def fake(label, cmd, workdir, timeout):
        seen.append((label, workdir))
        return outcomes.pop(0) if outcomes else True

    monkeypatch.setattr(self_deploy, "_run_gate_stage", fake)
    monkeypatch.setattr(self_deploy, "_selected_tests", lambda w, c: ["runner/tests/x.py"])
    return seen


def test_pin_checkout_sees_the_commit_not_the_dirty_live_tree(repo):
    pinned = self_deploy.pin_checkout(repo["path"], repo["head"])
    assert pinned, "a clean checkout must be obtainable"
    try:
        assert open(os.path.join(pinned, "runner", "mod.py")).read() == "VALUE = 2\n"
        assert not os.path.exists(os.path.join(pinned, "runner", "cruft.py")), \
            "uncommitted cruft in the live tree must not reach the gate"
    finally:
        self_deploy.unpin(repo["path"], pinned)
    assert not os.path.exists(pinned)
    assert pinned not in _git(repo["path"], "worktree", "list").stdout


def test_every_gate_stage_runs_inside_the_pin(repo, monkeypatch):
    seen = _record_stages(monkeypatch)

    assert self_deploy.canary_gate(repo["path"], repo["base"], repo["head"]) is True

    assert len(seen) == 3, [s[0] for s in seen]
    workdirs = {w for _label, w in seen}
    assert len(workdirs) == 1
    workdir = workdirs.pop()
    assert workdir != repo["path"], "the gate must not run in the mutating live tree"
    assert not os.path.exists(workdir), "the pin must be removed when the gate finishes"


def test_the_pin_is_removed_even_when_a_stage_fails(repo, monkeypatch):
    seen = _record_stages(monkeypatch, results=[True, True, False])

    assert self_deploy.canary_gate(repo["path"], repo["base"], repo["head"]) is False

    workdir = seen[0][1]
    assert not os.path.exists(workdir)
    assert workdir not in _git(repo["path"], "worktree", "list").stdout


def test_pinning_can_be_disabled(repo, monkeypatch):
    monkeypatch.setattr(self_deploy, "CANARY_PINNED", False)
    seen = _record_stages(monkeypatch)

    assert self_deploy.canary_gate(repo["path"], repo["base"], repo["head"]) is True
    assert {w for _l, w in seen} == {repo["path"]}


def test_a_pin_that_cannot_be_created_falls_back_to_the_live_tree(repo, monkeypatch):
    """Refusing to gate because a worktree failed would be a NEW way to stall the fleet."""
    real_git = self_deploy._git

    def no_worktrees(r, args, timeout=None):
        if args and args[0] == "worktree" and args[1] == "add":
            return subprocess.CompletedProcess(args, 128, "", "fatal: cannot create worktree")
        return real_git(r, args, timeout)

    monkeypatch.setattr(self_deploy, "_git", no_worktrees)
    seen = _record_stages(monkeypatch)

    assert self_deploy.canary_gate(repo["path"], repo["base"], repo["head"]) is True
    assert {w for _l, w in seen} == {repo["path"]}


def test_gate_output_keeps_both_ends_so_failures_stay_classifiable(monkeypatch):
    monkeypatch.setattr(self_deploy, "GATE_LOG_HEAD", 10)
    monkeypatch.setattr(self_deploy, "GATE_LOG_TAIL", 10)
    text = "FAILED the-real-cause" + ("x" * 500) + "idle daemon thread stack"

    out = self_deploy._excerpt(text)

    assert out.startswith("FAILED the")
    assert out.endswith("read stack")
    assert "omitted" in out


def test_short_output_is_not_truncated():
    assert self_deploy._excerpt("  boom  ") == "boom"


def test_both_worktree_removal_names_work(repo):
    """unpin() and remove_worktree() are the same operation under two names.

    The body lives in unpin() on purpose: a function whose body shrinks to one delegating
    call reads as `symbol/gutted` to the merge regression guard, and a gutted unpin()
    blocked the fleet's automatic origin reconcile until it was reshaped.
    """
    for remove in (self_deploy.unpin, self_deploy.remove_worktree):
        pinned = self_deploy.pin_checkout(repo["path"], repo["head"])
        assert pinned and os.path.exists(pinned)
        remove(repo["path"], pinned)
        assert not os.path.exists(pinned)
        assert pinned not in _git(repo["path"], "worktree", "list").stdout
