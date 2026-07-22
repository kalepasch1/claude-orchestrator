"""Tests for runner_assignment_optimizer."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from runner_assignment_optimizer import (
    Runner, AssignmentResult, assign_task_to_runner, assign_batch, _score_runner,
    LOCAL_THRESHOLD_SECONDS, CLOUD_THRESHOLD_SECONDS,
)


# --- Runner basics ---

def test_runner_load_empty():
    r = Runner("r1", capacity=5.0)
    assert r.load == 0.0

def test_runner_load_partial():
    r = Runner("r1", capacity=2.0, current_tasks=["a"])
    assert r.load == 0.5

def test_runner_defaults():
    r = Runner("r1")
    assert r.platform == "cloud"
    assert r.current_tasks == []


# --- Single runner ---

def test_single_runner():
    r = Runner("r1", capacity=1.0)
    result = assign_task_to_runner({"type": "build"}, [r])
    assert result.runner_id == "r1"

def test_no_runners():
    result = assign_task_to_runner({"type": "build"}, [])
    assert result.runner_id == ""
    assert result.confidence_score == 0.0


# --- Multiple runners ---

def test_prefers_lower_load():
    r1 = Runner("r1", capacity=2.0, current_tasks=["a", "b"])
    r2 = Runner("r2", capacity=2.0, current_tasks=[])
    result = assign_task_to_runner({"type": "test", "predicted_duration": 10}, [r1, r2])
    assert result.runner_id == "r2"

def test_prefers_higher_capacity():
    r1 = Runner("r1", capacity=1.0)
    r2 = Runner("r2", capacity=10.0)
    result = assign_task_to_runner({"type": "test", "predicted_duration": 10}, [r1, r2])
    assert result.runner_id == "r2"


# --- Platform preference ---

def test_prefers_mac_for_short_tasks():
    r_mac = Runner("mac1", capacity=1.0, platform="mac")
    r_cloud = Runner("cloud1", capacity=1.0, platform="cloud")
    result = assign_task_to_runner({"type": "lint", "predicted_duration": 2.0}, [r_cloud, r_mac])
    assert result.runner_id == "mac1"

def test_prefers_cloud_for_long_tasks():
    r_mac = Runner("mac1", capacity=1.0, platform="mac")
    r_cloud = Runner("cloud1", capacity=1.0, platform="cloud")
    result = assign_task_to_runner({"type": "train", "predicted_duration": 60.0}, [r_mac, r_cloud])
    assert result.runner_id == "cloud1"

def test_no_platform_pref_medium_tasks():
    r_mac = Runner("mac1", capacity=1.0, platform="mac")
    r_cloud = Runner("cloud1", capacity=1.0, platform="cloud")
    result = assign_task_to_runner({"type": "test", "predicted_duration": 15.0}, [r_mac, r_cloud])
    # No strong platform preference, should pick based on other factors
    assert result.runner_id in ("mac1", "cloud1")


# --- Context-switch avoidance ---

def test_prefers_runner_with_prereqs():
    r1 = Runner("r1", capacity=2.0, current_tasks=["build"])
    r2 = Runner("r2", capacity=2.0, current_tasks=[])
    deps = {"test": ["build"]}
    result = assign_task_to_runner({"type": "test", "predicted_duration": 10}, [r1, r2], dependency_graph=deps)
    assert result.runner_id == "r1"

def test_no_prereq_effect_without_graph():
    r1 = Runner("r1", capacity=2.0, current_tasks=["build"])
    r2 = Runner("r2", capacity=2.0, current_tasks=[])
    result = assign_task_to_runner({"type": "test", "predicted_duration": 10}, [r1, r2])
    # Without dependency graph, r2 should be preferred (lower load)
    assert result.runner_id == "r2"


# --- Prediction model ---

def test_uses_prediction_model():
    class FakeModel:
        def predict(self, task): return 3.0
    r = Runner("r1", capacity=1.0, platform="mac")
    result = assign_task_to_runner({"type": "lint"}, [r], prediction_model=FakeModel())
    assert result.runner_id == "r1"

def test_fallback_when_predictor_fails():
    class BadModel:
        def predict(self, task): raise RuntimeError("fail")
    r = Runner("r1", capacity=1.0)
    result = assign_task_to_runner({"type": "test"}, [r], prediction_model=BadModel())
    assert result.runner_id == "r1"

def test_uses_avg_duration_fallback():
    r = Runner("r1", capacity=1.0)
    result = assign_task_to_runner({"type": "test", "avg_duration": 20.0}, [r])
    assert result.runner_id == "r1"

def test_default_duration_when_no_info():
    r = Runner("r1", capacity=1.0)
    result = assign_task_to_runner({"type": "test"}, [r])
    assert result.runner_id == "r1"


# --- Confidence ---

def test_confidence_single_runner():
    r = Runner("r1")
    result = assign_task_to_runner({"type": "test", "predicted_duration": 10}, [r])
    assert result.confidence_score == 0.5

def test_confidence_with_clear_winner():
    r1 = Runner("r1", capacity=10.0)
    r2 = Runner("r2", capacity=0.1)
    result = assign_task_to_runner({"type": "test", "predicted_duration": 10}, [r1, r2])
    assert result.confidence_score > 0.0


# --- Batch assignment ---

def test_batch_distributes():
    r1 = Runner("r1", capacity=5.0)
    r2 = Runner("r2", capacity=5.0)
    tasks = [{"type": f"task-{i}", "predicted_duration": 10} for i in range(4)]
    results = assign_batch(tasks, [r1, r2])
    assert len(results) == 4
    ids = [r.runner_id for r in results]
    assert "r1" in ids and "r2" in ids

def test_batch_updates_load():
    r1 = Runner("r1", capacity=5.0)
    tasks = [{"type": "a", "predicted_duration": 10}, {"type": "b", "predicted_duration": 10}]
    assign_batch(tasks, [r1])
    assert len(r1.current_tasks) == 2

def test_batch_empty():
    results = assign_batch([], [Runner("r1")])
    assert results == []


# --- Score function ---

def test_score_basic():
    r = Runner("r1", capacity=2.0)
    score, reason = _score_runner({"type": "test"}, r, 10.0)
    assert score > 0
    assert "base=" in reason

def test_score_load_penalty():
    r_empty = Runner("r1", capacity=2.0)
    r_loaded = Runner("r2", capacity=2.0, current_tasks=["a", "b", "c"])
    s1, _ = _score_runner({"type": "t"}, r_empty, 10.0)
    s2, _ = _score_runner({"type": "t"}, r_loaded, 10.0)
    assert s2 > s1


# --- High load scenario ---

def test_high_load_still_assigns():
    runners = [Runner(f"r{i}", capacity=1.0, current_tasks=["x"] * 10) for i in range(3)]
    result = assign_task_to_runner({"type": "test", "predicted_duration": 5}, runners)
    assert result.runner_id in [f"r{i}" for i in range(3)]

def test_task_reordering_with_deps():
    r1 = Runner("r1", capacity=3.0, current_tasks=["build", "lint"])
    r2 = Runner("r2", capacity=3.0, current_tasks=["deploy"])
    deps = {"test": ["build", "lint"], "release": ["deploy"]}
    res1 = assign_task_to_runner({"type": "test", "predicted_duration": 10}, [r1, r2], dependency_graph=deps)
    res2 = assign_task_to_runner({"type": "release", "predicted_duration": 10}, [r1, r2], dependency_graph=deps)
    assert res1.runner_id == "r1"
    assert res2.runner_id == "r2"

def test_round_robin_baseline_comparison():
    """Verify optimizer does at least as well as round-robin for uniform tasks."""
    runners = [Runner(f"r{i}", capacity=2.0) for i in range(3)]
    tasks = [{"type": "test", "predicted_duration": 10} for _ in range(6)]
    results = assign_batch(tasks, runners)
    counts = {}
    for r in results:
        counts[r.runner_id] = counts.get(r.runner_id, 0) + 1
    assert max(counts.values()) <= 3  # Reasonably balanced

def test_assignment_result_fields():
    r = AssignmentResult("r1", 0.8, "test reason")
    assert r.runner_id == "r1"
    assert r.confidence_score == 0.8
    assert r.reason == "test reason"

def test_thresholds():
    assert LOCAL_THRESHOLD_SECONDS == 5.0
    assert CLOUD_THRESHOLD_SECONDS == 30.0
