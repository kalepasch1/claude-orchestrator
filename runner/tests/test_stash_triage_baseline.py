#!/usr/bin/env python3
"""Recorded-baseline accounting in stash_triage.

The audit addendum's instruction is "the triage result already exists — start
from it, do not recompute", but the result lived only in prose, so every
session rediscovered it with an hour of read-only git archaeology. The
baseline is now recorded next to the classifier that produced it.

The load-bearing assertion here is the arithmetic gap: the four buckets sum to
288 against a stated total of 315, so 27 stashes are in the pile and in no
bucket. `unaccounted()` derives that gap rather than storing it, so it cannot
drift out of sync with the counts — and a triage that silently balanced would
have hidden those 27 entirely.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import stash_triage as st


class TestBaselineShape(unittest.TestCase):

    def test_baseline_covers_all_four_buckets(self):
        for bucket in (st.EMPTY, st.ALREADY_LANDED, st.RECOVERABLE, st.CONFLICTED):
            self.assertIn(bucket, st.BASELINE["counts"])

    def test_baseline_is_dated_so_it_can_be_invalidated(self):
        self.assertTrue(st.BASELINE.get("measured_at"))
        self.assertTrue(st.BASELINE.get("host"))

    def test_permanent_loss_is_recorded(self):
        self.assertEqual(st.PERMANENT_LOSS["batches"], 282)
        self.assertTrue(st.PERMANENT_LOSS["root_cause_fixed"])


class TestUnaccounted(unittest.TestCase):

    def test_gap_is_derived_not_stored(self):
        counts = sum(st.BASELINE["counts"].values())
        self.assertEqual(st.unaccounted(), st.BASELINE["total"] - counts)

    def test_known_gap_is_27(self):
        self.assertEqual(st.unaccounted(), 27,
                         "27 stashes are in the pile and in no bucket")

    def test_gap_tracks_edited_counts(self):
        """Derivation, not a stored constant: change a count, gap moves."""
        edited = {"total": 315, "counts": dict(st.BASELINE["counts"])}
        edited["counts"][st.EMPTY] += 10
        self.assertEqual(st.unaccounted(edited), 17)

    def test_balanced_baseline_reports_zero(self):
        self.assertEqual(
            st.unaccounted({"total": 6, "counts": {st.EMPTY: 1, st.ALREADY_LANDED: 2,
                                                   st.RECOVERABLE: 3, st.CONFLICTED: 0}}),
            0)

    def test_explicitly_empty_baseline_is_not_the_module_default(self):
        """`is None`, not falsiness — an empty baseline measured nothing."""
        self.assertEqual(st.unaccounted({}), 0)

    def test_garbage_baseline_is_fail_soft(self):
        self.assertEqual(st.unaccounted({"total": "nope", "counts": {}}), 0)


class TestCompareToBaseline(unittest.TestCase):

    def test_unchanged_pile_says_do_not_recompute(self):
        result = st.compare_to_baseline(st.BASELINE["total"])
        self.assertFalse(result["changed"])
        self.assertEqual(result["delta"], 0)
        self.assertIn("do NOT recompute", result["recommendation"])

    def test_growth_says_triage_only_the_new_ones(self):
        result = st.compare_to_baseline(st.BASELINE["total"] + 4)
        self.assertTrue(result["changed"])
        self.assertEqual(result["delta"], 4)
        self.assertIn("ONLY the new ones", result["recommendation"])

    def test_shrinkage_demands_an_explanation(self):
        result = st.compare_to_baseline(st.BASELINE["total"] - 9)
        self.assertEqual(result["delta"], -9)
        self.assertIn("explain that", result["recommendation"])

    def test_zero_observed_is_a_real_comparison_not_an_error(self):
        result = st.compare_to_baseline(0)
        self.assertEqual(result["observed_total"], 0)
        self.assertEqual(result["delta"], -st.BASELINE["total"])

    def test_unreadable_input_never_raises(self):
        result = st.compare_to_baseline(None)
        self.assertIn("recompute nothing on a guess", result["recommendation"])
        self.assertIsNone(result["observed_total"])

    def test_custom_baseline_is_respected(self):
        custom = {"total": 10, "measured_at": "2026-01-01",
                  "counts": {st.EMPTY: 10, st.ALREADY_LANDED: 0,
                             st.RECOVERABLE: 0, st.CONFLICTED: 0}}
        self.assertFalse(st.compare_to_baseline(10, custom)["changed"])


class TestSummaryHelpers(unittest.TestCase):

    def test_summary_line_names_every_bucket(self):
        line = st.summary_line()
        for word in ("empty", "already-landed", "recoverable", "conflicted"):
            self.assertIn(word, line)

    def test_real_work_is_the_conflicted_count(self):
        self.assertEqual(st.real_work(), st.BASELINE["counts"][st.CONFLICTED])

    def test_real_work_is_fail_soft(self):
        self.assertEqual(st.real_work({"counts": "broken"}), 0)

    def test_format_baseline_surfaces_the_gap(self):
        text = st.format_baseline()
        self.assertIn("UNACCOUNTED", text)
        self.assertIn("27", text)
        self.assertIn("not recoverable", text)

    def test_format_baseline_hides_gap_when_balanced(self):
        balanced = {"host": "h", "measured_at": "2026-01-01", "total": 4,
                    "counts": {st.EMPTY: 4, st.ALREADY_LANDED: 0,
                               st.RECOVERABLE: 0, st.CONFLICTED: 0}}
        self.assertNotIn("UNACCOUNTED", st.format_baseline(balanced))


class TestCliBaselineMode(unittest.TestCase):

    def test_baseline_flag_does_not_scan(self):
        """--baseline must answer from the record, never shell out to git."""
        called = []
        original = st._git
        st._git = lambda *a, **k: called.append(a) or (_ for _ in ()).throw(
            AssertionError("--baseline must not invoke git"))
        try:
            self.assertEqual(st.main(["--baseline"]), 0)
        finally:
            st._git = original
        self.assertEqual(called, [])

    def test_baseline_json_mode_exits_clean(self):
        self.assertEqual(st.main(["--baseline", "--json"]), 0)

    def test_historical_refs_are_labelled_as_provenance_only(self):
        """Positional stash@{N} refs must not look like something to resolve."""
        self.assertNotIn("recoverable_refs", st.BASELINE)
        self.assertIn("recoverable_refs_historical", st.BASELINE)
        self.assertEqual(len(st.BASELINE["recoverable_refs_historical"]), 12)


if __name__ == "__main__":
    unittest.main()
