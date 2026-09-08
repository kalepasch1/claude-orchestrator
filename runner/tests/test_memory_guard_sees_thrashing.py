"""memory_guard watched a number that stayed high while the machine thrashed.

WHAT HAPPENED. On 2026-09-08 this host spent days in a memory crisis: 3.62 GB free of
48 GB, 44 GB of swap in use, 18,006,808 cumulative swapouts, and a 1-minute load average
of 55 with only 14 of 772 processes runnable -- the rest blocked on paging. Test verdicts
produced in that state were worthless: the same tests measured 601.38s loaded and 0.33s
quiet, and four of five "failures" from a full-suite run passed on a quiet box.

memory_guard existed the whole time, and it is good code -- it unloads the heaviest local
model, halves the throttle, reaps the oldest agent when critical, and durably lowers the
lane ceiling after a sustained streak. None of it ran. It gates on
memory_free_pct(), which parses macOS `memory_pressure`'s "System-wide memory free
percentage", and that number read 67% DURING the crisis. The warn threshold is 25%. The
guard was never reachable.

The percentage is not wrong, it answers the wrong question. macOS counts compressible and
reclaimable pages as free, so it stays high exactly when the machine is working hardest to
keep it high -- during that crisis the compressor held 5.04 GB representing 74.91 GB
uncompressed.

Eviction is what hurts, and eviction has its own counter. Ten consecutive 15-second
samples on this host while healthy:

    free_GB  swapins/s  swapouts/s  compressions/s  pressure%
       10.8          7           0               0        82
       10.9         32           0               0        83
       10.5          2           0               0        83
       ... (ten samples)
       11.5        863           0               0        83

swapouts/s was 0 in every one, while swapins ranged 2-863 and the pressure percentage sat
at 81-83 -- statistically indistinguishable from the 67% it reported mid-crisis. Swapins
were considered and rejected: they fire during ordinary recovery when a process touches a
page evicted hours ago. Swapins measure the past. Swapouts measure now.
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import resource_medic

#: The reading memory_pressure actually gave during the crisis, and the healthy one.
CRISIS_FREE_PCT = 67
HEALTHY_FREE_PCT = 83
STARVED_FREE_PCT = 8
#: Eviction rates either side of the threshold.
QUIET_SWAPOUTS_PPS = 0
THRASHING_SWAPOUTS_PPS = 5000
ONE_SECOND = 1.0
EXPECTED_NONE = 0


class TheOldSignalCouldNotSeeIt(unittest.TestCase):

    def test_the_crisis_reading_is_above_the_warn_threshold(self):
        """Stated as a test so nobody re-tunes the percentage and thinks it is fixed.

        67% against a 25% warn threshold. No tightening of this number reaches the
        failure without firing constantly on a healthy box at 81-83%.
        """
        self.assertGreater(CRISIS_FREE_PCT, resource_medic.PRESSURE_WARN)
        self.assertLess(abs(CRISIS_FREE_PCT - HEALTHY_FREE_PCT), HEALTHY_FREE_PCT)


class TheSwapoutRate(unittest.TestCase):

    def test_the_first_call_has_nothing_to_compare_against(self):
        state = {}
        with patch.object(resource_medic, "_swapouts_total", return_value=1000):
            self.assertIsNone(resource_medic.swapout_rate_pps(state))

    def test_a_second_call_reports_pages_per_second(self):
        state = {}
        with patch.object(resource_medic, "_swapouts_total", return_value=1000), \
             patch.object(resource_medic.time, "time", return_value=100.0):
            resource_medic.swapout_rate_pps(state)
        with patch.object(resource_medic, "_swapouts_total", return_value=1500), \
             patch.object(resource_medic.time, "time", return_value=100.0 + ONE_SECOND):
            self.assertAlmostEqual(resource_medic.swapout_rate_pps(state), 500.0)

    def test_a_counter_that_went_backwards_is_ignored(self):
        """A reboot resets it. A negative rate must never be read as calm."""
        state = {}
        with patch.object(resource_medic, "_swapouts_total", return_value=9000), \
             patch.object(resource_medic.time, "time", return_value=100.0):
            resource_medic.swapout_rate_pps(state)
        with patch.object(resource_medic, "_swapouts_total", return_value=5), \
             patch.object(resource_medic.time, "time", return_value=100.0 + ONE_SECOND):
            self.assertIsNone(resource_medic.swapout_rate_pps(state))

    def test_an_unreadable_counter_yields_none_rather_than_zero(self):
        """None means "no answer". Zero would mean "calm", and would be a lie."""
        state = {}
        with patch.object(resource_medic, "_swapouts_total", return_value=None):
            self.assertIsNone(resource_medic.swapout_rate_pps(state))


class TheGuardActsOnEitherSignal(unittest.TestCase):

    def _run_guard(self, free_pct, swapout_pps):
        state = {}
        actions = []
        with patch.object(resource_medic, "memory_free_pct", return_value=free_pct), \
             patch.object(resource_medic, "swapout_rate_pps", return_value=swapout_pps), \
             patch.object(resource_medic, "_unload_heaviest_model", return_value=None), \
             patch.object(resource_medic, "_reap_oldest_agent", return_value=None), \
             patch.object(resource_medic, "journal",
                          side_effect=lambda *a, **k: actions.append(a)):
            resource_medic.memory_guard(state)
        return state, actions

    def test_the_crisis_now_trips_the_guard_on_swapouts_alone(self):
        """67% free, which the old signal called healthy, plus real eviction."""
        state, _actions = self._run_guard(CRISIS_FREE_PCT, THRASHING_SWAPOUTS_PPS)
        self.assertGreater(state.get("mem_warn_streak", 0), EXPECTED_NONE,
                           "thrashing at 67% free still did not reach the guard")

    def test_it_says_which_signal_fired_and_that_the_percentage_missed_it(self):
        _state, actions = self._run_guard(CRISIS_FREE_PCT, THRASHING_SWAPOUTS_PPS)
        thrash_rows = [row for row in actions if "thrashing" in row]
        self.assertTrue(thrash_rows, "no journal row named the swapout trigger")

    def test_outright_starvation_still_trips_it_without_any_eviction(self):
        """The original signal must keep working; this adds a signal, it replaces none."""
        state, _actions = self._run_guard(STARVED_FREE_PCT, QUIET_SWAPOUTS_PPS)
        self.assertGreater(state.get("mem_warn_streak", 0), EXPECTED_NONE)

    def test_a_healthy_box_is_left_alone(self):
        state, actions = self._run_guard(HEALTHY_FREE_PCT, QUIET_SWAPOUTS_PPS)
        self.assertEqual(state.get("mem_warn_streak", 0), EXPECTED_NONE)
        self.assertEqual(len(actions), EXPECTED_NONE, "a quiet fleet must never be paged")

    def test_an_unreadable_swapout_counter_falls_back_to_the_percentage(self):
        """Off macOS, or where vm_stat fails, behaviour is exactly as it was before."""
        state, _actions = self._run_guard(HEALTHY_FREE_PCT, None)
        self.assertEqual(state.get("mem_warn_streak", 0), EXPECTED_NONE)
        state, _actions = self._run_guard(STARVED_FREE_PCT, None)
        self.assertGreater(state.get("mem_warn_streak", 0), EXPECTED_NONE)

    def test_neither_signal_readable_does_nothing_rather_than_guessing(self):
        state, actions = self._run_guard(None, None)
        self.assertEqual(len(actions), EXPECTED_NONE)


if __name__ == "__main__":
    unittest.main()
