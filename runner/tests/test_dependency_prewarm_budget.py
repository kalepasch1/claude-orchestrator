"""Regression tests for link_shared_runtime()'s aggregate activation budget.

Guards the merge_train crash loop root cause: activate_modules() bounded each
individual `cp` at 180s but link_shared_runtime() calls it once per package
root. With beethoven's 6 roots the worst case was 1080s, exceeding merge_train's
900s pass watchdog, so a single _build_gate could consume the whole pass and be
killed before integrating any card.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dependency_prewarm as dp


def test_total_budget_stays_under_merge_train_watchdog():
    """Aggregate budget must leave real headroom under the 900s watchdog."""
    assert dp._ACTIVATION_TOTAL_BUDGET_S < 900
    # Leave at least a third of the pass for actual integration work.
    assert dp._ACTIVATION_TOTAL_BUDGET_S <= 600


def test_per_call_timeout_never_exceeds_total_budget():
    assert dp._ACTIVATION_CALL_TIMEOUT_S <= dp._ACTIVATION_TOTAL_BUDGET_S


def _make_root(tmp_path, name):
    root = tmp_path / name
    (root / "node_modules" / "pkg").mkdir(parents=True)
    (root / "node_modules" / "pkg" / "index.js").write_text("//x")
    (root / "package.json").write_text('{"name":"%s"}' % name)
    return root


def test_activation_degrades_to_symlink_once_budget_spent(tmp_path, monkeypatch):
    """When the budget is exhausted, clone is skipped and we symlink instead.

    subprocess.run is stubbed to fail the test if the clone path is taken.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _make_root(repo, "a")
    worktree = tmp_path / "wt"
    (worktree / "a").mkdir(parents=True)

    monkeypatch.setattr(dp, "package_roots", lambda r: [str(repo / "a")])
    monkeypatch.setattr(dp, "_ready_snapshot", lambda r: None)
    # Zero budget => must never shell out.
    monkeypatch.setattr(dp, "_ACTIVATION_TOTAL_BUDGET_S", 0)

    def _boom(*a, **k):  # pragma: no cover - fails the test if reached
        raise AssertionError("clone attempted with no remaining budget")

    monkeypatch.setattr(dp.subprocess, "run", _boom)

    linked = dp.link_shared_runtime(str(repo), str(worktree))

    dst = worktree / "a" / "node_modules"
    assert dst.is_symlink(), "expected symlink fallback when budget is spent"
    assert str(dst) in linked


def test_clone_timeout_is_clamped_to_remaining_budget(tmp_path, monkeypatch):
    """The timeout handed to subprocess.run is min(per-call, remaining).

    This is about the `cp` fallback specifically. activate_modules now tries a
    single-syscall clonefile() first, which has no subprocess and therefore no
    timeout to clamp, so the clone is disabled here to exercise the path under
    test. tests/test_clonefile_activation.py covers the fast path.
    """
    monkeypatch.setenv("ORCH_DEPS_CLONEFILE", "false")
    repo = tmp_path / "repo"
    repo.mkdir()
    _make_root(repo, "a")
    worktree = tmp_path / "wt"
    (worktree / "a").mkdir(parents=True)

    monkeypatch.setattr(dp, "package_roots", lambda r: [str(repo / "a")])
    monkeypatch.setattr(dp, "_ready_snapshot", lambda r: None)
    monkeypatch.setattr(dp, "_ACTIVATION_TOTAL_BUDGET_S", 30)
    monkeypatch.setattr(dp, "_ACTIVATION_CALL_TIMEOUT_S", 180)

    seen = {}

    class _Res:
        returncode = 1

    def _capture(cmd, **kwargs):
        seen["timeout"] = kwargs.get("timeout")
        return _Res()

    monkeypatch.setattr(dp.subprocess, "run", _capture)

    dp.link_shared_runtime(str(repo), str(worktree))

    assert seen["timeout"] is not None
    # Clamped by remaining budget (30s), not the 180s per-call ceiling.
    assert seen["timeout"] <= 30
