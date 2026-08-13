"""A wedged periodic job must be interrupted, not merely counted.

The 'governor' wedge was invisible because a job that never returns holds its singleton
lock, every later invocation skips, and a skip exits 0. The skip counter reports that
after the fact; only a hard timeout ends it. These tests pin the ending.
"""
import os
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import periodic  # noqa: E402


class TimeoutBudgetTest(unittest.TestCase):
    def test_default_budget_is_used_when_nothing_is_set(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ORCH_PERIODIC_JOB_TIMEOUT_GOVERNOR", None)
            self.assertEqual(periodic._job_timeout("governor"), periodic._JOB_TIMEOUT_S)

    def test_per_job_override_wins(self):
        with patch.dict(os.environ, {"ORCH_PERIODIC_JOB_TIMEOUT_GOVERNOR": "7"}):
            self.assertEqual(periodic._job_timeout("governor"), 7)

    def test_hyphens_in_a_job_name_map_to_underscores(self):
        with patch.dict(os.environ, {"ORCH_PERIODIC_JOB_TIMEOUT_STUCK_REAPER": "11"}):
            self.assertEqual(periodic._job_timeout("stuck-reaper"), 11)

    def test_garbage_config_falls_back_instead_of_raising(self):
        """Bad config must not take the scheduler down — that would be worse than no cap."""
        with patch.dict(os.environ, {"ORCH_PERIODIC_JOB_TIMEOUT_GOVERNOR": "not-a-number"}):
            self.assertEqual(periodic._job_timeout("governor"), periodic._JOB_TIMEOUT_S)


class TimeLimitTest(unittest.TestCase):
    def test_a_hanging_body_is_actually_interrupted(self):
        started = time.time()
        with self.assertRaises(periodic.JobTimeout):
            with periodic._time_limit(1, "governor"):
                time.sleep(30)
        self.assertLess(time.time() - started, 10, "the sleep was not interrupted")

    def test_a_fast_body_is_untouched(self):
        with periodic._time_limit(30, "governor"):
            result = 1 + 1
        self.assertEqual(result, 2)

    def test_zero_disables_the_cap(self):
        """0 must mean 'no cap', not 'expire immediately'."""
        with periodic._time_limit(0, "governor"):
            result = 1 + 1
        self.assertEqual(result, 2)

    def test_the_alarm_does_not_leak_to_the_next_caller(self):
        """A timer left armed would fire inside unrelated later work."""
        with self.assertRaises(periodic.JobTimeout):
            with periodic._time_limit(1, "governor"):
                time.sleep(30)
        with periodic._time_limit(30, "other"):
            time.sleep(1.5)  # would raise if the previous 1s timer were still armed


class InvokeJobTest(unittest.TestCase):
    def test_a_wedging_job_returns_a_timeout_result_rather_than_hanging(self):
        def _hang():
            time.sleep(30)

        started = time.time()
        with patch.dict(periodic.JOBS, {"governor": _hang}), \
             patch.dict(os.environ, {"ORCH_PERIODIC_JOB_TIMEOUT_GOVERNOR": "1"}):
            result = periodic._invoke_job("governor")
        self.assertLess(time.time() - started, 10)
        self.assertTrue(result.get("timeout"))
        self.assertEqual(result.get("job"), "governor")

    def test_a_healthy_job_still_returns_its_own_value(self):
        with patch.dict(periodic.JOBS, {"governor": lambda: {"ok": True}}), \
             patch.dict(os.environ, {"ORCH_PERIODIC_JOB_TIMEOUT_GOVERNOR": "30"}):
            self.assertEqual(periodic._invoke_job("governor"), {"ok": True})


if __name__ == "__main__":
    unittest.main()
