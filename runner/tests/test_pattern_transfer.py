"""Tests for pattern_transfer — cross-project pattern transfer."""
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Stub db before importing the module
fake_db = MagicMock()
fake_db.select.return_value = []
with patch.dict(sys.modules, {"db": fake_db}):
    import pattern_transfer


class TestPatternTransferStats(unittest.TestCase):
    def test_stats_returns_dict(self):
        result = pattern_transfer.stats()
        self.assertIsInstance(result, dict)
        self.assertIn("transfers_attempted", result)


class TestDetectSimilarity(unittest.TestCase):
    def test_detect_similarity_same_project(self):
        with patch.object(pattern_transfer, "db") as mdb:
            mdb.select.return_value = []
            result = pattern_transfer.detect_similarity("p1", "p1")
            self.assertIsInstance(result, dict)
            self.assertIn("similarity", result)


class TestFindTransferable(unittest.TestCase):
    def test_find_transferable_no_data(self):
        with patch.object(pattern_transfer, "db") as mdb:
            mdb.select.return_value = []
            result = pattern_transfer.find_transferable("p1", "p2")
            self.assertIsInstance(result, list)
            self.assertEqual(len(result), 0)


if __name__ == "__main__":
    unittest.main()
