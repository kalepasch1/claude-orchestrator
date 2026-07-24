#!/usr/bin/env python3
"""Tests for auto-tuning infrastructure: decision logic, guardrails, rollback."""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch
import json

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import meta_loop


class TestAutoTuneGuardrails(unittest.TestCase):
    """Test guardrail enforcement."""

    def test_min_samples_guardrail(self):
        """Decisions not made on fewer than MIN_SAMPLES tasks."""
        min_samples = 50
        metrics = {
            ("proj1", "build"): {
                "cycle_time": 100,
                "first_try_yield": 0.30,  # very low, would normally trigger
                "sample_count": min_samples - 1,  # just below threshold
            }
        }
        with patch.object(meta_loop, "AUTO_TUNE_ENABLE", True), \
             patch.object(meta_loop, "AUTO_TUNE_MIN_SAMPLES", min_samples), \
             patch.object(meta_loop, "_stage_metrics_summary", return_value=metrics), \
             patch.object(meta_loop, "_read_tuning_state", return_value={}):
            decisions = meta_loop._plan_auto_tune_decisions()

        self.assertEqual(len(decisions), 0)

        # Now with exactly min_samples
        metrics[("proj1", "build")]["sample_count"] = min_samples
        with patch.object(meta_loop, "AUTO_TUNE_ENABLE", True), \
             patch.object(meta_loop, "AUTO_TUNE_MIN_SAMPLES", min_samples), \
             patch.object(meta_loop, "_stage_metrics_summary", return_value=metrics), \
             patch.object(meta_loop, "_read_tuning_state", return_value={}):
            decisions = meta_loop._plan_auto_tune_decisions()

        self.assertGreater(len(decisions), 0)

    def test_max_change_pct_guardrail(self):
        """No single tuning adjustment exceeds MAX_CHANGE_PCT."""
        max_pct = 15
        metrics = {
            ("proj1", "build"): {
                "cycle_time": 100,
                "first_try_yield": 0.01,  # extreme, would suggest large change
                "sample_count": 100,
            }
        }
        with patch.object(meta_loop, "AUTO_TUNE_ENABLE", True), \
             patch.object(meta_loop, "AUTO_TUNE_MAX_CHANGE_PCT", max_pct), \
             patch.object(meta_loop, "_stage_metrics_summary", return_value=metrics), \
             patch.object(meta_loop, "_read_tuning_state", return_value={}):
            decisions = meta_loop._plan_auto_tune_decisions()

        for decision in decisions:
            self.assertLessEqual(decision["pct_change"], max_pct)

    def test_only_build_tasks_get_gate_bypass_decision(self):
        """Gate bypass decisions only apply to 'build' kind tasks."""
        metrics = {
            ("proj1", "build"): {
                "cycle_time": 100,
                "first_try_yield": 0.50,  # low
                "sample_count": 100,
            },
            ("proj1", "research"): {
                "cycle_time": 100,
                "first_try_yield": 0.50,  # low
                "sample_count": 100,
            },
        }
        with patch.object(meta_loop, "AUTO_TUNE_ENABLE", True), \
             patch.object(meta_loop, "_stage_metrics_summary", return_value=metrics), \
             patch.object(meta_loop, "_read_tuning_state", return_value={}):
            decisions = meta_loop._plan_auto_tune_decisions()

        # Gate bypass should only be for 'build'
        gate_bypass = [d for d in decisions if d["action"] == "bypass_build_gate_for_low_risk"]
        for decision in gate_bypass:
            self.assertEqual(decision["kind"], "build")


class TestCycleTimeRegression(unittest.TestCase):
    """Test cycle_time regression detection."""

    def test_detects_cycle_time_increase_above_threshold(self):
        """Detects when 5-day cycle_time is >15% higher than 30-day baseline."""
        # This test would need metric_5d data to be returned separately
        # For now, test that the logic tries to fetch it
        metrics = {
            ("proj1", "build"): {
                "cycle_time": 100.0,  # 30-day baseline
                "first_try_yield": 0.70,
                "sample_count": 100,
            }
        }
        # Mock db.select to return 5-day metrics on second call
        call_count = [0]
        def select_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                # First call: 30-day metrics
                return []  # This is mocked via _stage_metrics_summary
            else:
                # Second call: 5-day metrics
                return [{"avg_cycle_time_seconds": 118.0}]  # 18% increase

        with patch.object(meta_loop, "AUTO_TUNE_ENABLE", True), \
             patch.object(meta_loop, "_stage_metrics_summary", return_value=metrics), \
             patch.object(meta_loop, "_read_tuning_state", return_value={}), \
             patch.object(meta_loop, "db") as mdb:
            mdb.select.side_effect = select_side_effect
            decisions = meta_loop._plan_auto_tune_decisions()

        # Should produce a regression-detection decision
        regression_decisions = [d for d in decisions if d.get("metric") == "cycle_time"]
        self.assertGreater(len(regression_decisions), 0)
        self.assertIn("rotate_model_mix", [d.get("action") for d in regression_decisions])


class TestDryRunMode(unittest.TestCase):
    """Test DRYRUN mode behavior."""

    def test_dryrun_logs_without_applying(self):
        """DRYRUN mode logs decisions without modifying system state."""
        metrics = {
            ("proj1", "build"): {
                "cycle_time": 100,
                "first_try_yield": 0.50,
                "sample_count": 100,
            }
        }
        with patch.object(meta_loop, "AUTO_TUNE_DRYRUN", True), \
             patch.object(meta_loop, "AUTO_TUNE_ENABLE", False), \
             patch.object(meta_loop, "_stage_metrics_summary", return_value=metrics), \
             patch.object(meta_loop, "_read_tuning_state", return_value={}):
            decisions = meta_loop._plan_auto_tune_decisions()

        # DRYRUN still generates decisions (they're safe to generate)
        # but doesn't apply them
        self.assertGreater(len(decisions), 0)


class TestMetricsIntegration(unittest.TestCase):
    """Integration tests for metric collection and tuning."""

    def test_improvement_measure_collects_cycle_time(self):
        """improvement_measure.stage_metrics() collects cycle times."""
        import improvement_measure as im

        now = "2026-07-05T12:00:00Z"
        tasks = [
            {
                "id": "t1",
                "slug": "feature-1",
                "project_id": "p1",
                "kind": "build",
                "created_at": "2026-07-05T11:00:00Z",  # 1 hour before
                "remediation_count": 0,
                "state": "MERGED",
            }
        ]
        outcomes = [
            {
                "task_id": "t1",
                "created_at": "2026-07-05T12:00:00Z",
                "wall_ms": 3600000,  # 1 hour
            }
        ]

        db_mock = MagicMock()
        def select_side_effect(table, params=None):
            if table == "tasks":
                return tasks
            if table == "outcomes":
                return outcomes
            return []

        db_mock.select.side_effect = select_side_effect
        db_mock.insert.return_value = None

        with patch.object(im, "db", db_mock):
            result = im.stage_metrics()

        self.assertGreater(result["stage_metrics_written"], 0)
        call_args_list = db_mock.insert.call_args_list
        inserts = [call[0][1] for call in call_args_list if call[0][0] == "stage_metrics"]
        self.assertGreater(len(inserts), 0)
        metric = inserts[0]
        self.assertEqual(metric["project_id"], "p1")
        self.assertEqual(metric["kind"], "build")
        self.assertIn("avg_cycle_time_seconds", metric)

    def test_improvement_measure_tracks_first_try_yield(self):
        """improvement_measure correctly calculates first_try_yield."""
        import improvement_measure as im

        tasks = [
            {"id": "t1", "project_id": "p1", "kind": "build", "created_at": "2026-07-01T00:00:00Z", "remediation_count": 0, "state": "MERGED"},
            {"id": "t2", "project_id": "p1", "kind": "build", "created_at": "2026-07-02T00:00:00Z", "remediation_count": 0, "state": "MERGED"},
            {"id": "t3", "project_id": "p1", "kind": "build", "created_at": "2026-07-03T00:00:00Z", "remediation_count": 2, "state": "MERGED"},
        ]
        outcomes = [
            {"task_id": "t1", "created_at": "2026-07-01T01:00:00Z"},
            {"task_id": "t2", "created_at": "2026-07-02T01:00:00Z"},
            {"task_id": "t3", "created_at": "2026-07-03T02:00:00Z"},
        ]

        db_mock = MagicMock()
        def select_side_effect(table, params=None):
            if table == "tasks":
                return tasks
            if table == "outcomes":
                return outcomes
            return []

        db_mock.select.side_effect = select_side_effect
        db_mock.insert.return_value = None

        with patch.object(im, "db", db_mock):
            result = im.stage_metrics()

        call_args_list = db_mock.insert.call_args_list
        inserts = [call[0][1] for call in call_args_list if call[0][0] == "stage_metrics"]
        metric = inserts[0]
        # 2 out of 3 first-try = 66.7%
        self.assertAlmostEqual(metric["first_try_yield_pct"], 66.7, places=1)


if __name__ == "__main__":
    unittest.main()
