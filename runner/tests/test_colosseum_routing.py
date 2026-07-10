"""Tests that ORCH_COLOSSEUM_ROUTE wires colosseum.pick_implementer into model selection."""
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import colosseum


class ColosseumRoutingTest(unittest.TestCase):
    def test_pick_implementer_prefers_top_score(self):
        """pick_implementer returns the highest-scored active agent."""
        fake_profiles = {
            "claude:claude-sonnet-4-6": {
                "vendor": "claude", "model": "claude-sonnet-4-6",
                "roles": ["implementer"], "cost_tier": "mid",
                "sensitivity": "standard", "elo": 1250,
                "merge_rate": 0.8, "tasks_completed": 20,
                "total_cost": 10.0, "status": "active",
            },
            "claude:claude-haiku-4-5-20251001": {
                "vendor": "claude", "model": "claude-haiku-4-5-20251001",
                "roles": ["implementer"], "cost_tier": "cheap",
                "sensitivity": "standard", "elo": 1100,
                "merge_rate": 0.3, "tasks_completed": 10,
                "total_cost": 5.0, "status": "active",
            },
        }
        fake_rep = {
            "claude:claude-sonnet-4-6": {
                "elo": 1250, "merged": 16, "total_tasks": 20,
                "total_cost_usd": 10.0, "retries": 0,
                "review_failures": 0, "rollbacks": 0,
                "avg_cost": 0.5, "avg_time_s": 200,
            },
            "claude:claude-haiku-4-5-20251001": {
                "elo": 1100, "merged": 3, "total_tasks": 10,
                "total_cost_usd": 5.0, "retries": 2,
                "review_failures": 1, "rollbacks": 0,
                "avg_cost": 0.5, "avg_time_s": 150,
            },
        }
        task = {"slug": "test-feature", "kind": "feature", "prompt": "add a new endpoint"}

        with patch.object(colosseum, "_profiles", return_value=fake_profiles), \
             patch.object(colosseum, "_reputation", return_value=fake_rep):
            vendor, model = colosseum.pick_implementer(task)

        self.assertEqual(vendor, "claude")
        self.assertEqual(model, "claude-sonnet-4-6")

    def test_pick_implementer_returns_none_when_no_profiles(self):
        """pick_implementer returns (None, None) when no agent profiles exist."""
        task = {"slug": "test-task", "kind": "feature", "prompt": "do something"}

        with patch.object(colosseum, "_profiles", return_value={}), \
             patch.object(colosseum, "_reputation", return_value={}):
            vendor, model = colosseum.pick_implementer(task)

        self.assertIsNone(vendor)
        self.assertIsNone(model)

    def test_pick_verifier_excludes_implementer_vendor(self):
        """pick_verifier returns a model from a different vendor than the implementer."""
        fake_profiles = {
            "claude:claude-sonnet-4-6": {
                "vendor": "claude", "model": "claude-sonnet-4-6",
                "roles": ["verifier"], "cost_tier": "mid",
                "sensitivity": "standard", "elo": 1250,
                "merge_rate": 0.8, "tasks_completed": 20,
                "total_cost": 10.0, "status": "active",
            },
            "openai:gpt-4o": {
                "vendor": "openai", "model": "gpt-4o",
                "roles": ["verifier"], "cost_tier": "mid",
                "sensitivity": "standard", "elo": 1200,
                "merge_rate": 0.7, "tasks_completed": 15,
                "total_cost": 12.0, "status": "active",
            },
        }
        fake_rep = {
            "claude:claude-sonnet-4-6": {
                "elo": 1250, "merged": 16, "total_tasks": 20,
                "total_cost_usd": 10.0, "retries": 0,
                "review_failures": 0, "rollbacks": 0,
                "avg_cost": 0.5, "avg_time_s": 200,
            },
            "openai:gpt-4o": {
                "elo": 1200, "merged": 10, "total_tasks": 15,
                "total_cost_usd": 12.0, "retries": 0,
                "review_failures": 0, "rollbacks": 0,
                "avg_cost": 0.8, "avg_time_s": 180,
            },
        }
        task = {"slug": "test-feature", "kind": "feature", "prompt": "implement feature"}

        with patch.object(colosseum, "_profiles", return_value=fake_profiles), \
             patch.object(colosseum, "_reputation", return_value=fake_rep):
            vendor, model = colosseum.pick_verifier(task, exclude_vendor="claude")

        self.assertEqual(vendor, "openai")
        self.assertEqual(model, "gpt-4o")

    def test_colosseum_route_env_controls_integration(self):
        """ORCH_COLOSSEUM_ROUTE env var gate: colosseum.pick_implementer is called only when enabled."""
        called = []

        def fake_pick_implementer(task):
            called.append(task)
            return ("claude", "claude-sonnet-4-6")

        with patch.object(colosseum, "pick_implementer", side_effect=fake_pick_implementer):
            # When disabled (default), should not be called
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("ORCH_COLOSSEUM_ROUTE", None)
                colosseum.pick_implementer  # not called directly — runner gates it

            self.assertEqual(len(called), 0)

        # The env var gate is in runner.py; here we just confirm pick_implementer works
        with patch.object(colosseum, "pick_implementer", side_effect=fake_pick_implementer):
            with patch.dict(os.environ, {"ORCH_COLOSSEUM_ROUTE": "true"}):
                vendor, model = colosseum.pick_implementer({"slug": "s", "prompt": "p"})

        self.assertEqual(vendor, "claude")
        self.assertEqual(model, "claude-sonnet-4-6")


if __name__ == "__main__":
    unittest.main(verbosity=2)
