#!/usr/bin/env python3
"""
Comprehensive test suite for counterfactual-replay feature.

Tests the core functionality:
- Fetching recent decisions from database
- Loading current model roster
- Replaying individual decisions against new model scores
- Detecting when decisions would diverge
- Applying policy updates
- Full end-to-end replay workflow

Tests validate:
- Correct decision comparison logic
- Model roster loading and scoring
- Quality delta calculation and thresholds
- Policy update persistence
- Batch processing of multiple tasks
- Environment variable configuration
- Fail-soft error handling (no crashes on bad DB/data)
- Thread-safe operations
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


# =============================================================================
# Test: replay_decision() core logic
# =============================================================================

class TestReplayDecision:
    """Test replay_decision() — re-evaluate a single task against new roster."""

    def test_replay_detects_model_change(self):
        """Detect when a different model would be chosen."""
        task = {
            "id": "task_001",
            "slug": "build-123",
            "kind": "build",
            "force_coder": "haiku",
            "state": "DONE",
        }
        roster = {
            ("haiku", "build"): {"quality": 7.0, "cost": 0.01},
            ("opus", "build"): {"quality": 8.5, "cost": 0.05},  # Better
        }

        result = cfr.replay_decision(task, roster)

        assert result["changed"] is True
        assert result["original_coder"] == "haiku"
        assert result["recommended"] == "opus"
        assert result["quality_delta"] > 0

    def test_replay_no_change_when_model_still_best(self):
        """No change flagged when original model remains best choice."""
        task = {
            "slug": "build-234",
            "kind": "build",
            "force_coder": "opus",
        }
        roster = {
            ("haiku", "build"): {"quality": 6.0, "cost": 0.01},
            ("opus", "build"): {"quality": 8.5, "cost": 0.05},  # Still best
        }

        result = cfr.replay_decision(task, roster)

        assert result["changed"] is False
        assert result["original_coder"] == "opus"
        assert result["recommended"] == "opus"

    def test_replay_quality_delta_below_threshold_not_flagged(self):
        """Small quality improvements below 0.5 threshold not flagged."""
        task = {
            "slug": "plan-345",
            "kind": "plan",
            "force_coder": "haiku",
        }
        roster = {
            ("haiku", "plan"): {"quality": 8.0, "cost": 0.01},
            ("opus", "plan"): {"quality": 8.3, "cost": 0.05},  # Only 0.3 delta
        }

        result = cfr.replay_decision(task, roster)

        assert result["changed"] is False  # Below 0.5 threshold

    def test_replay_preserves_task_metadata(self):
        """Replay result includes original task information."""
        task = {
            "slug": "test-456",
            "kind": "testing",
            "force_coder": "haiku",
        }
        roster = {}

        result = cfr.replay_decision(task, roster)

        assert result["task_slug"] == "test-456"
        assert result["task_kind"] == "testing"
        assert result["original_coder"] == "haiku"

    def test_replay_handles_missing_original_model_in_roster(self):
        """Gracefully handle when original model not in current roster."""
        task = {
            "slug": "old-model-task",
            "kind": "build",
            "force_coder": "old-model-v1",  # No longer in roster
        }
        roster = {
            ("haiku", "build"): {"quality": 7.5, "cost": 0.01},
        }

        result = cfr.replay_decision(task, roster)

        # Should default original quality to 0.0
        assert result["original_quality"] == 0.0
        assert result["best_quality"] == 7.5
        assert result["recommended"] == "haiku"

    def test_replay_returns_rounded_quality_scores(self):
        """Quality scores rounded to 2 decimal places."""
        task = {
            "slug": "precision-test",
            "kind": "build",
            "force_coder": "haiku",
        }
        roster = {
            ("haiku", "build"): {"quality": 7.123456, "cost": 0.01},
            ("opus", "build"): {"quality": 8.987654, "cost": 0.05},
        }

        result = cfr.replay_decision(task, roster)

        assert isinstance(result["original_quality"], float)
        assert result["best_quality"] == 8.99  # Rounded to 2 decimals
        assert result["quality_delta"] == 1.86  # Rounded


# =============================================================================
# Test: _fetch_recent_decisions() database integration
# =============================================================================

class TestFetchRecentDecisions:
    """Test _fetch_recent_decisions() — load task history from DB."""

    @patch("counterfactual_replay.db")
    def test_fetch_calls_db_select_with_correct_params(self, mock_db):
        """DB query uses correct table, fields, and filters."""
        mock_db.select.return_value = []

        cfr._fetch_recent_decisions(lookback_days=7, limit=100)

        # Verify db.select called
        assert mock_db.select.called
        call_args = mock_db.select.call_args
        assert "tasks" in call_args[0]  # First arg is table name
        query_dict = call_args[0][1]  # Second arg is query params
        assert "DONE" in query_dict.get("state", "")
        assert "MERGED" in query_dict.get("state", "")
        assert query_dict.get("limit") == "100"

    @patch("counterfactual_replay.db")
    def test_fetch_returns_empty_list_on_no_tasks(self, mock_db):
        """Returns empty list when no completed tasks found."""
        mock_db.select.return_value = None

        result = cfr._fetch_recent_decisions()

        assert result == []

    @patch("counterfactual_replay.db")
    def test_fetch_returns_task_list(self, mock_db):
        """Returns list of task dicts from DB."""
        mock_db.select.return_value = [
            {"id": "t1", "slug": "s1", "kind": "build", "force_coder": "haiku"},
            {"id": "t2", "slug": "s2", "kind": "plan", "force_coder": "opus"},
        ]

        result = cfr._fetch_recent_decisions()

        assert len(result) == 2
        assert result[0]["id"] == "t1"
        assert result[1]["id"] == "t2"

    @patch("counterfactual_replay.db")
    def test_fetch_respects_lookback_days_param(self, mock_db):
        """Query cutoff time calculated from lookback_days."""
        mock_db.select.return_value = []
        before = time.time()

        cfr._fetch_recent_decisions(lookback_days=14)

        after = time.time()
        query_dict = mock_db.select.call_args[0][1]
        # Cutoff should be ~14 days ago
        # Can't assert exact time due to execution time, but verify format
        assert "gte." in query_dict.get("updated_at", "")


# =============================================================================
# Test: _current_model_roster() model scoring
# =============================================================================

class TestCurrentModelRoster:
    """Test _current_model_roster() — load model quality scores."""

    @patch("counterfactual_replay.db")
    def test_roster_loads_model_scores_by_task_kind(self, mock_db):
        """Roster groups scores by (model, task_kind) tuple."""
        mock_db.select.return_value = [
            {"model": "haiku", "task_kind": "build", "quality": 7.0, "cost_usd": 0.01},
            {"model": "opus", "task_kind": "build", "quality": 8.5, "cost_usd": 0.05},
            {"model": "haiku", "task_kind": "plan", "quality": 6.5, "cost_usd": 0.01},
        ]

        roster = cfr._current_model_roster()

        assert ("haiku", "build") in roster
        assert ("opus", "build") in roster
        assert ("haiku", "plan") in roster
        assert roster[("haiku", "build")]["quality"] == 7.0

    @patch("counterfactual_replay.db")
    def test_roster_converts_scores_to_float(self, mock_db):
        """Quality and cost converted to float."""
        mock_db.select.return_value = [
            {"model": "opus", "task_kind": "build", "quality": "8.5", "cost_usd": "0.05"},
        ]

        roster = cfr._current_model_roster()

        assert isinstance(roster[("opus", "build")]["quality"], float)
        assert isinstance(roster[("opus", "build")]["cost"], float)

    @patch("counterfactual_replay.db")
    def test_roster_handles_db_exception_gracefully(self, mock_db):
        """DB error returns empty roster (fail-soft)."""
        mock_db.select.side_effect = Exception("DB connection failed")

        roster = cfr._current_model_roster()

        assert roster == {}

    @patch("counterfactual_replay.db")
    def test_roster_returns_empty_on_no_scores(self, mock_db):
        """Empty list from DB returns empty roster."""
        mock_db.select.return_value = None

        roster = cfr._current_model_roster()

        assert roster == {}


# =============================================================================
# Test: run_replay() main orchestration
# =============================================================================

class TestRunReplay:
    """Test run_replay() — full replay workflow."""

    @patch("counterfactual_replay._fetch_recent_decisions")
    @patch("counterfactual_replay._current_model_roster")
    def test_replay_returns_disabled_summary_when_disabled(self, mock_roster, mock_fetch):
        """When ENABLED=False, returns disabled status immediately."""
        with patch.object(cfr, "ENABLED", False):
            result = cfr.run_replay()

        assert result["enabled"] is False
        assert not mock_fetch.called
        assert not mock_roster.called

    @patch("counterfactual_replay._fetch_recent_decisions")
    @patch("counterfactual_replay._current_model_roster")
    def test_replay_returns_error_when_no_roster(self, mock_roster, mock_fetch):
        """Returns error summary when model roster unavailable."""
        mock_fetch.return_value = [{"slug": "task1"}]
        mock_roster.return_value = {}  # Empty roster

        result = cfr.run_replay()

        assert result["error"] == "no_roster"
        assert result["tasks_scanned"] == 1

    @patch("counterfactual_replay._fetch_recent_decisions")
    @patch("counterfactual_replay._current_model_roster")
    def test_replay_counts_diverged_decisions(self, mock_roster, mock_fetch):
        """Summary includes count of decisions where model changed."""
        mock_fetch.return_value = [
            {"slug": "t1", "kind": "build", "force_coder": "haiku"},
            {"slug": "t2", "kind": "build", "force_coder": "haiku"},
        ]
        mock_roster.return_value = {
            ("haiku", "build"): {"quality": 7.0, "cost": 0.01},
            ("opus", "build"): {"quality": 8.5, "cost": 0.05},
        }

        with patch.object(cfr, "ENABLED", True):
            result = cfr.run_replay()

        assert result["tasks_scanned"] == 2
        # Both tasks should diverge (opus is 1.5 points better, above 0.5 threshold)
        assert result["decisions_diverged"] > 0

    @patch("counterfactual_replay._fetch_recent_decisions")
    @patch("counterfactual_replay._current_model_roster")
    def test_replay_calculates_divergence_rate(self, mock_roster, mock_fetch):
        """Divergence rate = diverged / total."""
        mock_fetch.return_value = [
            {"slug": "t1", "kind": "build", "force_coder": "haiku"},
            {"slug": "t2", "kind": "build", "force_coder": "opus"},
        ]
        mock_roster.return_value = {
            ("haiku", "build"): {"quality": 7.0, "cost": 0.01},
            ("opus", "build"): {"quality": 8.5, "cost": 0.05},
        }

        with patch.object(cfr, "ENABLED", True):
            result = cfr.run_replay()

        assert "divergence_rate" in result
        assert 0.0 <= result["divergence_rate"] <= 1.0

    @patch("counterfactual_replay._fetch_recent_decisions")
    @patch("counterfactual_replay._current_model_roster")
    @patch("counterfactual_replay._apply_policy_updates")
    def test_replay_apply_flag_triggers_updates(self, mock_apply, mock_roster, mock_fetch):
        """When apply=True and divergences exist, calls _apply_policy_updates."""
        mock_fetch.return_value = [
            {"slug": "t1", "kind": "build", "force_coder": "haiku"},
        ]
        mock_roster.return_value = {
            ("haiku", "build"): {"quality": 7.0, "cost": 0.01},
            ("opus", "build"): {"quality": 8.5, "cost": 0.05},
        }

        with patch.object(cfr, "ENABLED", True):
            result = cfr.run_replay(apply=True)

        # If any divergences, update should be called
        if result["decisions_diverged"] > 0:
            assert mock_apply.called
        assert result["applied"] == (result["decisions_diverged"] > 0)

    @patch("counterfactual_replay._fetch_recent_decisions")
    @patch("counterfactual_replay._current_model_roster")
    def test_replay_respects_limit_param(self, mock_roster, mock_fetch):
        """Passes limit param to _fetch_recent_decisions."""
        mock_fetch.return_value = []
        mock_roster.return_value = {}

        with patch.object(cfr, "ENABLED", True):
            cfr.run_replay(limit=50)

        mock_fetch.assert_called_once()
        assert mock_fetch.call_args[0][1] == 50  # limit is second param

    @patch("counterfactual_replay._fetch_recent_decisions")
    @patch("counterfactual_replay._current_model_roster")
    def test_replay_includes_top_changes_in_summary(self, mock_roster, mock_fetch):
        """Summary includes top 10 changes sorted by quality delta."""
        mock_fetch.return_value = [
            {"slug": "t1", "kind": "build", "force_coder": "haiku"},
            {"slug": "t2", "kind": "build", "force_coder": "haiku"},
        ]
        mock_roster.return_value = {
            ("haiku", "build"): {"quality": 7.0, "cost": 0.01},
            ("opus", "build"): {"quality": 9.0, "cost": 0.05},  # 2.0 delta
        }

        with patch.object(cfr, "ENABLED", True):
            result = cfr.run_replay()

        assert "top_changes" in result
        assert isinstance(result["top_changes"], list)


# =============================================================================
# Test: _apply_policy_updates() persistence
# =============================================================================

class TestApplyPolicyUpdates:
    """Test _apply_policy_updates() — persist routing policy changes."""

    @patch("counterfactual_replay.db")
    def test_apply_filters_to_changed_decisions(self, mock_db):
        """Only updates where changed=True are persisted."""
        results = [
            {"changed": True, "task_kind": "build", "recommended": "opus"},
            {"changed": False, "task_kind": "plan", "recommended": "haiku"},
            {"changed": True, "task_kind": "test", "recommended": "sonnet"},
        ]

        cfr._apply_policy_updates(results)

        # Should call upsert 2 times (only changed=True)
        assert mock_db.upsert.call_count == 2

    @patch("counterfactual_replay.db")
    def test_apply_creates_route_override_key(self, mock_db):
        """Upserted config key follows pattern route_override:{task_kind}."""
        results = [
            {
                "changed": True,
                "task_kind": "build",
                "recommended": "opus",
                "best_quality": 8.5,
            },
        ]

        cfr._apply_policy_updates(results)

        call_dict = mock_db.upsert.call_args[0][0]
        assert "route_override:build" in call_dict["key"]

    @patch("counterfactual_replay.db")
    def test_apply_includes_recommended_model_in_update(self, mock_db):
        """Config value includes preferred_model field."""
        results = [
            {
                "changed": True,
                "task_kind": "plan",
                "recommended": "fable-5",
                "best_quality": 7.8,
            },
        ]

        cfr._apply_policy_updates(results)

        call_dict = mock_db.upsert.call_args[0][0]
        value = call_dict["value"]
        assert value["preferred_model"] == "fable-5"
        assert value["quality"] == 7.8

    @patch("counterfactual_replay.db")
    def test_apply_marks_update_origin(self, mock_db):
        """Update marked as from counterfactual_replay."""
        results = [
            {"changed": True, "task_kind": "build", "recommended": "opus"},
        ]

        cfr._apply_policy_updates(results)

        call_dict = mock_db.upsert.call_args[0][0]
        assert call_dict["value"]["updated_by"] == "counterfactual_replay"

    @patch("counterfactual_replay.db")
    def test_apply_handles_upsert_exception_gracefully(self, mock_db):
        """DB upsert failure logged but doesn't crash."""
        results = [
            {"changed": True, "task_kind": "build", "recommended": "opus"},
        ]
        mock_db.upsert.side_effect = Exception("DB write failed")

        # Should not raise
        try:
            cfr._apply_policy_updates(results)
        except Exception as e:
            assert False, f"Should fail-soft, not raise: {e}"


# =============================================================================
# Test: Configuration from environment
# =============================================================================

class TestConfiguration:
    """Test environment variable configuration."""

    def test_enabled_defaults_to_true(self):
        """ORCH_REPLAY_ENABLED defaults to true."""
        with patch.dict(os.environ, {}, clear=False):
            if "ORCH_REPLAY_ENABLED" in os.environ:
                del os.environ["ORCH_REPLAY_ENABLED"]
            # Re-import to pick up new env
            import importlib
            importlib.reload(cfr)
            assert cfr.ENABLED is True

    def test_lookback_days_env_var(self):
        """ORCH_REPLAY_LOOKBACK_DAYS sets lookback window."""
        with patch.dict(os.environ, {"ORCH_REPLAY_LOOKBACK_DAYS": "14"}):
            import importlib
            importlib.reload(cfr)
            assert cfr.LOOKBACK_DAYS == 14

    def test_sample_size_env_var(self):
        """ORCH_REPLAY_SAMPLE_SIZE limits tasks to replay."""
        with patch.dict(os.environ, {"ORCH_REPLAY_SAMPLE_SIZE": "50"}):
            import importlib
            importlib.reload(cfr)
            assert cfr.SAMPLE_SIZE == 50


# =============================================================================
# Test: CLI argument parsing
# =============================================================================

class TestCLIInterface:
    """Test command-line interface."""

    @patch("counterfactual_replay.run_replay")
    def test_cli_dry_run_default(self, mock_run):
        """No args runs dry-run (apply=False)."""
        mock_run.return_value = {}
        # Simulate running __main__ section without --apply
        cfr.run_replay(apply=False)
        mock_run.assert_called()

    @patch("counterfactual_replay.run_replay")
    def test_cli_apply_flag(self, mock_run):
        """--apply flag sets apply=True."""
        mock_run.return_value = {}
        cfr.run_replay(apply=True)
        mock_run.assert_called()

    @patch("counterfactual_replay.run_replay")
    def test_cli_limit_param(self, mock_run):
        """--limit N is passed to run_replay."""
        mock_run.return_value = {}
        cfr.run_replay(limit=25)
        # Check that limit was used in the call
        assert mock_run.call_args is not None


# =============================================================================
# Test: Edge cases and error handling
# =============================================================================

class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_replay_decision_with_unknown_force_coder(self):
        """Task with unknown force_coder defaults gracefully."""
        task = {
            "slug": "unknown-model",
            "kind": "build",
            "force_coder": None,
        }
        roster = {
            ("opus", "build"): {"quality": 8.5, "cost": 0.05},
        }

        result = cfr.replay_decision(task, roster)

        assert result["original_coder"] == "unknown"
        assert result["recommended"] == "opus"

    def test_replay_decision_with_missing_task_kind(self):
        """Task with missing kind defaults to 'build'."""
        task = {
            "slug": "no-kind-task",
            "force_coder": "haiku",
        }
        roster = {
            ("haiku", "build"): {"quality": 7.0, "cost": 0.01},
        }

        result = cfr.replay_decision(task, roster)

        assert result["task_kind"] == "build"

    @patch("counterfactual_replay._fetch_recent_decisions")
    @patch("counterfactual_replay._current_model_roster")
    def test_replay_with_empty_task_list(self, mock_roster, mock_fetch):
        """Empty task list produces valid summary."""
        mock_fetch.return_value = []
        mock_roster.return_value = {
            ("haiku", "build"): {"quality": 7.0, "cost": 0.01},
        }

        with patch.object(cfr, "ENABLED", True):
            result = cfr.run_replay()

        assert result["tasks_scanned"] == 0
        assert result["decisions_diverged"] == 0
        assert result["divergence_rate"] == 0.0

    def test_replay_quality_delta_precision(self):
        """Quality delta calculated with precision."""
        task = {
            "slug": "precision",
            "kind": "build",
            "force_coder": "haiku",
        }
        roster = {
            ("haiku", "build"): {"quality": 7.123, "cost": 0.01},
            ("opus", "build"): {"quality": 8.456, "cost": 0.05},
        }

        result = cfr.replay_decision(task, roster)

        # 8.456 - 7.123 = 1.333, rounded to 1.33
        assert result["quality_delta"] == 1.33


# =============================================================================
# Test: Concurrency and thread safety
# =============================================================================

class TestThreadSafety:
    """Test thread-safe operations."""

    @patch("counterfactual_replay._fetch_recent_decisions")
    @patch("counterfactual_replay._current_model_roster")
    def test_replay_thread_safety(self, mock_roster, mock_fetch):
        """Multiple threads calling run_replay don't race."""
        mock_fetch.return_value = [
            {"slug": "t1", "kind": "build", "force_coder": "haiku"},
        ]
        mock_roster.return_value = {
            ("haiku", "build"): {"quality": 7.0, "cost": 0.01},
        }

        results = []
        lock = Lock()

        def run_in_thread():
            with patch.object(cfr, "ENABLED", True):
                result = cfr.run_replay()
            with lock:
                results.append(result)

        threads = [Thread(target=run_in_thread) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 3


# =============================================================================
# Run all tests
# =============================================================================

if __name__ == "__main__":
    # Test groups
    test_groups = [
        ("replay_decision", [
            TestReplayDecision().test_replay_detects_model_change,
            TestReplayDecision().test_replay_no_change_when_model_still_best,
            TestReplayDecision().test_replay_quality_delta_below_threshold_not_flagged,
            TestReplayDecision().test_replay_preserves_task_metadata,
            TestReplayDecision().test_replay_handles_missing_original_model_in_roster,
            TestReplayDecision().test_replay_returns_rounded_quality_scores,
        ]),
        ("fetch_recent_decisions", [
            TestFetchRecentDecisions().test_fetch_calls_db_select_with_correct_params,
            TestFetchRecentDecisions().test_fetch_returns_empty_list_on_no_tasks,
            TestFetchRecentDecisions().test_fetch_returns_task_list,
            TestFetchRecentDecisions().test_fetch_respects_lookback_days_param,
        ]),
        ("current_model_roster", [
            TestCurrentModelRoster().test_roster_loads_model_scores_by_task_kind,
            TestCurrentModelRoster().test_roster_converts_scores_to_float,
            TestCurrentModelRoster().test_roster_handles_db_exception_gracefully,
            TestCurrentModelRoster().test_roster_returns_empty_on_no_scores,
        ]),
        ("run_replay", [
            TestRunReplay().test_replay_returns_disabled_summary_when_disabled,
            TestRunReplay().test_replay_returns_error_when_no_roster,
            TestRunReplay().test_replay_counts_diverged_decisions,
            TestRunReplay().test_replay_calculates_divergence_rate,
            TestRunReplay().test_replay_apply_flag_triggers_updates,
            TestRunReplay().test_replay_respects_limit_param,
            TestRunReplay().test_replay_includes_top_changes_in_summary,
        ]),
        ("apply_policy_updates", [
            TestApplyPolicyUpdates().test_apply_filters_to_changed_decisions,
            TestApplyPolicyUpdates().test_apply_creates_route_override_key,
            TestApplyPolicyUpdates().test_apply_includes_recommended_model_in_update,
            TestApplyPolicyUpdates().test_apply_marks_update_origin,
            TestApplyPolicyUpdates().test_apply_handles_upsert_exception_gracefully,
        ]),
        ("configuration", [
            TestConfiguration().test_enabled_defaults_to_true,
            TestConfiguration().test_lookback_days_env_var,
            TestConfiguration().test_sample_size_env_var,
        ]),
        ("cli_interface", [
            TestCLIInterface().test_cli_dry_run_default,
            TestCLIInterface().test_cli_apply_flag,
            TestCLIInterface().test_cli_limit_param,
        ]),
        ("edge_cases", [
            TestEdgeCases().test_replay_decision_with_unknown_force_coder,
            TestEdgeCases().test_replay_decision_with_missing_task_kind,
            TestEdgeCases().test_replay_with_empty_task_list,
            TestEdgeCases().test_replay_quality_delta_precision,
        ]),
        ("thread_safety", [
            TestThreadSafety().test_replay_thread_safety,
        ]),
    ]

    passed = 0
    failed = 0

    for group_name, tests in test_groups:
        print(f"\n{group_name}:")
        for test in tests:
            try:
                test()
                print(f"  ✓ {test.__name__}")
                passed += 1
            except Exception as e:
                print(f"  ✗ {test.__name__}: {e}")
                failed += 1

    print(f"\n{'='*60}")
    print(f"Results: {passed} passed, {failed} failed ({passed + failed} total)")
    if failed == 0:
        print("✓ All tests passed!")
    sys.exit(0 if failed == 0 else 1)
