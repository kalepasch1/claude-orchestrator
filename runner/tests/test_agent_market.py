#!/usr/bin/env python3
"""Tests for runner/agent_market.py — verifier independence and routing hygiene."""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import agent_market


class AgentMarketTest(unittest.TestCase):
    def test_verifier_excludes_author_provider(self):
        calls = []

        def fake_choose(task_class, need=6, sensitivity="standard", exclude_provider=None,
                        available_providers=None, use_empirical=True):
            calls.append({
                "task_class": task_class,
                "need": need,
                "sensitivity": sensitivity,
                "exclude_provider": exclude_provider,
            })
            return {"provider": "google", "model": "gemini-2.5-flash", "cap": 8, "tier": "cheap"}

        with patch.object(agent_market.model_catalog, "choose", side_effect=fake_choose), \
             patch.object(agent_market, "_record_bid", return_value=None):
            bid = agent_market.route_role("tomorrow", "verifier", author_model="gpt-5.5")

        self.assertEqual(bid["provider"], "google")
        self.assertEqual(calls[0]["exclude_provider"], "openai")
        self.assertEqual(bid["settlement"], agent_market.APP_MESHES["tomorrow"]["settlement"])

    def test_smarter_privacy_officer_uses_crown_jewel_sensitivity(self):
        calls = []

        def fake_choose(task_class, need=6, sensitivity="standard", exclude_provider=None,
                        available_providers=None, use_empirical=True):
            calls.append(sensitivity)
            return {"provider": "local", "model": "qwen3-coder:30b", "cap": 9, "tier": "free"}

        with patch.object(agent_market.model_catalog, "choose", side_effect=fake_choose), \
             patch.object(agent_market, "_record_bid", return_value=None):
            bid = agent_market.route_role("smarter", "privacy_officer", author_model="claude-opus-4-8")

        self.assertEqual(calls[0], "crown_jewel")
        self.assertEqual(bid["provider"], "local")
        self.assertGreater(bid["score"], 0)

    def test_seed_improvement_batches_is_idempotent_and_app_specific(self):
        projects = [
            {"id": "p1", "name": "beethoven", "repo_path": "/r/beethoven", "prod_branch": "main"},
            {"id": "p2", "name": "tomorrow", "repo_path": "/r/tomorrow", "prod_branch": "main"},
            {"id": "p3", "name": "apparently", "repo_path": "/r/apparently", "prod_branch": "main"},
            {"id": "p4", "name": "smarter", "repo_path": "/r/smarter", "prod_branch": "main"},
        ]
        inserted = []
        db = MagicMock()

        def fake_select(table, params=None):
            if table == "projects":
                return projects
            if table == "tasks":
                return []
            return []

        db.select.side_effect = fake_select
        db.insert.side_effect = lambda table, row, upsert=False: inserted.append((table, row))

        with patch.object(agent_market, "db", db):
            res = agent_market.seed_improvement_batches()

        task_rows = [r for table, r in inserted if table == "tasks"]
        self.assertEqual(len(task_rows), 4)
        self.assertEqual(set(res["queued"]), {spec["slug"] for spec in agent_market.APP_BATCHES.values()})
        prompts = "\n".join(r["prompt"] for r in task_rows).lower()
        self.assertIn("regulatory", prompts)
        self.assertIn("legal work-product", prompts)
        self.assertIn("otc", prompts)
        self.assertIn("agent market kernel", prompts)


if __name__ == "__main__":
    unittest.main(verbosity=2)
