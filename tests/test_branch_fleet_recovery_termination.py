"""Missing-branch recovery must terminate, not loop.

`recover_branch` requeues a task whose agent branch is gone everywhere as
`recover-<slug>`. Nothing stopped that requeued task from being recovered again once it
too reached DONE, so a branch that stayed lost produced `recover-recover-…` without
bound: repeated conflicting remediation for one underlying failure.

These tests pin the terminating behavior: recovery is bounded by depth, is idempotent
across repeated sweeps, and degrades to a stable no-op instead of raising.

NOTE ON SCOPE. The originating prompt named
`packages/darwin-kernel/src/passport/passport.ts`. That module is the identity/passport
layer and has no missing-branch handler; the real owner of this behavior is
`runner/branch_fleet_recovery.py`, so the regression lives with the code it guards.
"""
import os
import sys

import pytest

RUNNER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner")
if RUNNER not in sys.path:
    sys.path.insert(0, RUNNER)

import branch_fleet_recovery as bfr  # noqa: E402


@pytest.fixture
def no_branch_anywhere(monkeypatch):
    """Worst case: the branch is missing locally and on every remote, PAT present."""
    monkeypatch.setattr(bfr, "_branch_exists_local", lambda repo, branch: False)
    monkeypatch.setattr(bfr, "_branch_exists_remote", lambda repo, branch: False)
    monkeypatch.setattr(bfr, "DRY_RUN", False)
    monkeypatch.setattr(bfr.git_auth, "pat_available", lambda: True)


def _task(slug):
    return {"id": "t1", "slug": slug, "project_id": "p1", "kind": "build",
            "prompt": "do the thing", "base_branch": "master"}


def test_recovery_depth_counts_prefixes():
    assert bfr.recovery_depth("build-x") == 0
    assert bfr.recovery_depth("recover-build-x") == 1
    assert bfr.recovery_depth("recover-recover-build-x") == 2
    assert bfr.recovery_depth(None) == 0


def test_first_recovery_requeues_once(monkeypatch, no_branch_anywhere):
    inserted = []
    monkeypatch.setattr(bfr.db, "select", lambda *a, **k: [])
    monkeypatch.setattr(bfr.db, "insert", lambda t, row, **k: inserted.append(row))
    monkeypatch.setattr(bfr.db, "update", lambda *a, **k: None)

    res = bfr.recover_branch(_task("build-x"), "/tmp/repo")

    assert res["strategy"] == "requeued"
    assert res["detail"] == "recover-build-x"
    assert len(inserted) == 1


def test_already_recovered_task_does_not_recurse(monkeypatch, no_branch_anywhere):
    """The loop guard: a `recover-` slug terminates instead of minting recover-recover-."""
    inserted = []
    monkeypatch.setattr(bfr.db, "select", lambda *a, **k: [])
    monkeypatch.setattr(bfr.db, "insert", lambda t, row, **k: inserted.append(row))
    monkeypatch.setattr(bfr.db, "update", lambda *a, **k: None)

    res = bfr.recover_branch(_task("recover-build-x"), "/tmp/repo")

    assert res["recovered"] is False
    assert res["strategy"] == "recovery_exhausted"
    assert inserted == [], "an exhausted recovery must not queue more work"


def test_repeated_sweeps_are_stable(monkeypatch, no_branch_anywhere):
    """Second pass over the same task is a no-op — no duplicate remediation."""
    monkeypatch.setattr(bfr.db, "select", lambda *a, **k: [{"id": "existing"}])
    monkeypatch.setattr(bfr.db, "insert",
                        lambda *a, **k: pytest.fail("must not insert a duplicate"))
    monkeypatch.setattr(bfr.db, "update", lambda *a, **k: None)

    first = bfr.recover_branch(_task("build-x"), "/tmp/repo")
    second = bfr.recover_branch(_task("build-x"), "/tmp/repo")

    assert first == second, "recovery outcome must be stable across passes"
    assert first["strategy"] == "already_requeued"


def test_missing_pat_terminates_gracefully(monkeypatch, no_branch_anywhere):
    monkeypatch.setattr(bfr.git_auth, "pat_available", lambda: False)
    monkeypatch.setattr(bfr.db, "insert",
                        lambda *a, **k: pytest.fail("must not queue without auth"))
    res = bfr.recover_branch(_task("build-x"), "/tmp/repo")
    assert res == {"recovered": False, "strategy": "pat_unavailable"}


def test_db_failure_is_fail_soft(monkeypatch, no_branch_anywhere):
    def boom(*a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr(bfr.db, "select", boom)
    res = bfr.recover_branch(_task("build-x"), "/tmp/repo")
    assert res["recovered"] is False
    assert res["strategy"] == "error"


def test_present_branch_is_a_noop(monkeypatch):
    monkeypatch.setattr(bfr, "_branch_exists_local", lambda repo, branch: True)
    monkeypatch.setattr(bfr.db, "insert",
                        lambda *a, **k: pytest.fail("nothing to recover"))
    assert bfr.recover_branch(_task("build-x"), "/tmp/repo") == {
        "recovered": True, "strategy": "already_exists"}
