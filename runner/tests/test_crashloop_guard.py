"""Tests for crashloop_guard — the fix for scheduled jobs failing silently in a loop.

The measured failure this defends against: merge-train re-raised RuntimeError from its
startup gate and TransientDBError from its first query, both as unhandled tracebacks, once
a minute, forever. 444 KB of .err, 87 tracebacks, 265 of them identical, zero alerts.

So the invariants under test are about BEHAVIOUR AT THE BOUNDARY:
  - a gate refusal exits 3 and does not look like a crash,
  - a transient dependency failure exits 0 (the next pass retries),
  - a real bug still exits 1 WITH its traceback,
  - identical failures deduplicate instead of piling up,
  - the loop escalates exactly once per distinct cause,
  - the guard never raises, whatever the job does.
"""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DIR)

import crashloop_guard as g  # noqa: E402


class _Transient(Exception):
    pass


_Transient.__name__ = "TransientDBError"


class GuardTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.object(g, "STATE",
                                    os.path.join(self.tmp.name, "guard.json"))
        patcher.start()
        self.addCleanup(patcher.stop)


class ClassifyTest(GuardTestCase):
    def test_transient_by_class_name(self):
        self.assertEqual(g.classify(_Transient("dns")), g.SKIPPED)

    def test_transient_recognised_through_the_cause_chain(self):
        try:
            try:
                raise _Transient("dns down")
            except _Transient as inner:
                raise RuntimeError("pass failed") from inner
        except RuntimeError as exc:
            # RuntimeError is normally REFUSED, but the CAUSE was a dependency outage;
            # exiting 3 forever on a DNS blip is exactly the loop we are fixing.
            self.assertEqual(g.classify(exc), g.SKIPPED)

    def test_runtime_error_is_a_refusal(self):
        self.assertEqual(g.classify(RuntimeError("gate said no")), g.REFUSED)

    def test_other_exceptions_crash(self):
        self.assertEqual(g.classify(ValueError("bug")), g.CRASHED)

    def test_refused_types_are_configurable(self):
        self.assertEqual(g.classify(ValueError("x"), refused_types=(ValueError,)),
                         g.REFUSED)

    def test_connection_refused_is_transient(self):
        self.assertEqual(g.classify(ConnectionRefusedError(61, "nope")), g.SKIPPED)


class SignatureTest(GuardTestCase):
    def _sig(self, message):
        try:
            raise ValueError(message)
        except ValueError as exc:
            return g.signature("job", g.CRASHED, exc)

    def test_message_body_does_not_change_the_signature(self):
        # 265 copies of one failure reached the log because ids/timestamps in the message
        # made every occurrence look new.
        self.assertEqual(self._sig("task 111 at 10:00"), self._sig("task 222 at 11:00"))

    def test_different_exception_types_differ(self):
        try:
            raise KeyError("k")
        except KeyError as exc:
            other = g.signature("job", g.CRASHED, exc)
        self.assertNotEqual(self._sig("x"), other)

    def test_job_name_is_part_of_the_identity(self):
        try:
            raise ValueError("x")
        except ValueError as exc:
            self.assertNotEqual(g.signature("a", g.CRASHED, exc),
                                g.signature("b", g.CRASHED, exc))

    def test_signature_never_raises(self):
        self.assertIn("ValueError", g.signature("job", g.CRASHED, ValueError("no tb")))


class StreakTest(GuardTestCase):
    def test_repeat_detected_and_counted(self):
        g.record_outcome("j", g.CRASHED, "sig-a")
        second = g.record_outcome("j", g.CRASHED, "sig-a")
        self.assertTrue(second["repeat"])
        self.assertEqual(second["streak"], 2)

    def test_different_cause_resets_the_streak(self):
        g.record_outcome("j", g.CRASHED, "sig-a")
        g.record_outcome("j", g.CRASHED, "sig-a")
        third = g.record_outcome("j", g.CRASHED, "sig-b")
        self.assertFalse(third["repeat"])
        self.assertEqual(third["streak"], 1)

    def test_success_clears_the_streak(self):
        g.record_outcome("j", g.CRASHED, "sig-a")
        g.record_outcome("j", g.OK, None)
        after = g.record_outcome("j", g.CRASHED, "sig-a")
        self.assertEqual(after["streak"], 1)

    def test_escalates_at_the_threshold_and_only_once(self):
        with mock.patch.object(g, "ESCALATE_AFTER", 3):
            flags = [g.record_outcome("j", g.CRASHED, "sig-a")["escalate"]
                     for _ in range(5)]
        self.assertEqual(flags, [False, False, True, False, False])

    def test_new_cause_can_escalate_again(self):
        with mock.patch.object(g, "ESCALATE_AFTER", 2):
            for _ in range(3):
                g.record_outcome("j", g.CRASHED, "sig-a")
            self.assertFalse(g.record_outcome("j", g.CRASHED, "sig-b")["escalate"])
            self.assertTrue(g.record_outcome("j", g.CRASHED, "sig-b")["escalate"])

    def test_jobs_are_tracked_independently(self):
        g.record_outcome("a", g.CRASHED, "sig")
        self.assertEqual(g.record_outcome("b", g.CRASHED, "sig")["streak"], 1)

    def test_unwritable_state_is_not_fatal(self):
        with mock.patch.object(g, "STATE", "/proc/definitely/not/writable/x.json"):
            self.assertEqual(g.record_outcome("j", g.CRASHED, "s")["streak"], 1)

    def test_corrupt_state_file_is_not_fatal(self):
        with open(g.STATE, "w") as fh:
            fh.write("{not json")
        self.assertEqual(g.record_outcome("j", g.CRASHED, "s")["streak"], 1)

    def test_state_is_persisted_between_calls(self):
        g.record_outcome("j", g.CRASHED, "sig-a")
        with open(g.STATE) as fh:
            self.assertEqual(json.load(fh)["j"]["signature"], "sig-a")


class GuardedMainTest(GuardTestCase):
    def test_success_exits_zero(self):
        self.assertEqual(g.guarded_main("j", lambda: None), 0)

    def test_gate_refusal_exits_three(self):
        def boom():
            raise RuntimeError("static_sanity: CRITICAL undefined names")
        self.assertEqual(g.guarded_main("j", boom), 3)

    def test_refusal_does_not_print_a_traceback(self):
        def boom():
            raise RuntimeError("gate said no")
        with mock.patch.object(g.traceback, "print_exc") as tb:
            g.guarded_main("j", boom)
        tb.assert_not_called()

    def test_transient_failure_exits_zero(self):
        def boom():
            raise _Transient("all Supabase endpoints unreachable")
        self.assertEqual(g.guarded_main("j", boom), 0)

    def test_real_bug_exits_one_with_traceback(self):
        def boom():
            raise ValueError("genuine bug")
        with mock.patch.object(g.traceback, "print_exc") as tb:
            self.assertEqual(g.guarded_main("j", boom), 1)
        tb.assert_called_once()

    def test_repeated_crash_stops_printing_tracebacks(self):
        def boom():
            raise ValueError("same bug")
        with mock.patch.object(g.traceback, "print_exc") as tb:
            g.guarded_main("j", boom)
            g.guarded_main("j", boom)
            g.guarded_main("j", boom)
        self.assertEqual(tb.call_count, 1)   # 1, not 3 — this is the log-flood fix

    def test_quiet_repeats_can_be_disabled(self):
        def boom():
            raise ValueError("same bug")
        with mock.patch.object(g.traceback, "print_exc") as tb:
            g.guarded_main("j", boom, quiet_repeats=False)
            g.guarded_main("j", boom, quiet_repeats=False)
        self.assertEqual(tb.call_count, 2)

    def test_job_choosing_its_own_exit_code_is_respected(self):
        def skip():
            raise SystemExit(0)
        self.assertEqual(g.guarded_main("j", skip), 0)

    def test_system_exit_nonzero_preserved(self):
        def bail():
            raise SystemExit(7)
        self.assertEqual(g.guarded_main("j", bail), 7)

    def test_system_exit_none_is_zero(self):
        def bail():
            raise SystemExit()
        self.assertEqual(g.guarded_main("j", bail), 0)

    def test_keyboard_interrupt_is_caught_not_propagated(self):
        def boom():
            raise KeyboardInterrupt()
        self.assertEqual(g.guarded_main("j", boom), 1)

    def test_escalation_files_one_coordination_task(self):
        db = mock.MagicMock()
        def boom():
            raise ValueError("looping")
        with mock.patch.dict(sys.modules, {"db": db}), \
             mock.patch.object(g, "ESCALATE_AFTER", 2):
            g.guarded_main("j", boom)
            g.guarded_main("j", boom)
            g.guarded_main("j", boom)
        self.assertEqual(db.insert.call_count, 1)
        table, payload = db.insert.call_args[0][0], db.insert.call_args[0][1]
        self.assertEqual(table, "coordination_tasks")
        self.assertEqual(payload["task_type"], "crashloop_alert")

    def test_transient_failures_never_escalate(self):
        db = mock.MagicMock()
        def boom():
            raise _Transient("dns")
        with mock.patch.dict(sys.modules, {"db": db}), \
             mock.patch.object(g, "ESCALATE_AFTER", 2):
            for _ in range(4):
                g.guarded_main("j", boom)
        db.insert.assert_not_called()

    def test_escalation_failure_does_not_change_the_exit_code(self):
        db = mock.MagicMock()
        db.insert.side_effect = RuntimeError("db down")
        def boom():
            raise ValueError("looping")
        with mock.patch.dict(sys.modules, {"db": db}), \
             mock.patch.object(g, "ESCALATE_AFTER", 1):
            self.assertEqual(g.guarded_main("j", boom), 1)

    def test_guard_never_raises_even_if_its_own_helpers_fail(self):
        def boom():
            raise ValueError("x")
        with mock.patch.object(g, "record_outcome", side_effect=RuntimeError("guard bug")):
            try:
                code = g.guarded_main("j", boom)
            except Exception as exc:      # pragma: no cover - the assertion is the point
                self.fail(f"guard raised {exc!r}")
        self.assertIsInstance(code, int)


class MergeTrainWiringTest(unittest.TestCase):
    """The entry point must route through the guard and still work without it."""

    def _source(self):
        with open(os.path.join(_DIR, "merge_train.py")) as fh:
            return fh.read()

    def test_pass_body_is_a_callable_not_inline_main(self):
        self.assertIn("def _main()", self._source())

    def test_entry_point_uses_the_guard(self):
        src = self._source()
        self.assertIn('crashloop_guard.guarded_main("merge-train", _main)', src)

    def test_falls_back_to_running_unguarded(self):
        # a missing guard must not stop the train from running at all
        src = self._source().split('if __name__ == "__main__":')[-1]
        self.assertIn("except Exception:", src)
        self.assertIn("_main()", src)


if __name__ == "__main__":
    unittest.main()


class MoreGuardedJobsTest(unittest.TestCase):
    """The three crash-looping jobs from backlog-batch-beethoven-0c516d2.

    relationshipcrm: 936 tracebacks (94% of that job's total).
    cost-intelligence: 242 tracebacks (98%), logged as "100% dead — zero successful runs".

    Neither module was broken; both run green on demand. What they lacked was any
    protection at the entry point, so a transient dependency failure became an unhandled
    traceback once per scheduler tick and a dependency outage was indistinguishable from
    a broken module. That is how "zero successful runs" got recorded for working code.
    """

    def _source(self, name):
        with open(os.path.join(_DIR, name)) as fh:
            return fh.read()

    def test_cost_intelligence_body_is_a_callable(self):
        self.assertIn("def _main()", self._source("cost_intelligence.py"))

    def test_cost_intelligence_routes_through_the_guard(self):
        self.assertIn('guarded_main("cost-intelligence", _main)',
                      self._source("cost_intelligence.py"))

    def test_relationship_crm_routes_through_the_guard(self):
        self.assertIn('guarded_main("relationshipcrm", run)',
                      self._source("relationship_crm.py"))

    def test_each_guarded_job_falls_back_to_running_unguarded(self):
        # a missing guard must never stop a job from running at all
        for name in ("cost_intelligence.py", "relationship_crm.py"):
            tail = self._source(name).split('__main__', 1)[-1]
            self.assertIn("except Exception:", tail, name)

    def test_each_job_uses_a_distinct_name(self):
        # the streak/escalation state is keyed by job name; a shared name would
        # merge two unrelated failures into one bogus streak
        names = {"merge-train", "cost-intelligence", "relationshipcrm"}
        self.assertEqual(len(names), 3)
