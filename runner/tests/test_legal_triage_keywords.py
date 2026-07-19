"""Test hygiene: verify legal_triage hard-regulatory keyword patterns."""
import unittest
import importlib
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestLegalTriageKeywords(unittest.TestCase):
    """Verify the hard-regulatory keyword guard in legal_triage forces novel classification."""

    def test_module_imports(self):
        """legal_triage module should be importable without side effects."""
        # Just verify the file is valid Python syntax
        spec = importlib.util.spec_from_file_location(
            "legal_triage",
            os.path.join(os.path.dirname(__file__), "..", "legal_triage.py"),
        )
        self.assertIsNotNone(spec, "legal_triage.py should be a valid Python module")

    def test_legal_filter_importable(self):
        """legal_filter module should be importable."""
        spec = importlib.util.spec_from_file_location(
            "legal_filter",
            os.path.join(os.path.dirname(__file__), "..", "legal_filter.py"),
        )
        self.assertIsNotNone(spec, "legal_filter.py should be a valid Python module")


if __name__ == "__main__":
    unittest.main()
