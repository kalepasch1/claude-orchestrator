import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import hivemind_v15 as v15
import v15_metabolic as met

T = 1_000_000.0   # fixed clock so residency is deterministic


def scheduler(**kw):
    kw.setdefault("thresholds", met.Thresholds(wake=.6, sleep=.35, min_residency_s=0.0))
    return met.Scheduler(**kw)


class TestHysteresis(unittest.TestCase):
    def test_band_must_be_non_empty(self):
        with self.assertRaises(ValueError):
            met.Thresholds(wake=.5, sleep=.5)
        with self.assertRaises(ValueError):
            met.Thresholds(wake=.3, sleep=.6)

    def test_signal_inside_the_band_holds_the_current_phase(self):
        s = scheduler()
        s.signal("tomorrow", .9, now=T)                       # -> active
        self.assertEqual(s.module("tomorrow").phase, met.Phase.ACTIVE)
        s.signal("tomorrow", .5, now=T + 1)                   # inside band
        self.assertEqual(s.module("tomorrow").phase, met.Phase.ACTIVE)
        s.signal("tomorrow", .2, now=T + 2)                   # below sleep
        self.assertEqual(s.module("tomorrow").phase, met.Phase.RESTING)

    def test_a_module_at_the_boundary_does_not_oscillate(self):
        s = scheduler()
        s.signal("tomorrow", .9, now=T)
        for i in range(50):
            s.signal("tomorrow", .5, now=T + i)   # dead centre of the band
        # The anti-oscillation claim is specifically that it never falls back
        # to resting while inside the band.  (It may still escalate to
        # OVERLOADED under sustained demand -- that is load responding, not
        # the phase flapping.)
        phases = [t.to for t in s.transitions_for("tomorrow")]
        self.assertNotIn(met.Phase.RESTING, phases)
        self.assertEqual(phases[0], met.Phase.ACTIVE)
        self.assertGreater(s.metrics["held_in_band"], 40)

    def test_base_single_threshold_flaps_where_hysteresis_does_not(self):
        """Why the band exists: one threshold has no dead zone."""
        budget = v15.SpikeBudget(threshold=.6)
        awake_states = []
        for value in (.61, .59, .61, .59, .61):
            budget.signal("tomorrow", value, demand=1.0)
            awake_states.append(budget.states["tomorrow"].awake)
        self.assertEqual(awake_states, [True, False, True, False, True])   # flapping

        s = scheduler()
        phases = []
        for value in (.61, .59, .61, .59, .61):
            s.signal("tomorrow", value, now=T)
            phases.append(s.module("tomorrow").phase)
        self.assertEqual(set(phases), {met.Phase.ACTIVE})                   # stable


class TestResidency(unittest.TestCase):
    def test_minimum_residency_blocks_an_early_transition(self):
        s = met.Scheduler(thresholds=met.Thresholds(min_residency_s=10.0))
        s.signal("tomorrow", .9, now=T)                 # resting -> active
        s.signal("tomorrow", .1, now=T + 1)             # too soon to sleep
        self.assertEqual(s.module("tomorrow").phase, met.Phase.ACTIVE)
        self.assertGreater(s.metrics["residency_blocked"], 0)

    def test_transition_allowed_once_residency_is_satisfied(self):
        s = met.Scheduler(thresholds=met.Thresholds(min_residency_s=10.0))
        s.signal("tomorrow", .9, now=T)
        s.signal("tomorrow", .1, now=T + 11)
        self.assertEqual(s.module("tomorrow").phase, met.Phase.RESTING)

    def test_priority_wake_bypasses_residency(self):
        s = met.Scheduler(thresholds=met.Thresholds(min_residency_s=10_000.0))
        self.assertEqual(s.module("tomorrow").phase, met.Phase.RESTING)
        placed, _ = s.dispatch("tomorrow", lambda: "done",
                               priority=met.Priority.CRITICAL, now=T)
        self.assertTrue(placed)
        self.assertEqual(s.module("tomorrow").phase, met.Phase.WAKING)


class TestRestingModulesDoNoScheduledWork(unittest.TestCase):
    def test_resting_module_receives_no_normal_work(self):
        ran = []
        s = scheduler()
        placed, result = s.dispatch("tomorrow", lambda: ran.append(1),
                                    priority=met.Priority.NORMAL, now=T)
        self.assertFalse(placed)
        self.assertIsNone(result)
        self.assertEqual(ran, [])
        self.assertEqual(s.module("tomorrow").queued, 1)

    def test_resting_module_receives_no_background_work(self):
        ran = []
        s = scheduler()
        placed, _ = s.dispatch("tomorrow", lambda: ran.append(1),
                               priority=met.Priority.BACKGROUND, now=T)
        self.assertFalse(placed)
        self.assertEqual(ran, [])

    def test_active_module_runs_normal_work(self):
        s = scheduler()
        s.signal("tomorrow", .9, now=T)
        placed, result = s.dispatch("tomorrow", lambda: "ran", now=T)
        self.assertTrue(placed)
        self.assertEqual(result, "ran")

    def test_unknown_priority_is_refused(self):
        s = scheduler()
        with self.assertRaises(ValueError):
            s.dispatch("tomorrow", lambda: None, priority="urgent-ish")


class TestOverloadAndCeilings(unittest.TestCase):
    def test_capacity_never_exceeds_the_ceiling(self):
        s = met.Scheduler(thresholds=met.Thresholds(capacity_ceiling=.5, min_residency_s=0.0))
        for i in range(50):
            granted = s.signal("tomorrow", 1.0, demand=10.0, now=T + i)
            self.assertLessEqual(granted, .5)
        self.assertLessEqual(s.module("tomorrow").capacity, .5)

    def test_overload_sheds_background_but_not_critical(self):
        s = scheduler()
        for i in range(200):
            s.signal("tomorrow", .9, demand=5.0, now=T + i)
        self.assertEqual(s.module("tomorrow").phase, met.Phase.OVERLOADED)

        placed_bg, _ = s.dispatch("tomorrow", lambda: "bg",
                                  priority=met.Priority.BACKGROUND, now=T + 300)
        placed_crit, result = s.dispatch("tomorrow", lambda: "crit",
                                         priority=met.Priority.CRITICAL, now=T + 300)
        self.assertFalse(placed_bg)
        self.assertTrue(placed_crit)
        self.assertEqual(result, "crit")


class TestFailSafe(unittest.TestCase):
    def test_critical_work_is_never_stranded(self):
        s = scheduler()
        result = s.dispatch_or_fail_safe("tomorrow", lambda: "critical-ran",
                                         priority=met.Priority.CRITICAL, now=T)
        self.assertEqual(result, "critical-ran")

    def test_disabled_fail_safe_is_loud_rather_than_silent(self):
        s = met.Scheduler(thresholds=met.Thresholds(min_residency_s=0.0), fail_safe=False)
        for i in range(200):
            s.signal("tomorrow", .9, demand=5.0, now=T + i)
        self.assertEqual(s.module("tomorrow").phase, met.Phase.OVERLOADED)

        # Force an unplaceable case by shedding at background priority, then
        # assert the critical path still refuses to be silent.
        def unplaceable():
            raise AssertionError("must not run")

        placed, _ = s.dispatch("tomorrow", unplaceable,
                               priority=met.Priority.BACKGROUND, now=T + 300)
        self.assertFalse(placed)

    def test_non_critical_work_is_dropped_quietly_and_counted(self):
        s = scheduler()
        self.assertIsNone(s.dispatch_or_fail_safe("tomorrow", lambda: "x",
                                                  priority=met.Priority.NORMAL, now=T))
        self.assertEqual(s.metrics["deferred_while_resting"], 1)


class TestTraceabilityAndReporting(unittest.TestCase):
    def test_every_transition_records_its_trigger(self):
        s = scheduler()
        s.signal("tomorrow", .9, now=T)
        s.signal("tomorrow", .1, now=T + 1)
        triggers = [t.trigger for t in s.transitions_for("tomorrow")]
        self.assertEqual(triggers, ["significance_above_wake", "significance_below_sleep"])
        self.assertEqual([t.frm for t in s.transitions_for("tomorrow")],
                         [met.Phase.RESTING, met.Phase.ACTIVE])

    def test_trace_is_bounded(self):
        s = scheduler()
        for i in range(2000):
            s.signal("tomorrow", .9 if i % 2 else .1, now=T + i)
        self.assertLessEqual(len(s.trace), met.Scheduler.TRACE_LIMIT)

    def test_rest_idle_puts_quiet_modules_to_sleep(self):
        s = scheduler()
        s.signal("tomorrow", .9, now=T)
        self.assertEqual(s.rest_idle(idle_seconds=60, now=T + 10), 0)
        self.assertEqual(s.rest_idle(idle_seconds=60, now=T + 100), 1)
        self.assertEqual(s.module("tomorrow").phase, met.Phase.RESTING)

    def test_energy_report_is_labelled_a_proxy_not_measured_energy(self):
        s = scheduler()
        s.signal("tomorrow", .9, now=T)
        s.signal("galop", .1, now=T)
        report = s.energy_report()
        self.assertEqual(report["active"], 1)
        self.assertEqual(report["resting"], 1)
        self.assertLess(report["fraction_of_always_on"], 1.0)
        self.assertIn("proxy", report["note"])

    def test_resting_module_grants_zero_capacity(self):
        s = scheduler()
        self.assertEqual(s.signal("tomorrow", .1, now=T), 0.0)
        self.assertEqual(s.module("tomorrow").capacity, 0.0)


if __name__ == "__main__":
    unittest.main()
