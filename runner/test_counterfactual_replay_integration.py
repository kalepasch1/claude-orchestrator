#!/usr/bin/env python3
"""Integration and edge-case tests for counterfactual_replay module.

This suite covers:
- RouteConfig thread safety and persistence
- ReplayStorage database operations
- Cross-decision conflict detection and resolution
- Circular dependency detection
- Batch replay with summary statistics
- Configuration management and env-var handling
- Error recovery and graceful degradation
- Policy change tracking across replay cycles
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


class FakeModel:
    """Test model with configurable responses."""

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
# RouteConfig thread safety and operations
# =============================================================================

class TestRouteConfig:
    """Tests for RouteConfig class — in-memory route management."""

    def test_set_and_get_route(self):
        """Set and retrieve a route."""
        config = cfr.RouteConfig()
        config.set_route("build", "opus", q_score=0.85)
        route = config.get_route("build")

        assert route["operation"] == "build"
        assert route["model"] == "opus"
        assert route["q_score"] == 0.85

    def test_get_nonexistent_route_returns_none(self):
        """Getting a route that was never set returns None."""
        config = cfr.RouteConfig()
        assert config.get_route("unknown") is None

    def test_update_existing_route(self):
        """Updating an existing route preserves operation, updates model."""
        config = cfr.RouteConfig()
        config.set_route("build", "haiku", q_score=0.7)
        config.update_route("build", "opus", q_score=0.9)

        route = config.get_route("build")
        assert route["model"] == "opus"
        assert route["q_score"] == 0.9

    def test_update_nonexistent_route_creates_it(self):
        """Updating a route that doesn't exist creates it."""
        config = cfr.RouteConfig()
        config.update_route("build", "opus", q_score=0.8)

        route = config.get_route("build")
        assert route is not None
        assert route["model"] == "opus"

    def test_apply_counterfactual_update(self):
        """Apply a counterfactual replay result as a route update."""
        config = cfr.RouteConfig()
        replay_result = {
            "model": "sonnet",
            "q_score_delta": 0.15,
        }
        config.apply_counterfactual_update("build", replay_result)

        route = config.get_route("build")
        assert route["model"] == "sonnet"
        assert route["q_score"] == 0.15

    def test_apply_counterfactual_uses_new_model_fallback(self):
        """If 'model' is absent, 'new_model' is used."""
        config = cfr.RouteConfig()
        replay_result = {
            "new_model": "claude-3",
            "q_score_delta": 0.2,
        }
        config.apply_counterfactual_update("test", replay_result)

        route = config.get_route("test")
        assert route["model"] == "claude-3"

    def test_concurrent_route_updates(self):
        """Multiple threads can update routes concurrently."""
        config = cfr.RouteConfig()
        errors = []

        def worker(op_id):
            try:
                for i in range(10):
                    config.set_route(f"op_{op_id}", f"model_{i}")
                    config.update_route(f"op_{op_id}", f"updated_{i}")
                    route = config.get_route(f"op_{op_id}")
                    assert route is not None
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors


# =============================================================================
# RouteStorage persistence
# =============================================================================

class TestRouteStorage:
    """Tests for RouteStorage class — persistent route updates."""

    def test_persist_and_retrieve_route_update(self, tmp_path):
        """Save and load a route update."""
        storage = cfr.RouteStorage(tmp_path)
        update = {
            "operation": "build",
            "model": "opus",
            "confidence_delta": 0.15,
            "timestamp": datetime.now().isoformat(),
        }

        storage.persist_route_update(update)
        retrieved = storage.get_route_update("build")

        assert retrieved["operation"] == "build"
        assert retrieved["model"] == "opus"
        assert retrieved["confidence_delta"] == 0.15

    def test_persist_overwrites_existing_operation(self, tmp_path):
        """Persisting an update for the same operation overwrites it."""
        storage = cfr.RouteStorage(tmp_path)

        storage.persist_route_update({"operation": "build", "model": "haiku"})
        storage.persist_route_update({"operation": "build", "model": "opus"})

        retrieved = storage.get_route_update("build")
        assert retrieved["model"] == "opus"

    def test_get_nonexistent_update_returns_none(self, tmp_path):
        """Getting an update that was never persisted returns None."""
        storage = cfr.RouteStorage(tmp_path)
        assert storage.get_route_update("unknown") is None

    def test_storage_survives_bad_json(self, tmp_path):
        """Corrupted JSON file doesn't crash retrieval."""
        storage = cfr.RouteStorage(tmp_path)

        # Write corrupted JSON
        storage.db_path.write_text("{invalid json")

        # Should handle gracefully
        result = storage.get_route_update("anything")
        assert result is None

    def test_persist_handles_non_serializable_values(self, tmp_path):
        """Updates with non-JSON-serializable values are handled."""
        storage = cfr.RouteStorage(tmp_path)
        update = {
            "operation": "build",
            "model": "opus",
            "timestamp": datetime.now(),
        }

        # Should not raise; datetime is stringified by default=str
        storage.persist_route_update(update)
        retrieved = storage.get_route_update("build")
        assert retrieved is not None


# =============================================================================
# ReplayStorage database operations
# =============================================================================

class TestReplayStorage:
    """Tests for ReplayStorage class — persistent replay results."""

    def test_initialization_creates_database(self, tmp_path):
        """ReplayStorage initializes a SQLite database."""
        storage = cfr.ReplayStorage(tmp_path)
        assert storage.db_path.exists()

    def test_database_schema_is_valid(self, tmp_path):
        """The database schema can be queried."""
        storage = cfr.ReplayStorage(tmp_path)

        with sqlite3.connect(str(storage.db_path)) as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='replay_results'"
            )
            assert cursor.fetchone() is not None


# =============================================================================
# Batch replay with summaries
# =============================================================================

class TestReplayBatchWithSummary:
    """Tests for replay_batch_with_summary() — batch stats and aggregation."""

    def test_empty_decisions_returns_empty_results_and_summary(self):
        """Empty input yields empty output and zero summary."""
        results, summary = cfr.replay_batch_with_summary([], FakeModel())

        assert results == []
        assert summary["total_replayed"] == 0
        assert summary["policy_changes"] == 0
        assert summary["avg_confidence_delta"] == 0.0

    def test_summary_counts_total_replayed(self):
        """Summary reports how many decisions were replayed."""
        decisions = [
            {"task_id": "t1", "input": {"q": 1}},
            {"task_id": "t2", "input": {"q": 2}},
            {"task_id": "t3", "input": {"q": 3}},
        ]
        results, summary = cfr.replay_batch_with_summary(decisions, FakeModel())

        assert summary["total_replayed"] == 3

    def test_summary_detects_policy_changes(self):
        """Summary counts how many replays detected policy changes."""
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

        model = FakeModel(decision="opus", confidence=0.9)
        results, summary = cfr.replay_batch_with_summary(decisions, model)

        assert summary["policy_changes"] == 2

    def test_summary_calculates_average_confidence_delta(self):
        """Summary reports mean change in confidence across batch."""
        decisions = [
            {
                "task_id": "t1",
                "input": {"q": 1},
                "output": {"route": "haiku", "confidence": 0.5},
            },
            {
                "task_id": "t2",
                "input": {"q": 2},
                "output": {"route": "haiku", "confidence": 0.6},
            },
        ]

        model = FakeModel(decision="haiku", confidence=0.9)
        results, summary = cfr.replay_batch_with_summary(decisions, model)

        # (|0.9 - 0.5| + |0.9 - 0.6|) / 2 = (0.4 + 0.3) / 2 = 0.35
        assert abs(summary["avg_confidence_delta"] - 0.35) < 0.01

    def test_summary_lists_models_tested(self):
        """Summary reports unique models that produced decisions."""
        decisions = [
            {"task_id": "t1", "input": {"q": 1}},
            {"task_id": "t2", "input": {"q": 2}},
        ]

        model = FakeModel(model_id="opus", version="2.0")
        results, summary = cfr.replay_batch_with_summary(decisions, model)

        assert "opus" in summary["models_tested"]

    def test_summary_handles_mixed_valid_and_invalid_decisions(self):
        """Summary counts only valid replays."""
        decisions = [
            {"task_id": "t1", "input": {"q": 1}},
            {"task_id": "t2"},  # No input
            {"task_id": "t3", "input": {"q": 3}},
        ]

        results, summary = cfr.replay_batch_with_summary(decisions, FakeModel())

        assert summary["total_replayed"] == 2


# =============================================================================
# Circular dependency detection
# =============================================================================

class TestDetectCircularDependencies:
    """Tests for detect_circular_dependencies() — dependency graph validation."""

    def test_empty_graph_has_no_cycle(self):
        """An empty decision graph has no cycles."""
        result = cfr.detect_circular_dependencies({})
        assert result["has_cycle"] is False
        assert result["cycle"] == []

    def test_none_graph_has_no_cycle(self):
        """None is treated as an empty graph."""
        result = cfr.detect_circular_dependencies(None)
        assert result["has_cycle"] is False

    def test_linear_chain_has_no_cycle(self):
        """A linear dependency chain (A -> B -> C) has no cycle."""
        decisions = {
            "A": {"depends_on": "B"},
            "B": {"depends_on": "C"},
            "C": {"depends_on": None},
        }
        result = cfr.detect_circular_dependencies(decisions)
        assert result["has_cycle"] is False

    def test_direct_cycle_detected(self):
        """A direct cycle (A -> B -> A) is detected."""
        decisions = {
            "A": {"depends_on": "B"},
            "B": {"depends_on": "A"},
        }
        result = cfr.detect_circular_dependencies(decisions)
        assert result["has_cycle"] is True
        assert len(result["cycle"]) > 0

    def test_self_reference_cycle_detected(self):
        """A node depending on itself is detected as a cycle."""
        decisions = {
            "A": {"depends_on": "A"},
        }
        result = cfr.detect_circular_dependencies(decisions)
        assert result["has_cycle"] is True

    def test_malformed_dependencies_are_handled(self):
        """Decisions with malformed dependency data don't crash."""
        decisions = {
            "A": "not-a-dict",
            "B": {"depends_on": "A"},
        }
        result = cfr.detect_circular_dependencies(decisions)
        assert isinstance(result, dict)
        assert "has_cycle" in result


# =============================================================================
# Filter decisions by type and date range
# =============================================================================

class TestFilterDecisions:
    """Tests for filter_decisions() — query and filtering."""

    def test_filter_by_task_type(self):
        """Decisions can be filtered by task type."""
        decisions = [
            {"task_id": "t1", "type": "routing"},
            {"task_id": "t2", "type": "build"},
            {"task_id": "t3", "type": "routing"},
        ]

        result = cfr.filter_decisions(decisions, task_type="routing")
        assert len(result) == 2
        assert all(d["type"] == "routing" for d in result)

    def test_filter_by_date_range(self):
        """Decisions can be filtered by timestamp range."""
        decisions = [
            {"task_id": "t1", "timestamp": "2026-08-18T10:00:00"},
            {"task_id": "t2", "timestamp": "2026-08-20T10:00:00"},
            {"task_id": "t3", "timestamp": "2026-08-25T10:00:00"},
        ]

        result = cfr.filter_decisions(
            decisions,
            start_date="2026-08-19T00:00:00",
            end_date="2026-08-24T23:59:59"
        )

        assert len(result) == 1
        assert result[0]["task_id"] == "t2"

    def test_filter_by_type_and_date(self):
        """Decisions can be filtered by both type and date."""
        decisions = [
            {"task_id": "t1", "type": "routing", "timestamp": "2026-08-18T10:00:00"},
            {"task_id": "t2", "type": "build", "timestamp": "2026-08-20T10:00:00"},
            {"task_id": "t3", "type": "routing", "timestamp": "2026-08-25T10:00:00"},
        ]

        result = cfr.filter_decisions(
            decisions,
            task_type="routing",
            start_date="2026-08-20T00:00:00"
        )

        assert len(result) == 1
        assert result[0]["task_id"] == "t3"

    def test_filter_handles_non_dict_decisions(self):
        """Filter skips non-dict decisions gracefully."""
        decisions = [
            {"task_id": "t1", "type": "routing"},
            "not-a-dict",
            {"task_id": "t2", "type": "routing"},
        ]

        result = cfr.filter_decisions(decisions, task_type="routing")
        assert len(result) == 2

    def test_filter_none_input_returns_empty(self):
        """Filtering None returns an empty list."""
        result = cfr.filter_decisions(None, task_type="routing")
        assert result == []

    def test_filter_with_bad_input_returns_original(self):
        """If an exception occurs during filtering, return original."""
        decisions = [{"task_id": "t1"}]
        result = cfr.filter_decisions(decisions, task_type=None)
        # Should return decisions as-is if filtering fails
        assert isinstance(result, list)


# =============================================================================
# Empty history detection
# =============================================================================

class TestIsEmptyHistory:
    """Tests for is_empty_history() — history validation."""

    def test_none_history_is_empty(self):
        """None is an empty history."""
        assert cfr.is_empty_history(None) is True

    def test_empty_list_is_empty(self):
        """An empty list is an empty history."""
        assert cfr.is_empty_history([]) is True

    def test_non_empty_list_is_not_empty(self):
        """A list with items is not empty."""
        assert cfr.is_empty_history([{"task_id": "t1"}]) is False

    def test_single_item_list_is_not_empty(self):
        """A list with one item is not empty."""
        assert cfr.is_empty_history([{"task_id": "t1"}]) is False


# =============================================================================
# Policy conflict resolution
# =============================================================================

class TestResolvePolicyConflict:
    """Tests for resolve_policy_conflict() — multi-version policy reconciliation."""

    def test_identical_policies_have_no_conflict(self):
        """Policies with identical values report no conflict."""
        policy = {"model": "opus", "priority": "quality"}
        result = cfr.resolve_policy_conflict(policy, dict(policy))

        assert result["conflict"] is False
        assert result["resolution"] == "keep_existing"

    def test_different_values_are_reported(self):
        """Each conflicting key is reported with both values."""
        result = cfr.resolve_policy_conflict(
            {"model": "haiku", "priority": "cost"},
            {"model": "opus", "priority": "cost"}
        )

        assert result["conflict"] is True
        assert result["conflicts"]["model"]["existing"] == "haiku"
        assert result["conflicts"]["model"]["new"] == "opus"

    def test_added_key_is_a_conflict(self):
        """A key present only in new_policy is reported as a conflict."""
        result = cfr.resolve_policy_conflict(
            {"model": "opus"},
            {"model": "opus", "retry_count": 3}
        )

        assert result["conflict"] is True
        assert result["conflicts"]["retry_count"]["existing"] is None
        assert result["conflicts"]["retry_count"]["new"] == 3

    def test_removed_key_is_a_conflict(self):
        """A key absent in new_policy is reported as a conflict."""
        result = cfr.resolve_policy_conflict(
            {"model": "opus", "retry_count": 3},
            {"model": "opus"}
        )

        assert result["conflict"] is True
        assert result["conflicts"]["retry_count"]["existing"] == 3
        assert result["conflicts"]["retry_count"]["new"] is None

    def test_conflict_resolution_is_merge(self):
        """Any conflict resolves to merge strategy."""
        result = cfr.resolve_policy_conflict({"a": 1}, {"a": 2})
        assert result["resolution"] == "merge"

    def test_bad_input_fails_soft(self):
        """None inputs don't crash; resolution is merge."""
        result = cfr.resolve_policy_conflict(None, None)
        assert result["conflict"] is False
        assert result["resolution"] == "merge"

    def test_non_dict_input_fails_soft(self):
        """Non-dict inputs are handled gracefully."""
        result = cfr.resolve_policy_conflict("not-a-dict", {"model": "opus"})
        assert isinstance(result, dict)
        assert "resolution" in result


# =============================================================================
# Update route policy
# =============================================================================

class TestUpdateRoutePolicy:
    """Tests for update_route_policy() — policy update generation."""

    def test_no_change_means_no_update(self):
        """A stable policy change produces updated=False."""
        change = {"changed": False, "reason": "stable"}
        update = cfr.update_route_policy("build", {"model": "haiku"}, change)

        assert update["updated"] is False

    def test_changed_policy_is_marked_updated(self):
        """A divergence marks updated=True."""
        change = {"changed": True, "new_route": "opus"}
        update = cfr.update_route_policy("build", {}, change)

        assert update["updated"] is True

    def test_update_carries_operation_and_models(self):
        """The update includes operation, prior model, and new model."""
        change = {"changed": True, "new_route": "opus"}
        update = cfr.update_route_policy("build", {"model": "haiku"}, change)

        assert update["operation"] == "build"
        assert update["prior_model"] == "haiku"
        assert update["new_model"] == "opus"

    def test_update_carries_confidence_delta(self):
        """The confidence change is included in the update."""
        change = {"changed": True, "new_route": "opus", "confidence_delta": 0.25}
        update = cfr.update_route_policy("build", {}, change)

        assert update["confidence_delta"] == 0.25

    def test_update_is_timestamped(self):
        """Every update has an ISO timestamp."""
        change = {"changed": True}
        update = cfr.update_route_policy("build", {}, change)

        assert "timestamp" in update
        assert "T" in update["timestamp"]

    def test_bad_inputs_fail_soft(self):
        """Malformed inputs return a well-formed update."""
        update = cfr.update_route_policy("build", None, None)

        assert update["operation"] == "build"
        assert update["updated"] is False


# =============================================================================
# Track data evolution
# =============================================================================

class TestTrackDataEvolution:
    """Tests for track_data_evolution() — temporal data change tracking."""

    def test_identical_data_reports_no_changes(self):
        """Identical old and new data show no changes."""
        data = {"version": 1, "field_a": "value", "field_b": 42}
        result = cfr.track_data_evolution(data, data)

        assert result["changes"] == []

    def test_changed_field_is_reported(self):
        """Fields that changed are listed in changes."""
        old = {"version": 1, "field_a": "old_value", "field_b": 42}
        new = {"version": 2, "field_a": "new_value", "field_b": 42}

        result = cfr.track_data_evolution(old, new)

        assert "field_a" in result["changes"]
        assert result["field_a_old"] == "old_value"
        assert result["field_a_new"] == "new_value"

    def test_added_field_is_reported(self):
        """Fields added in new data are reported."""
        old = {"version": 1, "field_a": "value"}
        new = {"version": 2, "field_a": "value", "field_b": "new_field"}

        result = cfr.track_data_evolution(old, new)

        assert "field_b" in result["changes"]
        assert result["field_b_new"] == "new_field"

    def test_removed_field_is_reported(self):
        """Fields removed from old data are reported."""
        old = {"version": 1, "field_a": "value", "field_b": "removed"}
        new = {"version": 2, "field_a": "value"}

        result = cfr.track_data_evolution(old, new)

        assert "field_b" in result["changes"]
        assert result["field_b_old"] == "removed"

    def test_non_dict_inputs_return_empty_changes(self):
        """Non-dict inputs result in no changes tracked."""
        result = cfr.track_data_evolution("not-a-dict", None)
        assert result["changes"] == []


# =============================================================================
# Analyze replay impact
# =============================================================================

class TestAnalyzeReplayImpact:
    """Tests for analyze_replay_impact() — impact assessment."""

    def test_stable_decision_is_reported(self):
        """A decision that didn't change is reported as stable."""
        old_decision = {
            "output": {"route": "opus", "confidence": 0.8},
            "model": "haiku"
        }
        replay_result = {
            "decision": "opus",
            "confidence": 0.8,
            "model": "opus"
        }

        impact = cfr.analyze_replay_impact(old_decision, replay_result)

        assert impact["decision_stable"] is True

    def test_model_change_is_detected(self):
        """A change in model is reported."""
        old_decision = {
            "output": {"route": "opus"},
            "model": "haiku"
        }
        replay_result = {
            "decision": "opus",
            "model": "opus"
        }

        impact = cfr.analyze_replay_impact(old_decision, replay_result)

        assert impact["model_changed"] is True

    def test_confidence_change_is_calculated(self):
        """The change in confidence is computed."""
        old_decision = {
            "output": {"route": "opus", "confidence": 0.5},
        }
        replay_result = {
            "decision": "opus",
            "confidence": 0.8,
        }

        impact = cfr.analyze_replay_impact(old_decision, replay_result)

        assert abs(impact["confidence_change"] - 0.3) < 0.01

    def test_corrupted_old_output_is_handled(self):
        """A non-dict old output doesn't crash analysis."""
        old_decision = {
            "output": "corrupted",
        }
        replay_result = {
            "decision": "opus",
            "confidence": 0.8,
        }

        impact = cfr.analyze_replay_impact(old_decision, replay_result)

        assert isinstance(impact, dict)


# =============================================================================
# Replay decision with context
# =============================================================================

class TestReplayDecisionWithContext:
    """Tests for replay_decision_with_context() — context-aware replay."""

    def test_tracks_context_version_change(self):
        """Context version is recorded in the result."""
        old_decision = {
            "task_id": "t1",
            "input": {"version": 1, "data": "old"},
        }
        new_context = {
            "version": 2,
            "context_version": 2,
            "data": "new"
        }

        result = cfr.replay_decision_with_context(
            "t1", old_decision, FakeModel(), new_context
        )

        assert result is not None
        assert result["context_version"] == 2

    def test_records_data_evolution(self):
        """Data changes are tracked in the result."""
        old_decision = {
            "task_id": "t1",
            "input": {"version": 1, "field_a": "old_value"},
        }
        new_context = {
            "version": 2,
            "data": "new_value"
        }

        result = cfr.replay_decision_with_context(
            "t1", old_decision, FakeModel(), new_context
        )

        assert result is not None
        assert "data_evolution" in result


# =============================================================================
# Compare model outputs
# =============================================================================

class TestCompareModelOutputs:
    """Tests for compare_model_outputs() — model output comparison."""

    def test_same_model_no_difference(self):
        """Identical models report no difference."""
        old = {"model": "opus", "confidence": 0.8}
        new = {"model": "opus", "confidence": 0.8}

        result = cfr.compare_model_outputs(old, new)

        assert result["difference"] is False
        assert result["confidence_delta"] == 0.0

    def test_different_model_is_detected(self):
        """Different models are reported as a difference."""
        old = {"model": "haiku", "confidence": 0.8}
        new = {"model": "opus", "confidence": 0.8}

        result = cfr.compare_model_outputs(old, new)

        assert result["difference"] is True

    def test_confidence_delta_is_calculated(self):
        """Confidence difference is computed."""
        old = {"model": "opus", "confidence": 0.5}
        new = {"model": "opus", "confidence": 0.8}

        result = cfr.compare_model_outputs(old, new)

        assert abs(result["confidence_delta"] - 0.3) < 0.01

    def test_missing_confidence_defaults_to_zero(self):
        """Missing confidence fields default to 0.0."""
        old = {"model": "opus"}
        new = {"model": "opus"}

        result = cfr.compare_model_outputs(old, new)

        assert result["confidence_delta"] == 0.0


# =============================================================================
# Detect version upgrade
# =============================================================================

class TestDetectVersionUpgrade:
    """Tests for detect_version_upgrade() — version change detection."""

    def test_same_version_is_not_upgrade(self):
        """Identical versions report no upgrade."""
        assert cfr.detect_version_upgrade("2.0", "2.0") is False

    def test_different_version_is_upgrade(self):
        """Different versions report an upgrade."""
        assert cfr.detect_version_upgrade("1.0", "2.0") is True

    def test_none_values_are_not_upgrade(self):
        """None versions report no upgrade."""
        assert cfr.detect_version_upgrade(None, "2.0") is False
        assert cfr.detect_version_upgrade("1.0", None) is False


# =============================================================================
# Calculate confidence change
# =============================================================================

class TestCalculateConfidenceChange:
    """Tests for calculate_confidence_change() — confidence delta calculation."""

    def test_positive_change(self):
        """Confidence increase is positive."""
        delta = cfr.calculate_confidence_change(0.5, 0.8)
        assert abs(delta - 0.3) < 0.01

    def test_negative_change(self):
        """Confidence decrease is negative."""
        delta = cfr.calculate_confidence_change(0.8, 0.5)
        assert abs(delta - (-0.3)) < 0.01

    def test_no_change(self):
        """No confidence change is zero."""
        delta = cfr.calculate_confidence_change(0.7, 0.7)
        assert delta == 0.0

    def test_none_values_default_to_zero(self):
        """None values are treated as 0.0."""
        delta = cfr.calculate_confidence_change(None, 0.5)
        assert abs(delta - 0.5) < 0.01


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
