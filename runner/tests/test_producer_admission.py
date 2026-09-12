"""A producer that files work the fleet already has loses its quota. Any producer.

Over 30 days this fleet created 5,224 tasks and never attempted 3,980 (76%). Of those,
934 were filed for work that already existed and 320 were deduped as duplicates -- 31%
of the never-attempted pile was work the fleet already had.

The clearest offender was an external intake labelled "ChatGPT local-build audit
(operator-directed)": 1,920 tasks filed, 138 merged (7.2%), 0 ever deployed, 583
quarantined, 509 superseded. But 47 distinct producer labels were filing into this queue,
so nothing here names a vendor.

WHY THE SIGNAL IS REDUNDANCY, NOT MERGE RATE -- the test at the bottom pins this. Over
the same 14 days the WHOLE fleet merged 9 of 1,546 tasks (0.6%), because nine projects
were paused and the machine was thrashing. A merge-rate floor would have throttled nearly
every producer for a fault that belonged to the fleet. `backlog-batch` merged nothing
either, but only 2.4% of what it filed was redundant: a well-behaved producer in a broken
fleet. Redundancy separates them; merge rate does not.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import producer_admission as pa  # noqa: E402


class FakeDB:
    """Returns a fixed set of task rows for any select."""

    def __init__(self, rows):
        self.rows = rows
        self.calls = 0

    def select(self, table, query=None):
        self.calls += 1
        return list(self.rows)


def rows(filed, redundant=0, merged=0, recent=None):
    """`filed` rows, `redundant` of them work the fleet already had."""
    out = []
    for i in range(filed):
        state, note = "QUEUED", "queued"
        if i < redundant:
            state, note = "SUPERSEDED", "already integrated in orchestrator/dev"
        elif i < redundant + merged:
            state, note = "MERGED", "train: merged"
        out.append({"state": state, "note": note, "created_at": "2999-01-01T00:00:00Z"})
    if recent is not None:
        for i, r in enumerate(out):
            r["created_at"] = "2999-01-01T00:00:00Z" if i < recent else "1999-01-01T00:00:00Z"
    return out


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    pa.reset_cache()
    for key in ("ORCH_PRODUCER_ADMISSION", "ORCH_PRODUCER_MIN_SAMPLE",
                "ORCH_PRODUCER_REDUNDANT_CEILING", "ORCH_PRODUCER_THROTTLED_DAILY_CAP",
                "ORCH_PRODUCER_WINDOW_DAYS", "ORCH_PRODUCER_STATS_TTL_S"):
        monkeypatch.delenv(key, raising=False)
    yield
    pa.reset_cache()


CHATGPT = {"slug": "chatgpt-local-reconcile-tomorrow-abc123",
           "submitted_by_label": "ChatGPT local-build audit (operator-directed)"}

#: One read before the TTL expires, one after.
READS_AFTER_EXPIRY = 2


# ── identity ─────────────────────────────────────────────────────────────────────────

def test_a_label_identifies_the_producer():
    assert pa.producer_key(CHATGPT) == "label:ChatGPT local-build audit (operator-directed)"


def test_an_unlabelled_producer_is_grouped_by_its_slug_family():
    assert pa.producer_key({"slug": "chatgpt-local-reconcile-tomorrow-abc"}) == "slug:chatgpt-local"


def test_the_same_family_groups_across_projects():
    a = pa.producer_key({"slug": "chatgpt-local-reconcile-tomorrow-aaa"})
    b = pa.producer_key({"slug": "chatgpt-local-reconcile-smarter-bbb"})
    assert a == b


def test_an_unidentifiable_row_is_always_admitted():
    for row in ({}, {"slug": ""}, {"slug": "single"}, None):
        assert pa.producer_key(row) == ""
        assert pa.verdict(row, db=FakeDB([]))[0] is True


# ── the gate ─────────────────────────────────────────────────────────────────────────

def test_a_redundant_producer_over_its_daily_cap_is_throttled(monkeypatch):
    monkeypatch.setenv("ORCH_PRODUCER_MIN_SAMPLE", "50")
    monkeypatch.setenv("ORCH_PRODUCER_THROTTLED_DAILY_CAP", "25")
    db = FakeDB(rows(100, redundant=60))          # 60% redundant, all filed "today"
    admit, why = pa.verdict(CHATGPT, db=db)
    assert admit is False
    assert "60 of 100" in why
    assert "60.0%" in why


def test_the_refusal_says_the_quota_comes_back(monkeypatch):
    monkeypatch.setenv("ORCH_PRODUCER_MIN_SAMPLE", "50")
    db = FakeDB(rows(100, redundant=60))
    _admit, why = pa.verdict(CHATGPT, db=db)
    assert "not blocked" in why
    assert "returns as soon as" in why


def test_a_clean_producer_is_admitted_however_much_it_files(monkeypatch):
    monkeypatch.setenv("ORCH_PRODUCER_MIN_SAMPLE", "50")
    db = FakeDB(rows(500, redundant=5))           # 1% redundant
    assert pa.verdict(CHATGPT, db=db)[0] is True


def test_a_redundant_producer_under_its_daily_cap_still_files(monkeypatch):
    """Throttled means rationed, not silenced."""
    monkeypatch.setenv("ORCH_PRODUCER_MIN_SAMPLE", "50")
    monkeypatch.setenv("ORCH_PRODUCER_THROTTLED_DAILY_CAP", "25")
    db = FakeDB(rows(100, redundant=60, recent=10))   # only 10 filed in the last 24h
    assert pa.verdict(CHATGPT, db=db)[0] is True


def test_a_small_sample_is_never_judged(monkeypatch):
    monkeypatch.setenv("ORCH_PRODUCER_MIN_SAMPLE", "50")
    db = FakeDB(rows(20, redundant=20))           # 100% redundant but only 20 filed
    assert pa.verdict(CHATGPT, db=db)[0] is True


@pytest.mark.parametrize("redundant,expected_admit", [
    (0, True), (20, True), (35, True), (36, False), (60, False), (100, False),
])
def test_the_ceiling_is_where_it_says_it_is(monkeypatch, redundant, expected_admit):
    monkeypatch.setenv("ORCH_PRODUCER_MIN_SAMPLE", "50")
    monkeypatch.setenv("ORCH_PRODUCER_REDUNDANT_CEILING", "0.35")
    db = FakeDB(rows(100, redundant=redundant))
    assert pa.verdict(CHATGPT, db=db)[0] is expected_admit


# ── why not merge rate ───────────────────────────────────────────────────────────────

def test_a_producer_that_merges_nothing_but_files_no_duplicates_is_admitted():
    """THE POINT. Measured: the whole fleet merged 0.6% for a fortnight because nine
    projects were paused and the machine was thrashing. backlog-batch merged nothing and
    was 2.4% redundant. A merge-rate floor throttles it; redundancy correctly clears it."""
    db = FakeDB(rows(200, redundant=5, merged=0))
    admit, why = pa.verdict({"slug": "backlog-batch-beethoven-abc"}, db=db)
    assert admit is True, why


def test_a_producer_that_merges_well_but_floods_duplicates_is_throttled(monkeypatch):
    """The converse: merging some work does not license filing work we already have."""
    monkeypatch.setenv("ORCH_PRODUCER_MIN_SAMPLE", "50")
    db = FakeDB(rows(200, redundant=120, merged=40))   # 20% merged, 60% redundant
    assert pa.verdict(CHATGPT, db=db)[0] is False


# ── redundancy detection ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("note", [
    "semantic-dedupe: 0.971 duplicate of dropbox-mission-complete",
    "train: already integrated in orchestrator/dev @ b892885e",
    "cowork-executor-12: already delivered on master",
    "CLOSED: already completed by orch-operator",
    "backlog-compactor: collapsed into backlog-batch-beethoven-f298406",
])
def test_real_redundancy_notes_are_recognised(note):
    assert pa._is_redundant({"state": "QUEUED", "note": note}) is True


def test_the_superseded_state_counts_without_a_note():
    assert pa._is_redundant({"state": "SUPERSEDED", "note": ""}) is True


@pytest.mark.parametrize("note", [
    "train: tests failed on rebased agent/x",
    "agentic-repair:conflict",
    "",
])
def test_ordinary_failures_are_not_redundancy(note):
    assert pa._is_redundant({"state": "QUEUED", "note": note}) is False


# ── safety ───────────────────────────────────────────────────────────────────────────

def test_it_fails_open_when_the_evidence_cannot_be_read():
    class Broken:
        def select(self, *a, **kw):
            raise RuntimeError("database down")
    assert pa.verdict(CHATGPT, db=Broken())[0] is True


def test_a_producer_with_no_history_is_admitted():
    assert pa.verdict(CHATGPT, db=FakeDB([]))[0] is True


def test_the_gate_can_be_turned_off(monkeypatch):
    monkeypatch.setenv("ORCH_PRODUCER_ADMISSION", "false")
    assert pa.verdict(CHATGPT, db=FakeDB(rows(100, redundant=100)))[0] is True


def test_verdicts_are_cached_so_the_insert_path_stays_cheap(monkeypatch):
    monkeypatch.setenv("ORCH_PRODUCER_MIN_SAMPLE", "50")
    db = FakeDB(rows(100, redundant=60))
    for _ in range(5):
        pa.verdict(CHATGPT, db=db)
    assert db.calls == 1, "the DB was read %d times for one producer" % db.calls


def test_the_cache_expires(monkeypatch):
    monkeypatch.setenv("ORCH_PRODUCER_STATS_TTL_S", "30")
    db = FakeDB(rows(100, redundant=60))
    pa.verdict(CHATGPT, db=db)
    real = pa.time.time
    monkeypatch.setattr(pa.time, "time", lambda: real() + 100)
    pa.verdict(CHATGPT, db=db)
    assert db.calls == READS_AFTER_EXPIRY


# ── wiring, and the authority hole it depends on ─────────────────────────────────────

def test_db_insert_consults_the_gate():
    import db as db_mod
    src = open(db_mod.__file__.replace(".pyc", ".py")).read()
    assert "producer_admission.verdict(" in src
    assert '_record_refusal(row, "producer_admission"' in src


def test_operator_origin_needs_evidence_not_a_self_written_label():
    """A producer must not be able to grant itself operator authority.

    Measured: of 5,224 tasks in 30 days, ONE carried a real submitted_by id, 1,847
    carried only a self-written label, and 1,642 of those claimed "operator" in it.
    Operator origin bypasses the recovery-depth cap, release back-pressure and this gate.
    """
    import db as db_mod
    assert db_mod._is_operator_origin({"submitted_by_label": "totally the operator"}) is False
    assert db_mod._is_operator_origin(
        {"submitted_by_label": "ChatGPT local-build audit (operator-directed)"}) is False


def test_the_real_operator_paths_still_work():
    import db as db_mod
    assert db_mod._is_operator_origin({"slug": "dropbox-do-this-thing"}) is True
    assert db_mod._is_operator_origin({"submitted_by": "a-real-user-uuid"}) is True


def test_an_operator_can_explicitly_trust_a_label(monkeypatch):
    import db as db_mod
    monkeypatch.setenv("ORCH_TRUSTED_SUBMITTER_LABELS", "my trusted intake,another one")
    assert db_mod._is_operator_origin({"submitted_by_label": "My Trusted Intake"}) is True
    assert db_mod._is_operator_origin({"submitted_by_label": "some other bot"}) is False


def test_trusting_nothing_is_the_default(monkeypatch):
    import db as db_mod
    monkeypatch.delenv("ORCH_TRUSTED_SUBMITTER_LABELS", raising=False)
    assert db_mod._trusted_labels() == set()


# ── quota scaling by measured redundancy (added 2026-09-02) ───────────────────
#
# One flat cap treated 36% redundancy and 84% redundancy identically. Measured on the
# live fleet, 14-day window:
#
#     label:ChatGPT local-build audit   574 filed   3 merged   58.9% redundant
#     slug:recover-missing              154 filed   1 merged   61.0% redundant
#     slug:chatgpt-local                182 filed   1 merged   53.3% redundant
#     slug:log-p1                       285 filed   1 merged   53.0% redundant
#     slug:backlog-batch                 42 filed   0 merged    2.4% redundant  (clear)
#
# Four throttled producers, each still entitled to 25/day: up to 100 admissions a day
# from producers filing duplicates ~57% of the time. In the 24h to 18:40Z the fleet's
# own semantic-dedupe pass quarantined 95 near-duplicates (similarity 0.994-0.999) --
# the same number arriving by another route.

def test_a_producer_at_the_ceiling_keeps_the_full_cap():
    assert pa.quota_for(pa.redundant_ceiling()) \
        == pa.daily_cap()


def test_a_producer_below_the_ceiling_keeps_the_full_cap():
    assert pa.quota_for(0.0) == pa.daily_cap()


def test_quota_falls_as_redundancy_rises():
    a = pa.quota_for(0.40)
    b = pa.quota_for(0.60)
    c = pa.quota_for(0.85)
    assert a > b > c


def test_the_worst_possible_producer_still_gets_the_floor():
    """A throttle that reaches zero is a ban, and a producer filing mostly duplicates
    may still be the only source of the one thing that matters."""
    assert pa.quota_for(1.0) == pa.daily_floor()
    assert pa.daily_floor() > 0


def test_the_measured_producers_land_where_the_docstring_says():
    """The numbers in the docstring are load-bearing; assert them."""
    assert pa.quota_for(0.589) == 18
    assert pa.quota_for(0.530) == 19
    assert pa.quota_for(0.610) == 17
    assert pa.quota_for(0.842) == 10


def test_a_nonsense_rate_gets_the_full_cap():
    """Unmeasurable is not the same as bad -- the module's own rule."""
    assert pa.quota_for(None) == pa.daily_cap()
    assert pa.quota_for("x") == pa.daily_cap()


def test_quota_never_exceeds_the_cap_or_drops_below_the_floor():
    for i in range(0, 101):
        q = pa.quota_for(i / 100.0)
        assert pa.daily_floor() <= q <= pa.daily_cap()


def test_a_floor_above_the_cap_is_not_an_error(monkeypatch):
    monkeypatch.setenv("ORCH_PRODUCER_THROTTLED_DAILY_FLOOR", "999")
    assert pa.quota_for(0.9) == pa.daily_cap()


def test_the_refusal_reason_states_the_scaled_quota(monkeypatch):
    """An operator reading the log must see the quota that actually applied, not the
    ceiling constant."""
    monkeypatch.setattr(pa, "enabled", lambda: True)
    monkeypatch.setattr(pa, "producer_key", lambda row: "slug:x")
    monkeypatch.setattr(pa, "_measure", lambda key, db: {
        "filed": 200, "merged": 1, "redundant": 168, "redundant_rate": 0.84,
        "last_24h": 99})
    pa.reset_cache()
    ok, why = pa.verdict({"slug": "x-1"}, db=object())
    assert ok is False
    assert "quota 10/day" in why
    assert "floor" in why
