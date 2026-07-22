"""Tests for error_taxonomy.py fail-soft error classification.

Validates that:
  - Known error patterns are classified correctly
  - Unknown errors fall through to 'escalate_model'
  - Classification never raises (fail-soft guarantee)
  - Remediation mapping is complete
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import error_taxonomy


class TestErrorClassification(unittest.TestCase):
    """Verify classify() routes known error strings to the right class."""

    def test_rate_limit_429(self):
        result = error_taxonomy.classify("HTTP 429 Too Many Requests")
        self.assertEqual(result["error_class"], "rate_limit")

    def test_test_failure(self):
        result = error_taxonomy.classify("FAILED: test_login AssertionError")
        self.assertEqual(result["error_class"], "test_failure")

    def test_merge_conflict(self):
        result = error_taxonomy.classify("CONFLICT (content): merge conflict in foo.py")
        self.assertEqual(result["error_class"], "merge_conflict")

    def test_import_error(self):
        result = error_taxonomy.classify("ModuleNotFoundError: No module named 'flask'")
        self.assertEqual(result["error_class"], "import_error")

    def test_syntax_error(self):
        result = error_taxonomy.classify("SyntaxError: unexpected token '}'")
        self.assertEqual(result["error_class"], "syntax_error")

    def test_timeout(self):
        result = error_taxonomy.classify("Process timed out after 300s")
        self.assertEqual(result["error_class"], "timeout")

    def test_build_failure(self):
        result = error_taxonomy.classify("npm ERR! Build failed with exit code 1")
        self.assertEqual(result["error_class"], "build_failure")

    def test_permission_error(self):
        result = error_taxonomy.classify("Permission denied: EACCES /var/log")
        self.assertEqual(result["error_class"], "permission_error")

    def test_unknown_error(self):
        result = error_taxonomy.classify("something completely unknown happened")
        self.assertEqual(result["error_class"], "unknown")
        self.assertEqual(result["remediation"], "escalate_model")


class TestFailSoftGuarantee(unittest.TestCase):
    """Classify must never raise, regardless of input."""

    def test_none_input(self):
        result = error_taxonomy.classify(None)
        self.assertIn("error_class", result)

    def test_empty_string(self):
        result = error_taxonomy.classify("")
        self.assertIn("error_class", result)

    def test_integer_input(self):
        result = error_taxonomy.classify(42)
        self.assertIn("error_class", result)

    def test_huge_input(self):
        result = error_taxonomy.classify("x" * 100000)
        self.assertIn("error_class", result)


class TestRemediationMapping(unittest.TestCase):
    """Every classified error must map to a valid remediation."""

    def test_all_classes_have_remediation(self):
        for err_cls in error_taxonomy._CLASS_TO_REMEDIATION:
            remediation = error_taxonomy._CLASS_TO_REMEDIATION[err_cls]
            self.assertIsInstance(remediation, str)
            self.assertTrue(len(remediation) > 0)

    def test_classify_always_returns_remediation(self):
        for text in ["429", "CONFLICT", "SyntaxError", "unknown"]:
            result = error_taxonomy.classify(text)
            self.assertIn("remediation", result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
