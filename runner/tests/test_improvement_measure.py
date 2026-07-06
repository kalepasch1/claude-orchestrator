"""
test_improvement_measure.py — tests for cycle-time, first-try-yield, and auto-tune.

A) cycle_time_by_kind: averages merged task durations per kind; excludes old tasks.
B) first_try_yield: fraction of zero-remediation merges; respects null remediation_count.
C) auto_tune: emits decisions when metrics breach thresholds; respects cooldown + max_per_run.
D) persistence: load/save tuning state round-trips correctly; rollback by deleting the file.
"""
import datetime
import json
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import improvement_measure


def _ts(offset_s: float = 0) -> str:
    """Return an ISO-8601 UTC timestamp string offset_s seconds from now."""
    return datetime.datetime.utcfromtimestamp(time.time() + offset_s).strftime(
        "%Y-%m-%dT%H:%M:%S+00:00"
    )


class TestCycleTimeByKind(unittest.TestCase):

    def _db(self, rows):
        m = MagicMock()
        m.select.return_value = rows
        return m

    def test_empty_returns_empty_dict(self):
        with patch.object(improvement_measure, "db", self._db([])):
            self.assertEqual(improvement_measure.cycle_time_by_kind(), {})

    def test_computes_avg_seconds_by_kind(self):
        rows = [
            {"kind": "build", "created_at": _ts(-3600), "updated_at": _ts(0)},
            {"kind": "build", "created_at": _ts(-7200), "updated_at": _ts(0)},
            {"kind": "bugfix", "created_at": _ts(-1800), "updated_at": _ts(0)},
        ]
        with patch.object(improvement_measure, "db", self._db(rows)):
            ct = improvement_measure.cycle_time_by_kind()

        self.assertAlmostEqual(ct["build"], 5400.0, delta=30)   # avg of 3600 + 7200
        self.assertAlmostEqual(ct["bugfix"], 1800.0, delta=30)

    def test_excludes_tasks_older_than_window(self):
        old_ts = datetime.datetime.utcfromtimestamp(time.time() - 31 * 86400).strftime(
            "%Y-%m-%dT%H:%M:%S+00:00"
        )
        rows = [
            {"kind": "build", "created_at": old_ts, "updated_at": _ts(0)},  # > 30 days old
            {"kind": "build", "created_at": _ts(-900), "updated_at": _ts(0)},  # 15 min ago
        ]
        with patch.object(improvement_measure, "db", self._db(rows)):
            ct = improvement_measure.cycle_time_by_kind()

        # Only the recent task should count (~900 s, not the 31-day one)
        self.assertIn("build", ct)
        self.assertLess(ct["build"], 4000)

    def test_handles_malformed_timestamps_gracefully(self):
        rows = [{"kind": "build", "created_at": "not-a-date", "updated_at": "also-bad"}]
        with patch.object(improvement_measure, "db", self._db(rows)):
            self.assertEqual(improvement_measure.cycle_time_by_kind(), {})

    def test_defaults_to_build_when_kind_missing(self):
        rows = [{"kind": None, "created_at": _ts(-600), "updated_at": _ts(0)}]
        with patch.object(improvement_measure, "db", self._db(rows)):
            ct = improvement_measure.cycle_time_by_kind()
        self.assertIn("build", ct)


class TestFirstTryYield(unittest.TestCase):

    def _db(self, rows):
        m = MagicMock()
        m.select.return_value = rows
        return m

    def test_empty_returns_none_overall(self):
        with patch.object(improvement_measure, "db", self._db([])):
            result = improvement_measure.first_try_yield()
        self.assertIsNone(result["overall"])

    def test_all_first_try_gives_1_0(self):
        rows = [
            {"model": "sonnet", "remediation_count": 0, "created_at": _ts(0)},
            {"model": "sonnet", "remediation_count": 0, "created_at": _ts(0)},
        ]
        with patch.object(improvement_measure, "db", self._db(rows)):
            result = improvement_measure.first_try_yield()
        self.assertEqual(result["overall"], 1.0)
        self.assertEqual(result["sonnet"], 1.0)

    def test_mixed_remediation_counts(self):
        rows = [
            {"model": "haiku", "remediation_count": 0, "created_at": _ts(0)},
            {"model": "haiku", "remediation_count": 2, "created_at": _ts(0)},
            {"model": "haiku", "remediation_count": 0, "created_at": _ts(0)},
            {"model": "haiku", "remediation_count": 1, "created_at": _ts(0)},
        ]
        with patch.object(improvement_measure, "db", self._db(rows)):
            result = improvement_measure.first_try_yield()
        self.assertEqual(result["overall"], 0.5)   # 2 / 4
        self.assertEqual(result["haiku"], 0.5)

    def test_null_remediation_count_treated_as_zero(self):
        rows = [{"model": "m", "remediation_count": None, "created_at": _ts(0)}]
        with patch.object(improvement_measure, "db", self._db(rows)):
            result = improvement_measure.first_try_yield()
        self.assertEqual(result["overall"], 1.0)

    def test_different_models_tracked_separately(self):
        rows = [
            {"model": "haiku", "remediation_count": 1, "created_at": _ts(0)},  # not first-try
            {"model": "sonnet", "remediation_count": 0, "created_at": _ts(0)},  # first-try
        ]
        with patch.object(improvement_measure, "db", self._db(rows)):
            result = improvement_measure.first_try_yield()
        self.assertEqual(result["haiku"], 0.0)
        self.assertEqual(result["sonnet"], 1.0)
        self.assertEqual(result["overall"], 0.5)


class TestAutoTune(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mktemp(suffix=".json")
        self._orig = improvement_measure.TUNING_STATE_PATH
        improvement_measure.TUNING_STATE_PATH = self.tmp

    def tearDown(self):
        improvement_measure.TUNING_STATE_PATH = self._orig
        if os.path.exists(self.tmp):
            os.unlink(self.tmp)

    def test_no_decision_when_metrics_are_healthy(self):
        decisions = improvement_measure.auto_tune(
            cycle_times={"build": 1800.0},   # << 4 h threshold
            fty={"overall": 0.85},           # >> 60 % threshold
        )
        self.assertEqual(decisions, [])

    def test_low_fty_triggers_model_upgrade_suggestion(self):
        decisions = improvement_measure.auto_tune(
            cycle_times={},
            fty={"overall": 0.40},   # below 60 %
        )
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0]["metric"], "first_try_yield")
        self.assertEqual(decisions[0]["action"], "suggest_stronger_model")

    def test_high_cycle_time_triggers_batching_suggestion(self):
        decisions = improvement_measure.auto_tune(
            cycle_times={"build": 3600 * 8},   # 8 h >> 4 h threshold
            fty={"overall": 0.90},
        )
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0]["metric"], "cycle_time")
        self.assertEqual(decisions[0]["action"], "suggest_batching")

    def test_cooldown_prevents_second_tune_in_same_window(self):
        # First run emits a decision
        d1 = improvement_measure.auto_tune(cycle_times={}, fty={"overall": 0.40})
        self.assertEqual(len(d1), 1)

        # Second run within the same cooldown window must emit nothing
        d2 = improvement_measure.auto_tune(cycle_times={}, fty={"overall": 0.40})
        self.assertEqual(d2, [], "cooldown must block a second tune within 24 h")

    def test_decisions_persisted_to_file(self):
        improvement_measure.auto_tune(cycle_times={}, fty={"overall": 0.40})
        self.assertTrue(os.path.exists(self.tmp), "tuning state file must be written")
        with open(self.tmp) as f:
            state = json.load(f)
        self.assertEqual(len(state["decisions"]), 1)
        self.assertGreater(state["last_tuned_at"], 0)

    def test_max_one_decision_per_run_guardrail(self):
        # Both FTY and every cycle-time kind are bad — must still cap at MAX_TUNE_PER_RUN
        decisions = improvement_measure.auto_tune(
            cycle_times={"build": 3600 * 8, "bugfix": 3600 * 10},
            fty={"overall": 0.30},
        )
        self.assertLessEqual(len(decisions), improvement_measure.MAX_TUNE_PER_RUN)

    def test_rollback_by_deleting_file_resets_state(self):
        improvement_measure.auto_tune(cycle_times={}, fty={"overall": 0.40})
        os.unlink(self.tmp)

        # After deletion, load_tuning_state returns fresh defaults
        state = improvement_measure.load_tuning_state()
        self.assertEqual(state["decisions"], [])
        self.assertEqual(state["last_tuned_at"], 0)

    def test_decisions_accumulate_across_cooldown_windows(self):
        # First window
        improvement_measure.auto_tune(cycle_times={}, fty={"overall": 0.40})

        # Manually push last_tuned_at back beyond cooldown to simulate next day
        state = improvement_measure.load_tuning_state()
        state["last_tuned_at"] = time.time() - improvement_measure.TUNE_COOLDOWN_S - 1
        improvement_measure.save_tuning_state(state)

        # Second window should add another decision
        improvement_measure.auto_tune(cycle_times={}, fty={"overall": 0.40})
        state2 = improvement_measure.load_tuning_state()
        self.assertEqual(len(state2["decisions"]), 2)


class TestTuningStatePersistence(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mktemp(suffix=".json")
        self._orig = improvement_measure.TUNING_STATE_PATH
        improvement_measure.TUNING_STATE_PATH = self.tmp

    def tearDown(self):
        improvement_measure.TUNING_STATE_PATH = self._orig
        if os.path.exists(self.tmp):
            os.unlink(self.tmp)

    def test_load_returns_defaults_when_file_missing(self):
        state = improvement_measure.load_tuning_state()
        self.assertIn("decisions", state)
        self.assertIn("last_tuned_at", state)
        self.assertIn("guardrails", state)
        self.assertEqual(state["decisions"], [])
        self.assertEqual(state["last_tuned_at"], 0)

    def test_load_returns_defaults_on_corrupt_json(self):
        with open(self.tmp, "w") as f:
            f.write("{not valid json")
        state = improvement_measure.load_tuning_state()
        self.assertEqual(state["decisions"], [])

    def test_save_and_reload_roundtrip(self):
        state = improvement_measure.load_tuning_state()
        state["decisions"].append({"action": "test", "ts": 123})
        improvement_measure.save_tuning_state(state)

        reloaded = improvement_measure.load_tuning_state()
        self.assertEqual(len(reloaded["decisions"]), 1)
        self.assertEqual(reloaded["decisions"][0]["action"], "test")

    def test_guardrails_preserved_across_saves(self):
        state = improvement_measure.load_tuning_state()
        self.assertIn("cooldown_s", state["guardrails"])
        improvement_measure.save_tuning_state(state)
        reloaded = improvement_measure.load_tuning_state()
        self.assertEqual(
            reloaded["guardrails"]["cooldown_s"],
            state["guardrails"]["cooldown_s"],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
