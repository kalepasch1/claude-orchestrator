#!/usr/bin/env python3
"""Coverage for the queue_counters snapshot cache (real-time queue state, slice 1).

The invariants under test:
  * a cache HIT costs zero round-trips, and a miss costs exactly what it always did;
  * cached values are identical to uncached ones — the cache changes latency, not answers;
  * a caller passing its OWN db client never receives another client's snapshot;
  * TTL=0 restores the previous always-fresh behaviour exactly;
  * a broken counters view is reported, never silently swallowed.
"""
import importlib.util
import os
import sys

import pytest

_RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _RUNNER)


def _load_real_queue_counters():
    """Load queue_counters from disk, bypassing sys.modules.

    `test_scoreboard_history.py` installs a permanent ModuleType stub under the name
    `queue_counters` at import time and never removes it, so a plain
    `import queue_counters` here binds the stub or the real module depending purely on
    collection order — which is how this file passed alone and errored in the full run.
    Loading from the file path makes the import order-independent, and does it without
    reaching into another test module's global side effects to undo them.
    """
    spec = importlib.util.spec_from_file_location(
        "_real_queue_counters", os.path.join(_RUNNER, "queue_counters.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


qc = _load_real_queue_counters()


def full_read():
    """Round-trips one uncached fallback read costs.

    12 states + total + 2 prefixes + 1 canary + 5 release-fix prefixes counted twice.

    Deliberately a function, not a module-level constant: another test module in the
    suite installs a stub named `queue_counters` in sys.modules, and reading attributes
    off `qc` at import time made this whole file fail to COLLECT when run alongside it.
    """
    return len(qc.QUEUE_STATES) + 4 + 2 * len(qc.RELEASE_FIX_PREFIXES)


class CountingDB:
    """Counts round-trips so 'the cache saved calls' is measurable, not assumed."""

    def __init__(self, view_rows=None, view_explodes=False, n=7):
        self.count_calls = 0
        self.select_calls = 0
        self.view_rows = view_rows
        self.view_explodes = view_explodes
        self.n = n

    def count(self, table, params=None):
        self.count_calls += 1
        return self.n

    def select(self, table, params=None):
        self.select_calls += 1
        if self.view_explodes:
            raise RuntimeError("view missing")
        return list(self.view_rows or [])


@pytest.fixture(autouse=True)
def clean_cache(monkeypatch):
    monkeypatch.delenv("ORCH_QUEUE_COUNTER_TTL", raising=False)
    qc.invalidate()
    qc._snapshot.hits = 0
    qc._snapshot.misses = 0
    yield
    qc.invalidate()


@pytest.fixture()
def default_db(monkeypatch):
    """Install a fake as the module's DEFAULT client.

    Only the default client is cached (see exact_counts), so a test that passed its fake
    positionally would silently measure the uncached path and assert nothing.
    """
    db = CountingDB(view_explodes=True)
    monkeypatch.setattr(qc, "db", db)
    return db


# ── round-trip cost ─────────────────────────────────────────────────────────

def test_a_miss_still_costs_the_full_read(default_db):
    qc.exact_counts()
    assert default_db.count_calls == full_read()


def test_second_call_within_ttl_costs_zero_round_trips(default_db):
    qc.exact_counts(ttl=60)
    qc.exact_counts(ttl=60)
    assert default_db.count_calls == full_read()
    assert qc.stats()["hits"] == 1


def test_ten_pollers_share_one_read(default_db):
    for _ in range(10):
        qc.exact_counts(ttl=60)
    assert default_db.count_calls == full_read()
    assert qc.stats()["hits"] == 9


# ── the cache must not change answers ───────────────────────────────────────

def test_cached_payload_equals_the_uncached_one(default_db):
    uncached = qc.exact_counts(ttl=0)
    qc.invalidate()
    warmed = qc.exact_counts(ttl=60)
    assert qc.exact_counts(ttl=60) == uncached == warmed


def test_mutating_a_returned_dict_cannot_poison_the_cache(default_db):
    first = qc.exact_counts(ttl=60)
    first["queued"] = 999_999
    assert qc.exact_counts(ttl=60)["queued"] != 999_999


def test_expiry_recomputes(default_db):
    qc.exact_counts(ttl=60)
    qc._snapshot._at -= 120  # age the snapshot past its TTL
    qc.exact_counts(ttl=60)
    assert default_db.count_calls == 2 * full_read()


# ── cross-client isolation (regression) ─────────────────────────────────────

def test_an_explicit_client_never_receives_the_default_clients_snapshot(default_db):
    """Regression: the first draft keyed the cache on nothing and crossed fixtures."""
    qc.exact_counts(ttl=60)               # warms the cache from default_db (n=7)
    other = CountingDB(view_explodes=True, n=99)
    assert qc.exact_counts(other, ttl=60)["queued"] == 99
    assert other.count_calls == full_read()


def test_an_explicit_client_never_populates_the_shared_cache(default_db):
    qc.exact_counts(CountingDB(view_explodes=True, n=99), ttl=60)
    assert qc.stats()["cached"] is False
    assert qc.exact_counts(ttl=60)["queued"] == 7


# ── opt-outs ────────────────────────────────────────────────────────────────

def test_ttl_zero_disables_caching_entirely(default_db):
    qc.exact_counts(ttl=0)
    qc.exact_counts(ttl=0)
    assert default_db.count_calls == 2 * full_read()


def test_fresh_bypasses_and_clears_a_warm_cache(default_db):
    qc.exact_counts(ttl=60)
    qc.exact_counts(ttl=60, fresh=True)
    assert default_db.count_calls == 2 * full_read()
    assert qc.stats()["cached"] is False


def test_invalidate_forces_the_next_read_to_recompute(default_db):
    qc.exact_counts(ttl=60)
    qc.invalidate()
    qc.exact_counts(ttl=60)
    assert default_db.count_calls == 2 * full_read()


def test_env_var_sets_the_default_ttl(default_db, monkeypatch):
    monkeypatch.setenv("ORCH_QUEUE_COUNTER_TTL", "0")
    qc.exact_counts()
    qc.exact_counts()
    assert default_db.count_calls == 2 * full_read()


def test_a_garbage_ttl_env_value_falls_back_to_the_default(monkeypatch):
    monkeypatch.setenv("ORCH_QUEUE_COUNTER_TTL", "not-a-number")
    assert qc._default_ttl() == 5.0


def test_negative_ttl_is_clamped_not_treated_as_infinite(monkeypatch):
    monkeypatch.setenv("ORCH_QUEUE_COUNTER_TTL", "-10")
    assert qc._default_ttl() == 0.0


# ── the view fast-path ──────────────────────────────────────────────────────

def _view_rows():
    return [{"bucket": "state", "name": "QUEUED", "n": 3},
            {"bucket": "state", "name": "RUNNING", "n": 1},
            {"bucket": "total", "name": "tasks", "n": 4}]


def test_view_path_costs_one_round_trip_not_the_full_read():
    db = CountingDB(view_rows=_view_rows())
    result = qc.exact_counts(db, ttl=0)
    assert result["source"] == "v_task_queue_counters"
    assert db.count_calls == 0
    assert db.select_calls == 1


def test_broken_view_is_reported_before_it_is_swallowed(capsys):
    result = qc.exact_counts(CountingDB(view_explodes=True), ttl=0)
    assert result["source"] == "postgrest_exact_count"
    printed = capsys.readouterr().out
    assert "v_task_queue_counters unavailable" in printed
    assert "RuntimeError" in printed


def test_broken_view_still_returns_correct_counters():
    result = qc.exact_counts(CountingDB(view_explodes=True), ttl=0)
    assert result["queued"] == 7
    assert result["active_like"] == 21


# ── observability ───────────────────────────────────────────────────────────

def test_stats_reports_emptiness_before_any_read():
    s = qc.stats()
    assert s["cached"] is False and s["age"] is None


def test_stats_reports_a_warm_cache_with_an_age(default_db):
    qc.exact_counts(ttl=60)
    s = qc.stats()
    assert s["cached"] is True
    assert s["age"] is not None and s["age"] >= 0


def test_hit_and_miss_counters_track_reality(default_db):
    qc.exact_counts(ttl=60)
    qc.exact_counts(ttl=60)
    qc.exact_counts(ttl=60)
    s = qc.stats()
    assert s["misses"] == 1 and s["hits"] == 2
