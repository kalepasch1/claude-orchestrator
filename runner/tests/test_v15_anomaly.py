import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import hivemind_v15 as v15
import v15_anomaly as an

SCHEMA = an.FailureSchema(family="latency_spike", dimensions=4, scale=1.0)
HOLDOUT = an.FailureSchema(family="novel_family", dimensions=4, scale=1.0)
SAMPLE = [1.0, 2.0, 3.0, 4.0]
BENIGN = [[1.0, 2.0, 3.0, 4.0]] * 10


class TestPromotionAndDemotion(unittest.TestCase):
    def test_base_curriculum_only_ever_promotes(self):
        """The measurement bug this module fixes."""
        base = v15.AdversarialAnomalyCurriculum()
        for _ in range(64):
            base.record(False)          # a detector that catches nothing
        self.assertEqual(base.level, 1)  # never demotes, but also never adapts down
        for _ in range(64):
            base.record(True)
        self.assertGreater(base.level, 1)

    def test_mastery_promotes(self):
        c = an.Curriculum()
        for _ in range(an.WINDOW):
            c.record(True)
        self.assertEqual(c.level, 2)
        self.assertEqual(c.history[-1]["action"], "promote")

    def test_collapse_demotes(self):
        c = an.Curriculum()
        for _ in range(an.WINDOW):
            c.record(True)               # level 2
        for _ in range(an.WINDOW):
            c.record(False)              # detector degraded
        self.assertEqual(c.level, 1)
        self.assertEqual(c.history[-1]["action"], "demote")

    def test_level_never_drops_below_one(self):
        c = an.Curriculum()
        for _ in range(an.WINDOW * 4):
            c.record(False)
        self.assertEqual(c.level, 1)

    def test_middling_performance_holds_the_level(self):
        c = an.Curriculum()
        for i in range(an.WINDOW):
            c.record(i % 3 != 0)         # ~67%: between demote and promote
        self.assertEqual(c.level, 1)
        self.assertEqual(c.history, [])


class TestGenerationSafety(unittest.TestCase):
    def test_generation_uses_a_schema_not_a_raw_record(self):
        c = an.Curriculum()
        batch = c.generate(SCHEMA, SAMPLE, count=4)
        self.assertEqual(len(batch), 4)
        self.assertTrue(all(a.family == "latency_spike" for a in batch))

    def test_holdout_family_cannot_be_trained_on(self):
        c = an.Curriculum(holdout_families=("novel_family",))
        with self.assertRaises(ValueError) as ctx:
            c.generate(HOLDOUT, SAMPLE)
        self.assertIn("held out", str(ctx.exception))

    def test_provenance_is_immutable_and_verifiable(self):
        c = an.Curriculum(seed=5)
        a = c.generate(SCHEMA, SAMPLE, count=1)[0]
        self.assertTrue(a.verify(SCHEMA, 5))
        self.assertFalse(a.verify(HOLDOUT, 5))     # different schema
        self.assertFalse(a.verify(SCHEMA, 6))      # different seed

    def test_diversity_constraint_rejects_a_batch_of_clones(self):
        c = an.Curriculum()
        clone = an.Anomaly("f", 1, (1.0, 2.0), "p")
        self.assertEqual(c.diversity([clone] * 8), 1 / 8)
        self.assertEqual(c.diversity([]), 0.0)

    def test_generate_diverse_returns_a_varied_batch(self):
        c = an.Curriculum(seed=3)
        batch = c.generate_diverse(SCHEMA, SAMPLE, count=8, min_diversity=.5)
        self.assertGreaterEqual(c.diversity(batch), .5)


class TestFederatedPrivacy(unittest.TestCase):
    def test_cohort_below_k_is_suppressed_entirely(self):
        x = an.FederatedExchange(k=3)
        x.contribute("tomorrow", SCHEMA, .8, 100)
        x.contribute("galop", SCHEMA, .82, 100)
        report = x.aggregate()
        self.assertIn("latency_spike", report["suppressed"])
        self.assertEqual(report["families"], {})

    def test_cohort_at_k_is_published(self):
        x = an.FederatedExchange(k=3)
        for app in ("tomorrow", "galop", "smarter"):
            x.contribute(app, SCHEMA, .8, 100)
        report = x.aggregate()
        self.assertIn("latency_spike", report["families"])
        self.assertEqual(report["families"]["latency_spike"]["sources"], 3)

    def test_no_raw_vectors_are_ever_exchanged(self):
        x = an.FederatedExchange()
        x.contribute("tomorrow", SCHEMA, .8, 10)
        self.assertTrue(x.raw_leak_check())
        report = x.aggregate()
        # Inspect the DATA, not the prose: the explanatory note legitimately
        # contains the word "vectors".
        payload = repr({k: v for k, v in report.items() if k != "note"})
        self.assertNotIn("vector", payload)
        self.assertNotIn(str(SAMPLE), payload)

    def test_contributions_carry_no_vector_field_at_all(self):
        c = an.Contribution("tomorrow", SCHEMA, .8, 10)
        self.assertEqual(set(c.__dict__), {"source", "schema", "detection_rate", "samples"})

    def test_schema_digest_does_not_contain_the_family_payload(self):
        self.assertNotIn("latency", SCHEMA.digest())


class TestPoisonResistance(unittest.TestCase):
    def test_out_of_range_rate_is_refused(self):
        x = an.FederatedExchange()
        with self.assertRaises(an.Poisoned):
            x.contribute("tomorrow", SCHEMA, 5.0, 10)

    def test_unbacked_contribution_is_refused(self):
        x = an.FederatedExchange()
        with self.assertRaises(an.Poisoned):
            x.contribute("tomorrow", SCHEMA, .8, 0)

    def test_one_participant_cannot_flood_the_cohort(self):
        x = an.FederatedExchange(per_source_limit=3)
        for _ in range(3):
            x.contribute("tomorrow", SCHEMA, .8, 10)
        with self.assertRaises(an.Poisoned) as ctx:
            x.contribute("tomorrow", SCHEMA, .8, 10)
        self.assertIn("outvote", str(ctx.exception))

    def test_an_outlier_is_quarantined_not_averaged_in(self):
        x = an.FederatedExchange(k=3, outlier_sigma=1.5)
        for app in ("tomorrow", "galop", "smarter", "vigil"):
            x.contribute(app, SCHEMA, .80, 100)
        x.contribute("trojun", SCHEMA, .01, 100)      # the poisoned claim
        report = x.aggregate()
        family = report["families"]["latency_spike"]
        self.assertEqual(family["quarantined"], 1)
        self.assertGreater(family["mean_detection_rate"], .7)
        self.assertEqual(report["quarantined"][0]["source"], "trojun")


class TestHonestMetrics(unittest.TestCase):
    def test_evaluate_reports_all_four_counts(self):
        c = an.Curriculum()
        anomalies = c.generate(SCHEMA, SAMPLE, count=10)
        report = an.evaluate(lambda v: sum(v) != sum(SAMPLE), anomalies, BENIGN)
        for key in ("true_positives", "false_negatives", "false_positives", "true_negatives"):
            self.assertIn(key, report)
        self.assertEqual(report["true_positives"] + report["false_negatives"], 10)
        self.assertEqual(report["false_positives"] + report["true_negatives"], len(BENIGN))

    def test_report_contains_no_single_headline_accuracy(self):
        c = an.Curriculum()
        report = an.evaluate(lambda v: True, c.generate(SCHEMA, SAMPLE, 5), BENIGN)
        self.assertNotIn("accuracy", report)
        self.assertNotIn("improvement", report)
        self.assertIn("precision", report)
        self.assertIn("recall", report)

    def test_always_true_detector_is_exposed_by_the_false_positive_rate(self):
        c = an.Curriculum()
        report = an.evaluate(lambda v: True, c.generate(SCHEMA, SAMPLE, 5), BENIGN)
        self.assertEqual(report["recall"], 1.0)          # looks perfect alone
        self.assertEqual(report["false_positive_rate"], 1.0)   # and is useless

    def test_holdout_evaluation_requires_a_registered_holdout(self):
        c = an.Curriculum(holdout_families=("novel_family",))
        with self.assertRaises(ValueError):
            an.holdout_evaluation(c, lambda v: True, SCHEMA, SAMPLE, BENIGN)

    def test_holdout_evaluation_scores_an_untrained_family(self):
        c = an.Curriculum(holdout_families=("novel_family",))
        report = an.holdout_evaluation(c, lambda v: sum(v) != sum(SAMPLE),
                                       HOLDOUT, SAMPLE, BENIGN, count=8)
        self.assertTrue(report["held_out"])
        self.assertEqual(report["family"], "novel_family")
        self.assertEqual(report["true_positives"] + report["false_negatives"], 8)


class TestCalibration(unittest.TestCase):
    def test_threshold_meets_the_target_false_positive_rate(self):
        benign_scores = [float(i) for i in range(100)]
        cut = an.calibrated_threshold(benign_scores, target_fpr=.05)
        fpr = sum(1 for s in benign_scores if s > cut) / len(benign_scores)
        self.assertLessEqual(fpr, .06)

    def test_calibration_refuses_empty_or_impossible_input(self):
        with self.assertRaises(ValueError):
            an.calibrated_threshold([], target_fpr=.05)
        with self.assertRaises(ValueError):
            an.calibrated_threshold([1.0], target_fpr=0.0)


if __name__ == "__main__":
    unittest.main()
