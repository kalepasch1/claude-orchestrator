"""A promise that is false for a third of the table is not a promise.

reconcile_missing_cards() says, in its own docstring, "Every DONE task either has a
card or a recorded reason". Measured on the live fleet 2026-09-02:

    DONE tasks                                       1,017
    the scan's row cap                                 500
    DONE tasks past the cap, permanently invisible     517
    of those, with no card at all                        6

`within_hours` has been in the signature and the docstring since the function was
written and never reached the query, so every tick asked for the newest 500 DONE tasks
ordered by updated_at, and nothing older ever aged back into view. The fleet's own
truncation detector had been saying so 154 times in a single log:

    [db] TRUNCATED SCAN done_to_merged.py:128 -> tasks returned exactly its limit
         (500) ordered by updated_at.desc. Anything past the cap is invisible

Using the window the signature already declares fixes both halves at once. Only 8 DONE
tasks were updated in the last 24h, so the per-tick scan goes from 500 rows to single
digits AND stops truncating -- on a query that runs every 60 seconds. within_hours=0
disables the filter for a full sweep; run once by hand it filed the 6 missing cards and
recorded 2 refusals, taking uncarded DONE tasks from 8 to 2, both of which now carry a
reason.

The second fix here is the other end of the same function. A task that legitimately has
no branch re-recorded its refusal on EVERY pass, forever:

    admission_rejections rows      5,616
    distinct slugs                   872     (6.4 duplicates each)

A row per pass is not a record, it is a metronome.
"""
import calendar
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import done_to_merged  # noqa: E402


class _DB:
    def __init__(self, tasks=None, rejections=None):
        self.tasks = tasks or []
        self.rejections = rejections or []
        self.queries = []
        self.inserts = []

    def select(self, table, params=None):
        params = params or {}
        self.queries.append((table, params))
        if table == "tasks":
            return list(self.tasks)
        if table == "admission_rejections":
            return list(self.rejections)
        if table == "approvals":
            return [{"id": "1"}]          # everything is carded unless a test says else
        return []

    def insert(self, table, row, **kw):
        self.inserts.append((table, row))
        return row


@pytest.fixture
def db(monkeypatch, tmp_path):
    d = _DB()
    monkeypatch.setattr(done_to_merged, "db", d)
    # The hourly full sweep is tested on its own below. Stamp it as just-done so the
    # window tests exercise the WINDOW rather than the backstop; and point the stamp at
    # a temp home so no test writes into the live .runtime.
    monkeypatch.setenv("CLAUDE_ORCH_HOME", str(tmp_path / "home"))
    done_to_merged._mark_full_sweep()
    return d


# ── the scan window ───────────────────────────────────────────────────────────

def test_the_default_call_filters_by_updated_at(db):
    """The regression: `within_hours` never reached the query."""
    done_to_merged.reconcile_missing_cards()
    table, params = db.queries[0]
    assert table == "tasks"
    assert "updated_at" in params, (
        "the scan still asks for the newest N DONE tasks with no time bound")
    assert params["updated_at"].startswith("gte.")


def test_the_window_is_the_one_the_caller_asked_for(db):
    done_to_merged.reconcile_missing_cards(within_hours=1)
    cutoff = db.queries[0][1]["updated_at"][4:]
    # timegm, not mktime: the cutoff the module writes is UTC, and mktime would read
    # it as local time -- which is exactly how a "1 hour ago" filter silently becomes
    # "4 hours ago" on this host.
    asked = calendar.timegm(time.strptime(cutoff, "%Y-%m-%dT%H:%M:%SZ"))
    assert abs((time.time() - asked) - 3600) < 120


def test_zero_hours_means_a_full_sweep(db):
    """The periodic backfill needs to see everything, including 2026-08 tasks."""
    done_to_merged.reconcile_missing_cards(within_hours=0)
    assert "updated_at" not in db.queries[0][1]


def test_the_state_and_order_are_unchanged(db):
    done_to_merged.reconcile_missing_cards()
    params = db.queries[0][1]
    assert params["state"] == "eq.DONE"
    assert params["order"] == "updated_at.desc"


def test_a_still_truncated_scan_says_so(db, capsys):
    """If the window ever returns a full page, that must not be silent again."""
    db.tasks = [{"id": str(i), "slug": "s%d" % i, "note": "", "project_id": "p"}
                for i in range(5)]
    done_to_merged.reconcile_missing_cards(limit=5)
    out = capsys.readouterr().out
    assert "cap" in out and "not examined" in out


def test_a_scan_inside_the_cap_is_quiet(db, capsys):
    db.tasks = [{"id": "1", "slug": "s1", "note": "", "project_id": "p"}]
    done_to_merged.reconcile_missing_cards(limit=500)
    assert "not examined" not in capsys.readouterr().out


def test_a_failed_scan_still_returns_a_summary(db, monkeypatch):
    def _boom(table, params=None):
        raise RuntimeError("supabase 522")
    monkeypatch.setattr(db, "select", _boom)
    out = done_to_merged.reconcile_missing_cards()
    assert out["errors"] == 1 and out["scanned"] == 0


# ── the refusal is recorded once ──────────────────────────────────────────────

def test_an_identical_refusal_is_not_rewritten(db):
    db.rejections = [{"id": "1", "gate": done_to_merged.GATE,
                      "reason": "no branch by design: note matches 'superseded'"}]
    task = {"slug": "s1", "project_id": "p"}
    assert done_to_merged.record_rejection(
        task, "no branch by design: note matches 'superseded'") is True
    assert db.inserts == [], "the same refusal was written a second time"


def test_a_different_reason_is_recorded(db):
    db.rejections = [{"id": "1", "gate": done_to_merged.GATE, "reason": "old reason"}]
    done_to_merged.record_rejection({"slug": "s1", "project_id": "p"}, "a new reason")
    assert db.inserts and db.inserts[0][0] == "admission_rejections"


def test_a_first_refusal_is_always_recorded(db):
    done_to_merged.record_rejection({"slug": "s1", "project_id": "p"}, "because")
    assert len(db.inserts) == 1


def test_an_unreadable_table_fails_open_and_records(db, monkeypatch):
    """A missing refusal is a silent DONE task, which is the failure this module
    exists to stop. Duplicating a row is the cheaper mistake."""
    def _select(table, params=None):
        if table == "admission_rejections":
            raise RuntimeError("unreachable")
        return []
    monkeypatch.setattr(db, "select", _select)
    done_to_merged.record_rejection({"slug": "s1", "project_id": "p"}, "because")
    assert len(db.inserts) == 1


def test_the_operator_alert_still_fires(db, capsys):
    """An operator's task finishing with no card must stay loud."""
    done_to_merged.record_rejection(
        {"slug": "s1", "project_id": "p", "submitted_by": "molly"}, "because")
    assert "ALERT: operator task" in capsys.readouterr().out


def test_a_slugless_task_is_still_recorded(db):
    done_to_merged.record_rejection({"project_id": "p"}, "because")
    assert len(db.inserts) == 1


# ── the hourly full sweep (added with the window, not after it) ───────────────
#
# Narrowing the per-tick scan to 24h is what takes it from 500 rows to 8. On its own
# it would also let a task that goes DONE without a card simply age out of view -- the
# same invisibility as the 500-row cap, arriving more slowly. One sweep an hour ignores
# the window entirely, and it lives inside reconcile_missing_cards() rather than in the
# scheduler so no caller can forget it.

@pytest.fixture
def sweep_home(tmp_path, monkeypatch):
    """A home with NO stamp, so the hourly sweep is due."""
    home = tmp_path / "sweep-home"
    monkeypatch.setenv("CLAUDE_ORCH_HOME", str(home))
    return home


def test_the_first_call_of_the_hour_ignores_the_window(db, sweep_home):
    done_to_merged.reconcile_missing_cards()
    assert "updated_at" not in db.queries[0][1], (
        "the hourly backstop did not run; an aged-out DONE task stays invisible")


def test_the_next_call_uses_the_window_again(db, sweep_home):
    done_to_merged.reconcile_missing_cards()
    db.queries.clear()
    done_to_merged.reconcile_missing_cards()
    assert "updated_at" in db.queries[0][1], "every pass is now a full sweep"


def test_the_sweep_comes_due_again(db, sweep_home, monkeypatch):
    done_to_merged.reconcile_missing_cards()
    monkeypatch.setattr(done_to_merged, "FULL_SWEEP_MIN", 0.0000001)
    assert done_to_merged._full_sweep_due()


def test_the_sweep_raises_the_row_limit(db, sweep_home):
    done_to_merged.reconcile_missing_cards(limit=10)
    assert int(db.queries[0][1]["limit"]) >= done_to_merged.FULL_SWEEP_LIMIT


def test_an_explicit_full_sweep_is_not_stamped(db, sweep_home):
    """within_hours=0 is a caller asking for one; it must not consume the hourly slot."""
    done_to_merged.reconcile_missing_cards(within_hours=0)
    db.queries.clear()
    done_to_merged.reconcile_missing_cards()
    assert "updated_at" not in db.queries[0][1], (
        "a manual sweep silently used up the automatic one")


def test_the_sweep_can_be_disabled(db, sweep_home, monkeypatch):
    monkeypatch.setattr(done_to_merged, "FULL_SWEEP_MIN", 0.0)
    done_to_merged.reconcile_missing_cards()
    assert "updated_at" in db.queries[0][1]


def test_an_unwritable_stamp_does_not_break_the_pass(db, sweep_home, monkeypatch):
    monkeypatch.setattr(done_to_merged, "_full_sweep_stamp_path",
                        lambda: "/proc/definitely/not/writable/stamp")
    out = done_to_merged.reconcile_missing_cards()
    assert out["errors"] == 0


def test_the_stamp_lives_under_claude_orch_home(sweep_home):
    """Tests must not stamp the live runtime dir -- the conftest fixture is why."""
    assert str(sweep_home) in done_to_merged._full_sweep_stamp_path()
