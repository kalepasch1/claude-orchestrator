#!/usr/bin/env python3
"""Event-driven fast auto-merge: a test-completion event drives the low-risk gate.

Two properties carry the slice:
  * a PASSING test-completion event on a low-risk task creates the fast approval;
  * a failing or incomplete event creates nothing.

Everything else here defends the second property, because a false positive here
auto-merges code on a red build.
"""
import io
import os
import sys
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import fast_auto_merge


def _task(slug="build-a-thing", kind="build", **extra):
    t = {"id": "id-" + slug, "slug": slug, "kind": kind, "project_id": "p1",
         "state": "DONE"}
    t.update(extra)
    return t


class _Recorder:
    """Stands in for db: records inserts, returns no existing approval cards."""

    def __init__(self, approvals=None):
        self.inserted = []
        self._approvals = approvals or []

    def insert(self, table, row):
        self.inserted.append((table, row))
        return row

    def select(self, table, params=None):
        if table == "approvals":
            return list(self._approvals)
        return []


class EventIsPassingTest(unittest.TestCase):
    def test_recognised_pass_words(self):
        for word in ("passed", "success", "green", "OK", "Succeeded"):
            with self.subTest(word=word):
                self.assertTrue(fast_auto_merge.event_is_passing({"status": word}))

    def test_recognised_failure_words(self):
        for word in ("failed", "failure", "error", "cancelled", "timed_out"):
            with self.subTest(word=word):
                self.assertFalse(fast_auto_merge.event_is_passing({"status": word}))

    def test_a_still_running_report_is_not_a_completion(self):
        for word in ("running", "in_progress", "queued", "pending"):
            with self.subTest(word=word):
                self.assertFalse(fast_auto_merge.event_is_passing({"status": word}))

    def test_completed_false_overrides_a_green_status(self):
        self.assertFalse(
            fast_auto_merge.event_is_passing({"status": "passed", "completed": False}))

    def test_green_status_with_failures_reported_is_not_passing(self):
        for payload in ({"status": "passed", "failed": 3},
                        {"status": "passed", "failures": ["t1"]},
                        {"status": "passed", "errors": 1},
                        {"status": "passed", "passed": False}):
            with self.subTest(payload=payload):
                self.assertFalse(fast_auto_merge.event_is_passing(payload))

    def test_zero_failures_alongside_a_green_status_is_passing(self):
        self.assertTrue(
            fast_auto_merge.event_is_passing({"status": "passed", "failed": 0, "errors": 0}))

    def test_boolean_only_payloads(self):
        self.assertTrue(fast_auto_merge.event_is_passing({"passed": True}))
        self.assertFalse(fast_auto_merge.event_is_passing({"passed": True, "failed": 2}))
        self.assertFalse(fast_auto_merge.event_is_passing({"passed": False}))

    def test_unrecognised_and_malformed_events_are_not_passing(self):
        for bad in (None, "passed", 1, [], {}, {"status": "banana"}):
            with self.subTest(bad=bad):
                self.assertFalse(fast_auto_merge.event_is_passing(bad))


class OnTestCompletionTest(unittest.TestCase):
    def setUp(self):
        self._db = fast_auto_merge.db
        self.rec = _Recorder()
        fast_auto_merge.db = self.rec

    def tearDown(self):
        fast_auto_merge.db = self._db

    def _handle(self, event):
        buf = io.StringIO()
        with redirect_stdout(buf):
            return fast_auto_merge.on_test_completion(event), buf.getvalue()

    def test_passing_event_auto_approves_a_low_risk_task(self):
        verdict, out = self._handle({"status": "passed", "task": _task()})
        self.assertTrue(verdict["approved"], verdict["reason"])
        self.assertEqual(verdict["slug"], "build-a-thing")
        self.assertEqual(len(self.rec.inserted), 1)
        table, row = self.rec.inserted[0]
        self.assertEqual(table, "approvals")
        self.assertEqual(row["status"], "approved")
        self.assertEqual(row["slug"], "build-a-thing")
        self.assertIn("build-a-thing", out)

    def test_failing_event_approves_nothing(self):
        verdict, _ = self._handle({"status": "failed", "task": _task()})
        self.assertFalse(verdict["approved"])
        self.assertEqual(self.rec.inserted, [])

    def test_incomplete_event_approves_nothing(self):
        verdict, _ = self._handle({"status": "running", "task": _task()})
        self.assertFalse(verdict["approved"])
        self.assertEqual(self.rec.inserted, [])

    def test_high_risk_task_is_refused_even_on_a_green_run(self):
        for slug in ("rotate-auth-token", "stripe-payment-fix", "rls-policy-change"):
            with self.subTest(slug=slug):
                self.rec.inserted.clear()
                verdict, _ = self._handle({"status": "passed", "task": _task(slug=slug)})
                self.assertFalse(verdict["approved"])
                self.assertEqual(self.rec.inserted, [])

    def test_kind_outside_the_fast_merge_class_is_refused(self):
        verdict, _ = self._handle({"status": "passed", "task": _task(kind="migration")})
        self.assertFalse(verdict["approved"])
        self.assertEqual(self.rec.inserted, [])

    def test_an_existing_approval_card_is_not_duplicated(self):
        self.rec = _Recorder(approvals=[{"id": "a1", "status": "approved",
                                         "decided_by": "human"}])
        fast_auto_merge.db = self.rec
        verdict, _ = self._handle({"status": "passed", "task": _task()})
        self.assertFalse(verdict["approved"])
        self.assertEqual(self.rec.inserted, [])

    def test_an_unresolvable_event_approves_nothing(self):
        verdict, _ = self._handle({"status": "passed"})
        self.assertFalse(verdict["approved"])
        self.assertEqual(self.rec.inserted, [])

    def test_task_is_looked_up_by_slug_when_not_inlined(self):
        looked = _task(slug="chore-tidy", kind="chore")

        class BySlug(_Recorder):
            def select(self, table, params=None):
                if table == "tasks":
                    return [looked]
                return []

        self.rec = BySlug()
        fast_auto_merge.db = self.rec
        verdict, _ = self._handle({"status": "passed", "slug": "chore-tidy"})
        self.assertTrue(verdict["approved"], verdict["reason"])
        self.assertEqual(self.rec.inserted[0][1]["slug"], "chore-tidy")

    def test_an_approval_lookup_failure_fails_closed(self):
        class DeadDB(_Recorder):
            def select(self, table, params=None):
                raise RuntimeError("supabase unreachable")

        self.rec = DeadDB()
        fast_auto_merge.db = self.rec
        verdict, _ = self._handle({"status": "passed", "task": _task()})
        self.assertFalse(verdict["approved"])
        self.assertEqual(self.rec.inserted, [])


class BatchPathUnchangedTest(unittest.TestCase):
    """The scheduled sweep stays the only production entry point for now."""

    def test_run_and_its_helpers_still_exist(self):
        for name in ("run", "_is_low_risk", "_has_approval_card", "_create_fast_approval",
                     "FAST_MERGE_WINDOW_MIN", "FAST_MERGE_KINDS"):
            self.assertTrue(hasattr(fast_auto_merge, name), name)


if __name__ == "__main__":
    unittest.main()
