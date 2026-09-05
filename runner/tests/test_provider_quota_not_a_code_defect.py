"""Running out of provider credit is not an engineering task.

This test exists because the fleet queued one. The whole body of
`backlog-batch-darwn-cde71c9` was:

    The task failed due to an API error indicating that the team has either used
    all available credits or reached its monthly spending limit. To resolve this
    issue: ... Modify the relevant configuration or source code to use a
    different API key, increase the spending limit, or purchase additional
    credits if necessary. ... Commit the final implementation on the task branch.

A coding agent cannot buy credits, and it should not try. The task also carried a
preflight note already saying "No committable source/file change is defined" —
the pipeline knew, and queued it anyway.

The mechanism: retry_policy correctly classifies quota exhaustion as TRANSIENT
(right — another provider or the monthly reset can serve the work), and the
transient path calls agentic_repair.repair_patch, which rewrites the task's
prompt into a repair brief. agentic_repair's existing escape hatch,
`is_operator_decision`, matches on the SLUG, and a quota failure lands on
ordinary work whose slug says nothing about billing — so nothing caught it.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import agentic_repair as ar
import retry_policy as rp

QUOTA_SIGNALS = [
    "API error: the team has either used all available credits or reached its monthly spending limit",
    "xai 403 permission-denied: used all available credits",
    "insufficient credits",
    "quota exceeded",
    "Your credit balance is too low",
    "402 payment required",
]

REAL_FAILURES = [
    "TypeError: undefined is not a function at src/a.ts:12",
    "verify: 3 tests failed",
    "connection reset by peer",
    "read timed out",
]


def _task(**over):
    t = {"id": "x", "slug": "backlog-batch-darwn-cde71c9", "attempt": 2,
         "remediation_count": 1, "prompt": "Do the thing",
         "log_tail": "TypeError: undefined is not a function at src/a.ts:12"}
    t.update(over)
    return t


class QuotaIsRecognised(unittest.TestCase):
    def test_every_quota_phrasing_is_detected(self):
        for s in QUOTA_SIGNALS:
            self.assertTrue(rp.is_provider_quota(s), s)

    def test_ordinary_failures_are_not_quota(self):
        for s in REAL_FAILURES:
            self.assertFalse(rp.is_provider_quota(s), s)

    def test_bad_input_is_not_a_quota_signal(self):
        for s in (None, "", 0, []):
            self.assertFalse(rp.is_provider_quota(s))

    def test_quota_remains_transient_so_the_work_still_retries(self):
        # Deliberate: another provider, or the monthly reset, can serve this.
        # Reclassifying it terminal would strand real work on a billing blip.
        for s in QUOTA_SIGNALS:
            self.assertEqual(rp.classify(s), "transient", s)


class RepairDoesNotRewriteAQuotaFailure(unittest.TestCase):
    def test_a_quota_signal_produces_no_engineering_prompt(self):
        for s in QUOTA_SIGNALS:
            patch = ar.repair_patch(_task(), s, category="transient",
                                    directive="Resume and finish.")
            self.assertNotIn("prompt", patch,
                             "a billing incident must not be rewritten into a coding brief: %s" % s)

    def test_the_task_stays_queued_and_is_released_not_quarantined(self):
        patch = ar.repair_patch(_task(), QUOTA_SIGNALS[0], category="transient")
        self.assertEqual(patch["state"], "QUEUED")
        self.assertIsNone(patch["account"], "a dead claim must be released")

    def test_the_note_says_what_a_human_should_actually_do(self):
        patch = ar.repair_patch(_task(), QUOTA_SIGNALS[0], category="transient")
        note = patch["note"]
        self.assertIn("awaiting operator", note)
        self.assertIn("not a code defect", note)
        self.assertIn("Top up or re-point the router", note)

    def test_no_counter_is_burned_on_a_billing_failure(self):
        # Bumping attempt/remediation_count here would walk an otherwise healthy
        # task toward the terminal ceiling for something it did not do.
        patch = ar.repair_patch(_task(), QUOTA_SIGNALS[0], category="transient")
        self.assertNotIn("attempt", patch)
        self.assertNotIn("remediation_count", patch)

    def test_a_real_failure_still_gets_its_repair_prompt(self):
        patch = ar.repair_patch(_task(), REAL_FAILURES[0], category="transient",
                                directive="Resume and finish.")
        self.assertIn("prompt", patch,
                      "the quota carve-out must not disable ordinary repair")
        self.assertGreater(len(patch["prompt"]), 100)

    def test_a_transient_network_failure_still_gets_its_repair_prompt(self):
        patch = ar.repair_patch(_task(), "connection reset by peer", category="transient",
                                directive="Resume and finish.")
        self.assertIn("prompt", patch)

    def test_the_carve_out_fails_soft_if_retry_policy_is_unavailable(self):
        """A missing sibling module must restore old behaviour, not swallow the task."""
        real = sys.modules.pop("retry_policy", None)
        sys.modules["retry_policy"] = None  # import returns None -> AttributeError
        try:
            patch = ar.repair_patch(_task(), QUOTA_SIGNALS[0], category="transient",
                                    directive="Resume and finish.")
            self.assertIn("prompt", patch,
                          "with the check unavailable the task must still be repaired, "
                          "not silently dropped")
        finally:
            if real is not None:
                sys.modules["retry_policy"] = real
            else:
                sys.modules.pop("retry_policy", None)


class SlugBasedEscalationStillWorks(unittest.TestCase):
    def test_an_operator_decision_slug_is_still_short_circuited(self):
        for prefix in ar.OPERATOR_DECISION_PREFIXES:
            patch = ar.repair_patch(_task(slug=prefix + "something"), "anything")
            self.assertNotIn("prompt", patch)


if __name__ == "__main__":
    unittest.main()
