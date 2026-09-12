"""should_auto_approve() decides whether a config change ships without a human.

The comparison used to be inline in evaluate_change() as `risk <= THRESHOLD`,
so it had no name, no tests and no way to source the threshold from a reviewable
file. These cover the boundary in both directions — the case an inline
comparison makes easiest to get silently wrong — and pin the fail-closed
behaviour, because on this gate "unparseable" must mean "ask a human", never
"allow".
"""
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config_approval_engine as engine


class TestShouldAutoApproveBoundary(unittest.TestCase):
    def setUp(self):
        # Pin the threshold so these do not depend on the committed yaml or env.
        self._patch = patch.object(engine, "_low_risk_threshold", return_value=0.3)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()

    def test_below_the_threshold_is_approved(self):
        self.assertTrue(engine.should_auto_approve(0.0))
        self.assertTrue(engine.should_auto_approve(0.1))
        self.assertTrue(engine.should_auto_approve(0.29))

    def test_exactly_at_the_threshold_is_approved(self):
        # Inclusive on purpose: this is the pre-existing behaviour, and tightening
        # it would silently start sending previously-approved changes to a human.
        self.assertTrue(engine.should_auto_approve(0.3))

    def test_just_above_the_threshold_is_refused(self):
        self.assertFalse(engine.should_auto_approve(0.30001))
        self.assertFalse(engine.should_auto_approve(0.31))
        self.assertFalse(engine.should_auto_approve(1.0))

    def test_numeric_strings_are_accepted(self):
        self.assertTrue(engine.should_auto_approve("0.2"))
        self.assertFalse(engine.should_auto_approve("0.9"))

    def test_bad_input_fails_closed(self):
        for bad in (None, "", "high", [], {}, object()):
            self.assertFalse(engine.should_auto_approve(bad), repr(bad))

    def test_nan_fails_closed(self):
        # NaN <= x is False, but relying on that by accident is not the same as
        # deciding it: a score that is not a number must reach a human.
        self.assertFalse(engine.should_auto_approve(float("nan")))

    def test_infinity_is_refused_and_negative_infinity_is_not_special_cased(self):
        self.assertFalse(engine.should_auto_approve(float("inf")))
        self.assertTrue(engine.should_auto_approve(float("-inf")))


class TestThresholdSource(unittest.TestCase):
    def _threshold_with(self, text):
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as fh:
            fh.write(text)
            path = fh.name
        try:
            with patch.object(engine, "RISK_CONFIG_PATH", path):
                return engine._low_risk_threshold()
        finally:
            os.unlink(path)

    def test_yaml_thresholds_block_is_read(self):
        self.assertEqual(self._threshold_with("thresholds:\n  low_risk: 0.55\n"), 0.55)

    def test_flat_key_is_also_accepted(self):
        self.assertEqual(self._threshold_with("low_risk: 0.45\n"), 0.45)

    def test_a_missing_file_falls_back_to_the_env_default(self):
        with patch.object(engine, "RISK_CONFIG_PATH", "/nonexistent/risk_config.yaml"):
            self.assertEqual(engine._low_risk_threshold(), engine.AUTO_APPROVE_THRESHOLD)

    def test_malformed_yaml_falls_back_rather_than_raising(self):
        self.assertEqual(self._threshold_with("thresholds: [unclosed\n"),
                         engine.AUTO_APPROVE_THRESHOLD)

    def test_an_out_of_range_value_is_rejected(self):
        # A config saying 5.0 would auto-approve everything; refuse it.
        self.assertEqual(self._threshold_with("thresholds:\n  low_risk: 5.0\n"),
                         engine.AUTO_APPROVE_THRESHOLD)
        self.assertEqual(self._threshold_with("thresholds:\n  low_risk: -1\n"),
                         engine.AUTO_APPROVE_THRESHOLD)

    def test_the_committed_config_matches_the_previous_inline_default(self):
        # Committing the file must not change behaviour on its own.
        self.assertEqual(engine._low_risk_threshold(), 0.3)


class TestEvaluateChangeStillUsesTheGate(unittest.TestCase):
    def test_evaluate_change_routes_through_should_auto_approve(self):
        # Guards against the helper being added and then bypassed by a later edit.
        with patch.object(engine, "should_auto_approve", return_value=False) as gate:
            result = engine.evaluate_change("ORCH_HARMLESS", "1", "2")
        gate.assert_called_once()
        self.assertFalse(result["approved"])
        self.assertTrue(result["requires_human"])

    def test_approved_and_requires_human_stay_opposites(self):
        result = engine.evaluate_change("ORCH_HARMLESS", "1", "2")
        self.assertIs(result["requires_human"], not result["approved"])


if __name__ == "__main__":
    unittest.main()
