"""A paused repo is not warmed, not fetched, and not built.

2026-09-02, caught live on this host at 18:19Z:

    pid 26080  61.8% CPU  3.45 GB RSS
        node /Users/kpasch/Documents/_ARCHIVED-apparently-do-not-use/
             node_modules/.bin/nuxt build
        parent: pid 77316  runner/build_daemon.py

build_daemon was running `git fetch`, `npm install` and a full production build every
600 seconds against a directory named "_ARCHIVED-apparently-do-not-use" -- one of four
archived repos paused on 2026-09-01 for exactly this reason. Five of the fleet's sixteen
projects are paused (four archives plus beethoven, held since 2026-08-24); the daemon was
warming all five, 31% of its work.

The general shape, measured the same afternoon: of the 131 modules under runner/ that
select from `projects`, 10 read the pause flag. 121 do not. For a bot that only reads
rows that is harmless. For the bots that touch the disk it is the difference between a
paused project and an active one being nothing at all.

The fix is one helper, not 121 patches, and the tests that matter are the fail-open ones:
a control-plane read that errors must mean "nothing is paused", never "nothing is active".
A fleet that stops maintaining every repo it owns the moment Supabase blinks is a far
worse failure than one wasted sweep.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import active_projects  # noqa: E402


class _DB:
    def __init__(self, rows=None, boom=False):
        self.rows = rows or []
        self.boom = boom
        self.queries = []

    def select(self, table, params):
        self.queries.append((table, params))
        if self.boom:
            raise RuntimeError("supabase 522")
        return self.rows


PROJECTS = [
    {"name": "tomorrow", "repo_path": "/r/tomorrow"},
    {"name": "smarter", "repo_path": "/r/smarter"},
    {"name": "apparently-archived", "repo_path": "/r/_ARCHIVED-apparently-do-not-use"},
    {"name": "beethoven", "repo_path": "/r/claude-orchestrator"},
]
PAUSED = [{"project": "apparently-archived", "paused": True, "scope": "project"},
          {"project": "beethoven", "paused": True, "scope": "project"}]


def test_paused_projects_are_dropped():
    db = _DB(PAUSED)
    names = [p["name"] for p in active_projects.active(PROJECTS, db=db)]
    assert names == ["tomorrow", "smarter"]


def test_the_archived_repo_is_the_one_that_goes():
    db = _DB(PAUSED)
    kept = " ".join(p["repo_path"] for p in active_projects.active(PROJECTS, db=db))
    assert "_ARCHIVED" not in kept


def test_it_asks_only_for_paused_project_scoped_rows():
    """A filter done client-side on every control row is a different, slower bug."""
    db = _DB(PAUSED)
    active_projects.paused_names(db=db)
    table, params = db.queries[0]
    assert table == "controls"
    assert params.get("scope") == "eq.project"
    assert params.get("paused") == "is.true"


def test_a_control_plane_outage_means_nothing_is_paused():
    """FAIL OPEN. The alternative is a DB blink stopping all repo maintenance."""
    db = _DB(boom=True)
    assert active_projects.paused_names(db=db) == set()
    assert len(active_projects.active(PROJECTS, db=db)) == len(PROJECTS)


def test_no_paused_rows_keeps_everything():
    db = _DB([])
    assert len(active_projects.active(PROJECTS, db=db)) == 4


def test_an_unnamed_project_row_is_kept():
    """It cannot match a pause control; dropping it would invent a policy."""
    db = _DB(PAUSED)
    rows = PROJECTS + [{"repo_path": "/r/nameless"}]
    assert any(not p.get("name") for p in active_projects.active(rows, db=db))


def test_blank_and_whitespace_names_in_controls_are_ignored():
    db = _DB([{"project": "  ", "paused": True, "scope": "project"},
              {"project": None, "paused": True, "scope": "project"}])
    assert active_projects.paused_names(db=db) == set()


def test_names_are_matched_after_stripping():
    db = _DB([{"project": " beethoven ", "paused": True, "scope": "project"}])
    names = [p["name"] for p in active_projects.active(PROJECTS, db=db)]
    assert "beethoven" not in names


def test_the_kill_switch_restores_the_old_behaviour(monkeypatch):
    monkeypatch.setenv("ORCH_MAINTENANCE_SKIPS_PAUSED", "false")
    db = _DB(PAUSED)
    assert len(active_projects.active(PROJECTS, db=db)) == 4


def test_the_note_names_what_was_skipped():
    """An operator reading the log must be able to tell a skip from an outage."""
    db = _DB(PAUSED)
    note = active_projects.note(PROJECTS, db=db)
    assert "2 paused" in note
    assert "apparently-archived" in note and "beethoven" in note


def test_the_note_is_empty_when_nothing_is_skipped():
    assert active_projects.note(PROJECTS, db=_DB([])) == ""


def test_empty_input_is_not_an_error():
    db = _DB(PAUSED)
    assert active_projects.active([], db=db) == []
    assert active_projects.active(None, db=db) == []


# ── the callers ───────────────────────────────────────────────────────────────

def test_build_daemon_does_not_warm_a_paused_repo(monkeypatch):
    """The behavioural test for the process caught at 18:19Z."""
    import build_daemon

    monkeypatch.setattr(build_daemon.db, "select",
                        lambda table, params: PROJECTS if table == "projects" else [])
    monkeypatch.setattr(build_daemon.active_projects, "paused_names",
                        lambda db=None: {"apparently-archived", "beethoven"})
    warmed = []
    monkeypatch.setattr(build_daemon, "warm_repo",
                        lambda repo, proj: warmed.append(proj["name"]) or {
                            "deps_ok": True, "build_ok": None, "env_ok": True,
                            "warm_worktrees": 0, "issues": []})
    monkeypatch.setattr(build_daemon.os.path, "isdir", lambda p: True)
    monkeypatch.setattr(build_daemon.db, "insert", lambda *a, **k: None)
    build_daemon.run()
    assert warmed == ["tomorrow", "smarter"]
    assert "apparently-archived" not in warmed


@pytest.mark.parametrize("module", ["build_daemon.py", "clean_clone_gate.py"])
def test_the_expensive_bots_import_the_filter(module):
    """Structural: these two spend real disk and CPU per repo, every cycle."""
    runner = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(runner, module)) as fh:
        src = fh.read()
    assert "import active_projects" in src, (
        "%s sweeps every project row and does per-repo work; it must skip paused ones"
        % module)
    assert "active_projects.active(" in src, (
        "%s imports the filter but never applies it" % module)
