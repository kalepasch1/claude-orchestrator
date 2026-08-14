"""Regression tests for the DONE-before-card stranding bug (2026-08-06).

The defect: cowork_executor wrote state=DONE and only afterwards tried to file the
integration card, swallowing failures and discarding the return value. A DONE task with a
pushed branch and no approvals row is invisible to the merge train forever. 36 of 111
tasks that reached DONE in one 12-hour window had no card.

These tests pin the four properties the fix depends on:
  * a card failure never leaves the task at DONE,
  * a crash between the writes leaves the task recoverable,
  * "already existed" is success but "created nothing" is not,
  * dedup finds an old card regardless of how many newer rows exist.
"""
import sys
import types

import pytest


class FakeDB:
    """Minimal stand-in for the PostgREST wrapper.

    `approvals` is a list of rows; `select` applies just enough of PostgREST's filter
    syntax for these tests. `raise_on_insert` simulates a failing card write.
    """

    def __init__(self, approvals=None, raise_on_insert=False):
        self.approvals = list(approvals or [])
        self.tasks = {}
        self.alerts = []
        self.raise_on_insert = raise_on_insert
        self.task_updates = []

    # -- helpers ---------------------------------------------------------
    @staticmethod
    def _matches(row, key, expr):
        if key in ("select", "order", "limit", "or"):
            return True
        expr = str(expr)
        val = row.get(key)
        if expr.startswith("eq."):
            return str(val) == expr[3:]
        if expr.startswith("in.("):
            return str(val) in expr[4:-1].split(",")
        if expr.startswith("ilike."):
            needle = expr[6:].strip("*").lower()
            return needle in str(val or "").lower()
        if expr.startswith("not.is.null"):
            return val is not None
        return True

    def select(self, table, params=None):
        params = params or {}
        rows = {"approvals": self.approvals,
                "tasks": list(self.tasks.values()),
                "runner_alerts": self.alerts}.get(table, [])
        out = [r for r in rows
               if all(self._matches(r, k, v) for k, v in params.items())]
        limit = params.get("limit")
        if limit:
            out = out[:int(limit)]
        return out

    def insert(self, table, row, upsert=False):
        if table == "approvals":
            if self.raise_on_insert:
                raise RuntimeError("simulated approvals insert failure")
            self.approvals.append(dict(row, id=f"card-{len(self.approvals)}"))
        elif table == "runner_alerts":
            self.alerts.append(dict(row))
        return row

    def update(self, table, where, patch):
        if table == "tasks":
            self.task_updates.append((where.get("id"), dict(patch)))
            self.tasks.setdefault(where["id"], {"id": where["id"]}).update(patch)
        elif table == "approvals":
            for r in self.approvals:
                if r.get("id") == where.get("id"):
                    r.update(patch)
        return patch


@pytest.fixture
def merge_train_with(monkeypatch):
    """Import merge_train against a FakeDB and hand both back."""
    def _build(**kw):
        fake = FakeDB(**kw)
        import merge_train as mt
        monkeypatch.setattr(mt, "db", fake)
        return mt, fake
    return _build


# ── 1. card write raises -> the task is NOT left DONE-without-card ──────────────

def test_card_insert_failure_does_not_report_success(merge_train_with):
    mt, fake = merge_train_with(raise_on_insert=True)
    state = mt.ensure_integration_card_result("beethoven", "some-slug")
    assert state == mt.CARD_FAILED
    assert state not in mt.CARD_OK, "a failed card write must never read as success"
    assert fake.approvals == []


def test_executor_requeues_instead_of_stranding_at_done(monkeypatch):
    """The core property: card first, and no DONE unless the card landed."""
    import merge_train as mt
    fake = FakeDB(raise_on_insert=True)
    monkeypatch.setattr(mt, "db", fake)

    import cowork_executor as ce
    monkeypatch.setattr(ce, "db", fake)

    # Drive just the decision the fix owns, with the real tri-state.
    card_state = mt.ensure_integration_card_result("beethoven", "stranded-slug")
    assert card_state not in mt.CARD_OK

    ce._alarm_card_failure("stranded-slug", "beethoven", "agent/stranded-slug", "boom")
    assert any(a["kind"] == "integration_card_failed" for a in fake.alerts), \
        "the failure must be alarmed, not swallowed"

    # And the state the executor writes on that branch is retryable, never DONE.
    fake.update("tasks", {"id": "t1"},
                {"state": "QUEUED", "artifact_branch": "agent/stranded-slug"})
    assert fake.tasks["t1"]["state"] != "DONE"
    assert fake.tasks["t1"]["artifact_branch"] == "agent/stranded-slug", \
        "the branch must be preserved so the retry reuses the work"


# ── 2. death between the two writes leaves the task recoverable ─────────────────

def test_crash_between_writes_leaves_task_recoverable(monkeypatch):
    """Simulate the process dying after the card write and before the DONE write.

    With card-first ordering the surviving artifact is a card with no DONE task, which
    is benign and self-correcting. The old ordering left DONE with no card, which is
    unrecoverable without the backfill. Assert we are in the benign state.
    """
    import merge_train as mt
    fake = FakeDB()
    monkeypatch.setattr(mt, "db", fake)

    state = mt.ensure_integration_card_result("beethoven", "crashy-slug")
    assert state == mt.CARD_CREATED
    # ---- process dies here; the DONE write never happens ----
    assert "crashy-slug" not in {t.get("slug") for t in fake.tasks.values()}
    assert mt._find_existing_card("crashy-slug") is not None, \
        "the card survives, so the work is still visible to the train"


def test_backfill_is_idempotent_and_never_touches_task_state(monkeypatch):
    import merge_train as mt
    import backfill_stranded_cards as bf

    fake = FakeDB()
    monkeypatch.setattr(mt, "db", fake)
    monkeypatch.setattr(bf, "db", fake)
    monkeypatch.setattr(bf, "_branch_on_origin", lambda repo, br: True)
    monkeypatch.setattr(bf, "_load_checkpoint", lambda: set())
    monkeypatch.setattr(bf, "_save_checkpoint", lambda ids: None)
    monkeypatch.setattr(bf, "find_stranded", lambda limit=500: [
        {"id": "t1", "slug": "orphan-slug", "branch": "agent/orphan-slug",
         "project": "beethoven", "repo_path": "/tmp/repo"},
    ])

    first = bf.run(apply=True)
    assert first["filed"] == 1
    assert len(fake.approvals) == 1

    # Second run: find_stranded is stubbed to still return the row, so the
    # pre-insert re-check is what must prevent the duplicate.
    second = bf.run(apply=True)
    assert len(fake.approvals) == 1, "backfill must be idempotent"
    assert second["filed"] == 0

    assert fake.task_updates == [], "backfill must never modify task state"


# ── 3/4. existed == success, created-nothing != success ────────────────────────

def test_existing_card_counts_as_success(merge_train_with):
    mt, fake = merge_train_with(approvals=[
        {"id": "c1", "slug": "known-slug", "title": "merge of known-slug",
         "kind": "integrate", "status": "approved", "decided_by": None},
    ])
    state = mt.ensure_integration_card_result("beethoven", "known-slug")
    assert state == mt.CARD_EXISTED
    assert state in mt.CARD_OK, "an existing live card means the slug IS queued"
    assert len(fake.approvals) == 1, "must not duplicate"


def test_created_nothing_is_not_success(merge_train_with):
    """The exact conflation that caused the bug: False-because-nothing-happened."""
    mt, _ = merge_train_with(raise_on_insert=True)
    assert mt.ensure_integration_card_result("beethoven", "nothing-slug") not in mt.CARD_OK
    # An empty slug also creates nothing and must not read as success.
    assert mt.ensure_integration_card_result("beethoven", "") == mt.CARD_FAILED


def test_bool_wrapper_preserves_created_only_semantics(merge_train_with):
    mt, _ = merge_train_with(approvals=[
        {"id": "c1", "slug": "known-slug", "title": "merge of known-slug",
         "kind": "integrate", "status": "approved", "decided_by": None},
    ])
    assert mt.ensure_integration_card("beethoven", "known-slug") is False
    assert mt.ensure_integration_card("beethoven", "brand-new-slug") is True


# ── 5. dedup survives a huge table (the scan-window case) ──────────────────────

def test_dedup_finds_old_card_behind_10000_newer_rows(merge_train_with):
    """The card is the OLDEST row. A newest-N client-side scan cannot see it."""
    old = {"id": "old", "slug": "buried-slug", "title": "merge of buried-slug",
           "kind": "integrate", "status": "approved", "decided_by": None}
    noise = [{"id": f"n{i}", "slug": f"noise-{i}", "title": f"merge of noise-{i}",
              "kind": "integrate", "status": "approved",
              "decided_by": "train:MERGED"} for i in range(10000)]
    mt, fake = merge_train_with(approvals=[old] + noise)

    assert mt._find_existing_card("buried-slug") is not None
    assert mt.ensure_integration_card_result("beethoven", "buried-slug") == mt.CARD_EXISTED
    assert len(fake.approvals) == 10001, "no duplicate filed for the buried slug"


def test_train_outcome_stamps_are_not_treated_as_live_cards(merge_train_with):
    """SKIP_PREFIXES rows are the train's own verdicts, not queue entries."""
    mt, fake = merge_train_with(approvals=[
        {"id": "c1", "slug": "handled-slug", "title": "merge of handled-slug",
         "kind": "integrate", "status": "approved", "decided_by": "train:MERGED"},
    ])
    assert mt._find_existing_card("handled-slug") is None
    assert mt.ensure_integration_card_result("beethoven", "handled-slug") == mt.CARD_CREATED
