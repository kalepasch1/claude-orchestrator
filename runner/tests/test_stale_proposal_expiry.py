"""An unacted proposal must stop blocking the problem it describes from being raised again.

is_duplicate() consulted EVERY prior proposal for an app, forever, regardless of whether
anyone ever acted on it. Measured 2026-09-02 across 1,004 proposals:

    merged        395   (all older than 21 days)
    proposed      315   oldest 2026-07-13, 314 older than 21 days
    SUPERSEDED    197
    for_review     65   64 older than 21 days
    shipped        21
    reviewed       10
    validated       1   -- one, ever

378 proposals that never reached an outcome were permanently suppressing the fleet's
ability to re-raise the bottlenecks they describe, while exactly one proposal in the
table's whole history was ever validated. The miner's own log said so every run:

    improvement_miner(measured): 7 bottlenecks, 0 proposals, 6 deduped, 0 gated off

A proposal that REACHED an outcome is evidence and keeps blocking forever -- re-proposing
merged, shipped, validated or superseded work is re-doing settled work. A proposal still
sitting in the intake queue is not evidence of anything.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import improvement_ledger as il  # noqa: E402

OLD = "2026-06-01T00:00:00Z"     # far past any sane expiry
RECENT = "2099-01-01T00:00:00Z"  # far future: never stale


@pytest.fixture(autouse=True)
def default_expiry(monkeypatch):
    monkeypatch.delenv("ORCH_IMPROVE_STALE_PROPOSAL_DAYS", raising=False)


# ── what expires ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("status", ["proposed", "for_review", "PROPOSED", "For_Review"])
def test_an_old_unacted_proposal_expires(status):
    assert il.is_inert({"status": status, "created_at": OLD}) is True


@pytest.mark.parametrize("status", ["merged", "shipped", "validated", "SUPERSEDED",
                                    "reviewed", "regressed"])
def test_a_real_outcome_blocks_forever(status):
    """Re-proposing settled work is re-doing settled work."""
    assert il.is_inert({"status": status, "created_at": OLD}) is False


def test_a_recent_proposal_still_blocks():
    """Yesterday's proposal is a live intake item, not a stale note."""
    assert il.is_inert({"status": "proposed", "created_at": RECENT}) is False


def test_an_undated_row_never_expires():
    """Without a date there is no evidence of staleness, so keep the old behaviour."""
    assert il.is_inert({"status": "proposed"}) is False
    assert il.is_inert({"status": "proposed", "created_at": ""}) is False


def test_an_unparseable_date_never_expires():
    assert il.is_inert({"status": "proposed", "created_at": "not a date"}) is False


def test_a_missing_status_is_treated_as_intake():
    assert il.is_inert({"status": "", "created_at": OLD}) is True
    assert il.is_inert({"created_at": OLD}) is True


# ── the knob ─────────────────────────────────────────────────────────────────────────

def test_the_expiry_defaults_to_three_weeks():
    assert il.stale_proposal_days() == 21


def test_the_expiry_is_configurable(monkeypatch):
    monkeypatch.setenv("ORCH_IMPROVE_STALE_PROPOSAL_DAYS", "60")
    assert il.stale_proposal_days() == 60
    assert il.is_inert({"status": "proposed", "created_at": OLD}) is True


def test_zero_disables_the_expiry(monkeypatch):
    """The old behaviour is one env var away."""
    monkeypatch.setenv("ORCH_IMPROVE_STALE_PROPOSAL_DAYS", "0")
    assert il.is_inert({"status": "proposed", "created_at": OLD}) is False


@pytest.mark.parametrize("value", ["", "nonsense", "-5"])
def test_a_bad_expiry_falls_back_to_the_default(monkeypatch, value):
    monkeypatch.setenv("ORCH_IMPROVE_STALE_PROPOSAL_DAYS", value)
    assert il.stale_proposal_days() >= 0


# ── the effect on dedupe ─────────────────────────────────────────────────────────────

CANDIDATE = {"app": "beethoven", "surface": "orchestration-layer",
             "metric_name": "pct_tasks_quarantined",
             "title": "cut the quarantine rate",
             "proposal": "reduce tasks quarantined by fixing the stub gate"}

SAME = dict(CANDIDATE)


def test_a_stale_unacted_proposal_no_longer_blocks_a_fresh_one():
    """THE POINT: the bottleneck can be raised again."""
    history = [dict(SAME, status="proposed", created_at=OLD, dedupe_key=None)]
    assert il.is_duplicate(CANDIDATE, history=history)["duplicate"] is False


def test_a_merged_proposal_still_blocks_the_same_idea():
    history = [dict(SAME, status="merged", created_at=OLD, dedupe_key=None)]
    assert il.is_duplicate(CANDIDATE, history=history)["duplicate"] is True


def test_a_recent_proposal_still_blocks_the_same_idea():
    history = [dict(SAME, status="proposed", created_at=RECENT, dedupe_key=None)]
    assert il.is_duplicate(CANDIDATE, history=history)["duplicate"] is True


def test_an_identical_dedupe_key_on_a_stale_row_also_stops_blocking():
    """The key path and the semantic path must agree about what is stale."""
    key = il.dedupe_key("beethoven", "orchestration-layer", "pct_tasks_quarantined",
                        "cut the quarantine rate")
    history = [dict(SAME, status="proposed", created_at=OLD, dedupe_key=key)]
    assert il.is_duplicate(dict(CANDIDATE, dedupe_key=key),
                           history=history)["duplicate"] is False


def test_an_identical_dedupe_key_on_a_MERGED_row_still_blocks():
    key = il.dedupe_key("beethoven", "orchestration-layer", "pct_tasks_quarantined",
                        "cut the quarantine rate")
    history = [dict(SAME, status="merged", created_at=OLD, dedupe_key=key)]
    assert il.is_duplicate(dict(CANDIDATE, dedupe_key=key),
                           history=history)["duplicate"] is True


def test_one_stale_row_does_not_hide_a_live_one_behind_it():
    """Order must not decide the verdict."""
    history = [dict(SAME, status="proposed", created_at=OLD, dedupe_key=None),
               dict(SAME, status="merged", created_at=OLD, dedupe_key=None)]
    assert il.is_duplicate(CANDIDATE, history=history)["duplicate"] is True


def test_the_history_query_fetches_the_date_it_now_needs():
    """Structural: without created_at every row would look undated and never expire."""
    src = open(il.__file__.replace(".pyc", ".py")).read()
    start = src.index("def _history(")
    assert "created_at" in src[start:start + 500], src[start:start + 500]
