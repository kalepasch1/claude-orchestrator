"""Canary test: canary_economics promote/rollback gate (xai-6).

`canary_economics.decide()` is the gate that decides whether a canary reaches production,
and it had no test file at all — the only uncovered module among runner/canary*.py. These
are pure-function checks: `_canary_ops` and `_slo` are stubbed, so nothing here touches the
database or the network.

The gate's contract, in the order decide() applies it:
  1. no telemetry            -> hold      (never promote on silence)
  2. median quality below    -> rollback  (checked BEFORE the mean: outliers inflate a mean)
  3. mean quality below      -> rollback
  4. error spike             -> rollback  (> max(1, len(ops)//10))
  5. cost over hard ceiling  -> rollback
  6. otherwise               -> promote
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import canary_economics as ce


def op(quality=9.0, cost=0.10, ok=True):
    return {"quality_score": quality, "cost_usd": cost, "ok": ok}


@pytest.fixture
def gate(monkeypatch):
    """Drive decide() with an explicit ops list and SLO; no DB, no network."""
    def configure(ops, slo=None):
        monkeypatch.setattr(ce, "_canary_ops", lambda app, minutes: ops)
        monkeypatch.setattr(ce, "_slo", lambda app: slo or {
            "target_usd_per_merge": 1.0, "hard_ceiling_usd_per_merge": None})
        return ce.decide("demoapp")
    return configure


# --- 1. silence is not success ---------------------------------------------

def test_no_telemetry_holds_rather_than_promoting(gate):
    """The important direction: absence of evidence must never read as a pass."""
    result = gate([])
    assert result["decision"] == "hold"
    assert "no canary telemetry" in result["why"]


# --- 2/3. quality gates -----------------------------------------------------

def test_good_quality_and_no_errors_promotes(gate):
    result = gate([op(), op(), op()])
    assert result["decision"] == "promote"
    assert result["sample_size"] == 3
    assert result["error_pct"] == 0.0


def test_low_mean_quality_rolls_back(gate):
    result = gate([op(quality=2.0), op(quality=2.0)])
    assert result["decision"] == "rollback"
    assert "quality" in result["why"]


def test_the_median_catches_what_an_inflated_mean_would_hide(gate):
    """One brilliant outlier lifts the mean over the bar; the median must still fail it.
    This is why decide() checks the median FIRST."""
    ops = [op(quality=1.0), op(quality=1.0), op(quality=1.0), op(quality=100.0)]
    mean = sum(o["quality_score"] for o in ops) / len(ops)
    assert mean > ce.QUALITY_MIN, "fixture must actually inflate the mean"
    result = gate(ops)
    assert result["decision"] == "rollback"
    assert "median" in result["why"]


def test_quality_exactly_at_the_threshold_is_not_a_rollback(gate):
    """The comparison is `< QUALITY_MIN`; the boundary passes."""
    assert gate([op(quality=ce.QUALITY_MIN)])["decision"] == "promote"


def test_missing_quality_scores_do_not_crash_the_gate(gate):
    result = gate([op(quality=None), op(quality=None)])
    assert result["decision"] in ("promote", "rollback", "hold")


# --- 4. error spike ---------------------------------------------------------

def test_an_error_spike_rolls_back(gate):
    result = gate([op(ok=False) for _ in range(5)])
    assert result["decision"] == "rollback"
    assert "error spike" in result["why"]


def test_a_single_error_in_a_small_sample_is_tolerated(gate):
    """Threshold is `> max(1, len//10)`, so one failure never trips it on its own."""
    assert gate([op(ok=False), op(), op()])["decision"] == "promote"


def test_error_pct_is_reported_on_a_promote(gate):
    result = gate([op(ok=False)] + [op() for _ in range(19)])
    assert result["decision"] == "promote"
    assert result["error_pct"] == 5.0


# --- 5. cost ceiling --------------------------------------------------------

def test_cost_over_the_hard_ceiling_rolls_back(gate):
    result = gate([op(cost=5.0), op(cost=5.0)],
                  slo={"hard_ceiling_usd_per_merge": 1.0})
    assert result["decision"] == "rollback"
    assert "ceiling" in result["why"]


def test_no_ceiling_configured_does_not_block_a_promote(gate):
    result = gate([op(cost=99.0)], slo={"hard_ceiling_usd_per_merge": None})
    assert result["decision"] == "promote"


def test_cost_at_the_ceiling_is_not_over_it(gate):
    result = gate([op(cost=1.0)], slo={"hard_ceiling_usd_per_merge": 1.0})
    assert result["decision"] == "promote"


def test_a_missing_cost_counts_as_zero_not_as_a_crash(gate):
    result = gate([{"quality_score": 9.0, "ok": True}],
                  slo={"hard_ceiling_usd_per_merge": 1.0})
    assert result["decision"] == "promote"


# --- ordering ---------------------------------------------------------------

def test_quality_is_judged_before_cost(gate):
    """Both are violated; the reported reason must name the quality failure, so an
    operator reading the rollback sees the primary cause rather than a side effect."""
    result = gate([op(quality=1.0, cost=99.0)],
                  slo={"hard_ceiling_usd_per_merge": 1.0})
    assert result["decision"] == "rollback"
    assert "quality" in result["why"]


def test_every_decision_names_the_app_and_carries_a_reason(gate):
    for ops in ([], [op()], [op(quality=1.0)]):
        result = gate(ops)
        assert result["app"] == "demoapp"
        assert result["why"]


# --- _median ----------------------------------------------------------------

def test_median_of_an_odd_length_list():
    assert ce._median([3.0, 1.0, 2.0]) == 2.0


def test_median_of_an_even_length_list_averages_the_middle_pair():
    assert ce._median([1.0, 2.0, 3.0, 4.0]) == 2.5


def test_median_of_nothing_is_none():
    assert ce._median([]) is None
