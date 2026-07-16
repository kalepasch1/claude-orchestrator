import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config_validator as cv


class ValidateValueTest(unittest.TestCase):
    def test_valid_bool(self):
        self.assertEqual(cv.validate_value("ORCH_QUEUE_ELIMINATION", "true"), (True, None))
        self.assertEqual(cv.validate_value("ORCH_QUEUE_ELIMINATION", "false"), (True, None))
        self.assertEqual(cv.validate_value("ORCH_QUEUE_ELIMINATION", "1"), (True, None))

    def test_invalid_bool(self):
        valid, err = cv.validate_value("ORCH_QUEUE_ELIMINATION", "maybe")
        self.assertFalse(valid)
        self.assertIn("expected bool", err)

    def test_valid_int_in_range(self):
        self.assertEqual(cv.validate_value("ORCH_ELIM_SCAN_LIMIT", "50"), (True, None))

    def test_int_below_min(self):
        valid, err = cv.validate_value("ORCH_ELIM_SCAN_LIMIT", "0")
        self.assertFalse(valid)
        self.assertIn("below minimum", err)

    def test_int_above_max(self):
        valid, err = cv.validate_value("ORCH_ELIM_SCAN_LIMIT", "999")
        self.assertFalse(valid)
        self.assertIn("above maximum", err)

    def test_valid_float(self):
        self.assertEqual(cv.validate_value("ORCH_ELIM_MIN_CONF", "0.9"), (True, None))

    def test_float_out_of_range(self):
        valid, err = cv.validate_value("ORCH_ELIM_MIN_CONF", "1.5")
        self.assertFalse(valid)

    def test_unknown_key_passes(self):
        self.assertEqual(cv.validate_value("UNKNOWN_KEY", "anything"), (True, None))


class ValidateBatchTest(unittest.TestCase):
    def test_all_valid(self):
        config = {"ORCH_QUEUE_ELIMINATION": "true", "ORCH_ELIM_SCAN_LIMIT": "10"}
        valid, errors = cv.validate_batch(config)
        self.assertTrue(valid)
        self.assertEqual(errors, [])

    def test_mixed_valid_invalid(self):
        config = {"ORCH_QUEUE_ELIMINATION": "true", "ORCH_ELIM_SCAN_LIMIT": "0"}
        valid, errors = cv.validate_batch(config)
        self.assertFalse(valid)
        self.assertEqual(len(errors), 1)


if __name__ == "__main__":
    unittest.main()
