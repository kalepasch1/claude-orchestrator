#!/usr/bin/env python3
"""Diagnosing dangling dependency edges.

"no task has ever had the slug X" is true and useless. It names the symptom and
leaves the operator to work out whether they are looking at a typo, a deleted
row, or something structural — and the report's own advice, "drop the dep, or
fix the slug", is wrong for the structural case, because there is no slug to fix.

Every dangling edge on the live queue on 2026-08-26 was the same structural
thing: a decomposer produced <base>-slice-1..N, skipped one member, and a
sibling still depended on the member that was never created.

  improve-implement-automated-testing-framework  has slices 1, 3, 4, 5
                                                 and a dep on slice-2
  improve-implement-real-time-configuration-manage  has 1, 2, 3, 5
                                                 and a dep on slice-4

The dependency is not wrong about what it wanted. The work is missing from the
series. That is a different remedy — re-slice the parent — and the report could
not say so until it could tell the two apart.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import queue_deadlock_report as qdr  # noqa: E402


def by_slug(*slugs):
    return {s: {"slug": s, "state": "QUEUED"} for s in slugs}


class TestSliceSeriesGapsAreNamed:
    def test_the_real_case_from_the_live_queue(self):
        index = by_slug(
            "improve-implement-automated-testing-framework-slice-1",
            "improve-implement-automated-testing-framework-slice-3",
            "improve-implement-automated-testing-framework-slice-4",
            "improve-implement-automated-testing-framework-slice-5",
        )
        why = qdr._diagnose_dangling(
            "improve-implement-automated-testing-framework-slice-2", index)
        assert "gap in a slice series" in why
        assert "slice-2 was never created" in why
        assert "1, 3, 4, 5" in why

    def test_the_second_real_case(self):
        index = by_slug(
            "improve-implement-real-time-configuration-manage-slice-1",
            "improve-implement-real-time-configuration-manage-slice-2",
            "improve-implement-real-time-configuration-manage-slice-3",
            "improve-implement-real-time-configuration-manage-slice-5",
        )
        why = qdr._diagnose_dangling(
            "improve-implement-real-time-configuration-manage-slice-4", index)
        assert "1, 2, 3, 5" in why

    def test_the_advice_points_at_re_slicing_not_at_fixing_a_slug(self):
        index = by_slug("base-slice-1", "base-slice-3")
        why = qdr._diagnose_dangling("base-slice-2", index)
        assert "re-slice the parent" in why
        assert "fix the slug" not in why

    def test_siblings_are_listed_in_numeric_order_not_lexicographic(self):
        # slice-10 must not sort between slice-1 and slice-2.
        index = by_slug("base-slice-1", "base-slice-2", "base-slice-10")
        why = qdr._diagnose_dangling("base-slice-3", index)
        assert "1, 2, 10" in why


class TestABadSlugIsStillCalledABadSlug:
    def test_a_dep_that_is_not_a_slice_member(self):
        index = by_slug("something-else")
        why = qdr._diagnose_dangling("typo-slug", index)
        assert why == "no task has ever had the slug 'typo-slug'"

    def test_a_slice_member_whose_series_does_not_exist_at_all(self):
        # Not a gap in a series — there is no series. Calling it a gap would
        # send the operator to re-slice a parent that was never decomposed.
        index = by_slug("unrelated-slice-1")
        why = qdr._diagnose_dangling("nothing-like-it-slice-2", index)
        assert why == "no task has ever had the slug 'nothing-like-it-slice-2'"

    def test_a_trailing_number_that_is_not_a_slice_suffix(self):
        index = by_slug("base-slice-1")
        why = qdr._diagnose_dangling("base-part-2", index)
        assert "gap in a slice series" not in why


class TestClassifyStillBehaves:
    def test_a_dangling_dep_is_still_categorised_dangling(self):
        index = by_slug("base-slice-1")
        category, why = qdr._classify("base-slice-2", index, {}, {})
        assert category == "dangling"
        assert "gap in a slice series" in why

    def test_a_satisfied_dep_is_still_satisfied(self):
        index = {"done-thing": {"slug": "done-thing", "state": "MERGED"}}
        assert qdr._classify("done-thing", index, {}, {}) is None

    def test_a_qualified_cross_project_dep_is_diagnosed_on_the_bare_slug(self):
        index = by_slug("base-slice-1", "base-slice-3")
        category, why = qdr._classify("beethoven:base-slice-2", index, {}, {})
        assert category == "dangling"
        assert "gap in a slice series" in why
