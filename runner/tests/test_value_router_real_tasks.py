"""The value router must score the task shape this fleet actually produces.

estimate_value() read only `description` and `priority`. No task in the queue
has either: they carry `slug`, `kind` and `prompt`. Every real task therefore
scored the 50-point default and routed to queue:medium — including the ones
merge_train ranks by value (merge_train.py:1283). The existing unit tests never
caught it because they hand the router synthetic `description` dicts, which is
the one shape that did work.

These tests use real task shapes only. test_value_router.py keeps the synthetic
ones, which must continue to score identically.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import value_router


class TestRealTaskShapesAreScored(unittest.TestCase):

    def test_a_docs_task_is_not_scored_the_same_as_a_payment_bugfix(self):
        docs = value_router.estimate_value(
            {"slug": "update-docs-readme", "kind": "docs",
             "prompt": "Update docs/README.md"})
        payment = value_router.estimate_value(
            {"slug": "fix-payment-flow", "kind": "bugfix",
             "prompt": "Fix payment checkout in web/checkout.tsx"})

        self.assertLess(docs, payment - 40,
                        "these two must not land in the same bucket")

    def test_slug_hyphens_are_word_separators(self):
        """`update-docs-readme` tokenizes as one word, so `docs` never matched."""
        with_hyphens = value_router.estimate_value({"slug": "cleanup-lint-typo"})
        self.assertLess(with_hyphens, 50)

    def test_prompt_signals_are_read(self):
        task = {"slug": "x", "prompt": "production outage: revenue impacted"}
        self.assertGreater(value_router.estimate_value(task), 70)

    def test_kind_moves_the_score_on_its_own(self):
        bare = {"slug": "some-task", "prompt": "do a thing"}
        self.assertEqual(value_router.estimate_value(bare), 50.0)
        self.assertLess(
            value_router.estimate_value(dict(bare, kind="docs")), 50.0)
        self.assertGreater(
            value_router.estimate_value(dict(bare, kind="recovery")), 50.0)

    def test_an_unknown_kind_leaves_the_score_alone(self):
        self.assertEqual(
            value_router.estimate_value(
                {"slug": "some-task", "kind": "wildly-novel-kind"}), 50.0)

    def test_score_still_clamps_to_0_and_100(self):
        floor = value_router.estimate_value(
            {"slug": "chore-docs-typo-cleanup-lint", "kind": "docs",
             "prompt": "chore docs typo cleanup lint formatting comment readme"})
        ceiling = value_router.estimate_value(
            {"slug": "critical-security-outage", "kind": "recovery",
             "prompt": "critical security outage in production, revenue and "
                       "payment and checkout and billing regression",
             "value_score": 100})
        self.assertGreaterEqual(floor, 0.0)
        self.assertLessEqual(ceiling, 100.0)


class TestRoutingDecisions(unittest.TestCase):

    def test_low_tier_may_skip_integration_tests_and_auto_approve(self):
        routing = value_router.route_task(
            {"slug": "update-docs-readme", "kind": "docs",
             "prompt": "Update docs/README.md"})
        self.assertEqual(routing["tier"], "LOW")
        self.assertTrue(routing["skip_integration_tests"])
        self.assertTrue(routing["auto_approve"])

    def test_medium_is_the_cautious_default_not_a_free_pass(self):
        """An unscored task defaults to MEDIUM; MEDIUM must not auto-approve."""
        routing = value_router.route_task({"slug": "add-feature-x", "kind": "build",
                                           "prompt": "Implement feature X"})
        self.assertEqual(routing["tier"], "MEDIUM")
        self.assertFalse(routing["auto_approve"])
        self.assertFalse(routing["skip_integration_tests"])

    def test_high_tier_skips_nothing(self):
        routing = value_router.route_task(
            {"slug": "fix-payment-flow", "kind": "bugfix",
             "prompt": "Fix payment checkout in web/checkout.tsx"})
        self.assertEqual(routing["tier"], "HIGH")
        self.assertFalse(routing["skip_integration_tests"])
        self.assertFalse(routing["auto_approve"])

    def test_queue_and_tier_never_disagree(self):
        for task in ({"kind": "docs", "slug": "docs-typo"},
                     {"slug": "add-thing"},
                     {"priority": "critical"}):
            routing = value_router.route_task(task)
            expected = {"LOW": value_router.QUEUE_LOW,
                        "MEDIUM": value_router.QUEUE_MEDIUM,
                        "HIGH": value_router.QUEUE_HIGH}[routing["tier"]]
            self.assertEqual(routing["queue"], expected)


class TestStats(unittest.TestCase):

    def setUp(self):
        value_router.reset_stats()

    def tearDown(self):
        value_router.reset_stats()

    def test_routing_increments_the_total_and_the_tier(self):
        before = value_router.stats()
        value_router.route_task({"slug": "docs-typo", "kind": "docs"})

        after = value_router.stats()
        self.assertEqual(after["tasks_routed"], before["tasks_routed"] + 1)
        self.assertEqual(after["LOW"], before["LOW"] + 1)

    def test_stats_returns_a_copy_not_the_live_counter(self):
        snapshot = value_router.stats()
        value_router.route_task({"slug": "anything"})
        self.assertEqual(snapshot["tasks_routed"], 0)

    def test_reset_zeroes_every_counter(self):
        value_router.route_task({"slug": "anything"})
        value_router.reset_stats()
        self.assertEqual(set(value_router.stats().values()), {0})

    def test_route_batch_counts_every_task(self):
        value_router.route_batch([{"slug": "a"}, {"slug": "b"}, {"slug": "c"}])
        self.assertEqual(value_router.stats()["tasks_routed"], 3)


if __name__ == "__main__":
    unittest.main()
