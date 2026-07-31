import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import autoscale_signal as asc


class ThroughputSignalTest(unittest.TestCase):
    def test_returns_expected_keys(self):
        with patch.object(asc.db, "select", return_value=[]), \
             patch.object(asc.db, "count", return_value=0):
            result = asc.throughput_signal()
        for key in ["tasks_completed", "tasks_per_hour", "bottleneck"]:
            self.assertIn(key, result)

    def test_compute_bottleneck_when_queue_deep(self):
        tasks = [{"id": f"t{i}", "state": "DONE"} for i in range(5)]
        with patch.object(asc.db, "select", return_value=tasks), \
             patch.object(asc.db, "count", side_effect=[50, 3]):
            result = asc.throughput_signal()
        self.assertEqual(result["bottleneck"], "compute")

    def test_queue_empty_bottleneck(self):
        with patch.object(asc.db, "select", return_value=[]), \
             patch.object(asc.db, "count", side_effect=[1, 0]):
            result = asc.throughput_signal()
        self.assertEqual(result["bottleneck"], "queue_empty")


class ElasticRecommendationTest(unittest.TestCase):
    def test_hold_when_balanced(self):
        with patch.object(asc, "run", return_value={"recommend": 0, "weighted_demand": 5}), \
             patch.object(asc, "throughput_signal", return_value={
                 "bottleneck": "balanced", "queue_depth": 5, "running": 2, "tasks_per_hour": 10
             }):
            result = asc.elastic_recommendation()
        self.assertEqual(result["action"], "hold")

    def test_scale_down_when_empty(self):
        with patch.object(asc, "run", return_value={"recommend": 0, "weighted_demand": 1}), \
             patch.object(asc, "throughput_signal", return_value={
                 "bottleneck": "queue_empty", "queue_depth": 0, "running": 0, "tasks_per_hour": 0
             }):
            result = asc.elastic_recommendation()
        self.assertEqual(result["action"], "scale_down")


if __name__ == "__main__":
    unittest.main()
