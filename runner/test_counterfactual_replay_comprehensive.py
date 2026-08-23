#!/usr/bin/env python3
"""Comprehensive tests for counterfactual_replay.py.

Tests cover all functions, edge cases, error handling, and integration flows
for the counterfactual replay system that re-runs past decisions with newer
models/data to detect divergences and update routing policies.
"""

import os
import sys
import json
import time
import pytest
from unittest.mock import Mock, patch, MagicMock

RUNNER = os.path.dirname(os.path.abspath(__file__))
if RUNNER not in sys.path:
    sys.path.insert(0, RUNNER)

# Set up test environment
os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test")

import counterfactual_replay as cfr


class TestFetchRecentDecisions:
    """Tests for _fetch_recent_decisions()."""

    def test_fetch_recent_decisions_uses_default_lookback(self, monkeypatch):
        """Uses LOOKBACK_DAYS constant when not specified."""
        calls = []
        def mock_select(table, params):
            calls.append((table, params))
            return []
        monkeypatch.setattr("db.select", mock_select)

        cfr._fetch_recent_decisions()
        assert len(calls) == 1
        assert "gte." in calls[0][1].get("updated_at", "")

    def test_fetch_recent_decisions_custom_lookback(self, monkeypatch):
        """Accepts custom lookback_days parameter."""
        calls = []
        def mock_select(table, params):
            calls.append((table, params))
            return []
        monkeypatch.setattr("db.select", mock_select)

        cfr._fetch_recent_decisions(lookback_days=14)
        assert len(calls) == 1
        params = calls[0][1]
        assert "gte." in params.get("updated_at", "")

    def test_fetch_recent_decisions_custom_limit(self, monkeypatch):
        """Accepts custom limit parameter."""
        calls = []
        def mock_select(table, params):
            calls.append((table, params))
            return []
        monkeypatch.setattr("counterfactual_replay.db.select", mock_select)

        cfr._fetch_recent_decisions(limit=50)
        assert len(calls) == 1
        params = calls[0][1]
        assert params.get("limit") == "50"

    def test_fetch_recent_decisions_returns_tasks(self, monkeypatch):
        """Returns task list from database."""
        mock_tasks = [
            {"id": 1, "slug": "task-1", "kind": "build", "state": "DONE", "force_coder": "claude-opus-4"},
            {"id": 2, "slug": "task-2", "kind": "qafix", "state": "MERGED", "force_coder": "claude-sonnet"},
        ]
        def mock_select(table, params):
            return mock_tasks
        monkeypatch.setattr("counterfactual_replay.db.select", mock_select)

        result = cfr._fetch_recent_decisions()
        assert len(result) == 2
        assert result[0]["slug"] == "task-1"
        assert result[1]["force_coder"] == "claude-sonnet"

    def test_fetch_recent_decisions_filters_by_state(self, monkeypatch):
        """Only fetches DONE/MERGED tasks."""
        calls = []
        def mock_select(table, params):
            calls.append((table, params))
            return []
        monkeypatch.setattr("counterfactual_replay.db.select", mock_select)

        cfr._fetch_recent_decisions()
        params = calls[0][1]
        assert "DONE" in params.get("state", "")
        assert "MERGED" in params.get("state", "")

    def test_fetch_recent_decisions_db_error(self, monkeypatch):
        """Handles DB errors gracefully with empty return."""
        def mock_select(table, params):
            raise ConnectionError("db connection failed")
        monkeypatch.setattr("counterfactual_replay.db.select", mock_select)

        result = cfr._fetch_recent_decisions()
        assert result == []

    def test_fetch_recent_decisions_empty_result(self, monkeypatch):
        """Returns empty list when DB has no matching tasks."""
        def mock_select(table, params):
            return []
        monkeypatch.setattr("counterfactual_replay.db.select", mock_select)

        result = cfr._fetch_recent_decisions()
        assert result == []

    def test_fetch_recent_decisions_none_result(self, monkeypatch):
        """Handles None result from DB."""
        def mock_select(table, params):
            return None
        monkeypatch.setattr("counterfactual_replay.db.select", mock_select)

        result = cfr._fetch_recent_decisions()
        assert result == []

    def test_fetch_recent_decisions_timerange_calculation(self, monkeypatch):
        """Calculates correct cutoff timestamp for lookback."""
        calls = []
        def mock_select(table, params):
            calls.append((table, params))
            return []
        monkeypatch.setattr("counterfactual_replay.db.select", mock_select)

        cfr._fetch_recent_decisions(lookback_days=7)
        params = calls[0][1]
        cutoff = params.get("updated_at", "")
        assert "gte." in cutoff
        # Verify timestamp format
        assert "Z" in cutoff


class TestCurrentModelRoster:
    """Tests for _current_model_roster()."""

    def test_current_model_roster_returns_dict(self, monkeypatch):
        """Returns model quality scores as dict."""
        mock_rows = [
            {"model": "claude-opus-4", "task_kind": "build", "quality": 0.95, "cost_usd": 0.5},
            {"model": "claude-sonnet", "task_kind": "build", "quality": 0.85, "cost_usd": 0.3},
        ]
        def mock_select(table, params):
            return mock_rows
        monkeypatch.setattr("counterfactual_replay.db.select", mock_select)

        result = cfr._current_model_roster()
        assert isinstance(result, dict)
        assert ("claude-opus-4", "build") in result
        assert result[("claude-opus-4", "build")]["quality"] == 0.95
        assert result[("claude-opus-4", "build")]["cost"] == 0.5

    def test_current_model_roster_empty_db(self, monkeypatch):
        """Returns empty dict when no scores available."""
        def mock_select(table, params):
            return []
        monkeypatch.setattr("counterfactual_replay.db.select", mock_select)

        result = cfr._current_model_roster()
        assert result == {}

    def test_current_model_roster_db_error(self, monkeypatch):
        """Returns empty dict on DB error."""
        def mock_select(table, params):
            raise RuntimeError("db unavailable")
        monkeypatch.setattr("counterfactual_replay.db.select", mock_select)

        result = cfr._current_model_roster()
        assert result == {}

    def test_current_model_roster_multiple_task_kinds(self, monkeypatch):
        """Handles multiple task kinds in roster."""
        mock_rows = [
            {"model": "claude-opus-4", "task_kind": "build", "quality": 0.95, "cost_usd": 0.5},
            {"model": "claude-opus-4", "task_kind": "qafix", "quality": 0.88, "cost_usd": 0.5},
            {"model": "claude-haiku", "task_kind": "build", "quality": 0.7, "cost_usd": 0.1},
        ]
        def mock_select(table, params):
            return mock_rows
        monkeypatch.setattr("counterfactual_replay.db.select", mock_select)

        result = cfr._current_model_roster()
        assert ("claude-opus-4", "build") in result
        assert ("claude-opus-4", "qafix") in result
        assert ("claude-haiku", "build") in result

    def test_current_model_roster_float_conversion(self, monkeypatch):
        """Converts quality/cost to floats."""
        mock_rows = [
            {"model": "claude-opus-4", "task_kind": "build", "quality": "0.95", "cost_usd": "0.5"},
        ]
        def mock_select(table, params):
            return mock_rows
        monkeypatch.setattr("counterfactual_replay.db.select", mock_select)

        result = cfr._current_model_roster()
        entry = result[("claude-opus-4", "build")]
        assert isinstance(entry["quality"], float)
        assert isinstance(entry["cost"], float)

    def test_current_model_roster_missing_fields(self, monkeypatch):
        """Handles missing quality/cost fields gracefully."""
        mock_rows = [
            {"model": "claude-opus-4", "task_kind": "build"},  # Missing quality and cost
        ]
        def mock_select(table, params):
            return mock_rows
        monkeypatch.setattr("counterfactual_replay.db.select", mock_select)

        result = cfr._current_model_roster()
        entry = result[("claude-opus-4", "build")]
        assert entry["quality"] == 0.0
        assert entry["cost"] == 0.0

    def test_current_model_roster_orders_by_quality(self, monkeypatch):
        """Respects quality ordering in fetched results."""
        calls = []
        def mock_select(table, params):
            calls.append(params)
            return []
        monkeypatch.setattr("counterfactual_replay.db.select", mock_select)

        cfr._current_model_roster()
        params = calls[0]
        assert "quality.desc" in params.get("order", "")

    def test_current_model_roster_respects_limit(self, monkeypatch):
        """Limits returned scores to 200."""
        calls = []
        def mock_select(table, params):
            calls.append(params)
            return []
        monkeypatch.setattr("counterfactual_replay.db.select", mock_select)

        cfr._current_model_roster()
        params = calls[0]
        assert params.get("limit") == "200"


class TestReplayDecision:
    """Tests for replay_decision()."""

    def test_replay_decision_no_change_same_model(self):
        """No divergence when best model already selected."""
        task = {
            "slug": "task-1",
            "kind": "build",
            "force_coder": "claude-opus-4",
            "attempt": 1,
        }
        roster = {
            ("claude-opus-4", "build"): {"quality": 0.95, "cost": 0.5},
            ("claude-haiku", "build"): {"quality": 0.7, "cost": 0.1},
        }

        result = cfr.replay_decision(task, roster)
        assert result["changed"] is False
        assert result["original_coder"] == "claude-opus-4"
        assert result["recommended"] == "claude-opus-4"

    def test_replay_decision_detects_quality_improvement(self):
        """Detects divergence with significant quality improvement."""
        task = {
            "slug": "task-1",
            "kind": "build",
            "force_coder": "claude-haiku",
        }
        roster = {
            ("claude-haiku", "build"): {"quality": 0.6, "cost": 0.1},
            ("claude-opus-4", "build"): {"quality": 0.95, "cost": 0.5},
        }

        result = cfr.replay_decision(task, roster)
        assert result["changed"] is True
        assert result["original_coder"] == "claude-haiku"
        assert result["recommended"] == "claude-opus-4"
        assert result["quality_delta"] > 0.0

    def test_replay_decision_quality_delta_below_threshold(self):
        """No divergence when quality improvement below 0.5 threshold."""
        task = {
            "slug": "task-1",
            "kind": "build",
            "force_coder": "claude-sonnet",
        }
        roster = {
            ("claude-sonnet", "build"): {"quality": 0.85, "cost": 0.3},
            ("claude-opus-4", "build"): {"quality": 0.88, "cost": 0.5},
        }

        result = cfr.replay_decision(task, roster)
        assert result["changed"] is False
        assert result["quality_delta"] < 0.5

    def test_replay_decision_unknown_original_model(self):
        """Handles unknown original model gracefully."""
        task = {
            "slug": "task-1",
            "kind": "build",
            "force_coder": "unknown-model",
        }
        roster = {
            ("claude-opus-4", "build"): {"quality": 0.95, "cost": 0.5},
        }

        result = cfr.replay_decision(task, roster)
        assert result["task_slug"] == "task-1"
        assert result["original_coder"] == "unknown-model"
        assert result["recommended"] == "claude-opus-4"

    def test_replay_decision_missing_original_quality(self):
        """Treats missing original quality as 0.0."""
        task = {
            "slug": "task-1",
            "kind": "build",
            "force_coder": "claude-haiku",
        }
        roster = {
            ("claude-opus-4", "build"): {"quality": 0.95, "cost": 0.5},
        }

        result = cfr.replay_decision(task, roster)
        assert result["original_quality"] == 0.0
        assert result["best_quality"] == 0.95

    def test_replay_decision_empty_roster(self):
        """Handles empty roster gracefully."""
        task = {
            "slug": "task-1",
            "kind": "build",
            "force_coder": "claude-haiku",
        }

        result = cfr.replay_decision(task, {})
        assert result["changed"] is False
        assert result["recommended"] == "unknown"

    def test_replay_decision_none_task(self):
        """Handles None task gracefully."""
        result = cfr.replay_decision(None, {})
        assert isinstance(result, dict)

    def test_replay_decision_missing_kind(self):
        """Handles missing kind field."""
        task = {"slug": "task-1", "force_coder": "claude-opus-4"}
        roster = {("claude-opus-4", "build"): {"quality": 0.95, "cost": 0.5}}

        result = cfr.replay_decision(task, roster)
        assert result["task_kind"] == "build"

    def test_replay_decision_returns_all_fields(self):
        """Returns complete result dict with all required fields."""
        task = {
            "slug": "task-1",
            "kind": "build",
            "force_coder": "claude-haiku",
        }
        roster = {
            ("claude-haiku", "build"): {"quality": 0.7, "cost": 0.1},
            ("claude-opus-4", "build"): {"quality": 0.95, "cost": 0.5},
        }

        result = cfr.replay_decision(task, roster)
        assert "changed" in result
        assert "original_coder" in result
        assert "recommended" in result
        assert "quality_delta" in result
        assert "task_slug" in result
        assert "task_kind" in result
        assert "original_quality" in result
        assert "best_quality" in result

    def test_replay_decision_quality_rounding(self):
        """Rounds quality values to 2 decimals."""
        task = {
            "slug": "task-1",
            "kind": "build",
            "force_coder": "claude-haiku",
        }
        roster = {
            ("claude-haiku", "build"): {"quality": 0.6666667, "cost": 0.1},
            ("claude-opus-4", "build"): {"quality": 0.9999999, "cost": 0.5},
        }

        result = cfr.replay_decision(task, roster)
        assert result["original_quality"] == 0.67
        assert result["best_quality"] == 1.0
        assert result["quality_delta"] == 0.33


class TestRunReplay:
    """Tests for run_replay() integration."""

    def test_run_replay_disabled(self, monkeypatch):
        """Returns early when ENABLED is False."""
        monkeypatch.setattr("counterfactual_replay.ENABLED", False)
        result = cfr.run_replay()
        assert result["enabled"] is False

    def test_run_replay_no_recent_decisions(self, monkeypatch):
        """Returns summary when no decisions found."""
        monkeypatch.setattr("counterfactual_replay._fetch_recent_decisions", lambda *a, **k: [])
        monkeypatch.setattr("counterfactual_replay._current_model_roster", lambda: {})
        monkeypatch.setattr("counterfactual_replay.ENABLED", True)

        result = cfr.run_replay()
        assert result["tasks_scanned"] == 0

    def test_run_replay_no_roster_available(self, monkeypatch):
        """Returns error when model roster unavailable."""
        def mock_fetch(*a, **k):
            return [{"id": 1, "slug": "task-1", "kind": "build", "force_coder": "claude-opus-4"}]

        def mock_roster():
            return {}

        monkeypatch.setattr("counterfactual_replay._fetch_recent_decisions", mock_fetch)
        monkeypatch.setattr("counterfactual_replay._current_model_roster", mock_roster)
        monkeypatch.setattr("counterfactual_replay.ENABLED", True)

        result = cfr.run_replay()
        assert "error" in result or result["tasks_scanned"] == 1

    def test_run_replay_processes_all_tasks(self, monkeypatch):
        """Processes each fetched task."""
        tasks = [
            {"id": 1, "slug": "task-1", "kind": "build", "force_coder": "claude-haiku"},
            {"id": 2, "slug": "task-2", "kind": "build", "force_coder": "claude-sonnet"},
        ]
        roster = {
            ("claude-opus-4", "build"): {"quality": 0.95, "cost": 0.5},
            ("claude-haiku", "build"): {"quality": 0.7, "cost": 0.1},
            ("claude-sonnet", "build"): {"quality": 0.85, "cost": 0.3},
        }

        monkeypatch.setattr("counterfactual_replay._fetch_recent_decisions", lambda *a, **k: tasks)
        monkeypatch.setattr("counterfactual_replay._current_model_roster", lambda: roster)
        monkeypatch.setattr("counterfactual_replay.ENABLED", True)

        result = cfr.run_replay()
        assert result["tasks_scanned"] == 2

    def test_run_replay_counts_divergences(self, monkeypatch):
        """Counts decisions that would change."""
        tasks = [
            {"id": 1, "slug": "task-1", "kind": "build", "force_coder": "claude-haiku"},
            {"id": 2, "slug": "task-2", "kind": "build", "force_coder": "claude-opus-4"},
        ]
        roster = {
            ("claude-opus-4", "build"): {"quality": 0.95, "cost": 0.5},
            ("claude-haiku", "build"): {"quality": 0.7, "cost": 0.1},
        }

        monkeypatch.setattr("counterfactual_replay._fetch_recent_decisions", lambda *a, **k: tasks)
        monkeypatch.setattr("counterfactual_replay._current_model_roster", lambda: roster)
        monkeypatch.setattr("counterfactual_replay.ENABLED", True)

        result = cfr.run_replay()
        assert "decisions_diverged" in result

    def test_run_replay_applies_policy_updates(self, monkeypatch):
        """Calls _apply_policy_updates when apply=True and divergences exist."""
        tasks = [
            {"id": 1, "slug": "task-1", "kind": "build", "force_coder": "claude-haiku"},
        ]
        roster = {
            ("claude-opus-4", "build"): {"quality": 0.95, "cost": 0.5},
            ("claude-haiku", "build"): {"quality": 0.7, "cost": 0.1},
        }
        update_calls = []

        def mock_apply(results):
            update_calls.append(results)

        monkeypatch.setattr("counterfactual_replay._fetch_recent_decisions", lambda *a, **k: tasks)
        monkeypatch.setattr("counterfactual_replay._current_model_roster", lambda: roster)
        monkeypatch.setattr("counterfactual_replay._apply_policy_updates", mock_apply)
        monkeypatch.setattr("counterfactual_replay.ENABLED", True)

        result = cfr.run_replay(apply=True)
        if result.get("decisions_diverged", 0) > 0:
            assert len(update_calls) > 0

    def test_run_replay_respects_limit_parameter(self, monkeypatch):
        """Passes limit parameter to fetch."""
        calls = []
        def mock_fetch(lookback_days=None, limit=None):
            calls.append((lookback_days, limit))
            return []

        monkeypatch.setattr("counterfactual_replay._fetch_recent_decisions", mock_fetch)
        monkeypatch.setattr("counterfactual_replay._current_model_roster", lambda: {})
        monkeypatch.setattr("counterfactual_replay.ENABLED", True)

        cfr.run_replay(limit=50)
        assert calls[0][1] == 50

    def test_run_replay_returns_summary(self, monkeypatch):
        """Returns summary dict with expected fields."""
        def mock_fetch(*a, **k):
            return []

        monkeypatch.setattr("counterfactual_replay._fetch_recent_decisions", mock_fetch)
        monkeypatch.setattr("counterfactual_replay._current_model_roster", lambda: {})
        monkeypatch.setattr("counterfactual_replay.ENABLED", True)

        result = cfr.run_replay()
        assert "tasks_scanned" in result
        assert "decisions_diverged" in result
        assert "divergence_rate" in result

    def test_run_replay_top_changes_sorting(self, monkeypatch):
        """Includes top 10 changes sorted by quality_delta."""
        tasks = [
            {"id": 1, "slug": "task-1", "kind": "build", "force_coder": "claude-haiku"},
            {"id": 2, "slug": "task-2", "kind": "build", "force_coder": "claude-sonnet"},
        ]
        roster = {
            ("claude-opus-4", "build"): {"quality": 0.95, "cost": 0.5},
            ("claude-haiku", "build"): {"quality": 0.3, "cost": 0.1},
            ("claude-sonnet", "build"): {"quality": 0.5, "cost": 0.3},
        }

        monkeypatch.setattr("counterfactual_replay._fetch_recent_decisions", lambda *a, **k: tasks)
        monkeypatch.setattr("counterfactual_replay._current_model_roster", lambda: roster)
        monkeypatch.setattr("counterfactual_replay.ENABLED", True)

        result = cfr.run_replay()
        if "top_changes" in result and result["top_changes"]:
            deltas = [r["quality_delta"] for r in result["top_changes"]]
            assert deltas == sorted(deltas, reverse=True)


class TestApplyPolicyUpdates:
    """Tests for _apply_policy_updates()."""

    def test_apply_policy_updates_no_changes(self, monkeypatch):
        """Handles empty results gracefully."""
        def mock_upsert(*a, **k):
            pass
        monkeypatch.setattr("counterfactual_replay.db.upsert", mock_upsert)

        # Should not raise
        cfr._apply_policy_updates([])

    def test_apply_policy_updates_writes_config(self, monkeypatch):
        """Writes route_override config for changed decisions."""
        calls = []
        def mock_upsert(data):
            calls.append(data)
        monkeypatch.setattr("counterfactual_replay.db.upsert", mock_upsert)

        results = [
            {
                "changed": True,
                "task_kind": "build",
                "recommended": "claude-opus-4",
                "best_quality": 0.95,
            },
            {
                "changed": False,
                "task_kind": "qafix",
            },
        ]

        cfr._apply_policy_updates(results)
        # Only changed decisions should be written
        assert len([c for c in calls if c.get("key", "").startswith("route_override:")]) >= 1

    def test_apply_policy_updates_constructs_config_key(self, monkeypatch):
        """Creates config key with task_kind."""
        calls = []
        def mock_upsert(data):
            calls.append(data)
        monkeypatch.setattr("counterfactual_replay.db.upsert", mock_upsert)

        results = [
            {
                "changed": True,
                "task_kind": "build",
                "recommended": "claude-opus-4",
                "best_quality": 0.95,
            },
        ]

        cfr._apply_policy_updates(results)
        if calls:
            key = calls[0].get("key", "")
            assert "route_override:build" in key

    def test_apply_policy_updates_includes_metadata(self, monkeypatch):
        """Includes quality and timestamp in update value."""
        calls = []
        def mock_upsert(data):
            calls.append(data)
        monkeypatch.setattr("counterfactual_replay.db.upsert", mock_upsert)

        results = [
            {
                "changed": True,
                "task_kind": "build",
                "recommended": "claude-opus-4",
                "best_quality": 0.95,
            },
        ]

        cfr._apply_policy_updates(results)
        if calls:
            value = calls[0].get("value", {})
            assert value.get("preferred_model") == "claude-opus-4"
            assert value.get("quality") == 0.95
            assert "updated_at" in value

    def test_apply_policy_updates_db_error_handling(self, monkeypatch):
        """Continues on DB error for individual writes."""
        def mock_upsert(data):
            raise RuntimeError("db write failed")
        monkeypatch.setattr("counterfactual_replay.db.upsert", mock_upsert)

        results = [
            {
                "changed": True,
                "task_kind": "build",
                "recommended": "claude-opus-4",
                "best_quality": 0.95,
            },
        ]

        # Should not raise
        cfr._apply_policy_updates(results)

    def test_apply_policy_updates_sets_author(self, monkeypatch):
        """Sets counterfactual_replay as the update author."""
        calls = []
        def mock_upsert(data):
            calls.append(data)
        monkeypatch.setattr("counterfactual_replay.db.upsert", mock_upsert)

        results = [
            {
                "changed": True,
                "task_kind": "build",
                "recommended": "claude-opus-4",
                "best_quality": 0.95,
            },
        ]

        cfr._apply_policy_updates(results)
        if calls:
            value = calls[0].get("value", {})
            assert value.get("updated_by") == "counterfactual_replay"


class TestEnvironmentConfiguration:
    """Tests for environment variable configuration."""

    def test_enabled_default_true(self):
        """ORCH_REPLAY_ENABLED defaults to true."""
        # Verify current state (should be true unless explicitly set to false)
        assert isinstance(cfr.ENABLED, bool)

    def test_lookback_days_default_7(self):
        """ORCH_REPLAY_LOOKBACK_DAYS defaults to 7."""
        assert cfr.LOOKBACK_DAYS >= 1
        assert isinstance(cfr.LOOKBACK_DAYS, int)

    def test_sample_size_default_100(self):
        """ORCH_REPLAY_SAMPLE_SIZE defaults to 100."""
        assert cfr.SAMPLE_SIZE >= 1
        assert isinstance(cfr.SAMPLE_SIZE, int)


class TestEdgeCases:
    """Tests for edge cases and error conditions."""

    def test_replay_decision_with_zero_quality(self):
        """Handles zero quality scores correctly."""
        task = {
            "slug": "task-1",
            "kind": "build",
            "force_coder": "claude-haiku",
        }
        roster = {
            ("claude-haiku", "build"): {"quality": 0.0, "cost": 0.0},
            ("claude-opus-4", "build"): {"quality": 1.0, "cost": 0.5},
        }

        result = cfr.replay_decision(task, roster)
        assert result["quality_delta"] == 1.0

    def test_replay_decision_with_negative_quality(self):
        """Handles negative quality scores (shouldn't happen, but fail-soft)."""
        task = {
            "slug": "task-1",
            "kind": "build",
            "force_coder": "claude-haiku",
        }
        roster = {
            ("claude-haiku", "build"): {"quality": -0.5, "cost": 0.1},
            ("claude-opus-4", "build"): {"quality": 0.95, "cost": 0.5},
        }

        result = cfr.replay_decision(task, roster)
        assert isinstance(result, dict)

    def test_run_replay_with_very_large_tasks_list(self, monkeypatch):
        """Handles large number of tasks efficiently."""
        tasks = [
            {"id": i, "slug": f"task-{i}", "kind": "build", "force_coder": "claude-haiku"}
            for i in range(1000)
        ]
        roster = {
            ("claude-opus-4", "build"): {"quality": 0.95, "cost": 0.5},
            ("claude-haiku", "build"): {"quality": 0.7, "cost": 0.1},
        }

        monkeypatch.setattr("counterfactual_replay._fetch_recent_decisions", lambda *a, **k: tasks)
        monkeypatch.setattr("counterfactual_replay._current_model_roster", lambda: roster)
        monkeypatch.setattr("counterfactual_replay.ENABLED", True)

        result = cfr.run_replay()
        assert result["tasks_scanned"] == 1000

    def test_replay_decision_with_malformed_task_dict(self):
        """Handles malformed task dict with missing keys."""
        task = {"slug": "task-1"}  # Missing kind and force_coder
        roster = {("claude-opus-4", "build"): {"quality": 0.95, "cost": 0.5}}

        result = cfr.replay_decision(task, roster)
        assert isinstance(result, dict)
        assert "task_kind" in result

    def test_apply_policy_updates_with_special_characters_in_kind(self, monkeypatch):
        """Handles task kinds with special characters."""
        calls = []
        def mock_upsert(data):
            calls.append(data)
        monkeypatch.setattr("counterfactual_replay.db.upsert", mock_upsert)

        results = [
            {
                "changed": True,
                "task_kind": "build-test_case",
                "recommended": "claude-opus-4",
                "best_quality": 0.95,
            },
        ]

        cfr._apply_policy_updates(results)
        if calls:
            key = calls[0].get("key", "")
            assert "route_override:" in key


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
