"""Tests for affinity_router."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from affinity_router import (
    compute_affinity, compute_value_weight, route_task, route_batch, AffinityScore,
)

def test_affinity_project_match():
    r = {"recent_project": "p1"}
    t = {"project_id": "p1"}
    assert compute_affinity(r, t) >= 0.4

def test_affinity_model_match():
    r = {"loaded_model": "claude"}
    t = {"preferred_model": "claude"}
    assert compute_affinity(r, t) >= 0.3

def test_affinity_no_match():
    assert compute_affinity({}, {}) == 0.0

def test_affinity_full_match():
    r = {"recent_project": "p1", "loaded_model": "m1", "experienced_classes": ["build"], "idle_seconds": 10}
    t = {"project_id": "p1", "preferred_model": "m1", "task_class": "build"}
    assert compute_affinity(r, t) == 1.0

def test_value_weight_default():
    assert compute_value_weight({"priority": 5}) == 0.5

def test_value_weight_high_priority():
    assert compute_value_weight({"priority": 10}) == 1.0

def test_value_weight_blocking():
    w = compute_value_weight({"priority": 5, "blocking_count": 3})
    assert w > 0.5

def test_value_weight_blocked():
    w = compute_value_weight({"priority": 5, "is_blocked_by_count": 2})
    assert w < 0.5

def test_route_task_single():
    r = route_task({"project_id": "p1", "priority": 5}, [{"id": "r1"}])
    assert r is not None
    assert r.runner_id == "r1"

def test_route_task_empty():
    assert route_task({}, []) is None

def test_route_task_prefers_affinity():
    runners = [
        {"id": "r1", "recent_project": "other"},
        {"id": "r2", "recent_project": "p1"},
    ]
    r = route_task({"project_id": "p1", "priority": 5}, runners)
    assert r.runner_id == "r2"

def test_route_batch():
    tasks = [{"priority": 3}, {"priority": 8}]
    runners = [{"id": "r1"}]
    results = route_batch(tasks, runners)
    assert len(results) == 2

def test_affinity_score_weighted():
    s = AffinityScore("r1", 0.8, 1.5)
    assert s.weighted_score == 1.2
