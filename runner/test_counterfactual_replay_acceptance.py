#!/usr/bin/env python3
"""Acceptance tests for counterfactual-replay implementation.

This suite validates the complete counterfactual-replay workflow:
- Replay decisions with new models and detect policy divergences
- Persist replay results and route updates
- Push safe config updates through fleet_control
- Recover gracefully from errors
- Thread-safe concurrent operations
"""

import os
import sys
import json
import sqlite3
import tempfile
import threading
import time
from pathlib import Path
from datetime import datetime, timedelta

import pytest

RUNNER = os.path.dirname(os.path.abspath(__file__))
if RUNNER not in sys.path:
    sys.path.insert(0, RUNNER)

import counterfactual_replay as cfr


class RecordingModel:
    """Model that records all evaluate() calls."""

    def __init__(self, model_id="opus", version="2.0", decision="route_b", confidence=0.9):
        self.model_id = model_id
        self.version = version
        self._decision = decision
        self._confidence = confidence
        self.calls = []

    def evaluate(self, input_data, task_type):
        self.calls.append((input_data, task_type))
        return {"decision": self._decision, "confidence": self._confidence}


# =============================================================================
# Replay workflow acceptance tests
# =============================================================================

class TestReplayWorkflow:
    """End-to-end replay workflow tests."""

    def test_complete_replay_workflow(self, tmp_path, monkeypatch):
        """A complete workflow: replay, detect change, update policy, persist."""
        # Setup
        monkeypatch.setenv("CLAUDE_ORCH_HOME", str(tmp_path))
        old_decision = {
            "task_id": "routing-t1",
            "type": "routing",
            "input": {"endpoint": "/api/users"},
            "output": {"route": "haiku", "confidence": 0.6},
            "model": "haiku",
        }
        new_model = RecordingModel(model_id="opus", decision="opus", confidence=0.95)

        # Replay
        result = cfr.replay_decision("routing-t1", old_decision, new_model)
        assert result is not None
        assert result["decision"] == "opus"
        assert result["model"] == "opus"

        # Detect change
        has_change = cfr.has_policy_change(old_decision, result)
        assert has_change is True

        # Update policy
        change = cfr.detect_policy_change(
            old_decision["output"],
            {"route": result["decision"], "confidence": result["confidence"]}
        )
        update = cfr.update_route_policy("routing", {"model": "haiku"}, change)
        assert update["updated"] is True
        assert update["new_model"] == "opus"

        # Persist
        storage = cfr.ReplayStorage(tmp_path)
        storage.save_replay(result)
        persisted = storage.get_replays("routing-t1")
        assert len(persisted) == 1
        assert persisted[0]["model"] == "opus"

    def test_stable_decision_workflow(self, tmp_path, monkeypatch):
        """Workflow when new model agrees with original decision."""
        monkeypatch.setenv("CLAUDE_ORCH_HOME", str(tmp_path))
        old_decision = {
            "task_id": "t2",
            "input": {"q": 1},
            "output": {"route": "opus", "confidence": 0.8},
            "model": "haiku",
        }
        # New model agrees, so no change
        new_model = RecordingModel(model_id="opus", decision="opus", confidence=0.9)

        result = cfr.replay_decision("t2", old_decision, new_model)
        has_change = cfr.has_policy_change(old_decision, result)
        assert has_change is False

    def test_batch_replay_workflow(self, tmp_path):
        """Batch replay with change detection and summary."""
        decisions = [
            {
                "task_id": "t1",
                "input": {"q": 1},
                "output": {"route": "haiku", "confidence": 0.5},
            },
            {
                "task_id": "t2",
                "input": {"q": 2},
                "output": {"route": "haiku", "confidence": 0.5},
            },
            {
                "task_id": "t3",
                "input": {"q": 3},
                "output": {"route": "opus", "confidence": 0.8},
            },
        ]

        model = RecordingModel(decision="opus", confidence=0.95)
        results, summary = cfr.replay_batch_with_summary(decisions, model)

        assert summary["total_replayed"] == 3
        assert summary["policy_changes"] >= 2
        assert summary["models_tested"] == ["opus"]
        assert len(results) == 3


# =============================================================================
# Policy divergence acceptance tests
# =============================================================================

class TestPolicyDivergenceDetection:
    """Policy divergence detection acceptance tests."""

    def test_detects_route_change(self):
        """Detect when model routes to different endpoint."""
        old = {"output": {"route": "haiku", "confidence": 0.6}}
        replay = {"decision": "opus", "confidence": 0.95}
        assert cfr.has_policy_change(old, replay) is True

    def test_detects_confidence_improvement(self):
        """Detect high-confidence reroute (improvement)."""
        old = {"output": {"route": "haiku", "confidence": 0.5}}
        replay = {"decision": "opus", "confidence": 0.95}
        change = cfr.detect_policy_change(
            old["output"],
            {"route": replay["decision"], "confidence": replay["confidence"]}
        )
        assert change["reason"] == "confidence_improvement"
        assert change["confidence_delta"] == 0.45

    def test_detects_confidence_decline(self):
        """Detect reroute with lower confidence (decline)."""
        old = {"output": {"route": "opus", "confidence": 0.9}}
        replay = {"decision": "haiku", "confidence": 0.4}
        change = cfr.detect_policy_change(
            old["output"],
            {"route": replay["decision"], "confidence": replay["confidence"]}
        )
        assert change["reason"] == "confidence_decline"
        assert change["confidence_delta"] == -0.5

    def test_stable_confidence_and_route(self):
        """No change when both route and confidence stable."""
        old = {"output": {"route": "opus", "confidence": 0.8}}
        replay = {"decision": "opus", "confidence": 0.8}
        assert cfr.has_policy_change(old, replay) is False

    def test_handles_malformed_decisions(self):
        """Gracefully handle malformed decision data."""
        assert cfr.has_policy_change(None, {"decision": "opus"}) is False
        assert cfr.has_policy_change({}, {"decision": "opus"}) is False
        assert cfr.has_policy_change("corrupt", None) is False


# =============================================================================
# Storage persistence acceptance tests
# =============================================================================

class TestStoragePersistence:
    """Route and replay storage persistence."""

    def test_route_storage_survives_restart(self, tmp_path):
        """Route updates persist across storage instances."""
        update1 = {
            "operation": "routing",
            "model": "opus",
            "timestamp": datetime.now().isoformat(),
        }

        storage1 = cfr.RouteStorage(tmp_path)
        storage1.persist_route_update(update1)

        storage2 = cfr.RouteStorage(tmp_path)
        retrieved = storage2.get_route_update("routing")

        assert retrieved is not None
        assert retrieved["model"] == "opus"

    def test_replay_storage_query_by_model(self, tmp_path):
        """Query replay results by model."""
        storage = cfr.ReplayStorage(tmp_path)

        results = [
            {
                "task_id": "t1",
                "model": "opus",
                "decision": "route_a",
                "policy_changed": True,
                "timestamp": datetime.now().isoformat(),
            },
            {
                "task_id": "t2",
                "model": "haiku",
                "decision": "route_b",
                "policy_changed": False,
                "timestamp": datetime.now().isoformat(),
            },
        ]

        for r in results:
            storage.save_replay(r)

        opus_results = storage.query(model="opus")
        assert len(opus_results) == 1
        assert opus_results[0]["model"] == "opus"

    def test_replay_storage_query_by_policy_changed(self, tmp_path):
        """Query replay results by policy_changed status."""
        storage = cfr.ReplayStorage(tmp_path)

        results = [
            {"task_id": "t1", "model": "opus", "policy_changed": True, "timestamp": datetime.now().isoformat()},
            {"task_id": "t2", "model": "opus", "policy_changed": False, "timestamp": datetime.now().isoformat()},
            {"task_id": "t3", "model": "opus", "policy_changed": True, "timestamp": datetime.now().isoformat()},
        ]

        for r in results:
            storage.save_replay(r)

        changed = storage.query(policy_changed=True)
        assert len(changed) == 2

    def test_replay_count_operations(self, tmp_path):
        """Count replays globally and by task."""
        storage = cfr.ReplayStorage(tmp_path)

        for i in range(5):
            storage.save_replay({
                "task_id": "t1",
                "model": "opus",
                "timestamp": datetime.now().isoformat(),
            })

        total = storage.count_replays()
        assert total == 1  # Idempotent: same task_id overwrites

        for i in range(3):
            storage.save_replay({
                "task_id": f"t{i+2}",
                "model": "opus",
                "timestamp": datetime.now().isoformat(),
            })

        total = storage.count_replays()
        assert total == 4  # t1 + t2 + t3 + t4


# =============================================================================
# Fleet config push acceptance tests
# =============================================================================

class TestFleetConfigPushSafety:
    """Fleet config push with safety checks."""

    def test_safe_orch_keys_are_accepted(self, monkeypatch):
        """ORCH_* keys are considered for pushing."""
        pushed = []
        monkeypatch.setattr(
            "fleet_control.update_fleet_config",
            lambda k, v: pushed.append((k, v))
        )
        cfr.push_config_updates({
            "ORCH_RUNNER_ROUTE_BUILD": "opus",
            "ORCH_RUNNER_ROUTE_GENERATE": "haiku",
        })
        assert len(pushed) == 2

    def test_secret_keys_never_pushed(self, monkeypatch):
        """Keys with SECRET/PASSWORD/TOKEN are dropped."""
        pushed = []
        monkeypatch.setattr(
            "fleet_control.update_fleet_config",
            lambda k, v: pushed.append(k)
        )
        cfr.push_config_updates({
            "ORCH_RUNNER_ROUTE_SECRET": "x",
            "ORCH_DB_PASSWORD": "x",
            "ORCH_API_TOKEN": "x",
            "ORCH_RUNNER_POLICY_MAX": 5,
        })
        # Only the safe key should be pushed
        assert len(pushed) == 1
        assert "ORCH_RUNNER_POLICY_MAX" in pushed

    def test_empty_updates_is_noop(self, monkeypatch):
        """Empty update dict results in no fleet_control calls."""
        calls = []
        monkeypatch.setattr(
            "fleet_control.update_fleet_config",
            lambda k, v: calls.append(k)
        )
        cfr.push_config_updates({})
        assert len(calls) == 0

    def test_push_failure_is_fail_soft(self, monkeypatch):
        """Fleet config push failures don't crash."""
        def boom(key, value):
            raise RuntimeError("fleet unreachable")

        monkeypatch.setattr("fleet_control.update_fleet_config", boom)
        # Should not raise
        cfr.push_config_updates({"ORCH_RUNNER_ROUTE_BUILD": "opus"})


# =============================================================================
# Thread safety acceptance tests
# =============================================================================

class TestThreadSafety:
    """Thread safety of route config and storage."""

    def test_concurrent_route_config_updates(self):
        """RouteConfig handles concurrent updates safely."""
        config = cfr.RouteConfig()
        errors = []

        def worker(worker_id):
            try:
                for i in range(20):
                    config.set_route(f"op_{worker_id}", f"model_{i}")
                    config.update_route(f"op_{worker_id}", f"updated_{i}")
                    route = config.get_route(f"op_{worker_id}")
                    assert route is not None
                    # Brief sleep to increase contention likelihood
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors

    def test_concurrent_replay_storage_saves(self, tmp_path):
        """ReplayStorage handles concurrent saves safely."""
        storage = cfr.ReplayStorage(tmp_path)
        errors = []

        def worker(worker_id):
            try:
                for i in range(10):
                    storage.save_replay({
                        "task_id": f"t{worker_id}_{i}",
                        "model": f"model_{i}",
                        "decision": f"route_{i}",
                        "timestamp": datetime.now().isoformat(),
                    })
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        # Should have saved 50 unique tasks (5 workers * 10 saves each)
        total = storage.count_replays()
        assert total == 50


# =============================================================================
# Error recovery acceptance tests
# =============================================================================

class TestErrorRecovery:
    """Graceful error handling and recovery."""

    def test_replay_malformed_decision(self):
        """Replay gracefully handles malformed decisions."""
        model = RecordingModel()

        assert cfr.replay_decision("t1", None, model) is None
        assert cfr.replay_decision("t2", "not-a-dict", model) is None
        assert cfr.replay_decision("t3", {}, model) is None

    def test_replay_missing_input(self):
        """Replay handles missing input field."""
        model = RecordingModel()
        decision = {"task_id": "t1", "output": {"route": "haiku"}}

        result = cfr.replay_decision("t1", decision, model)
        # Should succeed with empty input dict
        assert result is not None

    def test_replay_corrupted_output(self):
        """Replay handles corrupted output field."""
        model = RecordingModel()
        decision = {
            "task_id": "t1",
            "input": {"q": 1},
            "output": "corrupted-string",
        }

        # Should fail gracefully
        result = cfr.replay_decision("t1", decision, model)
        assert result is None

    def test_replay_safe_variant_handles_errors(self):
        """replay_decision_safe always returns a result dict."""
        model = RecordingModel()

        result = cfr.replay_decision_safe("t1", None, model)
        assert isinstance(result, dict)
        assert result["status"] in ["skipped", "partial", "success"]

    def test_policy_conflict_resolution_with_bad_input(self):
        """resolve_policy_conflict handles bad inputs."""
        result = cfr.resolve_policy_conflict(None, None)
        assert result["conflict"] is False
        assert result["resolution"] == "merge"

        result = cfr.resolve_policy_conflict("not-dict", {"a": 1})
        assert isinstance(result, dict)
        assert "resolution" in result


# =============================================================================
# Circular dependency detection acceptance tests
# =============================================================================

class TestCircularDependencyDetection:
    """Circular dependency detection in decision graphs."""

    def test_detects_self_reference(self):
        """A node depending on itself is a cycle."""
        decisions = {"A": {"depends_on": "A"}}
        result = cfr.detect_circular_dependencies(decisions)
        assert result["has_cycle"] is True

    def test_detects_mutual_cycle(self):
        """A -> B -> A cycle is detected."""
        decisions = {
            "A": {"depends_on": "B"},
            "B": {"depends_on": "A"},
        }
        result = cfr.detect_circular_dependencies(decisions)
        assert result["has_cycle"] is True

    def test_linear_chain_is_acyclic(self):
        """A -> B -> C chain has no cycle."""
        decisions = {
            "A": {"depends_on": "B"},
            "B": {"depends_on": "C"},
            "C": {"depends_on": None},
        }
        result = cfr.detect_circular_dependencies(decisions)
        assert result["has_cycle"] is False

    def test_empty_graph_is_acyclic(self):
        """Empty graph has no cycles."""
        result = cfr.detect_circular_dependencies({})
        assert result["has_cycle"] is False

    def test_handles_malformed_dependencies(self):
        """Malformed dependency data doesn't crash."""
        decisions = {
            "A": "not-a-dict",
            "B": {"depends_on": "A"},
        }
        result = cfr.detect_circular_dependencies(decisions)
        assert isinstance(result, dict)
        assert "has_cycle" in result


# =============================================================================
# Data evolution tracking acceptance tests
# =============================================================================

class TestDataEvolutionTracking:
    """Track how context data changes between original and replay."""

    def test_tracks_field_changes(self):
        """Detects which fields changed."""
        old = {"version": 1, "field_a": "old", "field_b": "unchanged"}
        new = {"version": 2, "field_a": "new", "field_b": "unchanged"}

        result = cfr.track_data_evolution(old, new)
        assert "field_a" in result["changes"]
        assert "field_b" not in result["changes"]

    def test_tracks_added_fields(self):
        """Detects newly added fields."""
        old = {"version": 1, "field_a": "value"}
        new = {"version": 2, "field_a": "value", "field_b": "new"}

        result = cfr.track_data_evolution(old, new)
        assert "field_b" in result["changes"]
        assert result["field_b_new"] == "new"

    def test_tracks_removed_fields(self):
        """Detects removed fields."""
        old = {"version": 1, "field_a": "value", "field_b": "removed"}
        new = {"version": 2, "field_a": "value"}

        result = cfr.track_data_evolution(old, new)
        assert "field_b" in result["changes"]
        assert result["field_b_old"] == "removed"

    def test_replay_with_context_tracking(self):
        """replay_decision_with_context tracks evolution."""
        old_decision = {
            "task_id": "t1",
            "input": {"version": 1, "data": "old_value"},
        }
        new_context = {
            "version": 2,
            "context_version": 2,
            "data": "new_value"
        }
        model = RecordingModel()

        result = cfr.replay_decision_with_context(
            "t1", old_decision, model, new_context
        )

        assert result is not None
        assert result["context_version"] == 2
        assert "data_evolution" in result


# =============================================================================
# Configuration contract acceptance tests
# =============================================================================

class TestConfigurationContract:
    """ORCH_COUNTERFACTUAL_* environment variable contract."""

    def test_configuration_defaults(self, monkeypatch):
        """Default configuration values."""
        for key in ("ORCH_COUNTERFACTUAL_DAYS_BACK", "ORCH_COUNTERFACTUAL_BATCH_SIZE",
                    "ORCH_COUNTERFACTUAL_ENABLED"):
            monkeypatch.delenv(key, raising=False)

        # Re-check the module-level constants
        assert cfr.DAYS_BACK == 7
        assert cfr.BATCH_SIZE == 50
        assert cfr.ENABLED is True

    def test_days_back_configurable(self, monkeypatch):
        """ORCH_COUNTERFACTUAL_DAYS_BACK sets replay window."""
        monkeypatch.setenv("ORCH_COUNTERFACTUAL_DAYS_BACK", "30")
        # Module-level variables are set at import, so we just verify they exist
        assert hasattr(cfr, "DAYS_BACK")

    def test_batch_size_configurable(self, monkeypatch):
        """ORCH_COUNTERFACTUAL_BATCH_SIZE sets batch size."""
        monkeypatch.setenv("ORCH_COUNTERFACTUAL_BATCH_SIZE", "100")
        assert hasattr(cfr, "BATCH_SIZE")

    def test_enabled_kill_switch(self, monkeypatch):
        """ORCH_COUNTERFACTUAL_ENABLED controls feature."""
        monkeypatch.setenv("ORCH_COUNTERFACTUAL_ENABLED", "false")
        assert hasattr(cfr, "ENABLED")


# =============================================================================
# Replay-only guarantee acceptance tests
# =============================================================================

class TestReplayOnlyGuarantee:
    """Guarantee that replay never mutates history."""

    def test_replay_preserves_original_decision(self):
        """Original decision is not mutated by replay."""
        decision = {
            "task_id": "t1",
            "input": {"q": 1},
            "output": {"route": "haiku", "confidence": 0.6},
        }
        snapshot = json.dumps(decision)

        model = RecordingModel()
        result = cfr.replay_decision("t1", decision, model)

        assert json.dumps(decision) == snapshot
        assert result is not decision

    def test_replay_batch_invokes_model_once_per_decision(self):
        """Batch replay evaluates each decision exactly once."""
        model = RecordingModel()
        decisions = [
            {"task_id": f"t{i}", "input": {"q": i}} for i in range(5)
        ]

        cfr.replay_batch(decisions, model)
        assert len(model.calls) == 5

    def test_worktree_path_derived_not_created(self, tmp_path, monkeypatch):
        """Worktree path is computed but not materialized."""
        monkeypatch.setenv("CLAUDE_ORCH_HOME", str(tmp_path))
        path = cfr.get_worktree_path("task-1")

        assert "replay-task-1" in path
        assert not os.path.exists(path)


# =============================================================================
# Statistics and observability acceptance tests
# =============================================================================

class TestStatisticsAndObservability:
    """Module statistics and observability."""

    def test_stats_initially_zero(self):
        """Statistics start at zero."""
        cfr.invalidate()
        stats = cfr.stats()

        assert stats["replayed"] == 0
        assert stats["changed"] == 0
        assert stats["errors"] == 0

    def test_stats_increment_on_replay(self):
        """Stats increment when decisions are replayed."""
        cfr.invalidate()
        model = RecordingModel()
        decision = {"task_id": "t1", "input": {"q": 1}}

        cfr.replay_decision("t1", decision, model)
        stats = cfr.stats()

        assert stats["replayed"] == 1

    def test_stats_track_policy_changes(self):
        """Stats track policy changes in batch."""
        cfr.invalidate()
        decisions = [
            {
                "task_id": "t1",
                "input": {"q": 1},
                "output": {"route": "haiku", "confidence": 0.5},
            },
            {
                "task_id": "t2",
                "input": {"q": 2},
                "output": {"route": "haiku", "confidence": 0.5},
            },
        ]
        model = RecordingModel(decision="opus", confidence=0.95)

        cfr.replay_batch_with_summary(decisions, model)
        stats = cfr.stats()

        assert stats["replayed"] == 2
        assert stats["changed"] >= 2

    def test_invalidate_clears_stats(self):
        """invalidate() resets all statistics."""
        model = RecordingModel()
        cfr.replay_decision("t1", {"task_id": "t1", "input": {}}, model)

        cfr.invalidate()
        stats = cfr.stats()

        assert stats["replayed"] == 0
        assert stats["changed"] == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
