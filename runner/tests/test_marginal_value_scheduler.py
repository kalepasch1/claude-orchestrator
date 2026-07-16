"""
test_marginal_value_scheduler.py — marginal-value task ranking tests.

Covers:
  - High priority short task ranks above low priority long task
  - Equal priority tasks ranked by shorter duration
  - Zero/negative duration handled safely
  - Batch selection returns correct count
  - Empty task list handled gracefully
  - Stats output
  - Disabled via env flag
"""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _task(**over):
    t = {"id": "t1", "priority_weight": 50, "duration_estimate": 1}
    t.update(over)
    return t


class TestCalculateMarginalValue(unittest.TestCase):

    def test_high_priority_short_ranks_above_low_priority_long(self):
        import marginal_value_scheduler as mvs
        high_short = _task(priority_weight=100, duration_estimate=1)
        low_long = _task(priority_weight=25, duration_estimate=10)
        self.assertGreater(
            mvs.calculate_marginal_value(high_short),
            mvs.calculate_marginal_value(low_long),
        )

    def test_equal_priority_shorter_duration_wins(self):
        import marginal_value_scheduler as mvs
        short = _task(priority_weight=50, duration_estimate=2)
        long = _task(priority_weight=50, duration_estimate=10)
        self.assertGreater(
            mvs.calculate_marginal_value(short),
            mvs.calculate_marginal_value(long),
        )

    def test_zero_duration_handled_safely(self):
        import marginal_value_scheduler as mvs
        t = _task(priority_weight=80, duration_estimate=0)
        val = mvs.calculate_marginal_value(t)
        # duration clamped to 1 → value = 80 / 1 = 80
        self.assertAlmostEqual(val, 80.0)

    def test_negative_duration_handled_safely(self):
        import marginal_value_scheduler as mvs
        t = _task(priority_weight=60, duration_estimate=-5)
        val = mvs.calculate_marginal_value(t)
        # duration clamped to 1 → value = 60 / 1 = 60
        self.assertAlmostEqual(val, 60.0)


class TestRankTasks(unittest.TestCase):

    def test_ranking_order(self):
        import marginal_value_scheduler as mvs
        tasks = [
            _task(id="low", priority_weight=10, duration_estimate=10),
            _task(id="high", priority_weight=100, duration_estimate=1),
            _task(id="mid", priority_weight=50, duration_estimate=5),
        ]
        ranked = mvs.rank_tasks(tasks)
        ids = [r["task"]["id"] for r in ranked]
        self.assertEqual(ids, ["high", "mid", "low"])
        # Each entry carries its marginal_value
        self.assertIn("marginal_value", ranked[0])

    def test_empty_list(self):
        import marginal_value_scheduler as mvs
        self.assertEqual(mvs.rank_tasks([]), [])
        self.assertEqual(mvs.rank_tasks(None), [])


class TestSelectNextBatch(unittest.TestCase):

    def test_batch_returns_correct_count(self):
        import marginal_value_scheduler as mvs
        tasks = [_task(id=f"t{i}", priority_weight=i * 10, duration_estimate=1)
                 for i in range(1, 11)]
        batch = mvs.select_next_batch(tasks, batch_size=3)
        self.assertEqual(len(batch), 3)
        # Top 3 by weight: t10, t9, t8
        ids = [r["task"]["id"] for r in batch]
        self.assertEqual(ids, ["t10", "t9", "t8"])

    def test_batch_smaller_than_list(self):
        import marginal_value_scheduler as mvs
        tasks = [_task(id="a"), _task(id="b")]
        batch = mvs.select_next_batch(tasks, batch_size=5)
        self.assertEqual(len(batch), 2)

    def test_batch_empty_input(self):
        import marginal_value_scheduler as mvs
        self.assertEqual(mvs.select_next_batch([]), [])
        self.assertEqual(mvs.select_next_batch(None), [])


class TestStats(unittest.TestCase):

    def test_stats_returns_dict(self):
        import marginal_value_scheduler as mvs
        s = mvs.stats()
        self.assertIsInstance(s, dict)
        self.assertIn("tasks_scored", s)
        self.assertIn("tasks_ranked", s)
        self.assertIn("batches_selected", s)


class TestFeatureFlag(unittest.TestCase):

    def test_disabled_returns_zero(self):
        """When ORCH_MARGINAL_VALUE_ENABLED=false, calculate returns 0."""
        import importlib
        os.environ["ORCH_MARGINAL_VALUE_ENABLED"] = "false"
        import marginal_value_scheduler as mvs
        importlib.reload(mvs)
        try:
            val = mvs.calculate_marginal_value(
                _task(priority_weight=100, duration_estimate=1)
            )
            self.assertEqual(val, 0.0)
        finally:
            os.environ["ORCH_MARGINAL_VALUE_ENABLED"] = "true"
            importlib.reload(mvs)


if __name__ == "__main__":
    unittest.main()
