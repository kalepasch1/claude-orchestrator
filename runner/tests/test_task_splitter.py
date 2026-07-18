"""Tests for task_splitter module."""

import unittest
import sys
import os



from runner.task_splitter import estimate_complexity, split_task, _extract_title


class TestEstimateComplexity(unittest.TestCase):
    def test_empty_string(self):
        self.assertEqual(estimate_complexity(""), "low")

    def test_none_input(self):
        self.assertEqual(estimate_complexity(None), "low")

    def test_simple_task(self):
        self.assertEqual(estimate_complexity("Fix a typo"), "low")

    def test_medium_task(self):
        result = estimate_complexity("Add a new endpoint and implement caching")
        self.assertIn(result, ("medium", "high"))

    def test_high_complexity(self):
        desc = "Refactor and migrate the entire database layer, redesign the schema"
        self.assertEqual(estimate_complexity(desc), "high")

    def test_long_description_boosts(self):
        desc = " ".join(["word"] * 120)
        result = estimate_complexity(desc)
        self.assertIn(result, ("medium", "high"))


class TestSplitTask(unittest.TestCase):
    def test_empty_input(self):
        self.assertEqual(split_task(""), [])

    def test_none_input(self):
        self.assertEqual(split_task(None), [])

    def test_single_sentence(self):
        result = split_task("Fix the login bug.")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["order"], 1)

    def test_multiple_sentences(self):
        desc = ("Refactor auth module. Add rate limiting. "
                "Create integration tests. Update docs.")
        result = split_task(desc)
        self.assertGreaterEqual(len(result), 1)
        for st in result:
            self.assertIn("title", st)
            self.assertIn("description", st)
            self.assertIn("complexity", st)
            self.assertIn("order", st)

    def test_max_subtasks_respected(self):
        desc = ". ".join([f"Task number {i}" for i in range(20)])
        result = split_task(desc, max_subtasks=3)
        self.assertLessEqual(len(result), 3)

    def test_orders_sequential(self):
        desc = "Step A. Step B. Step C. Step D."
        result = split_task(desc)
        orders = [st["order"] for st in result]
        self.assertEqual(orders, list(range(1, len(orders) + 1)))

    def test_whitespace_only(self):
        self.assertEqual(split_task("   "), [])


class TestExtractTitle(unittest.TestCase):
    def test_short_text(self):
        self.assertEqual(_extract_title("Fix bug"), "Fix bug")

    def test_long_text_truncated(self):
        long_text = "A" * 100
        result = _extract_title(long_text, max_len=20)
        self.assertTrue(len(result) <= 24)  # max_len + "..."

    def test_empty(self):
        self.assertEqual(_extract_title(""), "Untitled")


if __name__ == "__main__":
    unittest.main()
