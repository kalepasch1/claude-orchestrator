#!/usr/bin/env python3
"""Low-EV early exit: refuse before enqueue, and never charge the PID for the refusal.

Two properties carry the whole change and each has its own block below:
  * a task with EV under the threshold is never enqueued, and says so;
  * a refused task reports counts_toward_pid=False, so a task that never entered the
    queue can never contribute to the queue-velocity PID's integral. That is the windup
    the sibling fix-pid-integral-windup slice exists to prevent, removed at the source.
"""
import io
import os
import sys
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import ev_scheduler


def _task(slug="build-a-thing", kind="build", **extra):
    t = {"id": "id-" + slug, "slug": slug, "kind": kind}
    t.update(extra)
    return t


class TaskEvTest(unittest.TestCase):
    def test_reads_the_common_field_names(self):
        for field in ("ev", "expected_value", "score", "value"):
            with self.subTest(field=field):
                self.assertEqual(ev_scheduler.task_ev(_task(**{field: 2.5})), 2.5)

    def test_numeric_strings_are_accepted(self):
        self.assertEqual(ev_scheduler.task_ev(_task(ev="1.75")), 1.75)

    def test_unknown_ev_is_none_not_zero(self):
        # None means "no producer supplied one"; 0.0 would be a measured verdict.
        self.assertIsNone(ev_scheduler.task_ev(_task()))

    def test_bools_are_not_evs(self):
        self.assertIsNone(ev_scheduler.task_ev(_task(ev=True)))
        self.assertIsNone(ev_scheduler.task_ev(_task(ev=False)))

    def test_nan_inf_and_garbage_are_not_measurements(self):
        for bad in (float("nan"), float("inf"), float("-inf"), "abc", [], {}, None):
            with self.subTest(bad=bad):
                self.assertIsNone(ev_scheduler.task_ev(_task(ev=bad)))

    def test_non_dict_input_does_not_raise(self):
        for bad in (None, "x", 5, []):
            self.assertIsNone(ev_scheduler.task_ev(bad))

    def test_zero_is_a_real_measurement(self):
        self.assertEqual(ev_scheduler.task_ev(_task(ev=0)), 0.0)


class ShouldEnqueueTest(unittest.TestCase):
    def test_below_threshold_is_refused(self):
        v = ev_scheduler.should_enqueue(_task(ev=-1.0), threshold=0.0)
        self.assertFalse(v["enqueue"])
        self.assertIn("below threshold", v["reason"])

    def test_at_threshold_is_enqueued(self):
        # Strict `<`: exactly at the bar is in, not out.
        self.assertTrue(ev_scheduler.should_enqueue(_task(ev=0.0), threshold=0.0)["enqueue"])

    def test_above_threshold_is_enqueued(self):
        self.assertTrue(ev_scheduler.should_enqueue(_task(ev=5.0), threshold=0.0)["enqueue"])

    def test_a_log_message_is_emitted_on_refusal(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            ev_scheduler.should_enqueue(_task(slug="low-value-chore", ev=-2.0), threshold=0.0)
        out = buf.getvalue()
        self.assertIn("early exit", out)
        self.assertIn("low-value-chore", out)
        self.assertIn("not enqueuing", out)

    def test_no_log_noise_when_the_task_is_accepted(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            ev_scheduler.should_enqueue(_task(ev=5.0), threshold=0.0)
        self.assertEqual(buf.getvalue(), "")

    def test_unknown_ev_is_never_refused(self):
        # Refusing unmeasured work would silently drop every task from a producer that
        # has not adopted the EV field.
        v = ev_scheduler.should_enqueue(_task(), threshold=100.0)
        self.assertTrue(v["enqueue"])
        self.assertIn("EV unknown", v["reason"])

    def test_default_threshold_refuses_only_negative_ev(self):
        self.assertTrue(ev_scheduler.should_enqueue(_task(ev=0.0))["enqueue"])
        self.assertTrue(ev_scheduler.should_enqueue(_task(ev=0.001))["enqueue"])
        self.assertFalse(ev_scheduler.should_enqueue(_task(ev=-0.001))["enqueue"])

    def test_default_bar_is_lower_than_the_existing_park_threshold(self):
        # Refusing is stronger than parking, so it must be HARDER to trigger. A task at
        # 0.005 is park-eligible (< ZERO_EV) but must still be enqueued.
        self.assertLess(ev_scheduler.LOW_EV_THRESHOLD, ev_scheduler.ZERO_EV)
        self.assertTrue(ev_scheduler.should_enqueue(_task(ev=0.005))["enqueue"])

    def test_an_explicit_ev_argument_wins_over_the_task_field(self):
        v = ev_scheduler.should_enqueue(_task(ev=99.0), ev=-1.0, threshold=0.0)
        self.assertFalse(v["enqueue"])

    def test_verdict_carries_the_evidence(self):
        v = ev_scheduler.should_enqueue(_task(ev=-1.0), threshold=0.0)
        for key in ("enqueue", "reason", "ev", "threshold", "counts_toward_pid"):
            self.assertIn(key, v)
        self.assertEqual(v["ev"], -1.0)
        self.assertEqual(v["threshold"], 0.0)

    def test_a_broken_gate_fails_open(self):
        # A gate that raises must never drop work.
        original = ev_scheduler.task_ev
        ev_scheduler.task_ev = lambda t: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            v = ev_scheduler.should_enqueue(_task(), threshold=0.0)
        finally:
            ev_scheduler.task_ev = original
        self.assertTrue(v["enqueue"])
        self.assertIn("gate error", v["reason"])


class PidAccountingTest(unittest.TestCase):
    """A task that never entered the queue must never be integrated by the PID."""

    def test_refused_tasks_are_excluded_from_pid_accounting(self):
        v = ev_scheduler.should_enqueue(_task(ev=-5.0), threshold=0.0)
        self.assertFalse(v["enqueue"])
        self.assertFalse(v["counts_toward_pid"])

    def test_enqueued_tasks_are_included(self):
        v = ev_scheduler.should_enqueue(_task(ev=5.0), threshold=0.0)
        self.assertTrue(v["counts_toward_pid"])

    def test_unknown_ev_tasks_are_included(self):
        self.assertTrue(ev_scheduler.should_enqueue(_task())["counts_toward_pid"])

    def test_exempt_tasks_are_included(self):
        v = ev_scheduler.should_enqueue(_task(slug="recover-missing-branch-x", ev=-9.0))
        self.assertTrue(v["counts_toward_pid"])

    def test_counts_toward_pid_is_false_exactly_when_refused(self):
        for ev, expected in ((-1.0, False), (0.0, True), (1.0, True)):
            with self.subTest(ev=ev):
                v = ev_scheduler.should_enqueue(_task(ev=ev), threshold=0.0)
                self.assertEqual(v["counts_toward_pid"], v["enqueue"])
                self.assertEqual(v["counts_toward_pid"], expected)


class ExemptionTest(unittest.TestCase):
    """Recovery and evidence lanes exist for work whose value is not EV-expressible."""

    def test_exempt_slug_prefixes_are_never_refused(self):
        for slug in ("recovery-fix-001", "recover-missing-branch-abc",
                     "breach-remediation-2026", "canary-claude-27", "qafix-tomorrow-1",
                     "relfix-x", "buildfix-y", "deployfix-z", "toolchain-repair-1",
                     "rework-a"):
            with self.subTest(slug=slug):
                v = ev_scheduler.should_enqueue(_task(slug=slug, ev=-100.0), threshold=0.0)
                self.assertTrue(v["enqueue"], slug)
                self.assertIn("exempt", v["reason"])

    def test_exempt_kinds_are_never_refused(self):
        for kind in ("recovery", "canary", "toolchain-repair"):
            with self.subTest(kind=kind):
                v = ev_scheduler.should_enqueue(_task(kind=kind, ev=-100.0), threshold=0.0)
                self.assertTrue(v["enqueue"], kind)

    def test_ordinary_build_work_is_not_exempt(self):
        self.assertFalse(
            ev_scheduler.should_enqueue(_task(kind="build", ev=-100.0), threshold=0.0)["enqueue"])


class KillSwitchTest(unittest.TestCase):
    def setUp(self):
        self._flag = ev_scheduler.LOW_EV_EARLY_EXIT

    def tearDown(self):
        ev_scheduler.LOW_EV_EARLY_EXIT = self._flag

    def test_disabling_the_gate_enqueues_everything(self):
        ev_scheduler.LOW_EV_EARLY_EXIT = False
        v = ev_scheduler.should_enqueue(_task(ev=-1000.0), threshold=0.0)
        self.assertTrue(v["enqueue"])
        self.assertIn("disabled", v["reason"])
        self.assertTrue(v["counts_toward_pid"])


class FilterEnqueueableTest(unittest.TestCase):
    def test_splits_keep_from_skipped(self):
        tasks = [_task(slug="good", ev=5.0), _task(slug="bad", ev=-5.0),
                 _task(slug="unknown"), _task(slug="canary-x", ev=-5.0)]
        buf = io.StringIO()
        with redirect_stdout(buf):
            keep, skipped = ev_scheduler.filter_enqueueable(tasks, threshold=0.0)
        self.assertEqual([t["slug"] for t in keep], ["good", "unknown", "canary-x"])
        self.assertEqual([t["slug"] for t, _ in skipped], ["bad"])
        self.assertFalse(skipped[0][1]["counts_toward_pid"])

    def test_empty_and_none_inputs(self):
        self.assertEqual(ev_scheduler.filter_enqueueable([]), ([], []))
        self.assertEqual(ev_scheduler.filter_enqueueable(None), ([], []))

    def test_every_task_lands_on_exactly_one_side(self):
        tasks = [_task(slug=f"t{i}", ev=(i - 3)) for i in range(8)]
        buf = io.StringIO()
        with redirect_stdout(buf):
            keep, skipped = ev_scheduler.filter_enqueueable(tasks, threshold=0.0)
        self.assertEqual(len(keep) + len(skipped), len(tasks))
        self.assertEqual(set(t["slug"] for t in keep)
                         & set(t["slug"] for t, _ in skipped), set())


class ShelveLowEvTest(unittest.TestCase):
    """Already-queued rows the gate would have refused get marked, never deleted."""

    def setUp(self):
        self._db = ev_scheduler.db
        self.updates = []

        class FakeDB:
            def update(_s, table, match, patch):
                self.updates.append((table, match, patch))

        ev_scheduler.db = FakeDB()

    def tearDown(self):
        ev_scheduler.db = self._db

    def test_marks_only_the_refused_rows(self):
        scored = [(5.0, _task(slug="good")), (-1.0, _task(slug="bad")),
                  (-2.0, _task(slug="canary-x", kind="canary"))]
        buf = io.StringIO()
        with redirect_stdout(buf):
            n = ev_scheduler.shelve_low_ev(scored)
        self.assertEqual(n, 1)
        self.assertEqual(self.updates[0][1], {"id": "id-bad"})
        self.assertEqual(self.updates[0][2]["note"], ev_scheduler.LOW_EV_SKIP_NOTE)

    def test_state_is_never_changed_so_nothing_is_destroyed(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            ev_scheduler.shelve_low_ev([(-1.0, _task(slug="bad"))])
        self.assertNotIn("state", self.updates[0][2])

    def test_respects_the_park_cap(self):
        scored = [(-1.0, _task(slug=f"bad{i}")) for i in range(ev_scheduler.PARK_CAP + 5)]
        buf = io.StringIO()
        with redirect_stdout(buf):
            n = ev_scheduler.shelve_low_ev(scored)
        self.assertEqual(n, ev_scheduler.PARK_CAP)

    def test_a_failing_update_does_not_raise(self):
        class DeadDB:
            def update(self, *a, **k):
                raise RuntimeError("supabase unreachable")

        ev_scheduler.db = DeadDB()
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(ev_scheduler.shelve_low_ev([(-1.0, _task(slug="bad"))]), 0)


class BackwardCompatibilityTest(unittest.TestCase):
    def test_existing_symbols_are_untouched(self):
        for name in ("score", "rank_queue", "apply_ranking", "park_zero_ev", "run",
                     "ZERO_EV", "PARK_NOTE", "PARK_CAP", "TOP_N"):
            self.assertTrue(hasattr(ev_scheduler, name), name)

    def test_park_threshold_and_note_are_unchanged(self):
        self.assertEqual(ev_scheduler.ZERO_EV, 0.01)
        self.assertIn("ev-low-priority", ev_scheduler.PARK_NOTE)

    def test_the_new_note_is_distinct_from_the_park_note(self):
        self.assertNotEqual(ev_scheduler.LOW_EV_SKIP_NOTE, ev_scheduler.PARK_NOTE)


if __name__ == "__main__":
    unittest.main()
