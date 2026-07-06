#!/usr/bin/env python3
"""Tests for meta_loop.py - metric aggregation and auto-tune decisions."""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch
import json
import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import meta_loop


class TestMetricsAggregation(unittest.TestCase):
    """Test stage_metrics_summary() metric collection."""

    def test_stage_metrics_summary_aggregates_30d_window(self):
        """stage_metrics_summary reads and aggregates 30-day metrics."""
        rows = [
            {
                "project_id": "proj1",
                "kind": "build",
                "window_days": 30,
                "avg_cycle_time_seconds": 120.5,
                "first_try_yield_pct": 65.0,
                "sample_count": 50,
            },
            {
                "project_id": "proj2",
                "kind": "research",
                "window_days": 30,
                "avg_cycle_time_seconds": 180.0,
                "first_try_yield_pct": 55.0,
                "sample_count": 30,
            },
        ]
        with patch.object(meta_loop, "db") as mdb:
            mdb.select.return_value = rows
            summary = meta_loop._stage_metrics_summary()

        self.assertEqual(len(summary), 2)
        self.assertIn(("proj1", "build"), summary)
        self.assertEqual(summary[("proj1", "build")]["cycle_time"], 120.5)
        self.assertEqual(summary[("proj1", "build")]["first_try_yield"], 0.65)
        self.assertEqual(summary[("proj1", "build")]["sample_count"], 50)

    def test_stage_metrics_summary_filters_by_window(self):
        """stage_metrics_summary filters to 30-day window only."""
        rows = [
            {"project_id": "p1", "kind": "build", "window_days": 30, "avg_cycle_time_seconds": 100, "first_try_yield_pct": 60, "sample_count": 50},
            {"project_id": "p1", "kind": "build", "window_days": 5, "avg_cycle_time_seconds": 90, "first_try_yield_pct": 70, "sample_count": 10},
        ]
        with patch.object(meta_loop, "db") as mdb:
            mdb.select.return_value = rows
            summary = meta_loop._stage_metrics_summary()

        # Should only use 30-day window in query
        call_args = mdb.select.call_args
        self.assertIn("window_days", call_args[0][1])
        self.assertEqual(call_args[0][1]["window_days"], "eq.30")

    def test_stage_metrics_summary_handles_missing_data(self):
        """stage_metrics_summary gracefully handles missing metrics."""
        with patch.object(meta_loop, "db") as mdb:
            mdb.select.return_value = None
            summary = meta_loop._stage_metrics_summary()
        self.assertEqual(summary, {})

        with patch.object(meta_loop, "db") as mdb:
            mdb.select.side_effect = Exception("DB error")
            summary = meta_loop._stage_metrics_summary()
        self.assertEqual(summary, {})


class TestAutoTuneDecisions(unittest.TestCase):
    """Test _plan_auto_tune_decisions() tuning logic."""

    def test_auto_tune_disabled_by_default(self):
        """Auto-tune is disabled unless ORCH_AUTO_TUNE_ENABLE=true."""
        with patch.object(meta_loop, "AUTO_TUNE_ENABLE", False), \
             patch.object(meta_loop, "AUTO_TUNE_DRYRUN", False):
            decisions = meta_loop._plan_auto_tune_decisions()
        self.assertEqual(decisions, [])

    def test_auto_tune_fires_when_enabled(self):
        """Auto-tune fires when enabled via env var."""
        metrics = {
            ("proj1", "build"): {
                "cycle_time": 100,
                "first_try_yield": 0.50,  # below 0.60 threshold
                "sample_count": 100,  # enough samples
            }
        }
        with patch.object(meta_loop, "AUTO_TUNE_ENABLE", True), \
             patch.object(meta_loop, "_stage_metrics_summary", return_value=metrics), \
             patch.object(meta_loop, "_read_tuning_state", return_value={}):
            decisions = meta_loop._plan_auto_tune_decisions()

        # Should produce a decision for low first_try_yield
        self.assertGreater(len(decisions), 0)
        decision = decisions[0]
        self.assertEqual(decision["action"], "bypass_build_gate_for_low_risk")
        self.assertLess(decision["current_value"], 60)

    def test_auto_tune_respects_min_samples_guardrail(self):
        """Auto-tune requires minimum sample count (default 50)."""
        metrics = {
            ("proj1", "build"): {
                "cycle_time": 100,
                "first_try_yield": 0.50,
                "sample_count": 10,  # below threshold
            }
        }
        with patch.object(meta_loop, "AUTO_TUNE_ENABLE", True), \
             patch.object(meta_loop, "AUTO_TUNE_MIN_SAMPLES", 50), \
             patch.object(meta_loop, "_stage_metrics_summary", return_value=metrics), \
             patch.object(meta_loop, "_read_tuning_state", return_value={}):
            decisions = meta_loop._plan_auto_tune_decisions()

        # Should not produce a decision due to low sample count
        self.assertEqual(len(decisions), 0)

    def test_auto_tune_detects_first_try_yield_below_threshold(self):
        """Auto-tune fires when first_try_yield < 60% with sufficient samples."""
        metrics = {
            ("proj1", "build"): {
                "cycle_time": 100,
                "first_try_yield": 0.55,  # 55% < 60%
                "sample_count": 100,
            }
        }
        with patch.object(meta_loop, "AUTO_TUNE_ENABLE", True), \
             patch.object(meta_loop, "FIRST_TRY_YIELD_THRESHOLD", 0.60), \
             patch.object(meta_loop, "_stage_metrics_summary", return_value=metrics), \
             patch.object(meta_loop, "_read_tuning_state", return_value={}):
            decisions = meta_loop._plan_auto_tune_decisions()

        self.assertEqual(len(decisions), 1)
        decision = decisions[0]
        self.assertEqual(decision["action"], "bypass_build_gate_for_low_risk")
        self.assertEqual(decision["current_value"], 55.0)

    def test_auto_tune_ignores_first_try_yield_above_threshold(self):
        """Auto-tune does not fire when first_try_yield >= 60%."""
        metrics = {
            ("proj1", "build"): {
                "cycle_time": 100,
                "first_try_yield": 0.75,  # 75% > 60%
                "sample_count": 100,
            }
        }
        with patch.object(meta_loop, "AUTO_TUNE_ENABLE", True), \
             patch.object(meta_loop, "FIRST_TRY_YIELD_THRESHOLD", 0.60), \
             patch.object(meta_loop, "_stage_metrics_summary", return_value=metrics), \
             patch.object(meta_loop, "_read_tuning_state", return_value={}):
            decisions = meta_loop._plan_auto_tune_decisions()

        self.assertEqual(len(decisions), 0)

    def test_auto_tune_respects_max_change_pct_guardrail(self):
        """Auto-tune decisions are capped at MAX_CHANGE_PCT."""
        metrics = {
            ("proj1", "build"): {
                "cycle_time": 100,
                "first_try_yield": 0.10,  # very low
                "sample_count": 100,
            }
        }
        with patch.object(meta_loop, "AUTO_TUNE_ENABLE", True), \
             patch.object(meta_loop, "AUTO_TUNE_MAX_CHANGE_PCT", 15), \
             patch.object(meta_loop, "_stage_metrics_summary", return_value=metrics), \
             patch.object(meta_loop, "_read_tuning_state", return_value={}):
            decisions = meta_loop._plan_auto_tune_decisions()

        self.assertGreater(len(decisions), 0)
        decision = decisions[0]
        self.assertLessEqual(decision["pct_change"], 15)

    def test_auto_tune_includes_justification(self):
        """Auto-tune decisions include clear justification."""
        metrics = {
            ("proj1", "build"): {
                "cycle_time": 100,
                "first_try_yield": 0.50,
                "sample_count": 100,
            }
        }
        with patch.object(meta_loop, "AUTO_TUNE_ENABLE", True), \
             patch.object(meta_loop, "_stage_metrics_summary", return_value=metrics), \
             patch.object(meta_loop, "_read_tuning_state", return_value={}):
            decisions = meta_loop._plan_auto_tune_decisions()

        self.assertGreater(len(decisions), 0)
        decision = decisions[0]
        self.assertIn("justification", decision)
        self.assertIn("first_try_yield", decision["justification"])


class TestTuningStateManagement(unittest.TestCase):
    """Test tuning state tracking and logging."""

    def test_read_tuning_state_loads_active_decisions(self):
        """_read_tuning_state loads active tuning decisions from resource_events."""
        decision1 = {"decision_id": "d1", "action": "bypass_gate", "status": "active"}
        decision2 = {"decision_id": "d2", "action": "rotate_model", "status": "active"}
        events = [
            {"detail": json.dumps(decision1)},
            {"detail": json.dumps(decision2)},
        ]
        with patch.object(meta_loop, "db") as mdb:
            mdb.select.return_value = events
            state = meta_loop._read_tuning_state()

        self.assertIn("d1", state)
        self.assertIn("d2", state)
        self.assertEqual(state["d1"]["action"], "bypass_gate")

    def test_read_tuning_state_ignores_inactive_decisions(self):
        """_read_tuning_state ignores rolled-back or inactive decisions."""
        decision = {"decision_id": "d1", "action": "bypass_gate", "status": "rolled_back"}
        events = [{"detail": json.dumps(decision)}]
        with patch.object(meta_loop, "db") as mdb:
            mdb.select.return_value = events
            state = meta_loop._read_tuning_state()

        self.assertEqual(state, {})  # rolled_back not included

    def test_read_tuning_state_handles_corrupt_json(self):
        """_read_tuning_state gracefully handles malformed JSON in detail."""
        events = [
            {"detail": "not json"},
            {"detail": '{"valid": "json"}'},
        ]
        with patch.object(meta_loop, "db") as mdb:
            mdb.select.return_value = events
            state = meta_loop._read_tuning_state()

        # Should not crash, should return empty or with valid entries
        self.assertIsInstance(state, dict)

    def test_log_tuning_decision_writes_to_resource_events(self):
        """_log_tuning_decision writes decision to resource_events table."""
        decision = {
            "decision_id": "d1",
            "action": "bypass_gate",
            "project_id": "p1",
            "justification": "test"
        }
        db_mock = MagicMock()
        with patch.object(meta_loop, "db", db_mock):
            meta_loop._log_tuning_decision(decision)

        db_mock.insert.assert_called_once()
        call_args = db_mock.insert.call_args
        self.assertEqual(call_args[0][0], "resource_events")
        row = call_args[0][1]
        self.assertEqual(row["kind"], "auto_tune_decision")
        self.assertIn("decision_id", json.loads(row["detail"]))

    def test_log_tuning_decision_handles_db_errors(self):
        """_log_tuning_decision gracefully handles insert errors."""
        decision = {"decision_id": "d1"}
        db_mock = MagicMock()
        db_mock.insert.side_effect = Exception("DB error")
        with patch.object(meta_loop, "db", db_mock):
            # Should not raise
            meta_loop._log_tuning_decision(decision)


if __name__ == "__main__":
    unittest.main()
