import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config_drift


class ConfigHashTest(unittest.TestCase):
    def test_consistent_hash(self):
        rows = [{"key": "A", "value": "1"}]
        with patch.object(config_drift.db, "select", return_value=rows):
            h1 = config_drift._config_hash()
            h2 = config_drift._config_hash()
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), 16)

    def test_different_data_different_hash(self):
        with patch.object(config_drift.db, "select", return_value=[{"key": "A", "value": "1"}]):
            h1 = config_drift._config_hash()
        with patch.object(config_drift.db, "select", return_value=[{"key": "A", "value": "2"}]):
            h2 = config_drift._config_hash()
        self.assertNotEqual(h1, h2)


class CheckDriftTest(unittest.TestCase):
    def test_no_drift_returns_empty(self):
        with patch.object(config_drift, "_config_hash", return_value="abc"), \
             patch.object(config_drift, "_executor_hashes", return_value=[
                 {"key": "COWORK_EXECUTOR_1_LAST_RUN", "value": '{"config_hash": "abc"}'}
             ]):
            result = config_drift.check()
        self.assertEqual(result, [])

    def test_drift_detected(self):
        with patch.object(config_drift, "_config_hash", return_value="abc"), \
             patch.object(config_drift, "_executor_hashes", return_value=[
                 {"key": "COWORK_EXECUTOR_1_LAST_RUN", "value": '{"config_hash": "xyz"}'}
             ]):
            result = config_drift.check()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["expected"], "abc")
        self.assertEqual(result[0]["reported"], "xyz")

    def test_missing_hash_not_flagged(self):
        with patch.object(config_drift, "_config_hash", return_value="abc"), \
             patch.object(config_drift, "_executor_hashes", return_value=[
                 {"key": "COWORK_EXECUTOR_1_LAST_RUN", "value": '{"ts": "now"}'}
             ]):
            result = config_drift.check()
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
