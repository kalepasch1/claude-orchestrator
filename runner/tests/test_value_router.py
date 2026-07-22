"""Tests for value_router module."""

import unittest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from runner.value_router import estimate_value, route_task, route_batch, QUEUE_HIGH, QUEUE_MEDIUM, QUEUE_LOW


class TestEstimateValue(unittest.TestCase):
    def test_empty_task(self):
        self.assertEqual(estimate_value({}), 0.0)

    def test_none_task(self):
        self.assertEqual(estimate_value(None), 0.0)

    def test_critical_priority(self):
        task = {"priority": "critical", "description": "fix outage"}
        self.assertGreaterEqual(estimate_value(task), 90)

    def test_low_priority(self):
        task = {"priority": "low", "description": "fix typo in readme"}
        self.assertLessEqual(estimate_value(task), 35)

    def test_high_keywords_boost(self):
        task = {"description": "security regression in production"}
        self.assertGreater(estimate_value(task), 70)

    def test_low_keywords_reduce(self):
        task = {"description": "chore: cleanup lint formatting"}
        self.assertLess(estimate_value(task), 50)

    def test_explicit_score(self):
        task = {"value_score": 95}
        self.assertGreaterEqual(estimate_value(task), 90)

    def test_score_clamped(self):
        task = {"value_score": 200, "description": "security outage critical"}
        self.assertLessEqual(estimate_value(task), 100)

    def test_score_floor(self):
        task = {"value_score": -50, "description": "chore docs typo cleanup lint"}
        self.assertGreaterEqual(estimate_value(task), 0)


class TestRouteTask(unittest.TestCase):
    def test_high_value_routes_high(self):
        result = route_task({"priority": "critical"})
        self.assertEqual(result["queue"], QUEUE_HIGH)

    def test_low_value_routes_low(self):
        result = route_task({"priority": "low", "description": "typo docs"})
        self.assertEqual(result["queue"], QUEUE_LOW)

    def test_medium_value_routes_medium(self):
        result = route_task({"description": "add feature"})
        self.assertEqual(result["queue"], QUEUE_MEDIUM)

    def test_result_contains_task(self):
        task = {"id": 42}
        result = route_task(task)
        self.assertEqual(result["task"], task)


class TestRouteBatch(unittest.TestCase):
    def test_empty_batch(self):
        result = route_batch([])
        self.assertEqual(result[QUEUE_HIGH], [])
        self.assertEqual(result[QUEUE_LOW], [])

    def test_mixed_batch(self):
        tasks = [
            {"priority": "critical"},
            {"priority": "low", "description": "typo"},
            {"description": "normal task"},
        ]
        result = route_batch(tasks)
        total = sum(len(v) for v in result.values())
        self.assertEqual(total, 3)


if __name__ == "__main__":
    unittest.main()
