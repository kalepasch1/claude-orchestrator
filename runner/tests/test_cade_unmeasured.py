"""An app with no CADE telemetry must report unmeasured, not a confident 50.0.

compliance_periodic feeds throughput / backlog / completion_rate; cade_scorecard scores
win_rate_lift / calibration_gap / alignment_recall / alignment_surprise /
override_failure_rate. Every lookup missed and defaulted to 0.0, and because the three
"lower is better" dimensions carry exactly 0.50 of the weight and score 100 on a raw of
0.0, the composite came out at 25 + 10 + 15 = 50.00 for every app, every time -- 292
samples across 16 projects, all identical. A constant series has zero variance, so the
z-score anomaly detector could never flag it, and weakest_app tied on every project and
fell back to alphabetical order.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import cade_scorecard as cs  # noqa: E402

FLEET_TELEMETRY = {"throughput": 12.0, "backlog": 300.0, "completion_rate": 0.4}
REAL = {"win_rate_lift": 0.12, "calibration_gap": 0.1, "alignment_recall": 0.8,
        "alignment_surprise": 0.2, "override_failure_rate": 0.05}


class UnmeasuredAppTests(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("ORCH_CADE_STRICT_DIMENSIONS", None)

    def test_the_exact_50_point_0_bug(self):
        """Reproduce the old arithmetic, then assert we no longer report it as a score."""
        os.environ["ORCH_CADE_STRICT_DIMENSIONS"] = "false"
        legacy = cs.score_app(FLEET_TELEMETRY)
        self.assertEqual(legacy["composite"], 50.0,
                         "the historical value should still be reproducible with the flag off")

        os.environ["ORCH_CADE_STRICT_DIMENSIONS"] = "true"
        strict = cs.score_app(FLEET_TELEMETRY)
        self.assertIsNone(strict["composite"])
        self.assertTrue(strict["unmeasured"])
        self.assertEqual(len(strict["missing_dimensions"]), 5)

    def test_empty_telemetry_is_unmeasured(self):
        r = cs.score_app({})
        self.assertIsNone(r["composite"])
        self.assertTrue(r["unmeasured"])

    def test_real_telemetry_still_scores(self):
        r = cs.score_app(REAL)
        self.assertIsInstance(r["composite"], float)
        self.assertGreater(r["composite"], 0)
        self.assertLessEqual(r["composite"], 100)
        self.assertEqual(r["missing_dimensions"], [])
        self.assertNotIn("unmeasured", r)

    def test_partial_telemetry_still_scores(self):
        """One real dimension is thin evidence, but it is evidence. Unchanged behaviour."""
        r = cs.score_app({"win_rate_lift": 0.5})
        self.assertIsNotNone(r["composite"])
        self.assertEqual(len(r["missing_dimensions"]), 4)

    def test_two_unmeasured_apps_do_not_tie_at_50(self):
        """The tie is what made weakest_app fall back to alphabetical order."""
        a, b = cs.score_app({}), cs.score_app(FLEET_TELEMETRY)
        self.assertIsNone(a["composite"])
        self.assertIsNone(b["composite"])


if __name__ == "__main__":
    unittest.main()
