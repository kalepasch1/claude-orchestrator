#!/usr/bin/env python3
"""Tests for runner/critical_alert.py.

Covers the two hard ceilings (disk usage, error rate), the minimum-sample
guard that keeps a 1-of-3 failure run from paging, the fail-soft contract on
every probe, and the dispatch path into error_alerter.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import critical_alert  # noqa: E402


@pytest.fixture(autouse=True)
def _reset():
    critical_alert.reset()
    yield
    critical_alert.reset()


# ---------------------------------------------------------------- disk probe


def test_disk_usage_pct_returns_plausible_percentage():
    pct = critical_alert.disk_usage_pct()
    assert 0.0 <= pct <= 100.0


def test_disk_usage_pct_missing_path_is_fail_soft():
    assert critical_alert.disk_usage_pct("/no/such/path/anywhere") == 0.0


def test_disk_usage_pct_none_is_fail_soft():
    assert critical_alert.disk_usage_pct(None) >= 0.0


# ---------------------------------------------------------- error-rate probe


def test_error_rate_returns_tuple():
    rate, sample = critical_alert.error_rate()
    assert 0.0 <= rate <= 1.0
    assert sample >= 0


def _fake_db(counts, record=None):
    """A stub of the PostgREST-shaped db module. `counts` maps state-filter -> count."""
    class _Fake:
        @staticmethod
        def count(table, params=None):
            params = params or {}
            if record is not None:
                record.append((table, dict(params)))
            return counts[params.get("state")]

    return _Fake


def test_error_rate_db_failure_is_fail_soft(monkeypatch):
    class _Boom:
        @staticmethod
        def count(*_a, **_k):
            raise RuntimeError("db down")

    monkeypatch.setitem(sys.modules, "db", _Boom)
    assert critical_alert.error_rate() == (0.0, 0)


def test_error_rate_none_count_is_zero(monkeypatch):
    monkeypatch.setitem(sys.modules, "db", _fake_db(
        {"in.(DONE,MERGED,FAILED,BLOCKED,QUARANTINED)": None,
         "in.(FAILED,BLOCKED,QUARANTINED)": None}))
    assert critical_alert.error_rate() == (0.0, 0)


def test_error_rate_computes_fraction(monkeypatch):
    monkeypatch.setitem(sys.modules, "db", _fake_db(
        {"in.(DONE,MERGED,FAILED,BLOCKED,QUARANTINED)": 100,
         "in.(FAILED,BLOCKED,QUARANTINED)": 9}))
    rate, sample = critical_alert.error_rate()
    assert rate == pytest.approx(0.09)
    assert sample == 100


def test_error_rate_zero_total_does_not_divide_by_zero(monkeypatch):
    monkeypatch.setitem(sys.modules, "db", _fake_db(
        {"in.(DONE,MERGED,FAILED,BLOCKED,QUARANTINED)": 0,
         "in.(FAILED,BLOCKED,QUARANTINED)": 0}))
    assert critical_alert.error_rate() == (0.0, 0)


def test_error_rate_does_not_query_failures_when_there_is_no_sample(monkeypatch):
    """The second round trip is skipped when the first says the window is empty."""
    seen = []
    monkeypatch.setitem(sys.modules, "db", _fake_db(
        {"in.(DONE,MERGED,FAILED,BLOCKED,QUARANTINED)": 0,
         "in.(FAILED,BLOCKED,QUARANTINED)": 0}, record=seen))
    critical_alert.error_rate()
    assert len(seen) == 1


def test_error_rate_filters_on_the_window(monkeypatch):
    seen = []
    monkeypatch.setitem(sys.modules, "db", _fake_db(
        {"in.(DONE,MERGED,FAILED,BLOCKED,QUARANTINED)": 10,
         "in.(FAILED,BLOCKED,QUARANTINED)": 1}, record=seen))
    critical_alert.error_rate(window_minutes=30)
    assert seen and seen[0][0] == "tasks"
    assert seen[0][1]["updated_at"].startswith("gt.")


def test_error_rate_uses_postgrest_not_raw_sql(monkeypatch):
    """Regression guard: this fleet's db module has no query()/execute()."""
    import db as real_db

    assert not hasattr(real_db, "query")
    assert callable(getattr(real_db, "count", None))


# ------------------------------------------------------------------ evaluate


def test_evaluate_healthy_returns_empty(monkeypatch):
    monkeypatch.setattr(critical_alert, "disk_usage_pct", lambda *_a, **_k: 10.0)
    monkeypatch.setattr(critical_alert, "error_rate", lambda *_a, **_k: (0.0, 500))
    assert critical_alert.evaluate() == []


def test_evaluate_flags_disk_above_ceiling(monkeypatch):
    monkeypatch.setattr(critical_alert, "disk_usage_pct", lambda *_a, **_k: 97.5)
    monkeypatch.setattr(critical_alert, "error_rate", lambda *_a, **_k: (0.0, 500))
    conds = critical_alert.evaluate()
    assert [c["metric"] for c in conds] == ["disk_usage_pct"]
    assert conds[0]["pattern"] == "disk_full"
    assert conds[0]["value"] == pytest.approx(97.5)


def test_evaluate_disk_exactly_at_ceiling_does_not_fire(monkeypatch):
    monkeypatch.setattr(
        critical_alert, "disk_usage_pct",
        lambda *_a, **_k: critical_alert.DISK_CRITICAL_PCT,
    )
    monkeypatch.setattr(critical_alert, "error_rate", lambda *_a, **_k: (0.0, 500))
    assert critical_alert.evaluate() == []


def test_evaluate_flags_error_rate_above_ceiling(monkeypatch):
    monkeypatch.setattr(critical_alert, "disk_usage_pct", lambda *_a, **_k: 10.0)
    monkeypatch.setattr(critical_alert, "error_rate", lambda *_a, **_k: (0.4, 200))
    conds = critical_alert.evaluate()
    assert [c["metric"] for c in conds] == ["error_rate"]
    assert conds[0]["pattern"] == "test_failure"


def test_evaluate_small_sample_does_not_fire(monkeypatch):
    """1 failure out of 3 is 33% and means nothing."""
    monkeypatch.setattr(critical_alert, "disk_usage_pct", lambda *_a, **_k: 10.0)
    monkeypatch.setattr(critical_alert, "error_rate", lambda *_a, **_k: (0.33, 3))
    assert critical_alert.evaluate() == []


def test_evaluate_reports_both_conditions(monkeypatch):
    monkeypatch.setattr(critical_alert, "disk_usage_pct", lambda *_a, **_k: 99.0)
    monkeypatch.setattr(critical_alert, "error_rate", lambda *_a, **_k: (0.9, 100))
    assert len(critical_alert.evaluate()) == 2


def test_evaluate_updates_counters(monkeypatch):
    monkeypatch.setattr(critical_alert, "disk_usage_pct", lambda *_a, **_k: 99.0)
    monkeypatch.setattr(critical_alert, "error_rate", lambda *_a, **_k: (0.0, 500))
    critical_alert.evaluate()
    s = critical_alert.stats()
    assert s["evaluations"] == 1
    assert s["conditions_met"] == 1
    assert s["last_eval_ts"] > 0


# --------------------------------------------------------------- dispatching


class _RecordingAlerter:
    def __init__(self):
        self.calls = []

    def alert(self, pattern, project_id="", detail="", severity=""):
        self.calls.append((pattern, project_id, detail, severity))
        return True


def test_trigger_dispatches_one_alert_per_condition(monkeypatch):
    rec = _RecordingAlerter()
    monkeypatch.setitem(sys.modules, "error_alerter", rec)
    monkeypatch.setattr(critical_alert, "disk_usage_pct", lambda *_a, **_k: 99.0)
    monkeypatch.setattr(critical_alert, "error_rate", lambda *_a, **_k: (0.9, 100))

    out = critical_alert.trigger_critical_alert()
    assert out["dispatched"] == 2
    assert len(rec.calls) == 2
    assert all(c[3] == "critical" for c in rec.calls)


def test_trigger_healthy_dispatches_nothing(monkeypatch):
    rec = _RecordingAlerter()
    monkeypatch.setitem(sys.modules, "error_alerter", rec)
    monkeypatch.setattr(critical_alert, "disk_usage_pct", lambda *_a, **_k: 5.0)
    monkeypatch.setattr(critical_alert, "error_rate", lambda *_a, **_k: (0.0, 500))

    out = critical_alert.trigger_critical_alert()
    assert out == {"conditions": [], "dispatched": 0, "enabled": True}
    assert rec.calls == []


def test_trigger_dry_run_evaluates_without_dispatching(monkeypatch):
    rec = _RecordingAlerter()
    monkeypatch.setitem(sys.modules, "error_alerter", rec)
    monkeypatch.setattr(critical_alert, "disk_usage_pct", lambda *_a, **_k: 99.0)
    monkeypatch.setattr(critical_alert, "error_rate", lambda *_a, **_k: (0.0, 500))

    out = critical_alert.trigger_critical_alert(dry_run=True)
    assert len(out["conditions"]) == 1
    assert out["dispatched"] == 0
    assert rec.calls == []


def test_trigger_disabled_short_circuits(monkeypatch):
    monkeypatch.setattr(critical_alert, "ENABLED", False)
    out = critical_alert.trigger_critical_alert()
    assert out == {"conditions": [], "dispatched": 0, "enabled": False}
    assert critical_alert.stats()["evaluations"] == 0


def test_trigger_delivery_failure_is_fail_soft(monkeypatch):
    class _Boom:
        @staticmethod
        def alert(*_a, **_k):
            raise RuntimeError("webhook exploded")

    monkeypatch.setitem(sys.modules, "error_alerter", _Boom)
    monkeypatch.setattr(critical_alert, "disk_usage_pct", lambda *_a, **_k: 99.0)
    monkeypatch.setattr(critical_alert, "error_rate", lambda *_a, **_k: (0.0, 500))

    out = critical_alert.trigger_critical_alert()
    assert out["dispatched"] == 0
    assert len(out["conditions"]) == 1


def test_trigger_delivery_failure_writes_a_diagnostic(monkeypatch, capsys):
    """A swallowed failure that leaves no trace is how an outage goes unnoticed."""
    class _Boom:
        @staticmethod
        def alert(*_a, **_k):
            raise RuntimeError("nope")

    monkeypatch.setitem(sys.modules, "error_alerter", _Boom)
    monkeypatch.setattr(critical_alert, "disk_usage_pct", lambda *_a, **_k: 99.0)
    monkeypatch.setattr(critical_alert, "error_rate", lambda *_a, **_k: (0.0, 500))

    critical_alert.trigger_critical_alert()
    assert "critical_alert" in capsys.readouterr().err


def test_trigger_suppressed_delivery_counts_zero(monkeypatch):
    """error_alerter.alert() returning False (cooldown) is not a dispatch."""
    class _Cooled:
        @staticmethod
        def alert(*_a, **_k):
            return False

    monkeypatch.setitem(sys.modules, "error_alerter", _Cooled)
    monkeypatch.setattr(critical_alert, "disk_usage_pct", lambda *_a, **_k: 99.0)
    monkeypatch.setattr(critical_alert, "error_rate", lambda *_a, **_k: (0.0, 500))

    assert critical_alert.trigger_critical_alert()["dispatched"] == 0


# --------------------------------------------------------------- module shape


def test_stats_returns_a_copy():
    critical_alert.stats()["evaluations"] = 999
    assert critical_alert.stats()["evaluations"] == 0


def test_reset_clears_counters(monkeypatch):
    monkeypatch.setattr(critical_alert, "disk_usage_pct", lambda *_a, **_k: 99.0)
    monkeypatch.setattr(critical_alert, "error_rate", lambda *_a, **_k: (0.0, 500))
    critical_alert.evaluate()
    critical_alert.reset()
    assert critical_alert.stats()["evaluations"] == 0


def test_thresholds_are_named_constants_not_literals():
    assert critical_alert.DISK_CRITICAL_PCT > 0
    assert 0 < critical_alert.ERROR_RATE_CRITICAL < 1
    assert critical_alert.ERROR_RATE_MIN_SAMPLE > 0


def test_module_functions_delegate_to_singleton_state():
    assert set(critical_alert.stats()) >= {
        "evaluations", "conditions_met", "dispatched", "last_eval_ts",
    }
