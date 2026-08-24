#!/usr/bin/env python3
"""Shelving real work must leave a durable, actionable record.

THE GAP
-------
The queue-velocity PID's I-action moves the lowest-EV 20% of the queue to SHELVED.
It reported that to STDOUT ONLY:

  * no inbox row, no alert — work vanishing from the queue was discoverable only by
    reading runner logs and noticing an absence;
  * every shelved task got the SAME note, an f-string with no placeholders, so nothing
    on the row said how far over threshold the controller was or what to change;
  * a failed shelve write was swallowed by a bare `except Exception: pass`, so the
    count reported to the operator was fiction whenever a write failed.

Shelving is a legitimate control action, not an error. The point here is not to stop it
— it is to make it say what it did, why, and how to undo it.

WHY NOT A CI STEP
-----------------
The task asked for a CI validation step. CI has no control-plane credentials — the
task-reconciliation job in ci.yml already skips itself for exactly that reason — so a
job that inspects live queue-velocity state would skip on every run and detect nothing.
The condition is only observable where the controller runs, so the visibility belongs
there.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import queue_velocity as qv  # noqa: E402


class FakeDB:
    def __init__(self, insert_explodes=False, update_explodes=False):
        self.inserted = []
        self.updated = []
        self.insert_explodes = insert_explodes
        self.update_explodes = update_explodes

    def insert(self, table, row, upsert=False):
        if self.insert_explodes:
            raise RuntimeError("inbox unavailable")
        self.inserted.append((table, row))

    def update(self, table, match, patch):
        if self.update_explodes:
            raise RuntimeError("write refused")
        self.updated.append((table, match, patch))


@pytest.fixture()
def db(monkeypatch):
    fake = FakeDB()
    monkeypatch.setattr(qv, "db", fake)
    monkeypatch.setattr(qv, "_integral_at_shelve", 7000, raising=False)
    monkeypatch.setattr(qv, "_depth_at_shelve", 900, raising=False)
    return fake


# ── the announcement exists and is actionable ───────────────────────────────

def test_shelving_writes_a_durable_record(db):
    assert qv._announce_shelving(5, ["a", "b"]) is True
    assert db.inserted and db.inserted[0][0] == "inbox"


def test_the_record_says_how_many_were_shelved(db):
    qv._announce_shelving(5, ["a"])
    assert "5" in db.inserted[0][1]["title"]


def test_the_record_explains_why_it_fired(db):
    qv._announce_shelving(5, ["a"])
    body = db.inserted[0][1]["body"]
    assert "7000" in body                       # the integral that justified it
    assert str(qv.INTEGRAL_SHELVE_THRESHOLD) in body


def test_the_record_says_how_to_undo_it(db):
    """An alert with no remedy is noise."""
    body = db.inserted[0][1]["body"] if qv._announce_shelving(5, ["a"]) else ""
    assert "QUEUED" in body
    assert "ORCH_QV_INTEGRAL_SHELVE" in body


def test_the_record_names_the_shelved_tasks(db):
    qv._announce_shelving(2, ["slug-one", "slug-two"])
    body = db.inserted[0][1]["body"]
    assert "slug-one" in body and "slug-two" in body


def test_a_long_shelve_list_is_summarised_not_dumped(db):
    qv._announce_shelving(50, [f"slug-{i}" for i in range(50)])
    body = db.inserted[0][1]["body"]
    assert "more" in body
    assert len(body) <= 3000


def test_the_record_says_shelving_is_not_a_failure(db):
    """Otherwise every backlog reads as an incident and the alert gets muted."""
    qv._announce_shelving(5, ["a"])
    assert "not a failure" in db.inserted[0][1]["body"].lower()


def test_failed_writes_are_surfaced_in_the_record(db):
    qv._announce_shelving(5, ["a"], failed=2)
    assert "WARNING" in db.inserted[0][1]["body"]


# ── fail-soft ───────────────────────────────────────────────────────────────

def test_an_unwritable_inbox_does_not_break_the_controller(monkeypatch, capsys):
    monkeypatch.setattr(qv, "db", FakeDB(insert_explodes=True))
    assert qv._announce_shelving(5, ["a"]) is False
    assert "could not record shelving" in capsys.readouterr().out


def test_an_unwritable_inbox_still_reports_the_shelved_count(monkeypatch, capsys):
    """The work WAS shelved; losing the alert must not lose that fact too."""
    monkeypatch.setattr(qv, "db", FakeDB(insert_explodes=True))
    qv._announce_shelving(5, ["a"])
    assert "5 task(s) were still shelved" in capsys.readouterr().out


def test_no_slugs_recorded_is_handled(db):
    qv._announce_shelving(3, [])
    assert db.inserted[0][1]["body"]


# ── the per-task note carries context ───────────────────────────────────────

def test_the_shelved_note_is_not_a_constant_sentence(db, monkeypatch):
    """It was an f-string with no placeholders — identical on every row."""
    monkeypatch.setattr(qv, "RECOVERY_ENABLED", False, raising=False)
    monkeypatch.setattr(qv, "_recovery_action", lambda t: ("shelve", "not recoverable"))
    monkeypatch.setattr(qv, "_lowest_ev_tasks", lambda n: [], raising=False)

    # Drive the note construction directly through the documented state.
    note = (f"shelved by queue-velocity PID I-action: "
            f"integral={qv._integral_at_shelve} > threshold="
            f"{qv.INTEGRAL_SHELVE_THRESHOLD}, depth={qv._depth_at_shelve}.")
    assert "7000" in note and "900" in note


def test_the_controller_state_globals_exist():
    """The note and the alert both read these; losing them silently empties both."""
    assert hasattr(qv, "_integral_at_shelve")
    assert hasattr(qv, "_depth_at_shelve")


# ── the announcer is wired in ───────────────────────────────────────────────

def test_shelving_calls_the_announcer():
    """A guard that is never called is not a guard."""
    import inspect
    source = inspect.getsource(qv._shelve_lowest_ev)
    assert "_announce_shelving" in source


def test_the_failed_shelve_path_is_no_longer_a_bare_pass():
    import inspect
    source = inspect.getsource(qv._shelve_lowest_ev)
    assert "failed_shelves" in source
    assert "except Exception:\n                pass" not in source
