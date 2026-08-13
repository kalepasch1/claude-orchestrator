#!/usr/bin/env python3
"""The low-risk fast-merge gate is triggered by test-completion events, not by a batch clock.

Acceptance for this slice:
  * no production code or config invokes the gate from a batch/hourly schedule;
  * a test-completion event does trigger the approval path;
  * the old batch sweep is inert unless an operator explicitly re-enables it.
"""
import os
import re
import sys
import unittest
from unittest.mock import patch

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RUNNER)

os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-key")

import fast_auto_merge as fam  # noqa: E402

LOW_RISK_TASK = {"id": "t1", "slug": "cleanup-dead-imports", "kind": "cleanup",
                 "project_id": "p1", "state": "DONE"}
RISKY_TASK = {"id": "t2", "slug": "rotate-auth-token", "kind": "cleanup",
              "project_id": "p1", "state": "DONE"}


class BatchSweepIsRetiredTest(unittest.TestCase):

    def test_batch_sweep_is_off_by_default(self):
        env = {k: v for k, v in os.environ.items() if k != "ORCH_FAST_MERGE_BATCH_SWEEP"}
        with patch.dict(os.environ, env, clear=True):
            self.assertFalse(fam.batch_sweep_enabled())

    def test_run_creates_no_approvals_by_default(self):
        inserts, selects = [], []
        env = {k: v for k, v in os.environ.items() if k != "ORCH_FAST_MERGE_BATCH_SWEEP"}
        with patch.dict(os.environ, env, clear=True), \
             patch.object(fam.db, "select", side_effect=lambda *a, **k: selects.append(a) or []), \
             patch.object(fam.db, "insert", side_effect=lambda *a, **k: inserts.append(a)):
            self.assertEqual(fam.run(), 0)
        self.assertEqual(inserts, [], "the retired batch path must not create approvals")
        self.assertEqual(selects, [], "the retired batch path must not even query")

    def test_run_still_works_as_an_explicit_manual_fallback(self):
        with patch.dict(os.environ, {"ORCH_FAST_MERGE_BATCH_SWEEP": "1"}):
            self.assertTrue(fam.batch_sweep_enabled())

    def test_no_schedule_entry_invokes_this_module(self):
        """The acceptance criterion: nothing periodic may still call the gate."""
        offenders = []
        for name in ("runner.py", "periodic.py"):
            path = os.path.join(RUNNER, name)
            if not os.path.isfile(path):
                continue
            with open(path, encoding="utf-8") as f:
                for i, line in enumerate(f, 1):
                    if "fast_auto_merge" not in line:
                        continue
                    # A scheduled entry names the module inside a schedule/JOBS table.
                    if re.search(r'"(interval|daily|weekly|hourly)"', line) or \
                            re.search(r'fast_auto_merge(\.py)?"\s*[,:]\s*("|\d)', line):
                        offenders.append(f"{name}:{i}: {line.strip()}")
        self.assertEqual(offenders, [], f"gate still scheduled: {offenders}")

    def test_module_docstring_no_longer_describes_a_batch_trigger(self):
        doc = fam.__doc__ or ""
        self.assertIn("event-driven", doc)
        self.assertIn("ORCH_FAST_MERGE_BATCH_SWEEP", doc)


class EventTriggersTheGateTest(unittest.TestCase):

    def _dispatch(self, task, passed, *, existing_cards=(), env=None):
        inserts = []
        base = dict(os.environ)
        base.pop("ORCH_FAST_MERGE_EVENT_DISPATCH", None)
        base.update(env or {})
        with patch.dict(os.environ, base, clear=True), \
             patch.object(fam.db, "select", return_value=list(existing_cards)), \
             patch.object(fam.db, "insert", side_effect=lambda t, r: inserts.append(r)):
            verdict = fam.dispatch_test_completion(task, passed)
        return verdict, inserts

    def test_passing_low_risk_task_is_approved_immediately(self):
        verdict, inserts = self._dispatch(LOW_RISK_TASK, True)
        self.assertTrue(verdict["approved"], verdict)
        self.assertEqual(verdict["slug"], "cleanup-dead-imports")
        self.assertEqual(len(inserts), 1)
        self.assertEqual(inserts[0]["status"], "approved")
        self.assertEqual(inserts[0]["decided_by"], "fast-auto-merge:auto-approved")

    def test_failing_tests_do_not_approve(self):
        verdict, inserts = self._dispatch(LOW_RISK_TASK, False)
        self.assertFalse(verdict["approved"])
        self.assertEqual(inserts, [])

    def test_risky_slug_is_not_fast_merged_even_when_green(self):
        verdict, inserts = self._dispatch(RISKY_TASK, True)
        self.assertFalse(verdict["approved"])
        self.assertIn("low-risk", verdict["reason"])
        self.assertEqual(inserts, [])

    def test_existing_approval_card_is_not_duplicated(self):
        verdict, inserts = self._dispatch(
            LOW_RISK_TASK, True, existing_cards=[{"id": "c1", "status": "approved"}])
        self.assertFalse(verdict["approved"])
        self.assertEqual(inserts, [])

    def test_dispatch_can_be_disabled(self):
        verdict, inserts = self._dispatch(LOW_RISK_TASK, True,
                                          env={"ORCH_FAST_MERGE_EVENT_DISPATCH": "0"})
        self.assertIsNone(verdict)
        self.assertEqual(inserts, [])

    def test_dispatch_never_raises_into_the_caller(self):
        """record() is on every task's hot path; the gate must not be able to break it."""
        with patch.object(fam, "on_test_completion", side_effect=RuntimeError("boom")):
            self.assertIsNone(fam.dispatch_test_completion(LOW_RISK_TASK, True))


class StartupWiringTest(unittest.TestCase):

    def test_runner_record_dispatches_the_event(self):
        with open(os.path.join(RUNNER, "runner.py"), encoding="utf-8") as f:
            source = f.read()
        self.assertIn("fast_auto_merge.dispatch_test_completion", source,
                      "runner.record() must be the live trigger for the gate")

    def test_subscribe_registers_on_a_dispatcher(self):
        seen = []

        class Bus:
            def subscribe(self, kind, handler):
                seen.append((kind, handler))

        self.assertTrue(fam.subscribe(Bus()))
        self.assertEqual(seen[0][0], fam.EVENT_KIND)
        self.assertIs(seen[0][1], fam.on_test_completion)

    def test_subscribe_accepts_an_on_style_bus(self):
        seen = []

        class Bus:
            def on(self, kind, handler):
                seen.append(kind)

        self.assertTrue(fam.subscribe(Bus()))
        self.assertEqual(seen, [fam.EVENT_KIND])

    def test_subscribe_is_a_no_op_without_a_dispatcher(self):
        self.assertFalse(fam.subscribe(None))
        self.assertFalse(fam.subscribe(object()))


if __name__ == "__main__":
    unittest.main()
