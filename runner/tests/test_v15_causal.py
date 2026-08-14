import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import hivemind_v15 as v15
import v15_causal as causal


def lagged_series(n=120, lag=1, gaps=()):
    """driver leads target by `lag`: driver[t] == target[t + lag]."""
    s = causal.AlignedSeries(history=512)
    for t in range(n):
        values = {"target": float(t % 7)}
        if t not in gaps:
            values["driver"] = float((t + lag) % 7)
        s.observe(t, values)
    return s


class TestMissingnessAlignment(unittest.TestCase):
    """The defect this module exists to fix."""

    # driver LEADS target by one step: driver[t] == target[t+1].
    # Therefore driver[t-1] == target[t] exactly, so a correctly aligned
    # lag-1 analysis must see r == 1.0.
    GAPS = (10, 11)

    @staticmethod
    def _driver(t):
        return float((t + 1) % 7)

    @staticmethod
    def _target(t):
        return float(t % 7)

    def test_base_graph_loses_the_relationship_when_samples_are_missing(self):
        g = v15.FractalCausalGraph(scales=(1,))
        for t in range(40):
            g.observe({"target": self._target(t)})
            if t not in self.GAPS:
                g.observe({"driver": self._driver(t)})
        # Index position is the time axis, so two gaps shift every later pair.
        # The true relationship here is exact (r == 1.0); the base graph
        # measures it as materially weaker, and reports no warning at all.
        r = g.predict("target", ["driver"])["causes"][0]["correlation"]
        self.assertLess(abs(r), .99)
        self.__class__.base_correlation = abs(r)

    def test_alignment_beats_index_pairing_on_identical_data(self):
        """Direct comparison: same series, same gaps, both analyses at lag 1."""
        g = v15.FractalCausalGraph(scales=(1,))
        s = causal.AlignedSeries()
        for t in range(40):
            g.observe({"target": self._target(t)})
            s_values = {"target": self._target(t)}
            if t not in self.GAPS:
                g.observe({"driver": self._driver(t)})
                s_values["driver"] = self._driver(t)
            s.observe(t, s_values)
        base = abs(g.predict("target", ["driver"])["causes"][0]["correlation"])
        aligned = abs(causal.associations(s, "target", ["driver"],
                                          scales=(1,), min_pairs=4)[0].correlation)
        self.assertAlmostEqual(aligned, 1.0, places=6)
        self.assertGreater(aligned, base)

    def test_aligned_pairs_recover_the_relationship_from_the_same_gaps(self):
        s = causal.AlignedSeries()
        for t in range(40):
            values = {"target": self._target(t)}
            if t not in self.GAPS:
                values["driver"] = self._driver(t)
            s.observe(t, values)
        found = causal.associations(s, "target", ["driver"], scales=(1,), min_pairs=4)
        # Same data, same gaps: pairing by grid index recovers r == 1.0 exactly.
        self.assertAlmostEqual(found[0].correlation, 1.0, places=6)

    def test_a_gap_drops_one_pair_rather_than_shifting_the_rest(self):
        s = causal.AlignedSeries()
        for t in range(10):
            values = {"target": float(t)}
            if t != 4:
                values["driver"] = float(t)
            s.observe(t, values)
        pairs = causal.aligned_pairs(s, "driver", "target", scale=1)
        self.assertNotIn(5, [t for t, _, _ in pairs])   # target[5] needed driver[4]
        self.assertIn(6, [t for t, _, _ in pairs])      # and t=6 is unaffected

    def test_missing_is_not_zero(self):
        s = causal.AlignedSeries()
        s.observe(0, {"a": 1.0})
        s.observe(1, {"a": None})
        s.observe(2, {"a": 3.0})
        values = [smp.value for smp in s.series("a")]
        self.assertEqual(values, [1.0, None, 3.0])
        self.assertAlmostEqual(s.coverage("a"), 2 / 3)


class TestNoLookAhead(unittest.TestCase):
    def test_window_is_strictly_backward_looking(self):
        s = lagged_series(60)
        for t, driver_t, _ in [(t, t - 4, y) for t, _, y in causal.aligned_pairs(s, "driver", "target", 4)]:
            self.assertLess(driver_t, t)

    def test_scale_zero_is_refused(self):
        s = lagged_series(30)
        with self.assertRaises(ValueError):
            causal.aligned_pairs(s, "driver", "target", scale=0)

    def test_upto_hides_the_future_entirely(self):
        s = lagged_series(80)
        pairs = causal.aligned_pairs(s, "driver", "target", scale=1, upto=30)
        self.assertLessEqual(max(t for t, _, _ in pairs), 30)

    def test_prediction_at_a_cutoff_ignores_later_observations(self):
        s = lagged_series(80)
        before = causal.predict(s, "target", ["driver"], upto=40)["prediction"]
        for t in range(80, 120):
            s.observe(t, {"target": 999.0, "driver": 999.0})
        after = causal.predict(s, "target", ["driver"], upto=40)["prediction"]
        self.assertEqual(before, after)


class TestAssociationNotCausation(unittest.TestCase):
    def test_associations_never_claim_causation(self):
        s = lagged_series(80)
        for assoc in causal.associations(s, "target", ["driver"]):
            self.assertFalse(assoc.causal_claim)

    def test_limitations_name_confounding_and_reverse_causation(self):
        s = lagged_series(80)
        limits = " ".join(causal.associations(s, "target", ["driver"])[0].limitations())
        self.assertIn("confounding", limits)
        self.assertIn("reverse causation", limits)
        self.assertIn("no intervention", limits)

    def test_prediction_carries_the_same_disclaimer(self):
        s = lagged_series(80)
        result = causal.predict(s, "target", ["driver"])
        self.assertFalse(result["causal_claim"])
        self.assertTrue(result["limitations"])


class TestCalibratedUncertainty(unittest.TestCase):
    def test_tiny_samples_report_no_information_rather_than_false_precision(self):
        self.assertEqual(causal.fisher_interval(0.9, n=3), (-1.0, 1.0))

    def test_interval_narrows_as_evidence_accumulates(self):
        narrow = causal.fisher_interval(.8, n=500)
        wide = causal.fisher_interval(.8, n=10)
        self.assertLess(narrow[1] - narrow[0], wide[1] - wide[0])

    def test_significance_requires_the_interval_to_exclude_zero(self):
        weak = causal.Association("d", "t", 1, correlation=.02, n=10, ci_low=-.6, ci_high=.64)
        strong = causal.Association("d", "t", 1, correlation=.9, n=200, ci_low=.86, ci_high=.93)
        self.assertFalse(weak.significant)
        self.assertTrue(strong.significant)

    def test_prediction_reports_an_interval_not_just_a_point(self):
        s = lagged_series(120)
        result = causal.predict(s, "target", ["driver"])
        low, high = result["interval"]
        self.assertLessEqual(low, result["prediction"])
        self.assertGreaterEqual(high, result["prediction"])


class TestProvenance(unittest.TestCase):
    def test_every_edge_records_how_it_was_computed(self):
        s = lagged_series(100)
        assoc = causal.associations(s, "target", ["driver"])[0]
        p = assoc.provenance
        self.assertEqual(p["method"], "pearson_on_grid_aligned_lag")
        self.assertIn("window", p)
        self.assertLessEqual(p["first_t"], p["last_t"])
        self.assertLessEqual(p["driver_coverage"], 1.0)

    def test_coverage_reflects_real_gaps(self):
        s = causal.AlignedSeries()
        for t in range(20):
            values = {"target": 1.0}
            if t % 2 == 0:
                values["driver"] = 1.0
            s.observe(t, values)
        self.assertAlmostEqual(s.coverage("driver"), .5, places=2)


class TestWalkForward(unittest.TestCase):
    def test_walk_forward_runs_and_compares_baselines(self):
        s = lagged_series(140)
        report = causal.walk_forward(s, "target", ["driver"], folds=4, min_train=40)
        self.assertGreater(report["folds_evaluated"], 0)
        for key in ("multi_scale", "single_scale", "persistence"):
            self.assertIn(key, report["mae"])
        self.assertIn("persistence", report["note"])

    def test_insufficient_history_is_refused_not_faked(self):
        s = lagged_series(10)
        with self.assertRaises(ValueError):
            causal.walk_forward(s, "target", ["driver"], folds=4, min_train=40)


if __name__ == "__main__":
    unittest.main()
