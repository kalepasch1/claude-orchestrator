"""Tests for train_status_backfill — attributing train/deploy outcomes to coders."""
import unittest
from unittest.mock import patch, MagicMock


class TestTrainStatusBackfill(unittest.TestCase):

    def test_deployed_value_per_minute_basic(self):
        from runner.train_status_backfill import deployed_value_per_minute
        outcomes = {
            "claude": [
                {"kind": "build", "slug": "feat-x", "wall_ms": 60000, "deployed": True, "deploy_status": "deployed"},
                {"kind": "build", "slug": "feat-y", "wall_ms": 60000, "deployed": False, "deploy_status": ""},
                {"kind": "build", "slug": "feat-z", "wall_ms": 60000, "deployed": True, "deploy_status": "deployed"},
                {"kind": "build", "slug": "feat-a", "wall_ms": 60000, "deployed": False, "deploy_status": ""},
                {"kind": "build", "slug": "feat-b", "wall_ms": 60000, "deployed": True, "deploy_status": "deployed"},
            ],
        }
        result = deployed_value_per_minute(outcomes)
        # 3 deployed / 5 minutes = 0.6 per minute
        self.assertAlmostEqual(result["claude"]["build"], 0.6, places=3)

    def test_deployed_value_per_minute_empty(self):
        from runner.train_status_backfill import deployed_value_per_minute
        result = deployed_value_per_minute({})
        self.assertEqual(result, {})

    def test_stage_classification(self):
        from runner.train_status_backfill import _stage_of_outcome
        self.assertEqual(_stage_of_outcome({"slug": "recover-branch-x", "kind": "build"}), "recovery")
        self.assertEqual(_stage_of_outcome({"slug": "feat-x", "kind": "build"}), "build")
        self.assertEqual(_stage_of_outcome({"slug": "buildfail-fix", "kind": "build"}), "build-fix")

    def test_is_deployed_checks_status(self):
        from runner.train_status_backfill import _is_deployed
        self.assertTrue(_is_deployed({"deployed": True}))
        self.assertTrue(_is_deployed({"deploy_status": "merged"}))
        self.assertTrue(_is_deployed({"deploy_status": "passed"}))
        self.assertFalse(_is_deployed({"deployed": False, "deploy_status": ""}))
        self.assertFalse(_is_deployed({"deploy_status": "train-testfail"}))


if __name__ == "__main__":
    unittest.main()
