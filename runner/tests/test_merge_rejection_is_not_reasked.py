"""Six branches, merged and rolled back, then merged and rolled back again an hour later.

Read off master's reflog on 2026-09-04:

    05:35:48  merge agent/backlog-batch-beethoven-52d9da1
    05:35:52  reset: moving to af2ea939...            (four seconds later)
    ... four more branches, each merged and immediately reset ...
    06:31:45  merge agent/backlog-batch-beethoven-52d9da1     <- the same six branches
    06:31:49  reset: moving to af2ea939...               again, an hour later

auto_conflict_resolver._reject_merge is doing its job: the anti-regression gate found the
merge would destroy code, so the merge is undone and the branch deliberately kept. The
work is safe. What is not safe is the cost -- each round is a real merge, a full gate run
and a hard reset of the base branch -- for a question already answered.

The gate is a pure function of the two trees it compares, so re-running it on an
unchanged (branch tip, base tip) pair cannot return a different verdict. The moment
either side moves, the merge is attempted again.
"""
import json
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import auto_conflict_resolver as acr


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, timeout=60)


@pytest.fixture(autouse=True)
def ledger_in_tmp(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_ORCH_HOME", str(tmp_path / "home"))
    return tmp_path


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-b", "main")
    _git(r, "config", "user.email", "t@example.com")
    _git(r, "config", "user.name", "T")
    (r / "keep.py").write_text("def keep():\n    return 1\n")
    _git(r, "add", "-A")
    _git(r, "commit", "-m", "seed")
    # a branch that deletes the improvement -- exactly what the gate exists to refuse
    _git(r, "checkout", "-b", "agent/deleter")
    (r / "keep.py").write_text("# gone\n")
    _git(r, "commit", "-am", "removes keep()")
    _git(r, "checkout", "main")
    return str(r)


def _attempts(repo):
    """How many merge commits this repo has seen created, per its reflog."""
    out = _git(repo, "reflog", "show", "main", "--format=%gs").stdout or ""
    return sum(1 for line in out.splitlines() if line.startswith(("merge ", "commit (merge)")))


def test_the_same_rejection_is_not_re_attempted(repo, monkeypatch):
    """THE REGRESSION. Two passes over an unchanged pair must cost one merge, not two."""
    monkeypatch.setattr(acr, "_verify_merge", lambda *a, **k: "[net-deletion] keep.py")

    first = acr.resolve_branch(repo, "agent/deleter", "main")
    assert first["merged"] is False and "REGRESSION BLOCKED" in first["error"]
    after_first = _attempts(repo)

    second = acr.resolve_branch(repo, "agent/deleter", "main")
    assert second["merged"] is False
    assert "already refused" in second["error"], second["error"]
    assert _attempts(repo) == after_first, "the merge was attempted a second time"


def test_the_branch_is_still_preserved(repo, monkeypatch):
    """The refusal must never start deleting what the rollback exists to keep."""
    monkeypatch.setattr(acr, "_verify_merge", lambda *a, **k: "[net-deletion] keep.py")
    acr.resolve_branch(repo, "agent/deleter", "main")
    acr.resolve_branch(repo, "agent/deleter", "main")
    assert _git(repo, "rev-parse", "--verify", "agent/deleter").returncode == 0


def test_a_moved_branch_gets_a_fresh_answer(repo, monkeypatch):
    """A fixed branch must not inherit its predecessor's refusal."""
    monkeypatch.setattr(acr, "_verify_merge", lambda *a, **k: "[net-deletion] keep.py")
    acr.resolve_branch(repo, "agent/deleter", "main")

    _git(repo, "checkout", "agent/deleter")
    (open(os.path.join(repo, "keep.py"), "w")).write("def keep():\n    return 1\n")
    _git(repo, "commit", "-am", "put it back")
    _git(repo, "checkout", "main")

    monkeypatch.setattr(acr, "_verify_merge", lambda *a, **k: "")
    third = acr.resolve_branch(repo, "agent/deleter", "main")
    assert third["merged"] is True, third


def test_a_moved_base_gets_a_fresh_answer(repo, monkeypatch):
    monkeypatch.setattr(acr, "_verify_merge", lambda *a, **k: "[net-deletion] keep.py")
    acr.resolve_branch(repo, "agent/deleter", "main")
    before = _attempts(repo)

    open(os.path.join(repo, "other.py"), "w").write("x = 1\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "base advances")

    acr.resolve_branch(repo, "agent/deleter", "main")
    assert _attempts(repo) > before, "an advanced base must be re-tried"


def test_an_expired_refusal_is_re_tried(repo, monkeypatch):
    monkeypatch.setattr(acr, "_verify_merge", lambda *a, **k: "[net-deletion] keep.py")
    acr.resolve_branch(repo, "agent/deleter", "main")
    before = _attempts(repo)

    path = acr._reject_ledger_path()
    data = json.load(open(path))
    for v in data.values():
        v["at"] = 0
    json.dump(data, open(path, "w"))

    acr.resolve_branch(repo, "agent/deleter", "main")
    assert _attempts(repo) > before, "a stale refusal must not stand forever"


def test_an_unreadable_ledger_still_attempts_the_merge(repo, monkeypatch):
    """Fail-OPEN on bookkeeping: never refuse a merge because a JSON file is broken."""
    monkeypatch.setattr(acr, "_reject_ledger_load",
                        lambda: (_ for _ in ()).throw(OSError("boom")))
    monkeypatch.setattr(acr, "_verify_merge", lambda *a, **k: "")
    assert acr.resolve_branch(repo, "agent/deleter", "main")["merged"] is True
