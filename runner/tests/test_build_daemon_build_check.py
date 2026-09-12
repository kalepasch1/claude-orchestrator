"""The daemon's 10-minute production build fed a table that does not exist.

2026-09-02, checked against the live fleet DB:

    select table_name from information_schema.tables
     where table_schema='public' and table_name ilike '%health%';
    -> runner_health, deploy_health, portfolio_health, growth_brand_health,
       growth_account_health, v_project_health

There is no `repo_health`. HEALTH_TABLE has never existed. Every db.insert() in
run() has therefore been raising into a bare `except Exception: pass` for the life
of the daemon, and repo_health() -- the only reader in the tree -- has returned None
for every project, always, while the daemon printed "n/n repos healthy" each cycle.

What that unread field cost, per 600s cycle per project: one `npm run build` of the
LIVE working tree, 600s timeout, measured at 4.7 GB RSS on this host, writing
.nuxt/.output underneath whatever agent happened to be working in that repo. The
medic's journal caught the same build orphaned and reaped twice in one afternoon
(15:49Z, 17:23Z), each time after 30+ minutes of running with no parent left to read
its exit status.

Meanwhile the check it claims to perform is done three times over by gates whose
verdicts ARE read: build_gate (exact commit, disposable overlay), clean_clone_gate
(pristine export + real install) and release_train's production proof.

So the build check is off by default. The tests that matter here are the ones about
what a skipped check REPORTS: returning True for a check that never ran is the
"fabricated_critical_return" pattern this fleet's own stub_guard blocks in agent
diffs, and it would have turned every repo permanently "healthy" on no evidence.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import build_daemon  # noqa: E402


@pytest.fixture
def repo_with_build(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "package.json").write_text('{"scripts": {"build": "nuxt build"}}')
    return str(repo)


def test_default_is_off(monkeypatch):
    """The shipped default, read the way the module reads it."""
    monkeypatch.delenv("ORCH_BUILD_DAEMON_BUILD_CHECK", raising=False)
    assert os.environ.get("ORCH_BUILD_DAEMON_BUILD_CHECK", "false").lower() not in (
        "1", "true", "yes", "on")


def test_skipped_check_returns_none_not_true(repo_with_build, monkeypatch):
    """The whole point. `return True` here is a fabricated green."""
    monkeypatch.setattr(build_daemon, "BUILD_CHECK", False)
    result = {"issues": []}
    assert build_daemon._check_build(repo_with_build, result) is None
    assert result["build_checked"] is False


def test_skipped_check_runs_no_build(repo_with_build, monkeypatch):
    monkeypatch.setattr(build_daemon, "BUILD_CHECK", False)
    ran = []
    monkeypatch.setattr(build_daemon.subprocess, "run",
                        lambda *a, **k: ran.append(a) or (_ for _ in ()).throw(
                            AssertionError("a build was started with the check off")))
    assert build_daemon._check_build(repo_with_build, {"issues": []}) is None
    assert ran == []


def test_enabled_check_still_takes_a_slot(repo_with_build, monkeypatch):
    """Opting back in must not opt out of the fleet build limiter."""
    import contextlib
    monkeypatch.setattr(build_daemon, "BUILD_CHECK", True)
    held = []

    @contextlib.contextmanager
    def _hold(label="build", log=print):
        held.append(label)
        yield True

    class _R:
        returncode = 0
        stdout = stderr = ""

    monkeypatch.setattr(build_daemon.build_slots, "hold", _hold)
    monkeypatch.setattr(build_daemon.subprocess, "run", lambda *a, **k: _R())
    assert build_daemon._check_build(repo_with_build, {"issues": []}) is True
    assert held, "the build check ran outside build_slots.hold()"


def test_a_red_build_is_still_red_when_enabled(repo_with_build, monkeypatch):
    import contextlib
    monkeypatch.setattr(build_daemon, "BUILD_CHECK", True)

    @contextlib.contextmanager
    def _hold(label="build", log=print):
        yield True

    class _R:
        returncode = 1
        stdout = ""
        stderr = "ERR_MODULE_NOT_FOUND"

    monkeypatch.setattr(build_daemon.build_slots, "hold", _hold)
    monkeypatch.setattr(build_daemon.subprocess, "run", lambda *a, **k: _R())
    result = {"issues": []}
    assert build_daemon._check_build(repo_with_build, result) is False
    assert any("build failed" in i for i in result["issues"])


def test_no_package_json_is_no_verdict(tmp_path, monkeypatch):
    monkeypatch.setattr(build_daemon, "BUILD_CHECK", True)
    repo = tmp_path / "py"
    repo.mkdir()
    assert build_daemon._check_build(str(repo), {"issues": []}) is None


def test_a_skipped_build_does_not_mark_the_repo_degraded(monkeypatch, tmp_path):
    """`build_ok` is now tri-state; `if deps_ok and build_ok` would read None as red
    and report every repo degraded forever."""
    repo = tmp_path / "r"
    repo.mkdir()
    monkeypatch.setattr(build_daemon.db, "select", lambda *a, **k: [
        {"id": "1", "name": "proj", "repo_path": str(repo), "default_base": "main"}])
    monkeypatch.setattr(build_daemon, "warm_repo",
                        lambda repo, proj: {"deps_ok": True, "build_ok": None,
                                            "env_ok": True, "warm_worktrees": 0,
                                            "issues": []})
    rows = []
    monkeypatch.setattr(build_daemon.db, "insert",
                        lambda table, row, **k: rows.append(row))
    build_daemon.run()
    assert rows and rows[0]["status"] == "healthy"


def test_a_red_build_still_marks_the_repo_degraded(monkeypatch, tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    monkeypatch.setattr(build_daemon.db, "select", lambda *a, **k: [
        {"id": "1", "name": "proj", "repo_path": str(repo), "default_base": "main"}])
    monkeypatch.setattr(build_daemon, "warm_repo",
                        lambda repo, proj: {"deps_ok": True, "build_ok": False,
                                            "env_ok": True, "warm_worktrees": 0,
                                            "issues": ["build failed: x"]})
    rows = []
    monkeypatch.setattr(build_daemon.db, "insert",
                        lambda table, row, **k: rows.append(row))
    build_daemon.run()
    assert rows and rows[0]["status"] == "degraded"


def test_an_unwritable_health_sink_is_reported_not_swallowed(monkeypatch, tmp_path,
                                                             capsys):
    """The bug that hid the bug. `except Exception: pass` is why a table that never
    existed cost a production build every ten minutes for months."""
    repo = tmp_path / "r"
    repo.mkdir()
    monkeypatch.setattr(build_daemon.db, "select", lambda *a, **k: [
        {"id": "1", "name": "proj", "repo_path": str(repo), "default_base": "main"}])
    monkeypatch.setattr(build_daemon, "warm_repo",
                        lambda repo, proj: {"deps_ok": True, "build_ok": None,
                                            "env_ok": True, "warm_worktrees": 0,
                                            "issues": []})

    def _boom(table, row, **k):
        raise RuntimeError('relation "repo_health" does not exist')

    monkeypatch.setattr(build_daemon.db, "insert", _boom)
    build_daemon.run()
    out = capsys.readouterr().out
    assert "health sink unwritable" in out
    assert "repo_health" in out


def test_a_failing_sink_does_not_stop_the_sweep(monkeypatch, tmp_path):
    """Reporting the failure must not become a new way to break warming."""
    repo = tmp_path / "r"
    repo.mkdir()
    projects = [{"id": str(i), "name": "p%d" % i, "repo_path": str(repo),
                 "default_base": "main"} for i in range(3)]
    monkeypatch.setattr(build_daemon.db, "select", lambda *a, **k: projects)
    warmed = []
    monkeypatch.setattr(build_daemon, "warm_repo",
                        lambda repo, proj: warmed.append(proj["name"]) or {
                            "deps_ok": True, "build_ok": None, "env_ok": True,
                            "warm_worktrees": 0, "issues": []})

    def _boom(table, row, **k):
        raise RuntimeError("nope")

    monkeypatch.setattr(build_daemon.db, "insert", _boom)
    build_daemon.run()
    assert warmed == ["p0", "p1", "p2"]
