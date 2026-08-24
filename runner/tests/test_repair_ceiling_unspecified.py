#!/usr/bin/env python3
"""Terminate unimplementable tasks at the FIRST repair, not the eighth.

"repair-ceiling: rework after 8 repairs without reaching a completed state" is the largest
named quarantine cause on this fleet (30 rows in 7 days; next is branch_lost at 15). The
ceiling itself is right — it is what stopped tasks reaching remediation_count 28 — but a
task whose prompt is a bare "PATCH TEMPLATE <hex>" stub burns eight full repair cycles to
reach a conclusion available at the first one.

These tests pin both halves: the short-circuit fires for an unimplementable prompt, and it
does NOT fire for a well-specified task that is merely failing on a hard bug.
"""
import os
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import agentic_repair as ar  # noqa: E402

GARBAGE = """## ORCHESTRATION PIPELINE CONTRACT
- source: native-claim
## END ORCHESTRATION PIPELINE CONTRACT

# Original improvement request
PATCH TEMPLATE 6dc6d47e3003
Intent: 07062319 07071626 8b92d078e856 acceptance adapt agentic already alter analysis
Acceptance: preserve existing behavior, make the smallest mergeable diff, run build/tests.
"""

REAL = ("In runner/canary.py add process_response(response_text) returning 0 when the "
        "canary marker is present and 1 when it is absent, and have main() return it. "
        "Add a test module covering both branches.")


def _task(prompt=GARBAGE, attempt=3, rc=1, note="boom", slug="noise-slug"):
    return {"id": "t1", "slug": slug, "prompt": prompt, "attempt": attempt,
            "remediation_count": rc, "note": note, "log_tail": "Traceback: boom"}


class IsUnspecifiedTests(unittest.TestCase):
    def test_a_patch_template_stub_is_unspecified(self):
        self.assertTrue(ar.is_unspecified(_task()))

    def test_a_real_prompt_is_not_unspecified(self):
        self.assertFalse(ar.is_unspecified(_task(prompt=REAL)))

    def test_a_real_prompt_stays_specified_however_many_attempts(self):
        """Attempt-exhaustion is a verdict about HISTORY; it must not park real work."""
        self.assertFalse(ar.is_unspecified(_task(prompt=REAL, attempt=99)))

    def test_a_row_without_a_prompt_column_is_not_judged(self):
        """A sweep selecting a narrow column set must not park a task it cannot see."""
        self.assertFalse(ar.is_unspecified({"id": "t", "slug": "s", "attempt": 5}))

    def test_bad_input_is_not_unspecified(self):
        for bad in (None, 42, "task", [], object()):
            self.assertFalse(ar.is_unspecified(bad))

    def test_an_unavailable_classifier_never_parks_a_task(self):
        with mock.patch.dict(sys.modules, {"preflight_filter": None}):
            self.assertFalse(ar.is_unspecified(_task()))

    def test_a_raising_classifier_never_parks_a_task(self):
        broken = types.ModuleType("preflight_filter")

        def boom(*a, **k):
            raise RuntimeError("classifier down")

        broken.preflight_check = boom
        with mock.patch.dict(sys.modules, {"preflight_filter": broken}):
            self.assertFalse(ar.is_unspecified(_task()))


class RepairPatchTests(unittest.TestCase):
    def test_an_unimplementable_task_is_parked_at_the_first_repair(self):
        patch = ar.repair_patch(_task(rc=1), "boom")
        self.assertEqual(patch["state"], "QUARANTINED")
        self.assertTrue(patch["note"].startswith(ar.UNSPECIFIED_NOTE_PREFIX))
        self.assertIn("no implementation spec", patch["note"])
        self.assertLess(patch["remediation_count"], ar.GLOBAL_REPAIR_CEILING)

    def test_the_note_names_the_cause_not_the_symptom(self):
        """An operator needs 'no implementation spec', not 'did not converge'."""
        patch = ar.repair_patch(_task(), "boom")
        self.assertNotIn(ar.TERMINAL_NOTE_PREFIX, patch["note"])

    def test_a_well_specified_failing_task_is_still_repaired(self):
        patch = ar.repair_patch(_task(prompt=REAL), "boom")
        self.assertEqual(patch["state"], "QUEUED")
        self.assertEqual(patch["remediation_count"], 2)

    def test_a_never_run_task_still_gets_its_plain_requeue(self):
        """Ordering matters: never-ran is checked first, so a fresh row is not parked."""
        patch = ar.repair_patch(
            {"id": "t", "slug": "s", "prompt": GARBAGE, "attempt": 0}, "")
        self.assertEqual(patch["state"], "QUEUED")
        self.assertNotIn("remediation_count", patch)

    def test_an_operator_decision_is_still_never_consumed(self):
        prefix = ar.OPERATOR_DECISION_PREFIXES
        slug = (prefix[0] if isinstance(prefix, tuple) else prefix) + "x"
        patch = ar.repair_patch(_task(slug=slug), "boom")
        self.assertEqual(patch["state"], "QUEUED")
        self.assertNotIn("remediation_count", patch)

    def test_the_global_ceiling_still_wins_for_specified_work(self):
        patch = ar.repair_patch(
            _task(prompt=REAL, rc=ar.GLOBAL_REPAIR_CEILING + 1), "boom")
        self.assertEqual(patch["state"], "QUARANTINED")
        self.assertIn(ar.TERMINAL_NOTE_PREFIX, patch["note"])


if __name__ == "__main__":
    unittest.main()
