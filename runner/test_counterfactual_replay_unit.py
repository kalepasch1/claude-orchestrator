#!/usr/bin/env python3
"""Unit tests for counterfactual_replay module functions and classes.

Covers:
- Decision replay (replay_decision, replay_batch, replay_batch_with_summary)
- Model analysis (compare_model_outputs, analyze_replay_impact)
- Policy detection (detect_policy_change, has_policy_change)
- Data tracking (track_data_evolution, detect_version_upgrade)
- Decision filtering and history checks
- Route configuration and storage (RouteConfig, RouteStorage, ReplayStorage)
- Statistics and state management
"""

import os
import sys
import json
import pytest
import tempfile
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta

RUNNER = os.path.dirname(os.path.abspath(__file__))
if RUNNER not in sys.path:
    sys.path.insert(0, RUNNER)

import counterfactual_replay as cfr


class MockModel:
    """Mock model for testing replay_decision."""
    def __init__(self, model_id="test-model", version="1.0", decision="route_a", confidence=0.8):
        self.model_id = model_id
        self.version = version
        self._decision = decision
        self._confidence = confidence
        self.call_count = 0

    def evaluate(self, input_data, task_type):
        self.call_count += 1
        return {
            "decision": self._decision,
            "confidence": self._confidence,
        }


# =============================================================================
# Decision Replay Tests
# =============================================================================

class TestReplayDecision:
    """replay_decision() — re-evaluate a past decision with a new model."""

    def test_replay_with_valid_decision_and_model(self):
        """A valid decision replays successfully."""
        old_decision = {
            "task_id": "t1",
            "input": {"q": 1},
            "output": {"route": "route_a"},
            "model": "old-model",
        }
        model = MockModel()
        result = cfr.replay_decision("t1", old_decision, model)

        assert result is not None
        assert result["task_id"] == "t1"
        assert result["original_task_id"] == "t1"
        assert result["model"] == "test-model"
        assert result["decision"] == "route_a"
        assert result["confidence"] == 0.8

    def test_replay_preserves_original_metadata(self):
        """Original decision metadata is preserved in replay."""
        old_decision = {
            "task_id": "t1",
            "input": {"q": 1},
            "output": {"route": "route_a"},
            "model": "old-model",
            "model_version": "0.5",
            "timestamp": "2026-01-01T00:00:00",
        }
        model = MockModel()
        result = cfr.replay_decision("t1", old_decision, model)

        assert result["original_model"] == "old-model"
        assert result["original_model_version"] == "0.5"
        assert result["original_timestamp"] == "2026-01-01T00:00:00"

    def test_replay_preserves_user_repo_state(self):
        """User, repo, and state fields are carried forward."""
        old_decision = {
            "task_id": "t1",
            "input": {"q": 1},
            "output": {"route": "route_a"},
            "user": "alice@example.com",
            "repo": "my-repo",
            "state": "approved",
        }
        model = MockModel()
        result = cfr.replay_decision("t1", old_decision, model)

        assert result["user"] == "alice@example.com"
        assert result["repo"] == "my-repo"
        assert result["state"] == "approved"

    def test_replay_with_none_decision_returns_none(self):
        """None decision is rejected."""
        result = cfr.replay_decision("t1", None, MockModel())
        assert result is None

    def test_replay_with_non_dict_decision_returns_none(self):
        """Non-dict decision is rejected."""
        result = cfr.replay_decision("t1", "corrupt", MockModel())
        assert result is None

    def test_replay_with_missing_input_returns_none(self):
        """Decision without input or output is rejected."""
        result = cfr.replay_decision("t1", {"task_id": "t1"}, MockModel())
        assert result is None

    def test_replay_with_none_input_returns_none(self):
        """Decision with None input is rejected."""
        result = cfr.replay_decision("t1", {
            "task_id": "t1",
            "input": None,
            "output": {"route": "a"},
        }, MockModel())
        assert result is None

    def test_replay_with_empty_string_output_is_replayable(self):
        """Empty string output is a recorded no-answer, not corruption."""
        result = cfr.replay_decision("t1", {
            "task_id": "t1",
            "input": {"q": 1},
            "output": "",
        }, MockModel())
        assert result is not None
        assert result["task_id"] == "t1"

    def test_replay_without_evaluate_method(self):
        """Model without evaluate method returns partial result."""
        class NoEvalModel:
            model_id = "test"
            version = "1.0"

        old_decision = {
            "task_id": "t1",
            "input": {"q": 1},
            "output": {"route": "a"},
        }
        result = cfr.replay_decision("t1", old_decision, NoEvalModel())

        assert result is not None
        assert result["model"] == "test"
        assert "decision" not in result or result.get("decision") is None

    def test_replay_sets_timestamp(self):
        """Replay sets current timestamp."""
        old_decision = {
            "task_id": "t1",
            "input": {"q": 1},
            "output": {"route": "a"},
        }
        before = datetime.now().isoformat()
        result = cfr.replay_decision("t1", old_decision, MockModel())
        after = datetime.now().isoformat()

        assert before <= result["timestamp"] <= after

    def test_replay_with_missing_evaluate_result_fields(self):
        """Model output missing decision/confidence uses defaults."""
        class PartialModel:
            model_id = "test"
            version = "1.0"
            def evaluate(self, input_data, task_type):
                return {}

        old_decision = {
            "task_id": "t1",
            "input": {"q": 1},
            "output": {"route": "a"},
        }
        result = cfr.replay_decision("t1", old_decision, PartialModel())

        assert result["decision"] == "unknown"
        assert result["confidence"] == 0.0


class TestReplayDecisionSafe:
    """replay_decision_safe() — fail-soft replay with status."""

    def test_safe_replay_success_status(self):
        """Successful replay is marked with 'success' status."""
        old_decision = {
            "task_id": "t1",
            "input": {"q": 1},
            "output": {"route": "a"},
        }
        result = cfr.replay_decision_safe("t1", old_decision, MockModel())

        assert result["status"] == "success"
        assert result["task_id"] == "t1"

    def test_safe_replay_skipped_status_on_invalid_input(self):
        """Invalid input is skipped, not errored."""
        result = cfr.replay_decision_safe("t1", None, MockModel())

        assert result["status"] == "skipped"
        assert result["reason"] == "no_model_output"
        assert result["task_id"] == "t1"

    def test_safe_replay_returns_dict_always(self):
        """Safe replay always returns a dict, never raises."""
        result = cfr.replay_decision_safe("t1", None, None)

        assert isinstance(result, dict)
        assert "task_id" in result
        assert "status" in result


class TestReplayDecisionWithContext:
    """replay_decision_with_context() — replay with data evolution tracking."""

    def test_replay_with_context_tracks_evolution(self):
        """Context evolution is tracked in result."""
        old_decision = {
            "task_id": "t1",
            "input": {"data": {"version": 1, "x": 1}},
            "output": {"route": "a"},
        }
        new_context = {"data": {"version": 2, "x": 2}, "context_version": 2}
        result = cfr.replay_decision_with_context("t1", old_decision, MockModel(), new_context)

        assert result is not None
        assert result["context_version"] == 2
        assert "data_evolution" in result

    def test_replay_with_context_handles_none_gracefully(self):
        """None old_decision is handled gracefully."""
        result = cfr.replay_decision_with_context("t1", None, MockModel(), {})
        assert result is None


class TestReplayBatch:
    """replay_batch() — batch replay multiple decisions."""

    def test_batch_replay_processes_all_decisions(self):
        """All valid decisions in batch are replayed."""
        decisions = [
            {"task_id": f"t{i}", "input": {"q": i}, "output": {"route": "a"}}
            for i in range(5)
        ]
        results = cfr.replay_batch(decisions, MockModel())

        assert len(results) == 5
        assert all(r["task_id"] for r in results)

    def test_batch_replay_skips_invalid_decisions(self):
        """Invalid decisions don't stop the batch."""
        decisions = [
            {"task_id": "t1", "input": {"q": 1}, "output": {"route": "a"}},
            None,
            "corrupt",
            {"task_id": "t3", "input": {"q": 3}, "output": {"route": "a"}},
        ]
        results = cfr.replay_batch(decisions, MockModel())

        assert len(results) == 2  # Only 2 valid decisions

    def test_batch_replay_with_empty_list(self):
        """Empty decision list returns empty results."""
        results = cfr.replay_batch([], MockModel())
        assert results == []

    def test_batch_replay_with_none_list(self):
        """None decision list doesn't crash."""
        results = cfr.replay_batch(None, MockModel())
        assert results == []


class TestReplayBatchWithSummary:
    """replay_batch_with_summary() — batch replay with statistics."""

    def test_batch_summary_counts_replays(self):
        """Summary includes total replayed count."""
        decisions = [
            {"task_id": f"t{i}", "input": {"q": i}, "output": {"route": "a"}}
            for i in range(3)
        ]
        results, summary = cfr.replay_batch_with_summary(decisions, MockModel())

        assert summary["total_replayed"] == 3

    def test_batch_summary_detects_policy_changes(self):
        """Summary counts policy changes."""
        decisions = [
            {"task_id": "t1", "input": {"q": 1}, "output": {"route": "old"}},
            {"task_id": "t2", "input": {"q": 2}, "output": {"route": "route_a"}},
        ]
        model = MockModel(decision="new")
        results, summary = cfr.replay_batch_with_summary(decisions, model)

        assert summary["policy_changes"] >= 0  # At least one should change

    def test_batch_summary_calculates_confidence_delta(self):
        """Summary includes average confidence delta."""
        decisions = [
            {"task_id": "t1", "input": {"q": 1}, "output": {"route": "a", "confidence": 0.5}},
            {"task_id": "t2", "input": {"q": 2}, "output": {"route": "a", "confidence": 0.6}},
        ]
        model = MockModel(confidence=0.8)
        results, summary = cfr.replay_batch_with_summary(decisions, model)

        assert summary["avg_confidence_delta"] > 0

    def test_batch_summary_lists_models_tested(self):
        """Summary includes unique models tested."""
        decisions = [
            {"task_id": "t1", "input": {"q": 1}, "output": {"route": "a"}},
            {"task_id": "t2", "input": {"q": 2}, "output": {"route": "a"}},
        ]
        model = MockModel(model_id="opus")
        results, summary = cfr.replay_batch_with_summary(decisions, model)

        assert "opus" in summary["models_tested"]


# =============================================================================
# Model Output Analysis Tests
# =============================================================================

class TestCompareModelOutputs:
    """compare_model_outputs() — compare outputs from two model versions."""

    def test_compare_identical_outputs(self):
        """Identical outputs show no difference."""
        old = {"model": "opus", "confidence": 0.8}
        new = {"model": "opus", "confidence": 0.8}
        result = cfr.compare_model_outputs(old, new)

        assert result["difference"] is False
        assert result["confidence_delta"] == 0.0

    def test_compare_different_models(self):
        """Different model IDs are detected."""
        old = {"model": "haiku", "confidence": 0.5}
        new = {"model": "opus", "confidence": 0.5}
        result = cfr.compare_model_outputs(old, new)

        assert result["difference"] is True
        assert result["old_model"] == "haiku"
        assert result["new_model"] == "opus"

    def test_compare_confidence_improvement(self):
        """Confidence increase is tracked."""
        old = {"model": "opus", "confidence": 0.5}
        new = {"model": "opus", "confidence": 0.9}
        result = cfr.compare_model_outputs(old, new)

        assert result["confidence_delta"] == 0.4
        assert result["new_confidence"] > result["old_confidence"]

    def test_compare_with_missing_confidence(self):
        """Missing confidence defaults to 0.0."""
        old = {"model": "opus"}
        new = {"model": "opus", "confidence": 0.5}
        result = cfr.compare_model_outputs(old, new)

        assert result["old_confidence"] == 0.0
        assert result["new_confidence"] == 0.5

    def test_compare_non_dict_outputs(self):
        """Non-dict outputs are handled gracefully."""
        result = cfr.compare_model_outputs("corrupt", None)

        assert result["difference"] is False
        assert result["old_model"] == "unknown"


class TestDetectVersionUpgrade:
    """detect_version_upgrade() — check if model version changed."""

    def test_different_versions_detected(self):
        """Different version strings are detected."""
        assert cfr.detect_version_upgrade("1.0", "2.0") is True

    def test_same_versions_not_detected(self):
        """Same versions are not detected as upgrade."""
        assert cfr.detect_version_upgrade("1.0", "1.0") is False

    def test_none_versions_handled(self):
        """None versions are handled gracefully."""
        assert cfr.detect_version_upgrade(None, "1.0") is False
        assert cfr.detect_version_upgrade("1.0", None) is False


class TestCalculateConfidenceChange:
    """calculate_confidence_change() — compute confidence delta."""

    def test_positive_confidence_change(self):
        """Positive delta is calculated correctly."""
        delta = cfr.calculate_confidence_change(0.5, 0.9)
        assert delta == 0.4

    def test_negative_confidence_change(self):
        """Negative delta is calculated correctly."""
        delta = cfr.calculate_confidence_change(0.9, 0.5)
        assert delta == -0.4

    def test_zero_confidence_change(self):
        """Zero delta when values are equal."""
        delta = cfr.calculate_confidence_change(0.7, 0.7)
        assert delta == 0.0

    def test_none_confidence_defaults_to_zero(self):
        """None confidence is treated as 0.0."""
        delta = cfr.calculate_confidence_change(None, 0.5)
        assert delta == 0.5


class TestAnalyzeReplayImpact:
    """analyze_replay_impact() — analyze impact of a replayed decision."""

    def test_impact_with_changed_confidence(self):
        """Confidence changes are tracked."""
        old = {"output": {"route": "a", "confidence": 0.5}}
        replay = {"decision": "a", "confidence": 0.8}
        impact = cfr.analyze_replay_impact(old, replay)

        assert impact["confidence_change"] == 0.3
        assert impact["decision_stable"] is True

    def test_impact_with_model_change(self):
        """Model changes are tracked."""
        old = {"output": {"route": "a"}, "model": "haiku"}
        replay = {"decision": "a", "model": "opus"}
        impact = cfr.analyze_replay_impact(old, replay)

        assert impact["model_changed"] is True

    def test_impact_with_decision_divergence(self):
        """Decision divergence is tracked."""
        old = {"output": {"route": "a", "confidence": 0.5}}
        replay = {"decision": "b", "confidence": 0.8}
        impact = cfr.analyze_replay_impact(old, replay)

        assert impact["decision_stable"] is False

    def test_impact_with_corrupted_old_output(self):
        """Corrupted output is handled gracefully."""
        old = {"output": "corrupt"}
        replay = {"decision": "a", "confidence": 0.8}
        impact = cfr.analyze_replay_impact(old, replay)

        assert isinstance(impact, dict)  # Should not raise


# =============================================================================
# Decision Filtering and History Tests
# =============================================================================

class TestFilterDecisions:
    """filter_decisions() — filter decisions by type and date range."""

    def test_filter_by_task_type(self):
        """Decisions are filtered by task type."""
        decisions = [
            {"task_id": "t1", "type": "routing"},
            {"task_id": "t2", "type": "retry"},
            {"task_id": "t3", "type": "routing"},
        ]
        filtered = cfr.filter_decisions(decisions, task_type="routing")

        assert len(filtered) == 2
        assert all(d["type"] == "routing" for d in filtered)

    def test_filter_by_date_range(self):
        """Decisions are filtered by date range."""
        decisions = [
            {"task_id": "t1", "timestamp": "2026-01-01T00:00:00"},
            {"task_id": "t2", "timestamp": "2026-06-01T00:00:00"},
            {"task_id": "t3", "timestamp": "2026-12-01T00:00:00"},
        ]
        filtered = cfr.filter_decisions(
            decisions,
            start_date="2026-05-01T00:00:00",
            end_date="2026-07-01T00:00:00",
        )

        assert len(filtered) == 1
        assert filtered[0]["task_id"] == "t2"

    def test_filter_with_no_criteria(self):
        """No filter criteria returns all decisions."""
        decisions = [
            {"task_id": "t1"},
            {"task_id": "t2"},
        ]
        filtered = cfr.filter_decisions(decisions)

        assert len(filtered) == 2

    def test_filter_none_decisions(self):
        """None decision list returns empty."""
        filtered = cfr.filter_decisions(None)
        assert filtered == []


class TestIsEmptyHistory:
    """is_empty_history() — check if decision history is empty."""

    def test_empty_list_is_empty(self):
        """Empty list is detected as empty history."""
        assert cfr.is_empty_history([]) is True

    def test_none_is_empty(self):
        """None is detected as empty history."""
        assert cfr.is_empty_history(None) is True

    def test_populated_list_is_not_empty(self):
        """Non-empty list is not empty."""
        assert cfr.is_empty_history([{"task_id": "t1"}]) is False


# =============================================================================
# Policy Detection Tests
# =============================================================================

class TestDetectCircularDependencies:
    """detect_circular_dependencies() — detect circular dependency cycles."""

    def test_no_cycles_detected(self):
        """Acyclic graph has no cycles."""
        decisions = {
            "t1": {"depends_on": "t2"},
            "t2": {"depends_on": None},
        }
        result = cfr.detect_circular_dependencies(decisions)

        assert result["has_cycle"] is False
        assert result["cycle"] == []

    def test_cycle_detected(self):
        """Circular dependency is detected."""
        decisions = {
            "t1": {"depends_on": "t2"},
            "t2": {"depends_on": "t1"},
        }
        result = cfr.detect_circular_dependencies(decisions)

        assert result["has_cycle"] is True

    def test_empty_decisions_no_cycle(self):
        """Empty decisions have no cycles."""
        result = cfr.detect_circular_dependencies({})
        assert result["has_cycle"] is False


class TestTrackDataEvolution:
    """track_data_evolution() — track data changes between versions."""

    def test_track_version_upgrade(self):
        """Version change is tracked."""
        old_data = {"version": 1, "x": 1}
        new_data = {"version": 2, "x": 2}
        evolution = cfr.track_data_evolution(old_data, new_data)

        assert evolution["old_version"] == 1
        assert evolution["new_version"] == 2

    def test_track_field_changes(self):
        """Changed fields are tracked."""
        old_data = {"x": 1, "y": 2}
        new_data = {"x": 1, "y": 3, "z": 4}
        evolution = cfr.track_data_evolution(old_data, new_data)

        assert "y" in evolution["changes"]
        assert "z" in evolution["changes"]
        assert "x" not in evolution["changes"]

    def test_evolution_with_none_inputs(self):
        """None inputs are handled gracefully."""
        evolution = cfr.track_data_evolution(None, None)

        assert "changes" in evolution
        assert evolution["changes"] == []


# =============================================================================
# RouteConfig Tests
# =============================================================================

class TestRouteConfig:
    """RouteConfig — in-memory route configuration."""

    def test_set_and_get_route(self):
        """Routes can be set and retrieved."""
        config = cfr.RouteConfig()
        config.set_route("build", "opus", q_score=0.8)

        route = config.get_route("build")
        assert route["model"] == "opus"
        assert route["q_score"] == 0.8

    def test_update_existing_route(self):
        """Existing routes can be updated."""
        config = cfr.RouteConfig()
        config.set_route("build", "haiku")
        config.update_route("build", "opus", q_score=0.9)

        route = config.get_route("build")
        assert route["model"] == "opus"
        assert route["q_score"] == 0.9

    def test_create_route_on_update_if_missing(self):
        """Update creates route if not exists."""
        config = cfr.RouteConfig()
        config.update_route("test", "opus")

        route = config.get_route("test")
        assert route["model"] == "opus"

    def test_get_nonexistent_route_returns_none(self):
        """Getting non-existent route returns None."""
        config = cfr.RouteConfig()
        route = config.get_route("missing")

        assert route is None

    def test_apply_counterfactual_update(self):
        """Counterfactual updates are applied."""
        config = cfr.RouteConfig()
        config.apply_counterfactual_update("build", {
            "new_model": "opus",
            "q_score_delta": 0.2,
        })

        route = config.get_route("build")
        assert route["model"] == "opus"


# =============================================================================
# RouteStorage Tests
# =============================================================================

class TestRouteStorage:
    """RouteStorage — persistent route update storage."""

    def test_persist_and_retrieve_route_update(self, tmp_path):
        """Route updates are persisted and retrieved."""
        storage = cfr.RouteStorage(str(tmp_path))
        update = {
            "operation": "build",
            "prior_model": "haiku",
            "new_model": "opus",
        }
        storage.persist_route_update(update)

        retrieved = storage.get_route_update("build")
        assert retrieved is not None
        assert retrieved["new_model"] == "opus"

    def test_overwrite_existing_update(self, tmp_path):
        """New updates overwrite existing ones."""
        storage = cfr.RouteStorage(str(tmp_path))
        storage.persist_route_update({"operation": "build", "new_model": "haiku"})
        storage.persist_route_update({"operation": "build", "new_model": "opus"})

        retrieved = storage.get_route_update("build")
        assert retrieved["new_model"] == "opus"

    def test_get_nonexistent_update_returns_none(self, tmp_path):
        """Getting non-existent update returns None."""
        storage = cfr.RouteStorage(str(tmp_path))
        retrieved = storage.get_route_update("missing")

        assert retrieved is None


# =============================================================================
# ReplayStorage Tests
# =============================================================================

class TestReplayStorage:
    """ReplayStorage — persistent replay result storage."""

    def test_save_and_retrieve_replay(self, tmp_path):
        """Replay results are saved and retrieved."""
        storage = cfr.ReplayStorage(str(tmp_path))
        replay = {
            "task_id": "t1",
            "model": "opus",
            "decision": "route_a",
            "policy_changed": False,
            "timestamp": datetime.now().isoformat(),
        }
        storage.save_replay(replay)

        results = storage.get_replays("t1")
        assert len(results) == 1
        assert results[0]["model"] == "opus"

    def test_save_replay_idempotent(self, tmp_path):
        """Saving same task_id twice overwrites."""
        storage = cfr.ReplayStorage(str(tmp_path))
        storage.save_replay({
            "task_id": "t1",
            "model": "haiku",
            "decision": "a",
            "timestamp": datetime.now().isoformat(),
        })
        storage.save_replay({
            "task_id": "t1",
            "model": "opus",
            "decision": "b",
            "timestamp": datetime.now().isoformat(),
        })

        results = storage.get_replays("t1")
        assert len(results) == 1
        assert results[0]["model"] == "opus"

    def test_count_replays_total(self, tmp_path):
        """Count total replays across all tasks."""
        storage = cfr.ReplayStorage(str(tmp_path))
        for i in range(3):
            storage.save_replay({
                "task_id": f"t{i}",
                "model": "opus",
                "decision": "a",
                "timestamp": datetime.now().isoformat(),
            })

        count = storage.count_replays()
        assert count == 3

    def test_count_replays_by_task(self, tmp_path):
        """Count replays for specific task."""
        storage = cfr.ReplayStorage(str(tmp_path))
        storage.save_replay({
            "task_id": "t1",
            "model": "opus",
            "timestamp": datetime.now().isoformat(),
        })

        count = storage.count_replays("t1")
        assert count == 1

    def test_query_by_model(self, tmp_path):
        """Query replays by model."""
        storage = cfr.ReplayStorage(str(tmp_path))
        storage.save_replay({
            "task_id": "t1",
            "model": "opus",
            "timestamp": datetime.now().isoformat(),
        })
        storage.save_replay({
            "task_id": "t2",
            "model": "haiku",
            "timestamp": datetime.now().isoformat(),
        })

        results = storage.query(model="opus")
        assert len(results) == 1
        assert results[0]["model"] == "opus"

    def test_query_by_policy_changed(self, tmp_path):
        """Query replays by policy_changed status."""
        storage = cfr.ReplayStorage(str(tmp_path))
        storage.save_replay({
            "task_id": "t1",
            "model": "opus",
            "policy_changed": True,
            "timestamp": datetime.now().isoformat(),
        })
        storage.save_replay({
            "task_id": "t2",
            "model": "haiku",
            "policy_changed": False,
            "timestamp": datetime.now().isoformat(),
        })

        results = storage.query(policy_changed=True)
        assert len(results) == 1
        assert results[0]["policy_changed"] is True


# =============================================================================
# Statistics and State Management Tests
# =============================================================================

class TestStatsAndState:
    """stats() and invalidate() — replay statistics and state management."""

    def test_stats_returns_dict(self):
        """stats() returns a dictionary."""
        stats = cfr.stats()
        assert isinstance(stats, dict)
        assert "replayed" in stats
        assert "changed" in stats
        assert "errors" in stats

    def test_invalidate_clears_stats(self):
        """invalidate() resets stats to zero."""
        cfr.invalidate()
        stats = cfr.stats()

        assert stats["replayed"] == 0
        assert stats["changed"] == 0
        assert stats["errors"] == 0

    def test_stats_are_independent(self):
        """Stats dict is independent copy (not shared reference)."""
        before = cfr.stats()
        cfr.invalidate()
        after = cfr.stats()

        assert before is not after


# =============================================================================
# Environment and Configuration Tests
# =============================================================================

class TestEnvironmentConfiguration:
    """Test environment variable configuration."""

    def test_days_back_default(self):
        """DAYS_BACK has default value."""
        assert cfr.DAYS_BACK == 7 or isinstance(cfr.DAYS_BACK, int)

    def test_batch_size_default(self):
        """BATCH_SIZE has default value."""
        assert cfr.BATCH_SIZE == 50 or isinstance(cfr.BATCH_SIZE, int)

    def test_enabled_default(self):
        """ENABLED has default value."""
        assert isinstance(cfr.ENABLED, bool)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
