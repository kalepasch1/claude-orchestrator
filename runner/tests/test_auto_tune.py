#!/usr/bin/env python3
"""Tests for auto-tuning infrastructure: decision logic, guardrails, rollback."""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch
import json

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import meta_loop

import datetime


def _ago(hours=0):
    """A UTC datetime `hours` in the past."""
    return datetime.datetime.utcnow() - datetime.timedelta(hours=hours)


def _iso(when):
    """The Z-suffixed ISO-8601 form the control plane stores."""
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


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
        metrics = {
            ("proj1", "build"): {
                "cycle_time": 100.0,  # 30-day baseline
                "first_try_yield": 0.70,
                "sample_count": 100,
            }
        }
        # THE FIRST db.select CALL *IS* THE 5-DAY ONE.
        #
        # This used to burn call 1 on "30-day metrics", with the comment "This
        # is mocked via _stage_metrics_summary" -- which is exactly why that
        # call never happens: _stage_metrics_summary is patched two lines below
        # and issues no query. So the only db.select the code makes, the 5-day
        # window read, received the [] meant for a call that does not exist,
        # `if metrics_5d:` was False, and no regression decision could ever be
        # produced. Answer the query that is actually asked.
        def select_side_effect(table, params=None, *args, **kwargs):
            assert (params or {}).get("window_days") == "eq.5", params
            return [{"avg_cycle_time_seconds": 118.0}]      # 18% over baseline

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

        # RELATIVE, NOT ABSOLUTE. These fixtures were pinned to 2026-07-05 and
        # stage_metrics() windows on wall-clock (5 and 30 days), so the data
        # aged out of every window and no row was ever grouped. A test whose
        # fixtures expire is a test with a shelf life; anchor it to now.
        finished_at = _iso(_ago(hours=1))
        started_at = _iso(_ago(hours=2))
        tasks = [
            {
                "id": "t1",
                "slug": "feature-1",
                "project_id": "p1",
                "kind": "build",
                "created_at": started_at,          # one hour before the outcome
                "remediation_count": 0,
                "state": "MERGED",
            }
        ]
        outcomes = [
            {
                "task_id": "t1",
                "created_at": finished_at,
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

        # Relative for the same reason as the test above.
        tasks = [
            {"id": "t1", "project_id": "p1", "kind": "build",
             "created_at": _iso(_ago(hours=6)), "remediation_count": 0, "state": "MERGED"},
            {"id": "t2", "project_id": "p1", "kind": "build",
             "created_at": _iso(_ago(hours=5)), "remediation_count": 0, "state": "MERGED"},
            {"id": "t3", "project_id": "p1", "kind": "build",
             "created_at": _iso(_ago(hours=4)), "remediation_count": 2, "state": "MERGED"},
        ]
        outcomes = [
            {"task_id": "t1", "created_at": _iso(_ago(hours=5))},
            {"task_id": "t2", "created_at": _iso(_ago(hours=4))},
            {"task_id": "t3", "created_at": _iso(_ago(hours=2))},
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
