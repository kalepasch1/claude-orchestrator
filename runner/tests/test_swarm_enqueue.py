"""The swarm bots' filer must actually file.

conflict_marker_sentinel (bot #1) was wired into the periodic loop against
`enqueue.enqueue_task`, which takes three REQUIRED keyword-only callables. The bots call
`enqueue_fn(record)` with one positional argument, so every call raised TypeError — and
every bot swallows enqueue failures by design (`except Exception: filed = False`). The
job ran every five minutes, reported filed=False, and filed nothing. These tests pin the
binding that makes it real, and the priority translation that keeps it behind user work.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import conflict_marker_sentinel  # noqa: E402
import enqueue as _enqueue  # noqa: E402
import swarm_enqueue  # noqa: E402


class _DB:
    def __init__(self, open_rows=None):
        self.open_rows = open_rows or []
        self.inserted = []
        self.updated = []

    def select(self, table, params=None):
        return list(self.open_rows) if table == "tasks" else []

    def insert(self, table, values):
        self.inserted.append((table, values))
        return {"id": f"task-{len(self.inserted)}"}

    def update(self, table, match, values):
        self.updated.append((table, match, values))
        return values


@pytest.fixture
def wired(monkeypatch):
    db = _DB()
    monkeypatch.setattr(swarm_enqueue, "db", db)
    monkeypatch.setattr(swarm_enqueue._et, "db", db)
    monkeypatch.setattr(swarm_enqueue._et, "project_by_name",
                        lambda name: {"id": "proj-uuid", "name": "beethoven",
                                      "default_base": "master"})
    return db


REC = {"slug": "remediation-conflict-markers-on-master", "kind": "remediation",
       "priority": 1, "prompt": "resolve the markers", "note": "filed by bot #1"}


def test_the_one_argument_call_the_bots_make_actually_works(wired):
    """The exact call shape every swarm bot uses. This is what used to raise TypeError."""
    result = swarm_enqueue.enqueue(dict(REC))

    assert result.action == "created"
    assert len(wired.inserted) == 1
    table, row = wired.inserted[0]
    assert table == "tasks"
    assert row["slug"] == REC["slug"]
    assert row["project_id"] == "proj-uuid"
    assert row["kind"] == "remediation"
    assert "resolve the markers" in row["prompt"]


def test_enqueue_task_still_rejects_the_old_one_argument_call():
    """Guards the premise: if this ever stops raising, the binding is no longer needed."""
    with pytest.raises(TypeError):
        _enqueue.enqueue_task(dict(REC))


def test_swarm_work_is_never_filed_ahead_of_user_work(wired):
    """priority=1 in a bot record means 'tier-1'. The COLUMN sorts ascending on claim, so
    writing 1 would claim it FIRST — the exact opposite of the owner directive. Ordering
    below user work is ev_scheduler's project tier, not this column."""
    swarm_enqueue.enqueue(dict(REC))

    _table, row = wired.inserted[0]
    assert row["priority"] == swarm_enqueue.SWARM_PRIORITY
    assert row["priority"] >= 1000, "a swarm task must not outrank user-directed work"


def test_an_equivalent_open_intent_is_coalesced_not_duplicated(monkeypatch):
    db = _DB()
    monkeypatch.setattr(swarm_enqueue, "db", db)
    monkeypatch.setattr(swarm_enqueue._et, "db", db)
    monkeypatch.setattr(swarm_enqueue._et, "project_by_name",
                        lambda name: {"id": "proj-uuid", "name": "beethoven"})
    monkeypatch.setattr(swarm_enqueue._et, "_find_open_by_intent",
                        lambda pid, key: {"id": "existing-1", "state": "QUEUED"})

    result = swarm_enqueue.enqueue(dict(REC))

    assert result.action == "coalesced"
    assert db.inserted == [], "a five-minute sweep must not mint a task every cycle"
    assert db.updated, "the existing row must be bumped instead"


def test_a_slugless_record_is_refused_loudly(wired):
    with pytest.raises(ValueError):
        swarm_enqueue.enqueue({"prompt": "no slug"})


def test_an_insert_that_returns_no_receipt_raises_rather_than_reporting_success(monkeypatch):
    db = _DB()
    db.insert = lambda table, values: None
    monkeypatch.setattr(swarm_enqueue, "db", db)
    monkeypatch.setattr(swarm_enqueue._et, "db", db)
    monkeypatch.setattr(swarm_enqueue._et, "project_by_name",
                        lambda name: {"id": "proj-uuid", "name": "beethoven"})
    monkeypatch.setattr(swarm_enqueue._et, "_find_open_by_intent", lambda pid, key: None)

    with pytest.raises(RuntimeError):
        swarm_enqueue.enqueue(dict(REC))


def test_end_to_end_bot_one_reports_filed_true(tmp_path, wired, monkeypatch):
    """The whole point: sweep() -> swarm_enqueue.enqueue -> a row, with filed=True."""
    import subprocess
    repo = tmp_path / "r"
    repo.mkdir()
    for args in (("init", "-q", "-b", "master"), ("config", "user.email", "t@t"),
                 ("config", "user.name", "t")):
        subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True)
    (repo / "m.py").write_text("a=1\n<<<<<<< HEAD\nb=2\n=======\nb=3\n>>>>>>> x\n")
    subprocess.run(["git", "add", "."], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "c"], cwd=str(repo), check=True, capture_output=True)

    res = conflict_marker_sentinel.sweep(str(repo), swarm_enqueue.enqueue)

    assert res["found"] == ["m.py"]
    assert res["filed"] is True, "this was False for the entire life of the wired job"
    assert len(wired.inserted) == 1
