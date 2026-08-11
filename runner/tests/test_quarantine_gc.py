#!/usr/bin/env python3
"""Tests for quarantine_gc — GC of non-recoverable QUARANTINED tasks.

quarantine_gc runs unattended every 600s against the live tasks table and rewrites
rows in bulk, so its selection rules are the only thing standing between "sweep the
PATCH TEMPLATE junk" and "archive recoverable work". It shipped wired into
periodic.py and runner.py with no test at all; these cover the decisions that
actually mutate rows:

  - which notes match (and, more importantly, which do NOT)
  - idempotency: a second pass must not re-GC what the first pass already marked
  - the ARCHIVED-state canary and its fallback to note-prefixing, since the DB may
    or may not carry ARCHIVED in the task-state enum
  - the cap, so one cycle can never rewrite an unbounded number of rows
  - fail-soft on a dead DB, because this runs headless
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db
import quarantine_gc


def _task(tid, note, state="QUARANTINED"):
    return {"id": tid, "slug": tid, "note": note, "state": state}


class _FakeDB:
    """Records update() calls and lets a test choose how ARCHIVED behaves."""

    def __init__(self, rows, archived_supported=True, fail_ids=()):
        self.rows = rows
        self.archived_supported = archived_supported
        self.fail_ids = set(fail_ids)
        self.updates = []          # (id, payload) in call order
        self.select_params = None

    def select(self, table, params=None):
        self.select_params = params
        return list(self.rows) if table == "tasks" else []

    def update(self, table, where, payload):
        tid = where["id"]
        if tid in self.fail_ids:
            raise RuntimeError("update rejected")
        if payload.get("state") == "ARCHIVED" and not self.archived_supported:
            raise RuntimeError('invalid input value for enum task_state: "ARCHIVED"')
        self.updates.append((tid, payload))
        return [{"id": tid}]


@pytest.fixture
def fake(monkeypatch):
    """Install a _FakeDB over the db module quarantine_gc imported."""

    def _install(rows, archived_supported=True, fail_ids=()):
        f = _FakeDB(rows, archived_supported, fail_ids)
        monkeypatch.setattr(db, "select", f.select)
        monkeypatch.setattr(db, "update", f.update)
        return f

    return _install


# ── selection rules ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("note", [
    "quarantined: PATCH TEMPLATE ce97319efbef",
    "patch-template-corrupt: no readable intent",
    "queue_janitor: dedup of sibling slice",
    "duplicate of improve-foo-slice-2",
    "semantic-dedupe collapsed this row",
    "PaTcH TeMpLaTe",                       # matching is case-insensitive
])
def test_non_recoverable_notes_are_collected(fake, note):
    f = fake([_task("t1", note)])
    result = quarantine_gc.gc_quarantine()
    assert result == {"found": 1, "archived": 1}
    assert f.updates[0][0] == "t1"


@pytest.mark.parametrize("note", [
    # Real notes carried by live QUARANTINED rows. Each names work someone still
    # intends to recover, so a widened pattern that swept these up would be a
    # silent data-loss bug rather than a visible failure.
    "recovered: restored from batch-orphan quarantine for re-evaluation by fixed materializer",
    "integration_sweeper: missing branch; queued recovery recover-missing-branch-foo",
    "auto-decomposed from improve-upgrade-to-a-high-performance-database-slice-3",
    "blocked: no code target found for slug; looked in runner/db.py",
    "push failed: permission denied",
    "",                      # empty note carries no evidence of junk
    None,                    # NULL note
])
def test_recoverable_and_unknown_notes_are_left_alone(fake, note):
    """Anything without a junk marker keeps its state — GC must not eat real work."""
    f = fake([_task("t1", note)])
    assert quarantine_gc.gc_quarantine() == {"found": 0, "archived": 0}
    assert f.updates == []


def test_duplicate_matches_as_a_substring(fake):
    """`duplicate` is deliberately unanchored, so "deduplicated" matches too.

    Pinned because it is surprising next to the anchored `\\bdedup\\b` alternative
    sitting beside it: anyone tightening that one to a word boundary would assume
    the same held here and could not tell from the pattern alone that it does not.
    """
    f = fake([_task("t1", "queue_janitor: deduplicated against sibling")])
    assert quarantine_gc.gc_quarantine()["found"] == 1


def test_already_gcd_rows_are_skipped(fake):
    """Idempotency: the job reruns every 600s over the same rows."""
    f = fake([_task("done", "GC: PATCH TEMPLATE abc"),
              _task("fresh", "PATCH TEMPLATE def")])
    assert quarantine_gc.gc_quarantine() == {"found": 1, "archived": 1}
    assert [tid for tid, _ in f.updates] == ["fresh"]


def test_second_pass_over_its_own_output_is_a_no_op(fake):
    """Run the job, feed its own result back in, and nothing further happens."""
    rows = [_task("t1", "PATCH TEMPLATE abc"), _task("t2", "duplicate row")]
    first = fake(rows)
    quarantine_gc.gc_quarantine()
    rewritten = [_task(tid, payload["note"]) for tid, payload in first.updates]
    second = fake(rewritten)
    assert quarantine_gc.gc_quarantine() == {"found": 0, "archived": 0}
    assert second.updates == []


def test_only_quarantined_rows_are_queried(fake):
    """The scan must be scoped server-side; a bad filter would reach live work."""
    f = fake([])
    quarantine_gc.gc_quarantine()
    assert f.select_params["state"] == "eq.QUARANTINED"


# ── ARCHIVED canary and fallback ─────────────────────────────────────────────

def test_uses_archived_state_when_the_enum_supports_it(fake):
    f = fake([_task("t1", "PATCH TEMPLATE a"), _task("t2", "duplicate b")])
    assert quarantine_gc.gc_quarantine() == {"found": 2, "archived": 2}
    assert all(payload["state"] == "ARCHIVED" for _, payload in f.updates)
    assert all(payload["note"].startswith("GC: ") for _, payload in f.updates)


def test_falls_back_to_note_prefix_when_archived_is_not_a_valid_state(fake):
    """No ARCHIVED enum value: mark via note prefix and leave state untouched."""
    f = fake([_task("t1", "PATCH TEMPLATE a"), _task("t2", "duplicate b")],
             archived_supported=False)
    result = quarantine_gc.gc_quarantine()
    assert result["found"] == 2
    assert f.updates, "fallback must still mark the rows"
    assert all("state" not in payload for _, payload in f.updates)
    assert all(payload["note"].startswith("GC: ") for _, payload in f.updates)


def test_canary_failure_does_not_lose_the_first_row(fake):
    """The canary row is retried through the fallback, not silently dropped."""
    f = fake([_task("t1", "PATCH TEMPLATE a"), _task("t2", "duplicate b")],
             archived_supported=False)
    quarantine_gc.gc_quarantine()
    assert "t1" in [tid for tid, _ in f.updates]


def test_original_note_is_preserved_behind_the_gc_prefix(fake):
    f = fake([_task("t1", "queue_janitor: dedup of sibling slice")])
    quarantine_gc.gc_quarantine()
    _, payload = f.updates[0]
    assert "dedup of sibling slice" in payload["note"]


def test_long_notes_are_truncated_to_fit_the_column(fake):
    f = fake([_task("t1", "PATCH TEMPLATE " + "x" * 4000)])
    quarantine_gc.gc_quarantine()
    _, payload = f.updates[0]
    assert len(payload["note"]) <= 500


# ── cap and fail-soft ────────────────────────────────────────────────────────

def test_cap_bounds_how_many_rows_one_cycle_rewrites(fake, monkeypatch):
    monkeypatch.setattr(quarantine_gc, "GC_CAP", 3)
    f = fake([_task(f"t{i}", "PATCH TEMPLATE junk") for i in range(50)])
    assert quarantine_gc.gc_quarantine()["found"] == 3
    assert len(f.updates) == 3


def test_query_failure_is_fail_soft(monkeypatch):
    """A dead DB must not raise out of a headless periodic job."""
    def _boom(*_a, **_kw):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(db, "select", _boom)
    assert quarantine_gc.gc_quarantine() == {"found": 0, "archived": 0}


def test_partial_update_failure_does_not_abort_the_batch(fake):
    """One bad row must not strand the rest of the sweep."""
    f = fake([_task("t1", "PATCH TEMPLATE a"),
              _task("t2", "duplicate b"),
              _task("t3", "semantic-dedupe c")],
             fail_ids={"t2"})
    result = quarantine_gc.gc_quarantine()
    assert "t3" in [tid for tid, _ in f.updates]
    assert result["found"] == 3
    assert result["archived"] < result["found"]


def test_empty_queue_is_reported_not_crashed(fake):
    fake([])
    assert quarantine_gc.gc_quarantine() == {"found": 0, "archived": 0}


# ── periodic wiring ──────────────────────────────────────────────────────────

def test_run_is_the_periodic_entry_point(fake):
    fake([_task("t1", "PATCH TEMPLATE a")])
    assert quarantine_gc.run() == {"found": 1, "archived": 1}


def test_job_is_registered_in_periodic_and_safe_while_paused():
    """quarantine_gc only moves task state, so it must survive the kill switch."""
    import periodic
    assert "quarantine_gc" in periodic.JOBS
    src = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "periodic.py")).read()
    assert '"quarantine_gc",' in src.split("_SAFE_WHEN_PAUSED")[1][:2000]
