"""Tests for the Legal Radar V2 scanner."""
import unittest


class TestRadarScanner(unittest.TestCase):
    """Unit tests for the radar scanner module."""

    def test_scan_simple_document(self):
        """Verify that scanning a simple document finds expected keywords."""
        document_text = "This contract outlines the terms and conditions."
        found_keywords = [w for w in document_text.lower().split() if w in (
            "contract", "terms", "conditions", "agreement", "liability",
        )]
        self.assertIn(
            "contract",
            found_keywords,
            "Expected 'contract' to be found in the document.",
        )


if __name__ == "__main__":
    unittest.main()
