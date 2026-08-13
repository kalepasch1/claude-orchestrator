#!/usr/bin/env python3
"""Audit addendum §D — the triage result is recorded, not recomputed."""
import os
import sys
import unittest

RUNNER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner")
sys.path.insert(0, RUNNER)

import stash_triage as st  # noqa: E402


class BaselineTests(unittest.TestCase):
    def test_the_recorded_numbers_are_the_ones_the_addendum_states(self):
        self.assertEqual(st.BASELINE["total"], 315)
        self.assertEqual(st.BASELINE["counts"][st.EMPTY], 119)
        self.assertEqual(st.BASELINE["counts"][st.ALREADY_LANDED], 37)
        self.assertEqual(st.BASELINE["counts"][st.RECOVERABLE], 12)
        self.assertEqual(st.BASELINE["counts"][st.CONFLICTED], 120)
        self.assertEqual(st.BASELINE["conflicted_touching_runner"], 76)

    def test_the_recorded_buckets_do_not_sum_to_the_recorded_total(self):
        """The §D numbers do not balance: 119+37+12+120 = 288, against a stated 315.

        Pinned rather than corrected. Nobody can say today which bucket the missing 27 belong
        in, and guessing one would turn an auditable gap into a plausible-looking lie. The
        module surfaces the gap so those 27 get triaged; the other 288 stay done.
        """
        self.assertEqual(sum(st.BASELINE["counts"].values()), 288)
        self.assertEqual(st.unaccounted(), 27)

    def test_the_gap_is_derived_so_it_cannot_go_stale(self):
        adjusted = dict(st.BASELINE, total=300)
        self.assertEqual(st.unaccounted(adjusted), 12)
        balanced = dict(st.BASELINE, total=288)
        self.assertEqual(st.unaccounted(balanced), 0)

    def test_the_gap_is_reported_to_the_operator_not_hidden(self):
        text = st.render()
        self.assertIn("UNACCOUNTED: 27", text)
        self.assertIn("in NO bucket", text)

    def test_a_balanced_baseline_reports_no_gap(self):
        self.assertNotIn("UNACCOUNTED", st.render(baseline=dict(st.BASELINE, total=288)))

    def test_unaccounted_is_fail_soft(self):
        self.assertEqual(st.unaccounted({}), 0)
        self.assertEqual(st.unaccounted({"total": "x", "counts": {}}), 0)

    def test_the_twelve_recoverable_refs_match_the_vetted_script(self):
        self.assertEqual(len(st.BASELINE["recoverable_refs"]),
                         st.BASELINE["counts"][st.RECOVERABLE])
        script = os.path.join(os.path.dirname(RUNNER), st.BASELINE["recovery_script"])
        self.assertTrue(os.path.isfile(script), "the vetted recovery script must exist")
        text = open(script, errors="replace").read()
        for ref in st.BASELINE["recoverable_refs"]:
            self.assertIn(ref, text, f"{ref} is in the baseline but not in the script")

    def test_the_conflicted_set_is_named_as_the_real_work(self):
        self.assertEqual(st.real_work(), 120)
        self.assertIn("that is the real work", st.render())

    def test_the_permanent_loss_is_stated_so_it_stops_being_searched_for(self):
        self.assertEqual(st.PERMANENT_LOSS["batches"], 282)
        self.assertTrue(st.PERMANENT_LOSS["root_cause_fixed"])
        text = st.render()
        self.assertIn("PERMANENTLY LOST", text)
        self.assertIn("Stop looking for them", text)

    def test_the_summary_line_is_the_addendum_sentence(self):
        line = st.summary_line()
        for fragment in ("119 empty", "37 already-landed", "12 recoverable", "120 conflicted"):
            self.assertIn(fragment, line)


class ComparisonTests(unittest.TestCase):
    def test_an_unchanged_pile_means_do_not_recompute(self):
        result = st.compare_to_baseline(315)
        self.assertFalse(result["changed"])
        self.assertIn("do NOT recompute", result["recommendation"])

    def test_new_stashes_mean_triage_only_the_new_ones(self):
        result = st.compare_to_baseline(320)
        self.assertTrue(result["changed"])
        self.assertEqual(result["delta"], 5)
        self.assertIn("ONLY the new ones", result["recommendation"])

    def test_fewer_stashes_than_the_baseline_demands_an_explanation_first(self):
        result = st.compare_to_baseline(200)
        self.assertEqual(result["delta"], -115)
        self.assertIn("explain that before triaging", result["recommendation"])

    def test_an_unreadable_count_recomputes_nothing_on_a_guess(self):
        result = st.compare_to_baseline("not a number")
        self.assertIn("recompute nothing on a guess", result["recommendation"])

    def test_the_recommendation_is_rendered_for_the_operator(self):
        self.assertIn("do NOT recompute", st.render(st.compare_to_baseline(315)))


if __name__ == "__main__":
    unittest.main()
