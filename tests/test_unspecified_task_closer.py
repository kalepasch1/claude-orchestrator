#!/usr/bin/env python3
"""Tests for unspecified_task_closer — the sweep that stops garbage prompts recycling.

The two halves of the predicate are tested separately and together, because the whole
risk of this module is closing something salvageable.
"""
import os
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "runner"))

import unspecified_task_closer as closer  # noqa: E402

GARBAGE = """## ORCHESTRATION PIPELINE CONTRACT
- source: native-claim
## END ORCHESTRATION PIPELINE CONTRACT

# Original improvement request
PATCH TEMPLATE 6dc6d47e3003
Intent: 07062319 07071626 8b92d078e856 acceptance adapt agentic already alter analysis
Acceptance: preserve existing behavior, make the smallest mergeable diff, run build/tests.
"""

REAL = ("In runner/canary.py, add a process_response(response_text) function that returns "
        "0 when the canary marker is present and 1 when it is absent, and have main() "
        "return its result. Add a test module covering both branches.")


def _task(prompt=GARBAGE, attempt=9, slug="noise-slug", task_id="abc"):
    return {"id": task_id, "slug": slug, "prompt": prompt, "attempt": attempt,
            "state": "QUEUED", "note": ""}


class PredicateTests(unittest.TestCase):
    def test_an_unspecified_and_stale_task_closes(self):
        close, reason = closer.should_close(_task())
        self.assertTrue(close)
        self.assertIn("attempt 9", reason)
        self.assertTrue(reason.startswith(closer.CLOSE_NOTE_PREFIX))

    def test_an_unspecified_but_fresh_task_is_left_alone(self):
        """A repair pass may still write a real prompt; closing now would discard it."""
        self.assertEqual(closer.should_close(_task(attempt=0))[0], False)
        self.assertEqual(closer.should_close(_task(attempt=1))[0], False)

    def test_a_real_prompt_never_closes_however_stale(self):
        """The dangerous case. At attempt=99 preflight_check answers "exhausted 99
        attempts without success" — a verdict about the task's HISTORY. Acting on it
        here would quarantine a well-specified request because its bug was hard."""
        self.assertEqual(closer.should_close(_task(prompt=REAL, attempt=99))[0], False)

    def test_attempt_exhaustion_is_not_a_spec_quality_verdict(self):
        self.assertFalse(closer._is_spec_quality_reason(
            "preflight: exhausted 99 attempts without success (hard ceiling 12)"))
        self.assertTrue(closer._is_spec_quality_reason(
            "preflight: PATCH TEMPLATE or garbage prompt (auto-quarantine)"))
        self.assertTrue(closer._is_spec_quality_reason(
            "preflight: metadata-only prompt with no implementation spec"))

    def test_the_attempt_floor_is_configurable(self):
        self.assertTrue(closer.should_close(_task(attempt=2), min_attempts=2)[0])
        self.assertFalse(closer.should_close(_task(attempt=2), min_attempts=5)[0])

    def test_a_missing_or_bad_attempt_reads_as_never_ran(self):
        for value in (None, "", "lots", [], {}):
            task = _task(attempt=value)
            self.assertFalse(closer.should_close(task)[0], repr(value))


class FailSoftTests(unittest.TestCase):
    def test_non_dict_input_is_not_closed(self):
        for bad in (None, 42, "task", [], object()):
            self.assertEqual(closer.unspecified_reason(bad), "")
            self.assertEqual(closer.close_patch(bad), {})

    def test_an_unavailable_classifier_closes_nothing(self):
        """Fail-soft must mean 'leave it alone', never 'close it'."""
        with mock.patch.dict(sys.modules, {"preflight_filter": None}):
            self.assertEqual(closer.unspecified_reason(_task()), "")

    def test_a_raising_classifier_closes_nothing(self):
        broken = types.ModuleType("preflight_filter")

        def boom(*a, **k):
            raise RuntimeError("classifier down")

        broken.preflight_check = boom
        with mock.patch.dict(sys.modules, {"preflight_filter": broken}):
            self.assertEqual(closer.unspecified_reason(_task()), "")


class PatchShapeTests(unittest.TestCase):
    def test_the_patch_quarantines_rather_than_deletes(self):
        patch = closer.close_patch(_task())
        self.assertEqual(patch["state"], "QUARANTINED")
        self.assertIsNone(patch["account"])
        self.assertIn("note", patch)
        self.assertNotIn("prompt", patch, "the prompt is evidence; never overwrite it")

    def test_a_task_that_should_stay_gets_an_empty_patch(self):
        self.assertEqual(closer.close_patch(_task(prompt=REAL)), {})


class PlanTests(unittest.TestCase):
    def test_plan_selects_only_the_closable(self):
        tasks = [_task(slug="a"), _task(slug="b", prompt=REAL), _task(slug="c", attempt=0)]
        planned = closer.plan(tasks)
        self.assertEqual([t["slug"] for t, _ in planned], ["a"])

    def test_plan_on_empty_or_none_is_empty(self):
        self.assertEqual(closer.plan([]), [])
        self.assertEqual(closer.plan(None), [])


class SweepTests(unittest.TestCase):
    def _db(self, rows, updates):
        module = types.ModuleType("db")
        module.select = lambda *a, **k: rows
        module.update = lambda table, match, patch: updates.append((table, match, patch))
        return module

    def test_sweep_closes_the_stale_garbage_and_leaves_the_rest(self):
        rows = [_task(slug="a", task_id="1"),
                _task(slug="b", task_id="2", prompt=REAL),
                _task(slug="c", task_id="3", attempt=0)]
        updates = []
        with mock.patch.dict(sys.modules, {"db": self._db(rows, updates)}):
            out = closer.sweep()
        self.assertEqual(out["examined"], 3)
        self.assertEqual(out["closed"], 1)
        self.assertEqual(out["slugs"], ["a"])
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0][1], {"id": "eq.1"})
        self.assertEqual(updates[0][2]["state"], "QUARANTINED")

    def test_dry_run_reports_without_writing(self):
        updates = []
        with mock.patch.dict(sys.modules, {"db": self._db([_task()], updates)}):
            out = closer.sweep(dry_run=True)
        self.assertEqual(out["closed"], 1)
        self.assertTrue(out["dry_run"])
        self.assertEqual(updates, [])

    def test_a_db_outage_reports_zero_instead_of_raising(self):
        module = types.ModuleType("db")

        def boom(*a, **k):
            raise RuntimeError("supabase down")

        module.select = boom
        module.update = boom
        with mock.patch.dict(sys.modules, {"db": module}):
            out = closer.sweep()
        self.assertEqual(out, {"examined": 0, "closed": 0, "dry_run": False, "slugs": []})

    def test_one_rejected_update_does_not_stop_the_sweep(self):
        rows = [_task(slug="a", task_id="1"), _task(slug="b", task_id="2")]
        module = types.ModuleType("db")
        module.select = lambda *a, **k: rows
        calls = {"n": 0}

        def flaky(table, match, patch):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("rejected")

        module.update = flaky
        with mock.patch.dict(sys.modules, {"db": module}):
            out = closer.sweep()
        self.assertEqual(out["closed"], 1)
        self.assertEqual(out["slugs"], ["b"])

    def test_the_query_carries_a_deterministic_order(self):
        """Without one, PostgREST's page is not reproducible between runs."""
        captured = {}
        module = types.ModuleType("db")

        def select(table, params=None):
            captured.update(params or {})
            return []

        module.select = select
        module.update = lambda *a, **k: None
        with mock.patch.dict(sys.modules, {"db": module}):
            closer.sweep(limit=5)
        self.assertIn("order", captured)
        self.assertEqual(captured["limit"], "5")
        self.assertEqual(captured["state"], "eq.QUEUED")

    def test_a_zero_limit_is_a_no_op(self):
        out = closer.sweep(limit=0)
        self.assertEqual(out["examined"], 0)
        self.assertEqual(out["closed"], 0)


if __name__ == "__main__":
    unittest.main()
