"""Coming off the shelf must be bounded, or the shelf means nothing.

auto_remediate.recover_shelved() exists so no human ever has to requeue by hand. Its
requeue path sets `remediation_count = 0`, which is what makes a recovered task retryable
— and also erased the only evidence it had been here before. A task could shelve, recover,
fail, shelve again indefinitely, with the "shelved after N remediations (atomic +
unbuildable) — needs human re-scope" signal wiped each round, so the human it was escalated
to was never actually asked.

The recovery COUNT now lives in the note, which survives the reset.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import auto_remediate as ar  # noqa: E402


class FakeDB:
    def __init__(self, rows):
        self.rows = rows
        self.updates = []

    def select(self, _table, _params=None):
        return list(self.rows)

    def update(self, _table, match, payload):
        self.updates.append((match, payload))
        return payload


@pytest.fixture()
def wired(monkeypatch):
    """recover_shelved with its collaborators stubbed — no model, no network, no DB."""
    monkeypatch.setattr(ar, "_requires_human_hold", lambda *_a, **_k: False)
    monkeypatch.setattr(ar, "_already_decomposed", lambda *_a, **_k: True)
    monkeypatch.setattr(ar, "_decompose", lambda *_a, **_k: [])
    monkeypatch.setattr(ar.agentic_repair, "repair_patch",
                        lambda *_a, **_k: {"state": "QUEUED", "note": "repaired"})
    return monkeypatch


def _task(note="", slug="stuck-task"):
    return {"id": "t1", "slug": slug, "prompt": "do the thing", "note": note,
            "remediation_count": 5, "log_tail": ""}


class TestShelfRecoveries:
    def test_a_fresh_note_has_no_recoveries(self):
        assert ar.shelf_recoveries("shelved after 5 remediations") == 0

    def test_a_marked_note_reports_its_count(self):
        assert ar.shelf_recoveries("repaired\nshelf-recovery #2") == 2

    def test_the_highest_mark_wins(self):
        assert ar.shelf_recoveries("shelf-recovery #1\nshelf-recovery #3") == 3

    @pytest.mark.parametrize("note", [None, "", 7, []])
    def test_never_raises(self, note):
        assert ar.shelf_recoveries(note) == 0


class TestBoundedRecovery:
    def test_a_first_recovery_is_marked(self, wired):
        db = FakeDB([_task()])
        wired.setattr(ar, "db", db)
        decomposed, requeued = ar.recover_shelved()
        assert (decomposed, requeued) == (0, 1)
        _match, payload = db.updates[-1]
        assert "shelf-recovery #1" in payload["note"]
        assert payload["remediation_count"] == 0

    def test_the_count_increments_across_rounds(self, wired):
        db = FakeDB([_task(note="repaired\nshelf-recovery #1")])
        wired.setattr(ar, "db", db)
        ar.recover_shelved()
        assert "shelf-recovery #2" in db.updates[-1][1]["note"]

    def test_the_cap_stops_the_cycle(self, wired, monkeypatch):
        monkeypatch.setattr(ar, "SHELF_RECOVERY_CAP", 3)
        db = FakeDB([_task(note="shelf-recovery #3")])
        wired.setattr(ar, "db", db)
        decomposed, requeued = ar.recover_shelved()
        assert (decomposed, requeued) == (0, 0)

    def test_hitting_the_cap_says_so_in_the_note(self, wired, monkeypatch):
        monkeypatch.setattr(ar, "SHELF_RECOVERY_CAP", 3)
        db = FakeDB([_task(note="shelf-recovery #3")])
        wired.setattr(ar, "db", db)
        ar.recover_shelved()
        assert "shelf-recovery cap reached" in db.updates[-1][1]["note"]
        assert "human re-scope" in db.updates[-1][1]["note"]

    def test_the_cap_message_is_written_only_once(self, wired, monkeypatch):
        monkeypatch.setattr(ar, "SHELF_RECOVERY_CAP", 3)
        db = FakeDB([_task(note="shelf-recovery #3\nshelf-recovery cap reached (3/3)")])
        wired.setattr(ar, "db", db)
        ar.recover_shelved()
        assert db.updates == []

    def test_the_cap_is_fleet_tunable(self):
        """ORCH_-prefixed per CLAUDE.md so fleet_control.py can push it."""
        assert isinstance(ar.SHELF_RECOVERY_CAP, int)
        assert "ORCH_SHELF_RECOVERY_CAP" in open(ar.__file__, encoding="utf-8").read()

    def test_a_human_hold_is_still_skipped_before_any_of_this(self, wired):
        wired.setattr(ar, "_requires_human_hold", lambda *_a, **_k: True)
        db = FakeDB([_task()])
        wired.setattr(ar, "db", db)
        assert ar.recover_shelved() == (0, 0)
        assert db.updates == []

    def test_decomposition_still_takes_precedence_when_available(self, wired):
        wired.setattr(ar, "_already_decomposed", lambda *_a, **_k: False)
        wired.setattr(ar, "_decompose", lambda *_a, **_k: [{"slug": "child"}])
        wired.setattr(ar, "_spawn_subtasks", lambda *_a, **_k: True)
        db = FakeDB([_task()])
        wired.setattr(ar, "db", db)
        decomposed, requeued = ar.recover_shelved()
        assert (decomposed, requeued) == (1, 0)
