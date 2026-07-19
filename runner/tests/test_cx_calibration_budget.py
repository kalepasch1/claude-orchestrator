"""Tests for cx_calibration_budget."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cx_calibration_budget import (
    VerticalSignal, allocate_calibration_budget,
    score_urgency, should_trigger_calibration,
)


def test_stable_verticals_get_no_budget():
    signals = [
        VerticalSignal("insurance", accuracy=0.92, sample_count=100, drift_score=0.1),
        VerticalSignal("lending", accuracy=0.90, sample_count=50, drift_score=0.2),
    ]
    plan = allocate_calibration_budget(signals, total_budget_usd=100)
    assert plan.verticals_needing_calibration == 0
    assert plan.verticals_stable == 2
    assert len(plan.allocations) == 0


def test_low_accuracy_gets_budget():
    signals = [
        VerticalSignal("insurance", accuracy=0.70, sample_count=100, drift_score=0.1),
        VerticalSignal("lending", accuracy=0.95, sample_count=100, drift_score=0.1),
    ]
    plan = allocate_calibration_budget(signals, total_budget_usd=100)
    assert plan.verticals_needing_calibration == 1
    assert plan.allocations[0].vertical == "insurance"
    assert plan.allocations[0].budget_pct == 100.0


def test_high_drift_gets_budget():
    signals = [
        VerticalSignal("insurance", accuracy=0.90, sample_count=100, drift_score=0.8),
    ]
    plan = allocate_calibration_budget(signals, total_budget_usd=100)
    assert plan.verticals_needing_calibration == 1
    assert "drift" in plan.allocations[0].reason


def test_budget_proportional_to_urgency():
    signals = [
        VerticalSignal("insurance", accuracy=0.60, sample_count=100, drift_score=0.1),
        VerticalSignal("lending", accuracy=0.80, sample_count=100, drift_score=0.1),
    ]
    plan = allocate_calibration_budget(signals, total_budget_usd=200)
    assert len(plan.allocations) == 2
    assert plan.allocations[0].budget_pct > plan.allocations[1].budget_pct
    assert plan.allocations[0].priority == 1


def test_should_trigger():
    stable = VerticalSignal("ok", accuracy=0.95, sample_count=100, drift_score=0.1)
    unstable = VerticalSignal("bad", accuracy=0.70, sample_count=5, drift_score=0.5)
    assert not should_trigger_calibration(stable)
    assert should_trigger_calibration(unstable)


if __name__ == "__main__":
    test_stable_verticals_get_no_budget()
    test_low_accuracy_gets_budget()
    test_high_drift_gets_budget()
    test_budget_proportional_to_urgency()
    test_should_trigger()
    print("All cx_calibration_budget tests passed")
