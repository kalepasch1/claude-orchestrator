#!/usr/bin/env python3
"""The high-ROI fix boost in priority_scorer.score_task.

Provenance: this is the single hunk, out of 14,300 examined across the 13
rescue refs classified CONFLICTED_NEEDS_FOCUSED_TASK, that the focused triage
found genuinely missing from origin/master. Everything else in those refs was
already present, superseded, deletion-only, or aimed at a path base no longer
has. See docs/recovery-ledger/5dc36bf5e0be-focused-conflict-triage.md.

It arrives with tests because it did not have any, which is part of why it was
easy to lose.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import priority_scorer  # noqa: E402


def score(**row):
    """score_task with a blocker by default.

    Without deps, score_task applies its own -5 ready-to-run boost, which pushes
    the already-low fix bases into the `max(1, base)` floor and silently absorbs
    part of the boost being measured. TestBoostMeetsTheFloor pins that
    interaction deliberately; every other test avoids it so it is measuring one
    thing.
    """
    row.setdefault("deps", ["blocker"])
    return priority_scorer.score_task(row)


class TestHighRoiFixBoost(unittest.TestCase):
    def test_confident_untried_fix_is_boosted_most(self):
        plain = score(slug="qafix-a", kind="bugfix")
        boosted = score(slug="qafix-a", kind="bugfix", confidence=0.9, attempt=0)
        self.assertEqual(plain - boosted, 8)

    def test_one_prior_attempt_still_qualifies(self):
        self.assertEqual(
            score(slug="qafix-a", kind="bugfix", confidence=0.9, attempt=1),
            score(slug="qafix-a", kind="bugfix", confidence=0.9, attempt=0),
        )

    def test_retry_burn_drops_it_to_the_middle_tier(self):
        # Two attempts in, high confidence is no longer evidence of cheapness.
        plain = score(slug="qafix-a", kind="bugfix")
        retried = score(slug="qafix-a", kind="bugfix", confidence=0.9, attempt=2)
        self.assertEqual(plain - retried, 3)

    def test_middling_confidence_gets_the_smaller_boost(self):
        plain = score(slug="qafix-a", kind="bugfix")
        boosted = score(slug="qafix-a", kind="bugfix", confidence=0.5, attempt=0)
        self.assertEqual(plain - boosted, 3)

    def test_low_confidence_gets_nothing(self):
        self.assertEqual(
            score(slug="qafix-a", kind="bugfix", confidence=0.49, attempt=0),
            score(slug="qafix-a", kind="bugfix"),
        )

    def test_boundaries_are_inclusive(self):
        plain = score(slug="qafix-a", kind="bugfix")
        self.assertEqual(
            plain - score(slug="qafix-a", kind="bugfix", confidence=0.7, attempt=1), 8)
        self.assertEqual(
            plain - score(slug="qafix-a", kind="bugfix", confidence=0.5, attempt=0), 3)


class TestWhatCountsAsAFix(unittest.TestCase):
    def test_fix_kinds(self):
        for kind in ("bugfix", "qafix", "relfix"):
            plain = score(slug="something", kind=kind)
            boosted = score(slug="something", kind=kind, confidence=0.9, attempt=0)
            self.assertEqual(plain - boosted, 8, msg=kind)

    def test_fix_slug_prefixes(self):
        for prefix in ("qafix-", "relfix-", "buildfix-", "deployfix-", "hotfix-"):
            slug = prefix + "x"
            plain = score(slug=slug, kind="improvement")
            boosted = score(slug=slug, kind="improvement", confidence=0.9, attempt=0)
            self.assertEqual(plain - boosted, 8, msg=prefix)

    def test_a_non_fix_is_never_boosted(self):
        for slug, kind in (("improve-x", "improvement"), ("build-x", "build"),
                           ("cont-x", "canary"), ("test-x", "test")):
            self.assertEqual(
                score(slug=slug, kind=kind, confidence=0.99, attempt=0),
                score(slug=slug, kind=kind),
                msg=slug,
            )


class TestMalformedRowsDoNotCrashTheSweep(unittest.TestCase):
    """score_backlog() runs over whatever the table holds; a bad row must not
    take the whole sweep down."""

    def test_non_numeric_confidence_and_attempt_are_treated_as_zero(self):
        plain = score(slug="qafix-a", kind="bugfix")
        for bad in ("", "high", None, [], {}):
            self.assertEqual(
                score(slug="qafix-a", kind="bugfix", confidence=bad, attempt=bad),
                plain,
                msg=repr(bad),
            )

    def test_numeric_strings_still_work(self):
        plain = score(slug="qafix-a", kind="bugfix")
        self.assertEqual(
            plain - score(slug="qafix-a", kind="bugfix", confidence="0.9", attempt="0"),
            8,
        )


class TestBoostMeetsTheFloor(unittest.TestCase):
    """The boost is a nudge inside an ordering, not an unbounded discount."""

    def test_priority_never_drops_below_one(self):
        # qafix- base is 10; no-deps -5, boost -8, age -10 would go negative.
        s = score(slug="qafix-a", kind="bugfix", confidence=0.9, attempt=0,
                  deps=[], created_at="2020-01-01T00:00:00Z")
        self.assertGreaterEqual(s, 1)

    def test_the_floor_absorbs_part_of_the_boost_for_ready_fixes(self):
        # A ready-to-run qafix already scores 5 (base 10, -5 for no deps), so
        # the full -8 cannot land. This is the floor doing its job, not the
        # boost failing -- but it means the boost cannot separate two tasks that
        # are both already at the floor.
        plain = priority_scorer.score_task(
            {"slug": "qafix-a", "kind": "bugfix", "deps": []})
        boosted = priority_scorer.score_task(
            {"slug": "qafix-a", "kind": "bugfix", "deps": [],
             "confidence": 0.9, "attempt": 0})
        self.assertEqual(plain, 5)
        self.assertEqual(boosted, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
