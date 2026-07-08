import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import common_brain


class CommonBrainTest(unittest.TestCase):
    def test_recipe_for_maps_cade_to_each_core_app(self):
        orch = common_brain.recipe_for("orchestrator")
        tomorrow = common_brain.recipe_for("tomorrow")
        apparently = common_brain.recipe_for("apparently")
        smarter = common_brain.recipe_for("smarter")

        self.assertIn("merge", orch["cade"]["target"])
        self.assertIn("trade", tomorrow["cade"]["target"])
        self.assertIn("regulatory", apparently["cade"]["target"])
        self.assertIn("legal", smarter["cade"]["target"])
        self.assertIn("proof", "\n".join(orch["stages"]))

    def test_deployment_prompt_contains_shared_brain_and_product_specific_cade(self):
        recipe = common_brain.recipe_for("tomorrow")
        prompt = common_brain.deployment_prompt(recipe)

        self.assertIn("Shared brain stages", prompt)
        self.assertIn("CADE adaptation", prompt)
        self.assertIn("liquidity scout", prompt)
        self.assertIn("no-trade", prompt)
        self.assertIn("proof", prompt)

    def test_unknown_app_gets_generic_reusable_recipe(self):
        recipe = common_brain.recipe_for("new-app")

        self.assertEqual(recipe["app"], "new-app")
        self.assertIn("general platform optimization", recipe["domain"])
        self.assertIn("common-brain proof pack", recipe["cade"]["proof"])

    def test_seed_deployments_queues_four_app_specific_tasks(self):
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

        with patch.object(common_brain, "db", db), \
             patch.object(common_brain, "_write_snapshot", return_value="/tmp/snapshot.json"):
            res = common_brain.seed_deployments()

        task_rows = [r for table, r in inserted if table == "tasks"]
        self.assertEqual(len(task_rows), 4)
        self.assertEqual(len(res["queued"]), 4)
        prompts = "\n".join(r["prompt"] for r in task_rows).lower()
        self.assertIn("execution optimality receipt", prompts)
        self.assertIn("regulatory determination proof pack", prompts)
        self.assertIn("defensible-work receipt", prompts)
        self.assertIn("deployed-diff proof pack", prompts)

    def test_seed_deployments_backfills_existing_deployment_records(self):
        projects = [
            {"id": "p1", "name": "beethoven", "repo_path": "/r/beethoven", "prod_branch": "main"},
        ]
        inserted = []
        db = MagicMock()

        def fake_select(table, params=None):
            if table == "projects":
                return projects
            if table == "tasks":
                return [{"id": "already", "state": "QUEUED"}]
            return []

        db.select.side_effect = fake_select
        db.insert.side_effect = lambda table, row, upsert=False: inserted.append((table, row, upsert))

        with patch.object(common_brain, "db", db), \
             patch.object(common_brain, "_write_snapshot", return_value="/tmp/snapshot.json"):
            res = common_brain.seed_deployments(["beethoven"])

        self.assertEqual(len(res["queued"]), 0)
        self.assertEqual(len(res["skipped"]), 1)
        deployment_rows = [r for table, r, _ in inserted if table == "common_brain_deployments"]
        self.assertEqual(len(deployment_rows), 1)
        self.assertTrue(deployment_rows[0]["metadata"]["backfilled"])

    def test_cade_review_explains_reuse_across_apps(self):
        review = common_brain.cade_review()
        self.assertIn("Consensus", review["apparently_cade"])
        self.assertIn("merge", review["orchestrator_use"])
        self.assertIn("trade", review["tomorrow_use"])
        self.assertIn("legal", review["smarter_use"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
