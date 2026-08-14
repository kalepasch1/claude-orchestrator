"""Tests for runner/worktree_preflight.py.

Covers the three behaviours the preflight exists to guarantee:
  * green  -> the project stays claimable;
  * missing npm -> the project is blocked, WITH a reason a human can act on;
  * the verdict is cached once per project per day (no repeated installs).
"""
import json
import os

import pytest

import worktree_preflight as wp


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path, monkeypatch):
    """Never touch the real .runtime stamp dir or the real kill switch."""
    monkeypatch.setenv("ORCH_WORKTREE_PREFLIGHT_DIR", str(tmp_path / "stamps"))
    monkeypatch.setenv("ORCH_WORKTREE_PREFLIGHT_TODAY", "2026-08-06")
    monkeypatch.setattr(wp, "_block_project", lambda project, reason: _blocks.append((project, reason)))
    monkeypatch.setattr(wp, "_unblock_project", lambda project: _unblocks.append(project))
    _blocks.clear()
    _unblocks.clear()
    yield


_blocks = []
_unblocks = []


@pytest.fixture
def js_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "package.json").write_text(json.dumps({"name": "demo", "version": "1.0.0"}))
    return str(repo)


def _installs_ok(calls):
    def _fake(repo_path, timeout=None):
        calls.append(repo_path)
        return {"ok": True, "installed": True}
    return _fake


# --- green -> claimable ----------------------------------------------------

def test_green_project_is_claimable(js_repo, monkeypatch):
    monkeypatch.setattr(wp, "missing_tools", lambda: [])
    monkeypatch.setattr(wp, "_install", _installs_ok([]))

    res = wp.preflight("demo", js_repo)

    assert res["status"] == wp.STATUS_GREEN
    assert res["claimable"] is True
    assert res["blocked"] is False
    assert wp.blocked_reason("demo") is None
    assert wp.claimable("demo", js_repo) is True
    assert _blocks == []


def test_green_lifts_a_pause_this_module_owns(js_repo, monkeypatch):
    monkeypatch.setattr(wp, "missing_tools", lambda: [])
    monkeypatch.setattr(wp, "_install", _installs_ok([]))

    wp.preflight("demo", js_repo)

    assert _unblocks == ["demo"]


# --- missing npm -> blocked with a reason ----------------------------------

def test_missing_npm_blocks_with_reason(js_repo, monkeypatch):
    monkeypatch.setattr(wp, "missing_tools", lambda: ["npm"])
    monkeypatch.setattr(wp, "_install", _installs_ok([]))

    res = wp.preflight("demo", js_repo)

    assert res["status"] == wp.STATUS_BLOCKED
    assert res["claimable"] is False
    assert res["blocked"] is True
    assert "npm" in res["reason"]
    assert "PATH" in res["reason"]
    assert wp.blocked_reason("demo") == res["reason"]
    assert wp.claimable("demo", js_repo) is False
    assert _blocks and _blocks[0][0] == "demo" and "npm" in _blocks[0][1]


def test_missing_npm_does_not_attempt_an_install(js_repo, monkeypatch):
    calls = []
    monkeypatch.setattr(wp, "missing_tools", lambda: ["node", "npm"])
    monkeypatch.setattr(wp, "_install", _installs_ok(calls))

    wp.preflight("demo", js_repo)

    assert calls == [], "must not burn an install when the toolchain is absent"


def test_failed_install_blocks_with_the_installer_error(js_repo, monkeypatch):
    monkeypatch.setattr(wp, "missing_tools", lambda: [])
    monkeypatch.setattr(wp, "_install",
                        lambda repo_path, timeout=None: {"ok": False, "error": "ENOENT lockfile"})

    res = wp.preflight("demo", js_repo)

    assert res["status"] == wp.STATUS_BLOCKED
    assert "ENOENT lockfile" in res["reason"]


# --- once-per-day caching --------------------------------------------------

def test_verdict_is_cached_once_per_day(js_repo, monkeypatch):
    calls = []
    monkeypatch.setattr(wp, "missing_tools", lambda: [])
    monkeypatch.setattr(wp, "_install", _installs_ok(calls))

    first = wp.preflight("demo", js_repo)
    second = wp.preflight("demo", js_repo)
    third = wp.preflight("demo", js_repo)

    assert len(calls) == 1, "install must run at most once per project per day"
    assert first["cached"] is False
    assert second["cached"] is True and third["cached"] is True
    assert second["status"] == first["status"]


def test_cache_expires_on_the_next_day(js_repo, monkeypatch):
    calls = []
    monkeypatch.setattr(wp, "missing_tools", lambda: [])
    monkeypatch.setattr(wp, "_install", _installs_ok(calls))

    wp.preflight("demo", js_repo)
    monkeypatch.setenv("ORCH_WORKTREE_PREFLIGHT_TODAY", "2026-08-07")
    res = wp.preflight("demo", js_repo)

    assert len(calls) == 2
    assert res["cached"] is False


def test_force_bypasses_the_cache(js_repo, monkeypatch):
    calls = []
    monkeypatch.setattr(wp, "missing_tools", lambda: [])
    monkeypatch.setattr(wp, "_install", _installs_ok(calls))

    wp.preflight("demo", js_repo)
    wp.preflight("demo", js_repo, force=True)

    assert len(calls) == 2


def test_blocked_verdict_is_also_cached(js_repo, monkeypatch):
    calls = []
    monkeypatch.setattr(wp, "missing_tools", lambda: ["npm"])
    monkeypatch.setattr(wp, "_install", _installs_ok(calls))

    wp.preflight("demo", js_repo)
    _blocks.clear()
    res = wp.preflight("demo", js_repo)

    assert res["cached"] is True and res["blocked"] is True
    assert _blocks == [], "a cached verdict must not re-pause the project"


def test_projects_are_cached_independently(tmp_path, monkeypatch):
    good = tmp_path / "good"
    good.mkdir()
    (good / "package.json").write_text("{}")
    monkeypatch.setattr(wp, "missing_tools", lambda: [])
    monkeypatch.setattr(wp, "_install", _installs_ok([]))

    wp.preflight("alpha", str(good))

    assert wp.blocked_reason("beta") is None
    assert wp.claimable("beta") is True


# --- fail-soft / no-op paths ----------------------------------------------

def test_non_js_repo_is_skipped_not_blocked(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()

    res = wp.preflight("demo", str(plain))

    assert res["status"] == wp.STATUS_SKIPPED
    assert res["claimable"] is True


def test_missing_repo_is_skipped_not_blocked():
    res = wp.preflight("demo", "/nonexistent/path/for/tests")

    assert res["status"] == wp.STATUS_SKIPPED
    assert res["claimable"] is True
    assert _blocks == []


def test_disabled_by_env(js_repo, monkeypatch):
    monkeypatch.setenv("ORCH_WORKTREE_PREFLIGHT", "false")

    res = wp.preflight("demo", js_repo)

    assert res["status"] == wp.STATUS_SKIPPED
    assert res["claimable"] is True


def test_internal_error_never_blocks_a_project(js_repo, monkeypatch):
    def _boom():
        raise RuntimeError("preflight bug")
    monkeypatch.setattr(wp, "missing_tools", _boom)

    res = wp.preflight("demo", js_repo)

    assert res["claimable"] is True
    assert res["unverified"] is True
    assert _blocks == []


def test_unknown_project_is_claimable():
    assert wp.claimable("never-seen") is True
    assert wp.blocked_reason("never-seen") is None


def test_prepare_worktree_is_fail_soft(monkeypatch):
    assert wp.prepare_worktree("/nonexistent", "/also-nonexistent") == []
