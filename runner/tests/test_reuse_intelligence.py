import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import merged_diff_library
import model_catalog
import patch_transplant
import task_slicer
import verifier_marketplace


class ReuseIntelligenceTest(unittest.TestCase):
    def test_merged_diff_features_extract_symbols_tests_frameworks(self):
        diff = "function handleStripeWebhook() {}\nconst Checkout = 1\n"
        files = ["app/api/stripe/route.test.ts", "next.config.js"]
        feat = merged_diff_library.features("stripe webhook checkout", diff, files)
        self.assertIn("handleStripeWebhook", feat["symbols"])
        self.assertIn("Checkout", feat["symbols"])
        self.assertIn("app/api/stripe/route.test.ts", feat["tests"])
        self.assertIn("next", feat["frameworks"])
        self.assertIn("stripe", feat["frameworks"])

    def test_merged_diff_find_matches_prior_rows(self):
        db = MagicMock()
        db.select.return_value = [{
            "project": "tomorrow", "slug": "stripe-hook", "kind": "build",
            "prompt": "stripe webhook signature verification handler",
            "diff": "+ verify stripe webhook signature",
            "words": ["stripe", "webhook", "signature", "verification", "handler"],
        }]
        with patch.object(merged_diff_library, "db", db):
            hits = merged_diff_library.find({"prompt": "add stripe webhook verification"})
        self.assertEqual(hits[0]["slug"], "stripe-hook")

    def test_patch_transplant_prepends_hint(self):
        task = {"id": "t1", "prompt": "add stripe webhook verification"}
        hit = [{"project": "tomorrow", "slug": "stripe-hook", "similarity": 0.5,
                "summary": "prior stripe hook", "diff": "+ old patch"}]
        db = MagicMock()
        with patch.object(patch_transplant.merged_diff_library, "find", return_value=hit), \
             patch.object(patch_transplant, "db", db, create=True):
            out = patch_transplant.pre_claim_hook(task)
        self.assertIn("PATCH TRANSPLANT", out["prompt"])
        db.update.assert_called_once()

    def test_task_slicer_decomposes_long_prompt_and_retire_parent(self):
        prompt = "- one\n- two\n- three\n- four\n- five\n- six\n- seven\n"
        task = {"id": "p", "project_id": "proj", "slug": "big", "kind": "build", "prompt": prompt}
        db = MagicMock()
        with patch.object(task_slicer, "db", db), \
             patch.dict(os.environ, {"ORCH_SLICE_PROMPT_CHARS": "10"}, clear=False):
            self.assertTrue(task_slicer.pre_agent_hook(task))
        self.assertGreaterEqual(db.insert.call_count, 2)
        db.update.assert_called_once()
        self.assertEqual(db.update.call_args.args[2]["state"], "DECOMPOSED")

    def test_task_slicer_does_not_recursively_slice_recovery_work(self):
        prompt = "- one\n- two\n- three\n- four\n- five\n- six\n- seven\n"
        self.assertFalse(task_slicer.should_slice({"slug": "qafix-app-slice-1", "prompt": prompt}))
        self.assertFalse(task_slicer.should_slice({"slug": "rework-testfail-app", "prompt": prompt}))

    def test_task_slicer_does_not_slice_canary_tasks(self):
        # canary- slugs must never be sliced: the groomer treats canary-gpt-1-slice-1
        # as a duplicate queued slug and blocks it, stalling the coder-routing lane.
        prompt = "- one\n- two\n- three\n- four\n- five\n- six\n- seven\n"
        self.assertFalse(task_slicer.should_slice({"slug": "canary-gpt-1", "prompt": prompt}))
        self.assertFalse(task_slicer.should_slice({"slug": "canary-claude-3", "prompt": prompt}))

    def test_model_catalog_prefers_free_capable_model(self):
        with patch.object(model_catalog.model_gateway, "available", return_value=["local", "openai"]), \
             patch.object(model_catalog, "_empirical_score", return_value=0.0):
            pick = model_catalog.choose("review", need=5)
        self.assertEqual(pick["provider"], "local")

    def test_verifier_marketplace_avoids_author_provider(self):
        with patch.object(verifier_marketplace.model_catalog, "choose",
                          return_value={"provider": "deepseek", "model": "deepseek-chat"}):
            self.assertEqual(verifier_marketplace.choose(author_model="claude-opus-4-8"),
                             ("deepseek", "deepseek-chat"))


if __name__ == "__main__":
    unittest.main()
