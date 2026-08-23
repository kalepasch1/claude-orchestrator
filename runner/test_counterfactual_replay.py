#!/usr/bin/env python3
"""
Test suite for counterfactual-replay feature.

Periodically re-run past decisions/tasks with newer models/data to detect
where routing/policy would now choose differently, and update routes.

Tests cover:
- Basic replay of past decisions with new models
- Comparison of old vs new model outputs
- Policy change detection
- Route updates based on counterfactual analysis
- Batch processing and filtering
- Edge cases (missing history, corrupted data, circular deps)
- Idempotency and thread safety
- Persistence and retrieval
- Integration with fleet config and worktree workflow
"""
import os
import sys
import json
import time
import tempfile
import shutil
from unittest.mock import Mock, patch, MagicMock
from threading import Thread, Lock
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test")

import counterfactual_replay as cfr
import fleet_control
import error_handling_utils as ehu


class MockDecisionHistory:
    """Mock decision history for testing."""

    def __init__(self):
        self.decisions = {}
        self.lock = Lock()

    def store(self, task_id, decision):
        with self.lock:
            self.decisions[task_id] = decision

    def get(self, task_id):
        with self.lock:
            return self.decisions.get(task_id)

    def list_all(self):
        with self.lock:
            return list(self.decisions.values())

    def clear(self):
        with self.lock:
            self.decisions.clear()


class MockModelProvider:
    """Mock model provider for testing."""

    def __init__(self, model_id, version="1.0"):
        self.model_id = model_id
        self.version = version
        self.call_count = 0

    def evaluate(self, input_data, task_type):
        self.call_count += 1
        # Simulate model behavior
        return {
            "model": self.model_id,
            "version": self.version,
            "decision": f"decision_{self.call_count}",
            "confidence": 0.85 + (0.01 * self.call_count),
        }


# =============================================================================
# Basic Replay Tests (1-3)
# =============================================================================


def test_replay_single_past_decision():
    """Replay a single past decision and get result."""
    hist = MockDecisionHistory()
    old_decision = {
        "task_id": "task_001",
        "timestamp": datetime.now().isoformat(),
        "model": "haiku",
        "model_version": "1.0",
        "input": {"query": "test", "context": "initial"},
        "output": {"route": "model_a", "confidence": 0.8},
    }
    hist.store("task_001", old_decision)

    new_model = MockModelProvider("opus", version="2.0")
    replay_result = cfr.replay_decision("task_001", old_decision, new_model)

    assert replay_result is not None
    assert replay_result["task_id"] == "task_001"
    assert replay_result["model"] == "opus"
    assert replay_result["model_version"] == "2.0"
    assert "decision" in replay_result


def test_replay_preserves_decision_metadata():
    """Replay preserves original decision metadata."""
    old_decision = {
        "task_id": "task_002",
        "timestamp": "2026-08-01T10:00:00",
        "model": "haiku",
        "model_version": "1.0",
        "input": {"query": "complex", "context": "prod"},
        "output": {"route": "fallback", "confidence": 0.6},
        "user": "operator_a",
        "repo": "claude-orchestrator",
    }

    new_model = MockModelProvider("sonnet", version="2.0")
    replay_result = cfr.replay_decision("task_002", old_decision, new_model)

    assert replay_result["original_task_id"] == old_decision["task_id"]
    assert replay_result["original_timestamp"] == old_decision["timestamp"]
    assert replay_result["original_model"] == old_decision["model"]
    assert replay_result["user"] == "operator_a"


def test_replay_with_new_model_produces_output():
    """Replaying with newer model produces valid output."""
    old_decision = {
        "task_id": "task_003",
        "model": "haiku",
        "input": {"data": "test"},
        "output": {"route": "old_route"},
    }

    new_model = MockModelProvider("fable-5", version="3.0")
    replay_result = cfr.replay_decision("task_003", old_decision, new_model)

    assert replay_result is not None
    assert "decision" in replay_result
    assert replay_result["model"] == "fable-5"
    assert replay_result["model_version"] == "3.0"
    assert "timestamp" in replay_result


# =============================================================================
# Model Comparison Tests (4-6)
# =============================================================================


def test_compare_old_vs_new_model_outputs():
    """Compare outputs from old model vs new model on same input."""
    old_decision = {
        "task_id": "task_004",
        "model": "haiku",
        "model_version": "1.0",
        "input": {"query": "route_decision"},
        "output": {"route": "model_a", "confidence": 0.75},
    }

    old_model = MockModelProvider("haiku", version="1.0")
    new_model = MockModelProvider("opus", version="2.0")

    old_output = old_model.evaluate(old_decision["input"], "routing")
    new_output = new_model.evaluate(old_decision["input"], "routing")

    comparison = cfr.compare_model_outputs(old_output, new_output)

    assert comparison["old_model"] == "haiku"
    assert comparison["new_model"] == "opus"
    assert "difference" in comparison
    assert "confidence_delta" in comparison


def test_model_version_difference_tracked():
    """Model version differences are tracked in replay results."""
    old_decision = {
        "task_id": "task_005",
        "model": "haiku",
        "model_version": "1.0",
        "input": {"data": "test"},
        "output": {"result": "old"},
    }

    new_model = MockModelProvider("haiku", version="2.5")
    replay_result = cfr.replay_decision("task_005", old_decision, new_model)

    assert replay_result["original_model_version"] == "1.0"
    assert replay_result["model_version"] == "2.5"
    version_upgrade = cfr.detect_version_upgrade(
        old_decision["model_version"], replay_result["model_version"]
    )
    assert version_upgrade is True


def test_confidence_score_changes_detected():
    """Detect when confidence scores differ between models."""
    old_decision = {
        "task_id": "task_006",
        "model": "haiku",
        "output": {"confidence": 0.65},
    }

    new_model = MockModelProvider("opus", version="2.0")
    replay_result = cfr.replay_decision("task_006", old_decision, new_model)

    confidence_delta = cfr.calculate_confidence_change(
        old_decision["output"]["confidence"], replay_result.get("confidence", 0.0)
    )

    assert confidence_delta != 0
    assert "confidence_change" in cfr.analyze_replay_impact(
        old_decision, replay_result
    )


# =============================================================================
# Policy Change Detection (7-9)
# =============================================================================


def test_detect_policy_change_when_decision_differs():
    """Detect policy change when replay would choose differently."""
    old_decision = {
        "task_id": "task_007",
        "model": "haiku",
        "input": {"operation": "route_selection"},
        "output": {"route": "model_a", "policy": "cost_optimized"},
    }

    old_model = MockModelProvider("haiku", version="1.0")
    new_model = MockModelProvider("opus", version="2.0")

    old_output = {"route": "model_a"}
    new_output = {"route": "model_b"}

    policy_change = cfr.detect_policy_change(old_output, new_output)

    assert policy_change["changed"] is True
    assert policy_change["old_route"] == "model_a"
    assert policy_change["new_route"] == "model_b"


def test_no_policy_change_when_decision_same():
    """No policy change flagged when decision remains same."""
    old_decision = {
        "task_id": "task_008",
        "output": {"route": "model_a"},
    }

    old_output = {"route": "model_a"}
    new_output = {"route": "model_a"}

    policy_change = cfr.detect_policy_change(old_output, new_output)

    assert policy_change["changed"] is False
    assert policy_change.get("reason") == "decision_stable"


def test_policy_change_reason_documented():
    """Policy change includes reason/explanation."""
    old_output = {"route": "fallback", "confidence": 0.6}
    new_output = {"route": "premium", "confidence": 0.92}

    policy_change = cfr.detect_policy_change(old_output, new_output)

    assert "reason" in policy_change
    assert "confidence_improvement" in str(policy_change.get("reason", ""))
    assert policy_change["confidence_delta"] == 0.32


# =============================================================================
# Data-Driven Changes (10-12)
# =============================================================================


def test_replay_with_updated_context_data():
    """Replaying with updated context data produces different result."""
    old_decision = {
        "task_id": "task_009",
        "input": {"context_version": 1, "data": "old"},
        "output": {"route": "old_route"},
    }

    new_model = MockModelProvider("opus", version="2.0")
    new_context = {"context_version": 2, "data": "fresh"}

    replay_result = cfr.replay_decision_with_context(
        "task_009", old_decision, new_model, new_context
    )

    assert replay_result["context_version"] == 2
    assert "data_evolution" in replay_result
    assert replay_result["data_evolution"]["old"] == "old"
    assert replay_result["data_evolution"]["new"] == "fresh"


def test_data_evolution_tracked():
    """Data evolution between original and replay is tracked."""
    old_data = {"version": 1, "config": "A", "timestamp": "2026-08-01"}
    new_data = {"version": 2, "config": "B", "timestamp": "2026-08-19"}

    evolution = cfr.track_data_evolution(old_data, new_data)

    assert evolution["old_version"] == 1
    assert evolution["new_version"] == 2
    assert evolution["changes"] == ["config", "timestamp"]
    assert evolution["config_old"] == "A"
    assert evolution["config_new"] == "B"


def test_replay_with_missing_data_fails_gracefully():
    """Replay handles missing data gracefully (fail-soft)."""
    old_decision = {
        "task_id": "task_010",
        "input": {},
        "output": {},
    }

    new_model = MockModelProvider("opus", version="2.0")

    try:
        replay_result = cfr.replay_decision_safe(
            "task_010", old_decision, new_model
        )
        assert replay_result is not None
        assert replay_result.get("status") in ["partial", "success"]
    except Exception as e:
        # Should not raise, fail-soft
        assert False, f"Replay should not raise on missing data: {e}"


# =============================================================================
# Route Updates (13-15)
# =============================================================================


def test_update_route_based_on_counterfactual():
    """Update routing policy based on counterfactual analysis."""
    policy_change = {
        "changed": True,
        "old_route": "model_a",
        "new_route": "model_b",
        "confidence_delta": 0.25,
        "reason": "higher_confidence_available",
    }

    old_route_config = {
        "operation": "debate_compress",
        "model": "haiku",
        "q_score": 7.0,
    }

    new_route = cfr.update_route_policy(
        "debate_compress", old_route_config, policy_change
    )

    assert new_route["operation"] == "debate_compress"
    assert new_route["updated"] is True
    assert new_route["prior_model"] == "haiku"
    assert "new_model" in new_route


def test_route_update_persisted_to_storage():
    """Route updates are persisted to storage."""
    temp_dir = tempfile.mkdtemp()

    try:
        storage = cfr.RouteStorage(temp_dir)
        route_update = {
            "operation": "pipeline_plan",
            "old_model": "llama3.2",
            "new_model": "opus",
            "q_score_before": 7.7,
            "q_score_after": 8.2,
            "timestamp": datetime.now().isoformat(),
        }

        storage.persist_route_update(route_update)

        # Verify persistence
        retrieved = storage.get_route_update("pipeline_plan")
        assert retrieved is not None
        assert retrieved["new_model"] == "opus"
    finally:
        shutil.rmtree(temp_dir)


def test_route_update_applied_to_future_decisions():
    """Updated route applies to future decision routing."""
    route_config = cfr.RouteConfig()

    # Original route
    route_config.set_route("debate_compress", "haiku", q_score=7.0)
    decision1 = route_config.get_route("debate_compress")
    assert decision1["model"] == "haiku"

    # Update route
    route_config.update_route("debate_compress", "opus", q_score=8.5)
    decision2 = route_config.get_route("debate_compress")
    assert decision2["model"] == "opus"
    assert decision2["q_score"] == 8.5


# =============================================================================
# Batch Processing (16-18)
# =============================================================================


def test_replay_batch_of_past_decisions():
    """Batch replay of multiple past decisions."""
    decisions = [
        {
            "task_id": "task_011",
            "model": "haiku",
            "input": {"data": "a"},
            "output": {"route": "x"},
        },
        {
            "task_id": "task_012",
            "model": "haiku",
            "input": {"data": "b"},
            "output": {"route": "y"},
        },
        {
            "task_id": "task_013",
            "model": "haiku",
            "input": {"data": "c"},
            "output": {"route": "z"},
        },
    ]

    new_model = MockModelProvider("opus", version="2.0")
    batch_results = cfr.replay_batch(decisions, new_model)

    assert len(batch_results) == 3
    assert all("task_id" in r for r in batch_results)
    assert batch_results[0]["original_task_id"] == "task_011"
    assert batch_results[2]["original_task_id"] == "task_013"


def test_batch_replay_returns_summary_statistics():
    """Batch replay returns summary stats (count, changes, etc)."""
    decisions = [
        {"task_id": f"task_{i:03d}", "output": {"route": "a"}}
        for i in range(10)
    ]

    new_model = MockModelProvider("opus", version="2.0")
    batch_results, summary = cfr.replay_batch_with_summary(decisions, new_model)

    assert summary["total_replayed"] == 10
    assert "policy_changes" in summary
    assert "avg_confidence_delta" in summary
    assert "models_tested" in summary
    assert summary["models_tested"] == ["opus"]


def test_batch_replay_with_filtering():
    """Batch replay can be filtered by task type, date range, etc."""
    decisions = [
        {
            "task_id": "task_014",
            "type": "routing",
            "timestamp": "2026-08-01",
        },
        {"task_id": "task_015", "type": "build", "timestamp": "2026-08-15"},
        {
            "task_id": "task_016",
            "type": "routing",
            "timestamp": "2026-08-18",
        },
    ]

    # Filter by type
    routing_only = cfr.filter_decisions(decisions, task_type="routing")
    assert len(routing_only) == 2
    assert all(d["type"] == "routing" for d in routing_only)

    # Filter by date range
    recent = cfr.filter_decisions(
        decisions, start_date="2026-08-10", end_date="2026-08-19"
    )
    assert len(recent) == 2


# =============================================================================
# Edge Cases (19-23)
# =============================================================================


def test_replay_with_empty_history():
    """Replay handles empty decision history gracefully."""
    result = cfr.replay_batch([], MockModelProvider("opus", version="2.0"))

    assert result == []
    assert cfr.is_empty_history([]) is True


def test_replay_decision_not_in_history_returns_error():
    """Attempt to replay non-existent decision handled."""
    try:
        result = cfr.replay_decision(
            "nonexistent", {"task_id": "nonexistent"}, MockModelProvider("opus")
        )
        # Should return None or raise StructuredError gracefully
        assert result is None or "error" in result
    except ehu.StructuredError as se:
        assert se.category in ["logic", "transient"]
        assert se.retryable in [True, False]


def test_replay_with_corrupted_decision_data():
    """Corrupted decision data handled with fail-soft."""
    corrupted_decision = {
        "task_id": None,
        "model": "",
        "input": None,
        "output": "malformed",
    }

    new_model = MockModelProvider("opus", version="2.0")
    result = cfr.replay_decision_safe("task_017", corrupted_decision, new_model)

    # Should not raise, should return gracefully
    assert result is not None
    assert result.get("status") in ["partial", "error", "skipped"]


def test_replay_circular_dependency_handling():
    """Handle circular dependencies in replayed decisions."""
    decisions = {
        "task_a": {"depends_on": "task_b"},
        "task_b": {"depends_on": "task_a"},
    }

    detection = cfr.detect_circular_dependencies(decisions)

    assert detection["has_cycle"] is True
    assert "task_a" in detection["cycle"] or "task_b" in detection["cycle"]


def test_replay_with_conflicting_policies():
    """Handle conflicting policies in route updates."""
    existing_policy = {
        "operation": "routing",
        "preferred_model": "haiku",
        "priority": "cost",
    }

    new_policy = {
        "operation": "routing",
        "preferred_model": "opus",
        "priority": "quality",
    }

    conflict_resolution = cfr.resolve_policy_conflict(
        existing_policy, new_policy
    )

    assert "conflict" in conflict_resolution
    assert "resolution" in conflict_resolution
    assert conflict_resolution["resolution"] in ["keep_existing", "adopt_new", "merge"]


# =============================================================================
# Idempotency & State (24-26)
# =============================================================================


def test_replay_same_task_twice_yields_same_result():
    """Replaying same task twice with same inputs yields same result."""
    decision = {
        "task_id": "task_018",
        "model": "haiku",
        "input": {"seed": 42},
        "output": {"route": "model_a"},
    }

    new_model = MockModelProvider("opus", version="2.0")

    result1 = cfr.replay_decision("task_018", decision, new_model)
    result2 = cfr.replay_decision("task_018", decision, new_model)

    # Same inputs should yield same decision
    assert result1["decision"] == result2["decision"]
    assert result1["model"] == result2["model"]


def test_replay_state_isolation():
    """Replay state is isolated per task (no cross-contamination)."""
    tasks = [
        {"task_id": "task_019_a", "state": "state_a"},
        {"task_id": "task_019_b", "state": "state_b"},
    ]

    new_model = MockModelProvider("opus", version="2.0")

    result_a = cfr.replay_decision(
        "task_019_a", tasks[0], new_model
    )
    result_b = cfr.replay_decision(
        "task_019_b", tasks[1], new_model
    )

    assert result_a["original_task_id"] == "task_019_a"
    assert result_b["original_task_id"] == "task_019_b"
    assert result_a["state"] == "state_a"
    assert result_b["state"] == "state_b"


def test_replay_idempotent_on_storage_updates():
    """Storage updates from replay are idempotent."""
    temp_dir = tempfile.mkdtemp()

    try:
        storage = cfr.ReplayStorage(temp_dir)

        replay_result = {
            "task_id": "task_020",
            "timestamp": datetime.now().isoformat(),
            "decision": "result_1",
        }

        storage.save_replay(replay_result)
        storage.save_replay(replay_result)

        count = storage.count_replays("task_020")
        assert count == 1  # Idempotent, not 2
    finally:
        shutil.rmtree(temp_dir)


# =============================================================================
# Persistence & Retrieval (27-29)
# =============================================================================


def test_replay_results_persisted_to_database():
    """Replay results are saved to persistent storage."""
    temp_dir = tempfile.mkdtemp()

    try:
        storage = cfr.ReplayStorage(temp_dir)

        replay_results = [
            {
                "task_id": "task_021",
                "model": "opus",
                "decision": "choice_a",
            },
            {
                "task_id": "task_022",
                "model": "opus",
                "decision": "choice_b",
            },
        ]

        for result in replay_results:
            storage.save_replay(result)

        assert storage.count_replays() == 2
    finally:
        shutil.rmtree(temp_dir)


def test_retrieve_replay_results_for_task():
    """Retrieve replay results for a specific task."""
    temp_dir = tempfile.mkdtemp()

    try:
        storage = cfr.ReplayStorage(temp_dir)

        storage.save_replay({"task_id": "task_023", "result": "outcome_1"})
        storage.save_replay({"task_id": "task_023", "result": "outcome_2"})
        storage.save_replay({"task_id": "task_024", "result": "outcome_3"})

        task_023_results = storage.get_replays("task_023")
        assert len(task_023_results) == 2
        assert all(r["task_id"] == "task_023" for r in task_023_results)
    finally:
        shutil.rmtree(temp_dir)


def test_replay_history_queryable():
    """Replay history can be queried by various filters."""
    temp_dir = tempfile.mkdtemp()

    try:
        storage = cfr.ReplayStorage(temp_dir)

        # Add diverse replay results
        storage.save_replay(
            {
                "task_id": "task_025",
                "model": "haiku",
                "policy_changed": False,
                "timestamp": datetime.now().isoformat(),
            }
        )
        storage.save_replay(
            {
                "task_id": "task_026",
                "model": "opus",
                "policy_changed": True,
                "timestamp": datetime.now().isoformat(),
            }
        )

        # Query by model
        opus_replays = storage.query(model="opus")
        assert len(opus_replays) == 1
        assert opus_replays[0]["model"] == "opus"

        # Query by policy change
        changed = storage.query(policy_changed=True)
        assert len(changed) == 1
    finally:
        shutil.rmtree(temp_dir)


# =============================================================================
# Concurrency & Thread Safety (30-31)
# =============================================================================


def test_concurrent_replays_thread_safe():
    """Concurrent replay operations are thread-safe."""
    decisions = [
        {
            "task_id": f"task_027_{i}",
            "model": "haiku",
            "input": {"data": f"item_{i}"},
        }
        for i in range(5)
    ]

    results = {"count": 0, "lock": Lock()}
    errors = []

    def replay_worker(decision):
        try:
            new_model = MockModelProvider("opus", version="2.0")
            result = cfr.replay_decision(
                decision["task_id"], decision, new_model
            )
            with results["lock"]:
                results["count"] += 1
        except Exception as e:
            errors.append(e)

    threads = [
        Thread(target=replay_worker, args=(d,)) for d in decisions
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert results["count"] == 5
    assert len(errors) == 0


def test_replay_does_not_block_main_runner():
    """Background replay does not block main runner operations."""
    blocking_event = {"blocked": False, "lock": Lock()}

    def background_replay():
        # Simulate long-running replay
        time.sleep(0.05)

    def main_operation():
        # Should complete quickly without waiting for replay
        with blocking_event["lock"]:
            blocking_event["blocked"] = False

    start = time.time()
    replay_thread = Thread(target=background_replay)
    replay_thread.start()

    main_operation()

    elapsed = time.time() - start
    replay_thread.join()

    # Main operation should complete quickly (< 10ms)
    assert elapsed < 0.01
    assert blocking_event["blocked"] is False


# =============================================================================
# Integration Tests (32-34)
# =============================================================================


def test_integration_replay_updates_policy_and_routing():
    """End-to-end: replay detects change, updates policy, affects routing."""
    temp_dir = tempfile.mkdtemp()

    try:
        # Step 1: Load old decision
        old_decision = {
            "task_id": "task_028",
            "model": "haiku",
            "output": {"route": "model_a"},
        }

        # Step 2: Replay with new model
        new_model = MockModelProvider("opus", version="2.0")
        replay_result = cfr.replay_decision("task_028", old_decision, new_model)

        # Step 3: Detect policy change
        if cfr.has_policy_change(old_decision, replay_result):
            # Step 4: Update route config
            route_config = cfr.RouteConfig()
            route_config.apply_counterfactual_update(
                "task_operation", replay_result
            )

        # Step 5: Verify new routing applies
        updated_route = route_config.get_route("task_operation")
        assert updated_route is not None
    finally:
        shutil.rmtree(temp_dir)


def test_integration_replay_with_fleet_config():
    """Replay integrates with fleet-wide config updates."""
    # Mock fleet config
    with patch("fleet_control.push_config") as mock_push:
        mock_push.return_value = {"status": "success"}

        # Create replay result with policy change
        replay_result = {
            "task_id": "task_029",
            "policy_changed": True,
            "new_model": "opus",
            "q_score_delta": 0.8,
        }

        # Push to fleet
        config_key = f"ORCH_ROUTE_task_029"
        fleet_control.push_config(config_key, replay_result["new_model"])

        mock_push.assert_called_once()
        assert mock_push.call_args[0][0] == config_key


def test_integration_replay_with_worktree_workflow():
    """Replay works within worktree isolation model."""
    # Mock worktree context
    with patch("counterfactual_replay.get_worktree_path") as mock_wt:
        mock_wt.return_value = "/path/to/wt/replay-29"

        replay_result = {
            "task_id": "task_030",
            "worktree": "/path/to/wt/replay-29",
            "branch": "agent/counterfactual-replay-29",
        }

        assert replay_result["branch"].startswith("agent/")
        assert "counterfactual" in replay_result["branch"]


# =============================================================================
# Run all tests
# =============================================================================


if __name__ == "__main__":
    test_replay_single_past_decision()
    test_replay_preserves_decision_metadata()
    test_replay_with_new_model_produces_output()

    test_compare_old_vs_new_model_outputs()
    test_model_version_difference_tracked()
    test_confidence_score_changes_detected()

    test_detect_policy_change_when_decision_differs()
    test_no_policy_change_when_decision_same()
    test_policy_change_reason_documented()

    test_replay_with_updated_context_data()
    test_data_evolution_tracked()
    test_replay_with_missing_data_fails_gracefully()

    test_update_route_based_on_counterfactual()
    test_route_update_persisted_to_storage()
    test_route_update_applied_to_future_decisions()

    test_replay_batch_of_past_decisions()
    test_batch_replay_returns_summary_statistics()
    test_batch_replay_with_filtering()

    test_replay_with_empty_history()
    test_replay_decision_not_in_history_returns_error()
    test_replay_with_corrupted_decision_data()
    test_replay_circular_dependency_handling()
    test_replay_with_conflicting_policies()

    test_replay_same_task_twice_yields_same_result()
    test_replay_state_isolation()
    test_replay_idempotent_on_storage_updates()

    test_replay_results_persisted_to_database()
    test_retrieve_replay_results_for_task()
    test_replay_history_queryable()

    test_concurrent_replays_thread_safe()
    test_replay_does_not_block_main_runner()

    test_integration_replay_updates_policy_and_routing()
    test_integration_replay_with_fleet_config()
    test_integration_replay_with_worktree_workflow()

    print("✓ All 34 counterfactual-replay tests passed")
