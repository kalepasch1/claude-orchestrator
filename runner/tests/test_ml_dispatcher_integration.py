"""Tests for ml_dispatcher_integration."""
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from ml_dispatcher_integration import MLDispatcherIntegration


class FakeResult:
    def __init__(self, rid="r1", conf=0.8, reason="test"):
        self.runner_id = rid
        self.confidence_score = conf
        self.reason = reason


class FakeInferencer:
    def predict_dependencies(self, task_type):
        return {"build"} if task_type == "test" else set()


def fake_optimizer(task, runners, prediction_model=None, dependency_graph=None):
    return FakeResult()


def failing_optimizer(task, runners, **kw):
    raise RuntimeError("boom")


# --- Feature gate ---

def test_disabled_by_default():
    m = MLDispatcherIntegration()
    assert m.enabled is False

def test_enable():
    m = MLDispatcherIntegration(enabled=True)
    assert m.enabled is True

def test_toggle():
    m = MLDispatcherIntegration(enabled=False)
    m.enabled = True
    assert m.enabled is True


# --- Canary ---

def test_canary_disabled_returns_false():
    m = MLDispatcherIntegration(enabled=False, canary_percent=100)
    assert m.is_in_canary({"id": "x"}) is False

def test_canary_100_percent():
    m = MLDispatcherIntegration(enabled=True, canary_percent=100)
    assert m.is_in_canary({"id": "any"}) is True

def test_canary_0_percent():
    m = MLDispatcherIntegration(enabled=True, canary_percent=0)
    assert m.is_in_canary({"id": "any"}) is False

def test_canary_deterministic():
    m = MLDispatcherIntegration(enabled=True, canary_percent=50)
    result1 = m.is_in_canary({"id": "task-42"})
    result2 = m.is_in_canary({"id": "task-42"})
    assert result1 == result2


# --- Model loading ---

def test_load_model():
    m = MLDispatcherIntegration()
    m.load_model("my_model")
    assert m._prediction_model == "my_model"
    assert m._model_loaded_at is not None

def test_model_stale_initially():
    m = MLDispatcherIntegration()
    assert m.is_model_stale() is True

def test_model_fresh_after_load():
    m = MLDispatcherIntegration()
    m.load_model("x")
    assert m.is_model_stale() is False

def test_model_stale_after_threshold():
    m = MLDispatcherIntegration()
    m.load_model("x")
    m._model_loaded_at = time.time() - 7200
    assert m.is_model_stale() is True


# --- Dependency enrichment ---

def test_enrich_disabled():
    m = MLDispatcherIntegration(enabled=False, dependency_inferencer=FakeInferencer())
    task = {"type": "test"}
    result = m.enrich_with_dependencies(task)
    assert "predicted_dependencies" not in result

def test_enrich_enabled():
    m = MLDispatcherIntegration(enabled=True, dependency_inferencer=FakeInferencer())
    task = {"type": "test", "id": "t1"}
    result = m.enrich_with_dependencies(task)
    assert "build" in result["predicted_dependencies"]

def test_enrich_no_inferencer():
    m = MLDispatcherIntegration(enabled=True)
    task = {"type": "test"}
    result = m.enrich_with_dependencies(task)
    assert "predicted_dependencies" not in result

def test_enrich_error_handled():
    class BadInferencer:
        def predict_dependencies(self, t): raise RuntimeError("fail")
    m = MLDispatcherIntegration(enabled=True, dependency_inferencer=BadInferencer())
    task = {"type": "test", "id": "t1"}
    result = m.enrich_with_dependencies(task)
    assert result["predicted_dependencies"] == []


# --- Runner assignment ---

def test_assign_not_canary():
    m = MLDispatcherIntegration(enabled=True, canary_percent=0, runner_optimizer=fake_optimizer)
    result = m.assign_runner({"id": "t1"}, ["r1"])
    assert result is None

def test_assign_canary_success():
    m = MLDispatcherIntegration(enabled=True, canary_percent=100, runner_optimizer=fake_optimizer)
    result = m.assign_runner({"id": "t1"}, ["r1"])
    assert result is not None
    assert result["runner_id"] == "r1"
    assert result["source"] == "ml"

def test_assign_no_optimizer():
    m = MLDispatcherIntegration(enabled=True, canary_percent=100)
    result = m.assign_runner({"id": "t1"}, ["r1"])
    assert result is None

def test_assign_optimizer_error():
    m = MLDispatcherIntegration(enabled=True, canary_percent=100, runner_optimizer=failing_optimizer)
    result = m.assign_runner({"id": "t1"}, ["r1"])
    assert result is None


# --- Decision logging ---

def test_decisions_logged():
    m = MLDispatcherIntegration(enabled=True, canary_percent=100, runner_optimizer=fake_optimizer)
    m.assign_runner({"id": "t1", "type": "build"}, ["r1"])
    decisions = m.get_decisions()
    assert len(decisions) == 1
    assert decisions[0]["task_id"] == "t1"

def test_decisions_limit():
    m = MLDispatcherIntegration(enabled=True, canary_percent=100, runner_optimizer=fake_optimizer)
    for i in range(10):
        m.assign_runner({"id": f"t{i}"}, ["r1"])
    assert len(m.get_decisions(limit=3)) == 3

def test_decisions_trimmed():
    m = MLDispatcherIntegration(enabled=True, canary_percent=100, runner_optimizer=fake_optimizer)
    for i in range(10001):
        m._decisions.append({"task_id": f"t{i}", "decision": "test", "canary": True})
    m.assign_runner({"id": "final"}, ["r1"])
    assert len(m._decisions) <= 5002


# --- Canary metrics ---

def test_canary_metrics_empty():
    m = MLDispatcherIntegration(enabled=True, canary_percent=10)
    metrics = m.get_canary_metrics()
    assert metrics["canary_count"] == 0
    assert metrics["enabled"] is True

def test_canary_metrics_with_data():
    m = MLDispatcherIntegration(enabled=True, canary_percent=100, runner_optimizer=fake_optimizer)
    m.assign_runner({"id": "t1"}, ["r1"])
    m.assign_runner({"id": "t2"}, ["r1"])
    metrics = m.get_canary_metrics()
    assert metrics["canary_count"] == 2
    assert metrics["canary_ml_assigned"] == 2


# --- Cold start ---

def test_cold_start_no_model():
    m = MLDispatcherIntegration(enabled=True, canary_percent=100, runner_optimizer=fake_optimizer)
    # Works without loading a model
    result = m.assign_runner({"id": "t1"}, ["r1"])
    assert result is not None
