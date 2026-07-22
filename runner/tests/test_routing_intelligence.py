import os
import sys
import unittest
import datetime
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import agentic_coders
import adaptive_probe
import coder_canary
import ollama_install_planner
import ollama_calibrator
import patch_templates
import plan_stage
import prompt_result_cache
import provider_terms
import route_evidence
import router_stats
import thermal_map


class RoutingIntelligenceTest(unittest.TestCase):
    def test_provider_terms_default_external_not_crown_jewel(self):
        self.assertTrue(provider_terms.allowed("ollama", "crown_jewel"))
        self.assertFalse(provider_terms.allowed("gpt", "crown_jewel"))
        self.assertTrue(provider_terms.allowed("gpt", "standard"))

    def test_crown_jewel_routes_local_only(self):
        env = {
            "ORCH_AUTO_AGENTIC_CODERS": "true",
            "ORCH_USE_PAID_AGENTIC_CREDITS": "true",
            "ORCH_EASY_OFFLOAD_SHARE": "1.0",
        }
        task = {"slug": "core-moat", "kind": "build",
                "prompt": "change the crown jewel core algorithm", "sensitivity": "crown_jewel"}
        with patch.dict(os.environ, env, clear=False), \
             patch.object(agentic_coders, "_aider_available", return_value=True), \
             patch.object(agentic_coders, "_within_cap", return_value=True), \
             patch("model_gateway.available", return_value=["claude", "local", "openai"]):
            self.assertEqual(agentic_coders.pick(task), "ollama")

    def test_thermal_score_prefers_fast_high_value_work(self):
        ctx = {"revenue_by_project": {"app": 1000}, "surface_returns": {},
               "outcome_stats": {"app": {"success_rate": 0.8, "avg_usd": 0.2}},
               "approved_slugs": set()}
        fast = {"id": "fast", "project": "app", "kind": "bugfix", "prompt": "small pricing fix"}
        slow = {"id": "slow", "project": "app", "kind": "build", "prompt": "large architecture rewrite"}
        self.assertGreater(thermal_map.score(fast, ctx), thermal_map.score(slow, ctx))

    def test_router_penalizes_token_and_review_waste(self):
        rows = []
        for i in range(router_stats.MIN_SAMPLES):
            rows.append({"model": "wasteful", "kind": "build", "integrated": True,
                         "tests_passed": True, "usd": 0.0, "wall_ms": 60000,
                         "attempts": 1, "input_tokens": 200000,
                         "output_tokens": 100000, "diff_bytes": 10,
                         "review_failures": 3, "slug": f"w{i}"})
            rows.append({"model": "efficient", "kind": "build", "integrated": True,
                         "tests_passed": True, "usd": 0.0, "wall_ms": 60000,
                         "attempts": 1, "input_tokens": 1000,
                         "output_tokens": 500, "diff_bytes": 1000,
                         "review_failures": 0, "slug": f"e{i}"})
        db = MagicMock()
        db.select.return_value = rows
        with patch.object(router_stats, "db", db), \
             patch.object(router_stats, "_CACHE", {"t": 0.0, "table": {}}):
            self.assertEqual(router_stats.best_coder("build", ["wasteful", "efficient"]), "efficient")

    def test_router_dedupes_repeated_route_evidence_backfill_rows(self):
        duplicate = {"model": "ollama:m", "kind": "build", "integrated": True,
                     "tests_passed": True, "usd": 0.0, "wall_ms": 0,
                     "attempts": 1, "slug": "same-merged"}
        rows = [dict(duplicate) for _ in range(5)]
        rows.extend([
            {"model": "claude", "kind": "build", "integrated": True,
             "tests_passed": True, "usd": 0.0, "wall_ms": 0,
             "attempts": 1, "slug": "c1"},
            {"model": "claude", "kind": "build", "integrated": True,
             "tests_passed": True, "usd": 0.0, "wall_ms": 0,
             "attempts": 1, "slug": "c2"},
        ])
        db = MagicMock()
        db.select.return_value = rows
        with patch.object(router_stats, "db", db), \
             patch.object(router_stats, "MIN_SAMPLES", 2), \
             patch.object(router_stats, "_CACHE", {"t": 0.0, "table": {}}):
            table = router_stats._rebuild()

        self.assertEqual([r["coder"] for r in table["build"]], ["claude"])

    def test_coder_canary_queues_one_per_allowed_coder(self):
        inserted = []
        db = MagicMock()
        db.select.side_effect = [
            [{"id": "p1", "name": "beethoven"}],
            [],
            [],
        ]
        db.insert.side_effect = lambda table, row: inserted.append((table, row))
        with patch.dict(os.environ, {"ORCH_DRAIN_MODE": "false"}, clear=False), \
             patch.object(coder_canary, "db", db), \
             patch.object(coder_canary.agentic_coders, "available", return_value=["ollama", "gpt"]):
            res = coder_canary.run(limit_per_coder=1)
        self.assertEqual(res["queued"], 2)
        self.assertEqual({r["force_coder"] for _, r in inserted}, {"ollama", "gpt"})

    def test_coder_canary_does_not_let_stale_active_sample_block_new_sample(self):
        old = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=3)).isoformat()
        inserted = []
        db = MagicMock()
        db.select.side_effect = [
            [{"id": "p1", "name": "beethoven"}],
            [{"slug": "canary-gpt-1", "state": "RUNNING", "force_coder": "gpt", "updated_at": old}],
            [],
            [],
        ]
        db.insert.side_effect = lambda table, row: inserted.append((table, row))
        with patch.dict(os.environ, {"ORCH_DRAIN_MODE": "false"}, clear=False), \
             patch.object(coder_canary, "db", db), \
             patch.object(coder_canary.agentic_coders, "available", return_value=["gpt"]):
            res = coder_canary.run(limit_per_coder=1)
        self.assertEqual(res["queued"], 1)
        self.assertEqual(inserted[0][1]["slug"], "canary-gpt-2")

    def test_route_evidence_reports_stale_non_claude_canaries(self):
        old = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=3)).isoformat()
        db = MagicMock()
        db.select.return_value = [
            {"slug": "canary-gemini-1", "state": "RUNNING", "force_coder": "gemini", "updated_at": old}
        ]
        with patch.object(route_evidence, "db", db):
            stale = route_evidence.stale_canaries()
        self.assertEqual(stale[0]["coder"], "gemini")

    def test_route_evidence_requeues_stale_canaries(self):
        db = MagicMock()
        rows = [{"id": "t1", "slug": "canary-gpt-1", "coder": "gpt", "state": "RUNNING"}]
        with patch.object(route_evidence, "db", db):
            bumped = route_evidence.requeue_stale_canaries(rows)
        self.assertEqual(bumped, 1)
        db.update.assert_called_once()
        self.assertEqual(db.update.call_args.args[2]["state"], "QUEUED")

    def test_route_evidence_explains_disabled_agentic_providers(self):
        with patch("model_gateway.available", return_value=["claude", "openai", "local"]), \
             patch.object(agentic_coders, "available", return_value=["claude", "ollama", "gpt"]):
            status = route_evidence.provider_status()
        self.assertEqual(status["agentic_coders"], ["claude", "ollama", "gpt"])
        disabled = {row["provider"] for row in status["disabled_providers"]}
        self.assertIn("google", disabled)
        self.assertIn("deepseek", disabled)

    def test_coder_canary_prefers_historical_merged_prompt(self):
        inserted = []
        db = MagicMock()
        db.select.side_effect = [
            [{"id": "p1", "name": "beethoven"}],
            [],
            [{"slug": "merged-x", "kind": "build", "prompt": "Implement webhook validation with tests " * 8}],
        ]
        db.insert.side_effect = lambda table, row: inserted.append((table, row))
        with patch.dict(os.environ, {"ORCH_DRAIN_MODE": "false"}, clear=False), \
             patch.object(coder_canary, "db", db), \
             patch.object(coder_canary.agentic_coders, "available", return_value=["ollama"]):
            res = coder_canary.run(limit_per_coder=1)
        self.assertEqual(res["queued"], 1)
        self.assertIn("Historical merged-task canary", inserted[0][1]["prompt"])

    def test_coder_canary_uses_recovery_backlog_prompt_when_available(self):
        inserted = []
        db = MagicMock()
        recovery_prompt = "Recovery task prompt for missing branch reconstruction " * 3
        db.select.side_effect = [
            [{"id": "p1", "name": "beethoven"}],
            [],
            [{"slug": "recover-missing-branch-canary-gpt-1", "kind": "canary",
              "prompt": recovery_prompt}],
        ]
        db.insert.side_effect = lambda table, row: inserted.append((table, row))
        with patch.dict(os.environ, {"ORCH_DRAIN_MODE": "false"}, clear=False), \
             patch.object(coder_canary, "db", db), \
             patch.object(coder_canary.agentic_coders, "available", return_value=["ollama"]):
            res = coder_canary.run(limit_per_coder=1)
        self.assertEqual(res["queued"], 1)
        self.assertIn("Recovery-backlog canary", inserted[0][1]["prompt"])

    def test_patch_template_injects_prior_diff_directive(self):
        db = MagicMock()
        with patch.object(patch_templates, "db", db):
            task = {"id": "t1", "slug": "stripe-webhook", "kind": "build",
                    "prompt": "Add stripe webhook validation route and tests"}
            out = patch_templates.pre_claim_hook(task)
        self.assertIn("PATCH TEMPLATE", out["prompt"])
        self.assertIn("[patch-template:", out["prompt"])
        db.update.assert_not_called()  # original retry prompt must stay clean
        db.insert.assert_called_once()  # reusable template knowledge is persisted

    def test_prompt_result_cache_round_trip_by_intent(self):
        old = prompt_result_cache.CACHE
        try:
            prompt_result_cache.CACHE = os.path.join(os.environ.get("TMPDIR", "/tmp"), "prompt-cache-test.jsonl")
            try:
                os.unlink(prompt_result_cache.CACHE)
            except OSError:
                pass
            prompt_result_cache.store("local", "m", "review", "probe", "def foo(): pass", "cached")
            hit = prompt_result_cache.lookup("local", "m", "review", "probe", "def foo(): pass")
        finally:
            prompt_result_cache.CACHE = old
        self.assertEqual(hit["text"], "cached")

    def test_adaptive_probe_injects_cheap_slice(self):
        with patch.object(adaptive_probe, "make_probe", return_value="PROBE: use existing route"):
            prompt = adaptive_probe.inject({"kind": "build", "material": True}, "x" * 2000, "app")
        self.assertIn("PROBE: use existing route", prompt)

    def test_canaries_skip_multimodel_plan_stage(self):
        self.assertFalse(plan_stage.should_plan({"kind": "canary"}, "x" * 5000))

    def test_ollama_install_planner_recommends_missing_feasible_models(self):
        with patch.object(ollama_install_planner, "_disk_free_gb", return_value=200), \
             patch.object(ollama_install_planner, "_ram_free_gb", return_value=64), \
             patch.object(ollama_install_planner, "_installed", return_value=set()):
            p = ollama_install_planner.plan()
        self.assertTrue(any(m["model"] == "qwen3-coder:30b" and m["recommended"] for m in p["models"]))
        fable = next(m for m in p["models"] if m["model"] == "oroboroslabs/claude-fable-5Q")
        self.assertTrue(fable["gated"])
        self.assertFalse(fable["recommended"])

    def test_ollama_install_planner_canary_allows_unverified_fable_by_flag(self):
        with patch.dict(os.environ, {"ORCH_ALLOW_EXPERIMENTAL_OLLAMA_PULLS": "true"}, clear=False), \
             patch.object(ollama_install_planner, "_disk_free_gb", return_value=200), \
             patch.object(ollama_install_planner, "_ram_free_gb", return_value=64), \
             patch.object(ollama_install_planner, "_installed", return_value=set()):
            p = ollama_install_planner.plan()
        fable = next(m for m in p["models"] if m["model"] == "oroboroslabs/claude-fable-5Q")
        self.assertFalse(fable["gated"])
        self.assertTrue(fable["installable"])

    def test_ollama_calibrator_records_pass_fail_latency_samples(self):
        inserted = []
        db = MagicMock()
        db.insert.side_effect = lambda table, row: inserted.append((table, row))

        def fake_complete(provider, model, prompt, **kwargs):
            return {"text": "{\"ok\": true, \"n\": 7}\n1. inspect\n2. update\n3. test\nrange len index"}

        with patch.object(ollama_calibrator, "db", db), \
             patch.object(ollama_calibrator.ollama_catalog, "candidates", return_value=[
                 {"provider": "local", "model": "opus-4.6-local", "cap": 10, "tier": "free"}
             ]), \
             patch.object(ollama_calibrator.model_gateway, "complete", side_effect=fake_complete):
            res = ollama_calibrator.run(limit_models=1, max_probes_per_model=len(ollama_calibrator.PROBES))
        self.assertEqual(res["calibrated"], len(ollama_calibrator.PROBES))
        self.assertTrue(all(row["provider"] == "local" for _, row in inserted))
        self.assertTrue(all(row["operation"] == "ollama_calibration" for _, row in inserted))
        self.assertTrue(all(row["ok"] for _, row in inserted))


if __name__ == "__main__":
    unittest.main()
