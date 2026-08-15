"""Release-train hold deadlock.

A red gate self-heals by queueing one fix task. The planner decomposes that fix into a
DAG of 30-40 sub-tasks sharing the fix slug prefix. Because the hold was keyed on
`updated_at`, whichever sub-task happened to be RUNNING renewed the 180-minute
exclusivity window forever, so `_hold_for_open_fix` returned early on every cycle and
the train silently stopped attempting releases.

These tests pin the fix: the hold budget is measured from the lineage's OLDEST task.
"""
import datetime

import release_train


def _rows(lineage_age_h, touched_seconds_ago=5, slug="qafix-app-07161923",
          sub="qafix-app-07161923-diagnose-tsconfig", state="RUNNING"):
    now = datetime.datetime.now(datetime.timezone.utc)
    born = (now - datetime.timedelta(hours=lineage_age_h)).isoformat()
    touched = (now - datetime.timedelta(seconds=touched_seconds_ago)).isoformat()
    return [
        {"slug": sub, "state": state, "note": "auto-queued by release_train",
         "updated_at": touched, "created_at": born},
        {"slug": slug, "state": "QUEUED", "note": "auto-queued by release_train",
         "updated_at": touched, "created_at": born},
    ]


def test_old_lineage_with_fresh_subtask_does_not_hold(monkeypatch):
    """THE DEADLOCK: 90h-old fix lineage, sub-task touched seconds ago. Must not hold."""
    monkeypatch.setattr(release_train.db, "select", lambda *a, **k: _rows(90))
    monkeypatch.setattr(release_train, "RELEASE_FIX_HOLD_MAX_H", 12.0)
    monkeypatch.setenv("ORCH_RELEASE_FIX_HOLD_MIN", "180")
    assert release_train._open_release_fix_tasks({"id": "p"}, gate="qa") == []
    assert release_train._hold_for_open_fix({"id": "p"}, "app", "qa") is None


def test_young_lineage_still_holds_and_reports_age(monkeypatch):
    """The ceiling must not defeat the feature: a 1h-old lineage still holds."""
    monkeypatch.setattr(release_train.db, "select", lambda *a, **k: _rows(1))
    monkeypatch.setattr(release_train, "RELEASE_FIX_HOLD_MAX_H", 12.0)
    monkeypatch.setenv("ORCH_RELEASE_FIX_HOLD_MIN", "180")
    held = release_train._hold_for_open_fix({"id": "p"}, "app", "qa")
    assert held is not None
    assert held["held_hours"] == 1.0


def test_fix_lineage_root_groups_a_decomposed_dag():
    root = release_train._fix_lineage_root
    assert root("qafix-darwn-07161923") == root(
        "qafix-darwn-07161923-diagnose-test-tsconfig-resolution")
    assert root("qafix-darwn-07281812") != root("qafix-darwn-07161923")


def test_zero_ceiling_restores_unbounded_behaviour(monkeypatch):
    """Escape hatch: MAX_H=0 means a 500-hour lineage still holds, as it did before."""
    monkeypatch.setattr(release_train.db, "select", lambda *a, **k: _rows(500))
    monkeypatch.setattr(release_train, "RELEASE_FIX_HOLD_MAX_H", 0.0)
    monkeypatch.setenv("ORCH_RELEASE_FIX_HOLD_MIN", "180")
    assert release_train._hold_for_open_fix({"id": "p"}, "app", "qa") is not None


def test_hold_past_half_ceiling_raises_exactly_one_alarm(monkeypatch):
    inserted = []
    monkeypatch.setattr(release_train.db, "select",
                        lambda table, params=None, *a, **k: (
                            [] if table == "orch_gate_alarms" else _rows(8)))
    monkeypatch.setattr(release_train.db, "insert",
                        lambda table, row, **k: inserted.append((table, row)))
    monkeypatch.setattr(release_train, "RELEASE_FIX_HOLD_MAX_H", 12.0)
    monkeypatch.setenv("ORCH_RELEASE_FIX_HOLD_MIN", "180")
    release_train._hold_for_open_fix({"id": "p"}, "app", "qa")
    alarms = [r for t, r in inserted if t == "orch_gate_alarms"]
    assert len(alarms) == 1
    assert alarms[0]["kind"] == "release_hold"
    assert alarms[0]["detail"].startswith("app: ")


def test_existing_unresolved_alarm_is_not_duplicated(monkeypatch):
    inserted = []
    monkeypatch.setattr(release_train.db, "select",
                        lambda table, params=None, *a, **k: (
                            [{"id": "a1"}] if table == "orch_gate_alarms" else _rows(8)))
    monkeypatch.setattr(release_train.db, "insert",
                        lambda table, row, **k: inserted.append((table, row)))
    monkeypatch.setattr(release_train, "RELEASE_FIX_HOLD_MAX_H", 12.0)
    monkeypatch.setenv("ORCH_RELEASE_FIX_HOLD_MIN", "180")
    release_train._hold_for_open_fix({"id": "p"}, "app", "qa")
    assert [r for t, r in inserted if t == "orch_gate_alarms"] == []
