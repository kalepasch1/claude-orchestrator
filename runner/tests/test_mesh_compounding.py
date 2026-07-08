import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import agent_market
import brain_compiler
import common_brain
import merged_diff_library
import mesh_optimizer
import model_catalog
import model_slashing


class MeshCompoundingTest(unittest.TestCase):
    def test_brain_compiler_generates_repo_specific_plan(self):
        with tempfile.TemporaryDirectory() as repo:
            with open(os.path.join(repo, "package.json"), "w") as f:
                f.write("{}")
            os.makedirs(os.path.join(repo, "server", "api"))
            os.makedirs(os.path.join(repo, "supabase", "migrations"))
            task = {
                "slug": "improve-common-brain-regulatory-determination-hive",
                "prompt": "Deploy the reusable Common Brain into apparently",
            }

            plan = brain_compiler.compile_for_task(task, repo=repo, project="apparently")

        self.assertTrue(plan["has_plan"])
        self.assertEqual(plan["surface"], "apparently")
        self.assertIn("server/api", plan["plan_text"])
        self.assertIn("verified regulatory artifact", plan["plan_text"])

    def test_mesh_prepare_injects_intent_bankruptcy_sim_and_debate(self):
        task = {"id": "t1", "slug": "hard-api", "kind": "build", "prompt": "x" * 1000}
        debate = {"approach": "change one route", "files": ["server/api/x.ts"], "risks": [], "reuse_hints": []}
        with patch("merged_diff_library.adapter_directive", return_value="INTENT GRAPH"), \
             patch("prompt_bankruptcy.is_bankrupt", return_value=True), \
             patch("prompt_bankruptcy.restructure", side_effect=lambda task, prompt, project="": "RESTRUCTURED\n" + prompt), \
             patch("presettlement_sim.simulate", return_value={
                 "predicted_failure": True,
                 "failure_probability": 0.9,
                 "confidence": 0.91,
                 "recommended_action": "decompose_first",
                 "reasons": ["low merge rate"],
             }), \
             patch("debate_compress.compressed_debate", return_value=debate), \
             patch("debate_compress.inject_debate", side_effect=lambda prompt, d: "DEBATE\n" + prompt):
            res = mesh_optimizer.prepare_prompt(task, "ORIGINAL", project="beethoven")

        self.assertIn("DEBATE", res["prompt"])
        self.assertIn("PRE-SETTLEMENT", res["prompt"])
        self.assertIn("RESTRUCTURED", res["prompt"])
        self.assertIn("INTENT GRAPH", res["prompt"])
        self.assertIn("compressed-debate", res["notes"])

    def test_model_slashing_changes_model_catalog_choice(self):
        candidates = [
            {"provider": "openai", "model": "cheap-a", "cap": 8, "tier": "cheap"},
            {"provider": "google", "model": "cheap-b", "cap": 8, "tier": "cheap"},
        ]
        with patch.object(model_catalog, "_available_models", return_value=candidates), \
             patch.object(model_catalog, "_price_score", return_value=0.1), \
             patch.object(model_catalog, "_empirical_score", return_value=0.0), \
             patch.object(model_slashing, "score_adjustment", side_effect=lambda p, m: 2.0 if p == "openai" else 0.0):
            pick = model_catalog.choose("review", need=6, available_providers=["openai", "google"])
        self.assertEqual(pick["provider"], "google")

    def test_common_brain_record_outcome_updates_matching_deployment(self):
        db = MagicMock()
        task = {"slug": "improve-common-brain-now-approve-legal-work-product", "prompt": "common brain"}
        with patch.object(common_brain, "db", db):
            ok = common_brain.record_outcome(task, project="smarter", slug=task["slug"],
                                            status="merged", outcome="integrated",
                                            tokens_avoided=1200, minutes_avoided=4.5)
        self.assertTrue(ok)
        db.update.assert_called_once()
        patch_row = db.update.call_args.args[2]
        self.assertEqual(patch_row["status"], "merged")
        self.assertEqual(patch_row["tokens_avoided"], 1200)

    def test_cade_tournament_builds_independent_panel(self):
        calls = []

        def fake_route(app, role, objective="", author_model="", sensitivity=None, record=True):
            calls.append((role, author_model))
            return {"app": app, "role": role, "provider": "local", "model": f"{role}-model", "score": 1}

        with patch.object(agent_market, "route_role", side_effect=fake_route), \
             patch.object(agent_market, "_write_control", return_value=None):
            pack = agent_market.cade_tournament("tomorrow", "price a block trade")

        self.assertEqual(pack["app"], "tomorrow")
        self.assertIn("settlement", pack)
        self.assertTrue(any(role == "verifier" and author for role, author in calls))

    def test_intent_graph_exposes_adapter_templates(self):
        db = MagicMock()
        db.select.return_value = [{
            "project": "beethoven",
            "slug": "common-brain-adapter",
            "kind": "build",
            "prompt": "common brain proof adapter",
            "diff": "+ add common brain proof adapter",
            "words": ["common", "brain", "proof", "adapter"],
            "adapter_template": "dirs=server/api exts=.ts:1 shape=+30/-2",
            "intent_signature": "sig1",
        }]
        with patch.object(merged_diff_library, "db", db):
            graph = merged_diff_library.intent_graph({"prompt": "add common brain proof adapter"})

        self.assertEqual(graph["adapters"][0]["intent_signature"], "sig1")
        self.assertIn("server/api", graph["adapters"][0]["adapter_template"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
