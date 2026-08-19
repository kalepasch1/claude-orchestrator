"""The dedup read must be scoped to this pass, not to an arbitrary slice of the table.

config_approval.sweep() files one approval card per unreviewed fleet_config entry, and
avoids re-filing by reading back the cards that already exist. That read asked the wrong
question: "give me 2000 config approvals, any 2000", unordered, over a table it was itself
growing.

The loop is self-amplifying, which is why it ran away instead of plateauing. Each re-filed
row makes the table bigger; a bigger table makes the fixed 2000-row window a smaller
fraction of it; a smaller fraction means more keys look unseen next pass. Measured on
2026-08-19 before the fix:

    77,206 config approval rows for 205 distinct fingerprints  (99.7% duplicates)
     7,386 of them written in the preceding 24 hours

It was also a multiplier on the same day's Supabase outage: ~200 pointless writes per
cycle, each paying a full request timeout against a 522ing plane. The "60 skipped lines per
cycle and nothing else in the log" symptom was this.

Two things now prevent it. The read is scoped to the fingerprints of the current pass, so
it cannot be outgrown. And a partial unique index on approvals(detail) WHERE kind='config'
makes a duplicate insert a 23505 -> PostgREST 409 -> db.insert() returns None, so the
runaway cannot recur even if this read is bypassed or misconfigured again.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config_approval as ca  # noqa: E402


class _DB:
    """Records every select so the test can assert on the QUESTION, not just the answer."""

    def __init__(self, config_rows=(), existing_fps=(), approvals_extra=0):
        self.config_rows = list(config_rows)
        self.existing = set(existing_fps)
        self.approvals_extra = approvals_extra
        self.selects = []
        self.inserts = []

    def select(self, table, params=None):
        self.selects.append((table, dict(params or {})))
        if table == "fleet_config":
            return self.config_rows
        if table == "approvals":
            asked = _asked_fingerprints(params or {})
            if asked is None:                      # unscoped read: the old behaviour
                rows = [{"detail": f"fp:{fp}"} for fp in sorted(self.existing)]
                rows += [{"detail": f"fp:noise{i}"} for i in range(self.approvals_extra)]
                limit = int((params or {}).get("limit") or 0)
                return rows[:limit] if limit else rows
            return [{"detail": f"fp:{fp}"} for fp in sorted(asked & self.existing)]
        return []

    def insert(self, table, values):
        self.inserts.append(values)
        return {"id": len(self.inserts)}


def _asked_fingerprints(params):
    """The fingerprints an approvals select explicitly asked about, or None if it asked for all."""
    detail = str(params.get("detail") or "")
    if not detail.startswith("in.("):
        return None
    inner = detail[len("in.("):].rstrip(")")
    return {p[3:] for p in inner.split(",") if p.startswith("fp:")}


def _rows(n, prefix="ORCH_KEY"):
    return [{"key": f"{prefix}_{i}", "value": str(i), "note": ""} for i in range(n)]


@pytest.fixture(autouse=True)
def enabled(monkeypatch):
    monkeypatch.setattr(ca, "ENABLED", True)


# --- the question it asks ----------------------------------------------------------------

def test_the_dedup_read_names_the_fingerprints_it_cares_about(monkeypatch):
    db = _DB(config_rows=_rows(5))
    monkeypatch.setattr(ca, "db", db)

    ca.sweep()

    approvals_reads = [p for t, p in db.selects if t == "approvals"]
    assert approvals_reads, "the sweep must still dedupe"
    for params in approvals_reads:
        assert _asked_fingerprints(params) is not None, (
            "the read is unscoped — it asks for an arbitrary slice of the approvals table "
            "and will be outgrown by the rows it is itself creating")


def test_it_asks_about_exactly_this_passs_entries(monkeypatch):
    rows = _rows(5)
    db = _DB(config_rows=rows)
    monkeypatch.setattr(ca, "db", db)

    ca.sweep()

    asked = set()
    for table, params in db.selects:
        if table == "approvals":
            asked |= _asked_fingerprints(params) or set()
    expected = {ca._fingerprint(r["key"], r["value"]) for r in rows}
    assert asked == expected


def test_the_read_does_not_grow_with_the_approvals_table(monkeypatch):
    """The property that broke. 100k unrelated rows must change nothing about the read."""
    rows = _rows(5)
    small = _DB(config_rows=rows)
    huge = _DB(config_rows=rows, approvals_extra=100_000)
    monkeypatch.setattr(ca, "db", small)
    ca.sweep()
    monkeypatch.setattr(ca, "db", huge)
    ca.sweep()

    assert ([p for t, p in small.selects if t == "approvals"] ==
            [p for t, p in huge.selects if t == "approvals"])


# --- the behaviour it protects -----------------------------------------------------------

def test_an_already_assessed_entry_is_not_re_filed(monkeypatch):
    rows = _rows(3)
    seen = {ca._fingerprint(r["key"], r["value"]) for r in rows}
    db = _DB(config_rows=rows, existing_fps=seen)
    monkeypatch.setattr(ca, "db", db)

    approved, gated = ca.sweep()

    assert db.inserts == [], "re-filed a card for an entry already assessed"
    assert (approved, gated) == (0, 0)


def test_an_already_assessed_entry_stays_unfiled_under_a_huge_table(monkeypatch):
    """The regression itself: 100k rows used to push real fingerprints out of the window."""
    rows = _rows(3)
    seen = {ca._fingerprint(r["key"], r["value"]) for r in rows}
    db = _DB(config_rows=rows, existing_fps=seen, approvals_extra=100_000)
    monkeypatch.setattr(ca, "db", db)

    ca.sweep()

    assert db.inserts == []


def test_a_new_entry_is_still_filed(monkeypatch):
    """The fix must not turn the dedup into a blanket suppressor."""
    rows = _rows(3)
    already = ca._fingerprint(rows[0]["key"], rows[0]["value"])
    db = _DB(config_rows=rows, existing_fps={already})
    monkeypatch.setattr(ca, "db", db)

    approved, gated = ca.sweep()

    assert approved + gated == 2
    assert len(db.inserts) == 2


def test_a_changed_value_is_treated_as_new(monkeypatch):
    """The fingerprint covers key AND value — editing a config must be re-assessed."""
    db = _DB(config_rows=[{"key": "MAX_PARALLEL", "value": "4", "note": ""}],
             existing_fps={ca._fingerprint("MAX_PARALLEL", "8")})
    monkeypatch.setattr(ca, "db", db)

    approved, gated = ca.sweep()

    assert approved + gated == 1


# --- bounds and failure modes ------------------------------------------------------------

def test_large_passes_are_chunked_rather_than_sent_as_one_enormous_filter(monkeypatch):
    """A 200-key `in.()` is a long URL; chunking keeps each request a sane size."""
    monkeypatch.setattr(ca, "SEEN_LOOKUP_CHUNK", 25)
    db = _DB(config_rows=_rows(120))
    monkeypatch.setattr(ca, "db", db)

    ca.sweep()

    reads = [p for t, p in db.selects if t == "approvals"]
    assert len(reads) == 5
    for params in reads:
        assert len(_asked_fingerprints(params)) <= 25


def test_no_entries_means_no_dedup_request_at_all(monkeypatch):
    db = _DB(config_rows=[])
    monkeypatch.setattr(ca, "db", db)

    ca.sweep()

    assert [t for t, _ in db.selects if t == "approvals"] == []


def test_an_unreadable_dedup_index_suppresses_rather_than_re_files(monkeypatch):
    """Fail toward NOT writing.

    An exception here means the control plane is unhappy -- precisely when a re-file storm
    does the most damage. Treating the chunk as already-seen costs one skipped cycle;
    treating it as unseen is the runaway this whole file is about.
    """
    rows = _rows(4)
    db = _DB(config_rows=rows)

    def exploding(table, params=None):
        if table == "approvals":
            raise RuntimeError("HTTP Error 522: status code 522")
        return rows

    db.select = exploding
    monkeypatch.setattr(ca, "db", db)

    approved, gated = ca.sweep()

    assert (approved, gated) == (0, 0)
    assert db.inserts == []
