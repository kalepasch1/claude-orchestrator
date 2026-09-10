"""Tests for adaptive_pipeline.py — adaptive pipeline stage collapse.

Covers: _result helper, plan() with no cached knowledge, should_use_pipeline
heuristics, fail-soft when optional imports are missing, stage ordering.
"""
import importlib
import json
import os
import sys
import types
import unittest

# ---------------------------------------------------------------------------
# Stub db and optional modules before importing
# ---------------------------------------------------------------------------
sys.modules.setdefault("db", types.ModuleType("db"))
db_mod = sys.modules["db"]
db_mod.select = lambda *a, **kw: []
db_mod.upsert = lambda *a, **kw: None

# Ensure optional imports fail gracefully (they should)
for mod_name in ("intent_graph", "transfer_learning", "prompt_distillation", "cross_project_templates"):
    if mod_name in sys.modules:
        del sys.modules[mod_name]

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import adaptive_pipeline as ap


class TestResultHelper(unittest.TestCase):
    def test_remaining_stages(self):
        r = ap._result(["scout", "planner", "implementer", "verifier"],
                       ["scout", "planner"], "prompt", "shortcut", 8000)
        self.assertEqual(r["stages"], ["implementer", "verifier"])
        self.assertEqual(r["collapsed"], ["scout", "planner"])
        self.assertEqual(r["stage_count"], 2)

    def test_no_collapse(self):
        r = ap._result(["scout", "planner", "implementer", "verifier"],
                       [], "prompt", "none", 0)
        self.assertEqual(len(r["stages"]), 4)
        self.assertEqual(r["estimated_savings_tokens"], 0)

    def test_full_collapse(self):
        r = ap._result(["scout", "planner", "implementer", "verifier"],
                       ["scout", "planner", "implementer"], "p", "replay", 12000)
        self.assertEqual(r["stages"], ["verifier"])
        self.assertEqual(r["stage_count"], 1)

    def test_enriched_prompt_passthrough(self):
        r = ap._result(["a"], [], "my prompt", "none", 0)
        self.assertEqual(r["enriched_prompt"], "my prompt")


class TestPlanNoCache(unittest.TestCase):
    """With no optional modules available, plan returns full pipeline."""

    def test_full_pipeline_returned(self):
        task = {"prompt": "fix build", "kind": "build"}
        result = ap.plan(task, "beethoven", "/fake/repo")
        self.assertIn("stages", result)
        self.assertIn("collapsed", result)
        self.assertIn("enriched_prompt", result)
        # All optional imports fail → full pipeline
        self.assertEqual(len(result["stages"]), 4)
        self.assertEqual(result["collapsed"], [])

    def test_shortcut_is_none(self):
        result = ap.plan({"prompt": "x", "kind": "build"}, "proj")
        self.assertEqual(result["shortcut"], "none")

    def test_enriched_prompt_contains_original(self):
        result = ap.plan({"prompt": "original text", "kind": "test"}, "proj")
        self.assertIn("original text", result["enriched_prompt"])


class TestPlanWithIntentReplay(unittest.TestCase):
    """When intent_graph returns a high-confidence replay."""

    def setUp(self):
        ig = types.ModuleType("intent_graph")
        ig.find_replay = lambda task, repo: {"confidence": 0.95, "approach": "apply cached diff"}
        sys.modules["intent_graph"] = ig

    def tearDown(self):
        del sys.modules["intent_graph"]

    def test_collapses_three_stages(self):
        result = ap.plan({"prompt": "fix", "kind": "build"}, "proj", "/repo")
        self.assertIn("scout", result["collapsed"])
        self.assertIn("planner", result["collapsed"])
        self.assertIn("implementer", result["collapsed"])
        self.assertEqual(result["stages"], ["verifier"])

    def test_shortcut_mentions_replay(self):
        result = ap.plan({"prompt": "fix", "kind": "build"}, "proj", "/repo")
        self.assertIn("intent_replay", result["shortcut"])

    def test_savings_significant(self):
        result = ap.plan({"prompt": "fix", "kind": "build"}, "proj", "/repo")
        self.assertGreaterEqual(result["estimated_savings_tokens"], 10000)


class TestPlanWithTransfer(unittest.TestCase):
    """When transfer_learning provides a cross-project transfer."""

    def setUp(self):
        tl = types.ModuleType("transfer_learning")
        tl.find_transfer = lambda task, current_project="": {
            "confidence": 0.8,
            "source_project": "tomorrow",
            "adapted_files": ["a.py", "b.py", "c.py"],
        }
        tl.inject_transfer = lambda prompt, transfer: f"[TRANSFER]\n{prompt}"
        sys.modules["transfer_learning"] = tl
        # Remove intent_graph so it doesn't short-circuit
        sys.modules.pop("intent_graph", None)

    def tearDown(self):
        sys.modules.pop("transfer_learning", None)

    def test_collapses_scout_and_planner(self):
        result = ap.plan({"prompt": "add feature", "kind": "feature"}, "beethoven")
        self.assertIn("scout", result["collapsed"])
        self.assertIn("planner", result["collapsed"])

    def test_enriched_prompt_injected(self):
        result = ap.plan({"prompt": "add feature", "kind": "feature"}, "beethoven")
        self.assertIn("[TRANSFER]", result["enriched_prompt"])


class TestShouldUsePipeline(unittest.TestCase):
    def setUp(self):
        # Ensure optional modules fail
        sys.modules.pop("intent_graph", None)
        sys.modules.pop("prompt_distillation", None)

    def test_short_mechanical_skips(self):
        self.assertFalse(ap.should_use_pipeline(
            {"prompt": "fix typo", "kind": "mechanical"}, "proj"))

    def test_long_prompt_uses_pipeline(self):
        self.assertTrue(ap.should_use_pipeline(
            {"prompt": "x" * 1500, "kind": "feature"}, "proj"))

    def test_feature_kind_uses_pipeline(self):
        self.assertTrue(ap.should_use_pipeline(
            {"prompt": "short", "kind": "feature"}, "proj"))

    def test_refactor_uses_pipeline(self):
        self.assertTrue(ap.should_use_pipeline(
            {"prompt": "short", "kind": "refactor"}, "proj"))

    def test_short_config_skips(self):
        self.assertFalse(ap.should_use_pipeline(
            {"prompt": "set env var", "kind": "config"}, "proj"))


class TestStageOrdering(unittest.TestCase):
    def test_stages_preserve_order(self):
        result = ap.plan({"prompt": "x", "kind": "build"}, "proj")
        self.assertEqual(result["stages"], ["scout", "planner", "implementer", "verifier"])


if __name__ == "__main__":
    unittest.main()
