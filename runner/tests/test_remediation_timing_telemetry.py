#!/usr/bin/env python3
"""auto_remediate._record_timing — remediation pass duration as a real time series.

run() already measured its own duration but only printed it, so remediation
cadence was unobservable across passes. These tests pin the contract: the
timings reach metric_history, the slow-pass flag fires on the threshold, and
nothing in the telemetry path can raise into the remediation loop.
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import auto_remediate  # noqa: E402


class RecordTimingTests(unittest.TestCase):
    def _capture(self, *args, **kwargs):
        recorded = {}

        def _fake(metrics):
            recorded.update(metrics)
            return {"metrics": metrics}

        fake_module = mock.Mock()
        fake_module.record_snapshot.side_effect = _fake
        with mock.patch.dict(sys.modules, {"metric_history": fake_module}):
            out = auto_remediate._record_timing(*args, **kwargs)
        return out, recorded, fake_module

    def test_core_durations_are_recorded(self):
        _, rec, mod = self._capture(12.5, 9.0, 3, {"fetch_blocked": 1.25}, [])
        self.assertEqual(mod.record_snapshot.call_count, 1)
        self.assertEqual(rec["remediation_pass_seconds"], 12.5)
        self.assertEqual(rec["remediation_task_loop_seconds"], 9.0)
        self.assertEqual(rec["remediation_tasks_examined"], 3)

    def test_phases_are_flattened_with_a_prefix(self):
        _, rec, _ = self._capture(5.0, 4.0, 1, {"task_loop": 4.0, "fetch_blocked": 0.5}, [])
        self.assertEqual(rec["remediation_phase_task_loop_seconds"], 4.0)
        self.assertEqual(rec["remediation_phase_fetch_blocked_seconds"], 0.5)

    def test_seconds_per_task_is_derived(self):
        _, rec, _ = self._capture(10.0, 9.0, 3, {}, [])
        self.assertEqual(rec["remediation_seconds_per_task"], 3.0)

    def test_zero_tasks_omits_the_ratio_rather_than_dividing(self):
        _, rec, _ = self._capture(1.0, 0.0, 0, {}, [])
        self.assertNotIn("remediation_seconds_per_task", rec)
        self.assertEqual(rec["remediation_tasks_examined"], 0)

    def test_slowest_task_is_recorded(self):
        slowest = [{"slug": "a", "elapsed": 7.5}, {"slug": "b", "elapsed": 2.0}]
        _, rec, _ = self._capture(9.0, 9.0, 2, {}, slowest)
        self.assertEqual(rec["remediation_slowest_task_seconds"], 7.5)

    def test_no_slowest_task_is_not_an_error(self):
        _, rec, _ = self._capture(1.0, 1.0, 0, {}, [])
        self.assertNotIn("remediation_slowest_task_seconds", rec)


class SlowPassFlagTests(unittest.TestCase):
    def _flag(self, total):
        recorded = {}
        fake = mock.Mock()
        fake.record_snapshot.side_effect = lambda m: recorded.update(m)
        with mock.patch.dict(sys.modules, {"metric_history": fake}):
            auto_remediate._record_timing(total, total, 1, {}, [])
        return recorded.get("remediation_slow_pass")

    def test_fast_pass_is_not_flagged(self):
        self.assertEqual(self._flag(auto_remediate.SLOW_PASS_SECONDS - 1), 0)

    def test_slow_pass_is_flagged(self):
        self.assertEqual(self._flag(auto_remediate.SLOW_PASS_SECONDS + 1), 1)

    def test_threshold_itself_is_not_slow(self):
        self.assertEqual(self._flag(auto_remediate.SLOW_PASS_SECONDS), 0)

    def test_threshold_is_a_positive_number(self):
        self.assertIsInstance(auto_remediate.SLOW_PASS_SECONDS, float)
        self.assertGreater(auto_remediate.SLOW_PASS_SECONDS, 0)


class FailSoftTests(unittest.TestCase):
    """Telemetry is never allowed to raise into the remediation loop."""

    def test_recorder_that_raises_is_swallowed(self):
        fake = mock.Mock()
        fake.record_snapshot.side_effect = RuntimeError("disk full")
        with mock.patch.dict(sys.modules, {"metric_history": fake}):
            self.assertEqual(auto_remediate._record_timing(1.0, 1.0, 1, {}, []), {})

    def test_unimportable_metric_history_is_swallowed(self):
        with mock.patch.dict(sys.modules, {"metric_history": None}):
            with mock.patch("builtins.__import__", side_effect=ImportError("nope")):
                self.assertEqual(auto_remediate._record_timing(1.0, 1.0, 1, {}, []), {})

    def test_garbage_durations_do_not_raise(self):
        fake = mock.Mock()
        with mock.patch.dict(sys.modules, {"metric_history": fake}):
            for bad in ("x", None, object()):
                self.assertEqual(auto_remediate._record_timing(bad, 1.0, 1, {}, []), {})

    def test_unusable_phase_values_are_skipped_not_fatal(self):
        recorded = {}
        fake = mock.Mock()
        fake.record_snapshot.side_effect = lambda m: recorded.update(m)
        with mock.patch.dict(sys.modules, {"metric_history": fake}):
            auto_remediate._record_timing(
                1.0, 1.0, 1, {"good": 2.0, "bad": "not-a-number"}, [])
        self.assertEqual(recorded["remediation_phase_good_seconds"], 2.0)
        self.assertNotIn("remediation_phase_bad_seconds", recorded)

    def test_malformed_slowest_entry_is_skipped(self):
        recorded = {}
        fake = mock.Mock()
        fake.record_snapshot.side_effect = lambda m: recorded.update(m)
        with mock.patch.dict(sys.modules, {"metric_history": fake}):
            auto_remediate._record_timing(1.0, 1.0, 1, {}, [{"slug": "a"}])
        self.assertNotIn("remediation_slowest_task_seconds", recorded)
        self.assertIn("remediation_pass_seconds", recorded)

    def test_none_phases_and_none_slowest(self):
        recorded = {}
        fake = mock.Mock()
        fake.record_snapshot.side_effect = lambda m: recorded.update(m)
        with mock.patch.dict(sys.modules, {"metric_history": fake}):
            auto_remediate._record_timing(1.0, 1.0, 1, None, None)
        self.assertEqual(recorded["remediation_pass_seconds"], 1.0)


if __name__ == "__main__":
    unittest.main()
