"""Tests for predictive_queue — predictive queue generation."""
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Stub db before importing the module
fake_db = MagicMock()
fake_db.select.return_value = []
fake_db.insert.return_value = None
fake_db.update.return_value = None
with patch.dict(sys.modules, {"db": fake_db}):
    import predictive_queue


class TestPredictiveQueueStats(unittest.TestCase):
    def test_stats_returns_dict(self):
        result = predictive_queue.stats()
        self.assertIsInstance(result, dict)


class TestPredictDisabled(unittest.TestCase):
    def test_predict_disabled_by_default(self):
        # ORCH_PREDICTIVE_QUEUE_ENABLED defaults to false
        with patch.object(predictive_queue, "ENABLED", False):
            with patch.object(predictive_queue, "db") as mdb:
                result = predictive_queue.generate_speculative_tasks("p1", "proj", "/tmp")
                self.assertEqual(result, 0)


class TestScanTodos(unittest.TestCase):
    def test_scan_todos_nonexistent_repo(self):
        result = predictive_queue.scan_todos("/nonexistent/path")
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 0)


class TestConfirmPrediction(unittest.TestCase):
    def test_confirm_prediction_no_raise(self):
        with patch.object(predictive_queue, "db") as mdb:
            mdb.update.return_value = None
            # Should not raise
            predictive_queue.confirm_prediction("t1")


if __name__ == "__main__":
    unittest.main()
