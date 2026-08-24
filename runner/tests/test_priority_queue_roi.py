#!/usr/bin/env python3
"""Value-based express-lane pinning in runner/priority_queue.py.

Slug prefixes only cover work we can name in advance. These tests cover the
ORCH_PINNED_MIN_ROI path, which pins a task by its score at queue time, plus the
fail-soft guarantees around it: bad config must never widen the express lane.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import priority_queue  # noqa: E402

CONFIG_KEYS = (
    "ORCH_PRIORITY_QUEUE_ENABLED",
    "ORCH_PINNED_TASK_PREFIXES",
    "ORCH_PINNED_MIN_ROI",
)


class _Base(unittest.TestCase):
    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in CONFIG_KEYS}
        for k in CONFIG_KEYS:
            os.environ.pop(k, None)
        priority_queue.acquire().invalidate()

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        priority_queue.acquire().invalidate()

    def configure(self, enabled="true", prefixes=None, min_roi=None):
        os.environ["ORCH_PRIORITY_QUEUE_ENABLED"] = enabled
        if prefixes is not None:
            os.environ["ORCH_PINNED_TASK_PREFIXES"] = prefixes
        if min_roi is not None:
            os.environ["ORCH_PINNED_MIN_ROI"] = min_roi
        priority_queue.acquire().invalidate()


class TestRoiPinning(_Base):
    def test_high_roi_task_takes_express_lane_without_matching_prefix(self):
        self.configure(min_roi="5.0")
        result = priority_queue.classify_task({"slug": "unremarkable-name", "roi": 9.1})
        self.assertTrue(result["is_pinned"])
        self.assertEqual(result["pin_reason"], "roi")

    def test_roi_below_threshold_stays_in_normal_lane(self):
        self.configure(min_roi="5.0")
        result = priority_queue.classify_task({"slug": "unremarkable-name", "roi": 4.9})
        self.assertFalse(result["is_pinned"])
        self.assertEqual(result["pin_reason"], "")

    def test_threshold_is_inclusive(self):
        self.configure(min_roi="5.0")
        self.assertTrue(priority_queue.classify_task({"slug": "x", "roi": 5.0})["is_pinned"])

    def test_ev_score_and_value_per_minute_are_accepted_fallbacks(self):
        self.configure(min_roi="5.0")
        self.assertTrue(priority_queue.classify_task({"slug": "x", "ev_score": 7.0})["is_pinned"])
        self.assertTrue(
            priority_queue.classify_task({"slug": "x", "value_per_minute": 7.0})["is_pinned"]
        )

    def test_explicit_roi_wins_over_ev_score(self):
        # A task carrying both should be judged on the more direct signal, so a low
        # roi must not be rescued by a high modelled ev_score.
        self.configure(min_roi="5.0")
        task = {"slug": "x", "roi": 1.0, "ev_score": 99.0}
        self.assertFalse(priority_queue.classify_task(task)["is_pinned"])

    def test_string_scores_are_coerced(self):
        self.configure(min_roi="5.0")
        self.assertTrue(priority_queue.classify_task({"slug": "x", "roi": "8.5"})["is_pinned"])


class TestFailSoft(_Base):
    def test_unset_threshold_leaves_value_pinning_disabled(self):
        # Without the key, a very high scoring task must still take the normal lane:
        # the feature is opt-in.
        self.configure(prefixes="recovery")
        result = priority_queue.classify_task({"slug": "whatever", "roi": 10_000})
        self.assertFalse(result["is_pinned"])
        self.assertIsNone(priority_queue.stats()["min_roi"])

    def test_unparseable_threshold_disables_rather_than_defaulting_to_zero(self):
        # A 0.0 default would express-lane the entire queue, which is the failure mode
        # this guard exists to prevent.
        self.configure(min_roi="not-a-number")
        self.assertFalse(priority_queue.classify_task({"slug": "x", "roi": 0.0})["is_pinned"])
        self.assertIsNone(priority_queue.stats()["min_roi"])

    def test_non_numeric_task_score_does_not_raise(self):
        self.configure(min_roi="5.0")
        self.assertFalse(priority_queue.classify_task({"slug": "x", "roi": "high"})["is_pinned"])

    def test_boolean_score_is_not_treated_as_numeric(self):
        # bool is an int subclass; True must not silently read as 1.0.
        self.configure(min_roi="0.5")
        self.assertFalse(priority_queue.classify_task({"slug": "x", "roi": True})["is_pinned"])

    def test_task_without_any_score_stays_normal(self):
        self.configure(min_roi="5.0")
        self.assertFalse(priority_queue.classify_task({"slug": "x"})["is_pinned"])

    def test_disabled_queue_ignores_roi_entirely(self):
        self.configure(enabled="false", min_roi="1.0")
        self.assertFalse(priority_queue.classify_task({"slug": "x", "roi": 500})["is_pinned"])


class TestExistingBehaviorPreserved(_Base):
    def test_prefix_pinning_still_works(self):
        self.configure(prefixes="recovery,breach-remediation")
        result = priority_queue.classify_task({"slug": "recovery-fix-001"})
        self.assertTrue(result["is_pinned"])
        self.assertEqual(result["pin_reason"], "prefix")
        self.assertEqual(result["reason"], "matches pinned prefix")

    def test_prefix_reason_wins_when_both_apply(self):
        self.configure(prefixes="recovery", min_roi="1.0")
        result = priority_queue.classify_task({"slug": "recovery-fix-001", "roi": 99})
        self.assertEqual(result["pin_reason"], "prefix")

    def test_non_matching_task_reason_unchanged(self):
        self.configure(prefixes="recovery")
        self.assertEqual(
            priority_queue.classify_task({"slug": "other"})["reason"], "normal queue"
        )


class TestDispatchAndStats(_Base):
    def test_roi_pinned_task_dispatches_to_express_lane(self):
        self.configure(min_roi="5.0")
        out = priority_queue.dispatch({"slug": "x", "roi": 6.0})
        self.assertEqual(out["lane"], "express")
        self.assertEqual(out["wait_ms"], 0)
        self.assertEqual(out["pin_reason"], "roi")

    def test_roi_dispatches_are_counted_separately(self):
        self.configure(prefixes="recovery", min_roi="5.0")
        priority_queue.dispatch({"slug": "recovery-a"})
        priority_queue.dispatch({"slug": "plain-b", "roi": 6.0})
        priority_queue.dispatch({"slug": "plain-c", "roi": 0.1})
        stats = priority_queue.stats()
        self.assertEqual(stats["total_pinned"], 2)
        self.assertEqual(stats["total_pinned_by_roi"], 1)

    def test_stats_reports_configured_threshold(self):
        self.configure(min_roi="12.5")
        self.assertEqual(priority_queue.stats()["min_roi"], 12.5)


if __name__ == "__main__":
    unittest.main()
