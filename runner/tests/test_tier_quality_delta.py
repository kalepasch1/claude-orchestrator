"""Tests for tier_quality_delta.py"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from tier_quality_delta import (
    TaskOutcome, compute_tier_stats, compute_quality_deltas,
    recommend_model, QUALITY_THRESHOLD,
)

def _make_outcomes():
    outcomes = []
    for i in range(10):
        outcomes.append(TaskOutcome(task_id=f"h{i}", slug=f"bug-h{i}", model="haiku",
            task_shape="bugfix", verify_passed=i < 7, merged=i < 6, cost_usd=0.01))
    for i in range(10):
        outcomes.append(TaskOutcome(task_id=f"o{i}", slug=f"bug-o{i}", model="opus",
            task_shape="bugfix", verify_passed=i < 10, merged=i < 9, cost_usd=0.15))
    return outcomes

def test_compute_tier_stats():
    stats = compute_tier_stats(_make_outcomes())
    assert len(stats) == 2
    haiku = next(s for s in stats if s.model == "haiku")
    opus = next(s for s in stats if s.model == "opus")
    assert haiku.total == 10 and opus.total == 10
    assert opus.merge_rate > haiku.merge_rate

def test_quality_delta_recommends_high():
    stats = compute_tier_stats(_make_outcomes())
    deltas = compute_quality_deltas(stats)
    assert len(deltas) == 1
    d = deltas[0]
    assert d.merge_delta >= QUALITY_THRESHOLD
    assert d.recommendation == "use_high" and d.high_model == "opus"

def test_quality_delta_recommends_low():
    outcomes = []
    for i in range(10):
        outcomes.append(TaskOutcome(task_id=f"h{i}", slug=f"d-h{i}", model="haiku",
            task_shape="docs", verify_passed=True, merged=True, cost_usd=0.01))
        outcomes.append(TaskOutcome(task_id=f"o{i}", slug=f"d-o{i}", model="opus",
            task_shape="docs", verify_passed=True, merged=True, cost_usd=0.15))
    stats = compute_tier_stats(outcomes)
    deltas = compute_quality_deltas(stats)
    d = next(dd for dd in deltas if dd.task_shape == "docs")
    assert d.merge_delta < QUALITY_THRESHOLD and d.recommendation == "use_low"

def test_recommend_model():
    stats = compute_tier_stats(_make_outcomes())
    deltas = compute_quality_deltas(stats)
    assert recommend_model(deltas, "bugfix") == "opus"
    assert recommend_model(deltas, "unknown") == "haiku"

def test_cost_ratio():
    stats = compute_tier_stats(_make_outcomes())
    deltas = compute_quality_deltas(stats)
    assert deltas[0].cost_ratio > 1
