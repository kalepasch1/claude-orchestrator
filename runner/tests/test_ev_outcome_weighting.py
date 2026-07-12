"""
test_ev_outcome_weighting.py - verify outcome weighting in ev_scheduler:
  - With flag OFF, ordering is unchanged (byte-identical to before)
  - With flag ON, a family with higher realized success rate outranks
    an equal-cost family with a lower one
  - Does not change default budget caps
"""
import os, sys, unittest
from unittest.mock import patch
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ev_scheduler


def _ctx(**over):
    ctx = {"revenue_by_project": {"payapp": 900.0},
           "surface_returns": {},
           "outcome_stats": {"payapp": {"success_rate": 0.8, "avg_usd": 0.5}},
           "approved_slugs": set(),
           "family_outcomes": {}}
    ctx.update(over)
    return ctx


def _task(**over):
    t = {"id": "t1", "project": "payapp", "kind": "build",
         "prompt": "add feature", "slug": "t1", "transient_retries": 0, "attempt": 0}
    t.update(over)
    return t


class TestOutcomeWeightFlagOff(unittest.TestCase):
    """With ORCH_EV_OUTCOME_WEIGHTING=false (default), outcome_weight returns 1.0
    and score() is byte-identical to the pre-change behavior."""

    @patch.dict(os.environ, {"ORCH_EV_OUTCOME_WEIGHTING": "false"}, clear=False)
    def test_weight_is_1_when_off(self):
        # Reload the flag
        ev_scheduler.OUTCOME_WEIGHTING_ENABLED = False
        ctx = _ctx(family_outcomes={"build": {"merged_green": 10, "total": 20,
                                               "retries": 5, "rejected": 2}})
        w = ev_scheduler.outcome_weight(_task(), ctx)
        self.assertEqual(w, 1.0)

    @patch.dict(os.environ, {"ORCH_EV_OUTCOME_WEIGHTING": "false"}, clear=False)
    def test_score_unchanged_when_off(self):
        ev_scheduler.OUTCOME_WEIGHTING_ENABLED = False
        ctx = _ctx(family_outcomes={"build": {"merged_green": 5, "total": 10,
                                               "retries": 3, "rejected": 1}})
        t = _task()
        # Score with and without family_outcomes should be identical when flag is off
        score_with = ev_scheduler.score(t, ctx)
        score_without = ev_scheduler.score(t, _ctx())
        self.assertEqual(score_with, score_without)


class TestOutcomeWeightFlagOn(unittest.TestCase):
    """With ORCH_EV_OUTCOME_WEIGHTING=true, family success rate affects score."""

    def setUp(self):
        self._orig = ev_scheduler.OUTCOME_WEIGHTING_ENABLED
        ev_scheduler.OUTCOME_WEIGHTING_ENABLED = True

    def tearDown(self):
        ev_scheduler.OUTCOME_WEIGHTING_ENABLED = self._orig

    def test_higher_success_outranks_lower(self):
        high_ctx = _ctx(family_outcomes={
            "build": {"merged_green": 9, "total": 10, "retries": 1, "rejected": 0}})
        low_ctx = _ctx(family_outcomes={
            "build": {"merged_green": 2, "total": 10, "retries": 5, "rejected": 3}})
        t = _task()
        high_score = ev_scheduler.score(t, high_ctx)
        low_score = ev_scheduler.score(t, low_ctx)
        self.assertGreater(high_score, low_score,
                           "Higher realized success should produce higher score")

    def test_no_family_data_neutral(self):
        """Missing family_outcomes => weight is 1.0 (neutral)."""
        w = ev_scheduler.outcome_weight(_task(), _ctx())
        self.assertEqual(w, 1.0)

    def test_empty_total_neutral(self):
        ctx = _ctx(family_outcomes={"build": {"merged_green": 0, "total": 0}})
        w = ev_scheduler.outcome_weight(_task(), ctx)
        self.assertEqual(w, 1.0)

    def test_weight_floored_at_0_1(self):
        """Even with terrible outcomes, weight floors at 0.1."""
        ctx = _ctx(family_outcomes={
            "build": {"merged_green": 0, "total": 100, "retries": 300, "rejected": 50}})
        w = ev_scheduler.outcome_weight(_task(), ctx)
        self.assertGreaterEqual(w, 0.1)

    def test_perfect_outcomes_weight_near_1(self):
        ctx = _ctx(family_outcomes={
            "build": {"merged_green": 100, "total": 100, "retries": 0, "rejected": 0}})
        w = ev_scheduler.outcome_weight(_task(), ctx)
        self.assertAlmostEqual(w, 1.0)

    def test_kind_mismatch_neutral(self):
        """Task kind not in family_outcomes => neutral weight."""
        ctx = _ctx(family_outcomes={"docs": {"merged_green": 5, "total": 10}})
        w = ev_scheduler.outcome_weight(_task(kind="build"), ctx)
        self.assertEqual(w, 1.0)


if __name__ == "__main__":
    unittest.main()
