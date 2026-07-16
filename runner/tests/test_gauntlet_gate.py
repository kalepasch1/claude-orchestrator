import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gauntlet_gate


class TestDecideEntry(unittest.TestCase):

    def setUp(self):
        gauntlet_gate.reset_stats()
        # Clear env var so default applies
        os.environ.pop("ORCH_GAUNTLET_ADMIT_FLOOR", None)

    def test_confidence_at_floor_admits(self):
        """confidence == 0.50 (default floor) → admit."""
        result = gauntlet_gate.decide_entry({"confidence": 0.50})
        self.assertEqual(result["decision"], "admit")

    def test_confidence_above_floor_admits(self):
        result = gauntlet_gate.decide_entry({"confidence": 0.85})
        self.assertEqual(result["decision"], "admit")

    def test_confidence_below_floor_human_review(self):
        """confidence 0.49 < 0.50 default floor → human_review."""
        result = gauntlet_gate.decide_entry({"confidence": 0.49})
        self.assertEqual(result["decision"], "human_review")

    def test_zero_confidence_human_review(self):
        result = gauntlet_gate.decide_entry({"confidence": 0.0})
        self.assertEqual(result["decision"], "human_review")

    def test_hard_failure_citation_rejects(self):
        """Unresolved citation forces reject regardless of confidence."""
        result = gauntlet_gate.decide_entry({
            "confidence": 0.99,
            "failures": [{"type": "unresolved_citation"}],
        })
        self.assertEqual(result["decision"], "reject")
        self.assertIn("unresolved_citation", result["reason"])

    def test_hard_failure_source_rejects(self):
        result = gauntlet_gate.decide_entry({
            "confidence": 0.80,
            "failures": [{"type": "unresolved_source"}],
        })
        self.assertEqual(result["decision"], "reject")

    def test_hard_failure_precedent_rejects(self):
        result = gauntlet_gate.decide_entry({
            "confidence": 0.75,
            "unresolved_precedent": True,
        })
        self.assertEqual(result["decision"], "reject")

    def test_hard_failure_overrides_high_confidence(self):
        """Even confidence=1.0 gets rejected on hard failure."""
        result = gauntlet_gate.decide_entry({
            "confidence": 1.0,
            "failures": [{"type": "unresolved_citation"}],
        })
        self.assertEqual(result["decision"], "reject")

    def test_custom_threshold_via_env_var(self):
        """ORCH_GAUNTLET_ADMIT_FLOOR env var overrides default."""
        os.environ["ORCH_GAUNTLET_ADMIT_FLOOR"] = "0.80"
        try:
            # 0.79 < 0.80 → human_review
            r1 = gauntlet_gate.decide_entry({"confidence": 0.79})
            self.assertEqual(r1["decision"], "human_review")
            # 0.80 >= 0.80 → admit
            r2 = gauntlet_gate.decide_entry({"confidence": 0.80})
            self.assertEqual(r2["decision"], "admit")
        finally:
            os.environ.pop("ORCH_GAUNTLET_ADMIT_FLOOR", None)

    def test_custom_threshold_via_arg(self):
        """thresholds dict overrides env var."""
        os.environ["ORCH_GAUNTLET_ADMIT_FLOOR"] = "0.90"
        try:
            result = gauntlet_gate.decide_entry(
                {"confidence": 0.60},
                thresholds={"admit_floor": 0.55},
            )
            self.assertEqual(result["decision"], "admit")
        finally:
            os.environ.pop("ORCH_GAUNTLET_ADMIT_FLOOR", None)

    def test_stats_output(self):
        """stats() returns correct counters after decisions."""
        gauntlet_gate.decide_entry({"confidence": 0.80})  # admit
        gauntlet_gate.decide_entry({"confidence": 0.30})  # human_review
        gauntlet_gate.decide_entry({
            "confidence": 0.99,
            "failures": [{"type": "unresolved_citation"}],
        })  # reject
        s = gauntlet_gate.stats()
        self.assertEqual(s["decisions"], 3)
        self.assertEqual(s["admits"], 1)
        self.assertEqual(s["human_reviews"], 1)
        self.assertEqual(s["rejects"], 1)
        self.assertEqual(s["hard_failures"], 1)

    def test_fail_soft_on_bad_input(self):
        """Malformed input routes to human_review, not crash."""
        result = gauntlet_gate.decide_entry(None)
        self.assertEqual(result["decision"], "human_review")
        self.assertIn("fail-soft", result["reason"])


if __name__ == "__main__":
    unittest.main()
