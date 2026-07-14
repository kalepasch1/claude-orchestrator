import importlib
import importlib.util
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_gateway
import model_policy
import app_triage
import agentic_coders
import router_stats
import ollama_catalog
import local_model_slots
import resource_governor

_RUNNER_SPEC = importlib.util.spec_from_file_location(
    "runner_entrypoint", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner.py"))
runner_entrypoint = importlib.util.module_from_spec(_RUNNER_SPEC)
_RUNNER_SPEC.loader.exec_module(runner_entrypoint)


class ModelRoutingTest(unittest.TestCase):

    def test_available_uses_keys_and_does_not_count_dead_ollama(self):
        env = {
            "OPENAI_API_KEY": "sk-test",
            "GOOGLE_API_KEY": "g-test",
            "DEEPSEEK_API_KEY": "d-test",
            "OLLAMA_HOST": "http://localhost:11434 + ollama pull qwen",
        }
        with patch.dict(os.environ, env, clear=False), \
             patch.object(model_gateway, "_ollama_up", return_value=False):
            providers = model_gateway.available()
        self.assertIn("openai", providers)
        self.assertIn("google", providers)
        self.assertIn("deepseek", providers)
        self.assertNotIn("local", providers)

    def test_ollama_probe_falls_back_to_curl_when_urllib_is_denied(self):
        proc = MagicMock(returncode=0)
        with patch.object(model_gateway.urllib.request, "urlopen", side_effect=PermissionError("denied")), \
             patch.object(model_gateway.subprocess, "run", return_value=proc) as run:
            self.assertTrue(model_gateway._ollama_up())
        self.assertEqual(run.call_args[0][0][:2], ["curl", "-sf"])

    def test_explicit_ollama_config_counts_as_available_after_probe_failure(self):
        env = {"OLLAMA_HOST": "http://localhost:11434", "ORCH_ASSUME_CONFIGURED_OLLAMA": "true"}
        proc = MagicMock(returncode=7)
        with patch.dict(os.environ, env, clear=False), \
             patch.object(model_gateway.urllib.request, "urlopen", side_effect=PermissionError("denied")), \
             patch.object(model_gateway.subprocess, "run", return_value=proc):
            self.assertTrue(model_gateway._ollama_up())

    def test_ollama_catalog_discovers_and_scores_opus_like_local_model(self):
        tags = {"models": [{"name": "llama3.1"}, {"name": "opus-4.6-local"}]}
        resp = MagicMock()
        resp.read.return_value = __import__("json").dumps(tags).encode()
        resp.__enter__.return_value = resp
        with patch.object(ollama_catalog.urllib.request, "urlopen", return_value=resp), \
             patch.dict(os.environ, {}, clear=False):
            production = ollama_catalog.candidates()
            cs = ollama_catalog.candidates(include_canary_only=True)
        caps = {c["model"]: c["cap"] for c in cs}
        self.assertLess(caps["opus-4.6-local"], 10)
        self.assertIn("llama3.1", caps)
        self.assertFalse(any(c["model"] == "opus-4.6-local" for c in production))
        self.assertTrue(next(c for c in cs if c["model"] == "opus-4.6-local")["canary_only"])

    def test_ollama_catalog_keeps_repository_qualified_opus_tag(self):
        tags = {"models": [{"name": "sorc/qwen3.5-claude-4.6-opus:latest"}]}
        resp = MagicMock()
        resp.read.return_value = __import__("json").dumps(tags).encode()
        resp.__enter__.return_value = resp
        with patch.object(ollama_catalog.urllib.request, "urlopen", return_value=resp), \
             patch.dict(os.environ, {}, clear=False):
            cs = ollama_catalog.candidates(include_canary_only=True)
        self.assertEqual(cs[0]["model"], "sorc/qwen3.5-claude-4.6-opus:latest")
        self.assertLess(cs[0]["cap"], 10)
        self.assertEqual(cs[0]["trust"], "community-claim")
        self.assertTrue(cs[0]["canary_only"])

    def test_ollama_catalog_keeps_fable_canary_only_by_default(self):
        tags = {"models": [{"name": "oroboroslabs/claude-fable-5Q:latest"}]}
        resp = MagicMock()
        resp.read.return_value = __import__("json").dumps(tags).encode()
        resp.__enter__.return_value = resp
        with patch.object(ollama_catalog.urllib.request, "urlopen", return_value=resp), \
             patch.dict(os.environ, {"ORCH_TRUST_COMMUNITY_CLAUDE_OLLAMA": "false"}, clear=False):
            production = ollama_catalog.candidates()
            canary = ollama_catalog.candidates(include_canary_only=True)
        self.assertFalse(any(c["model"] == "oroboroslabs/claude-fable-5Q:latest" for c in production))
        fable = next(c for c in canary if c["model"] == "oroboroslabs/claude-fable-5Q:latest")
        self.assertEqual(fable["trust"], "unverified")
        self.assertEqual(fable["status"], "experimental")
        self.assertLess(fable["cap"], 10)
        self.assertTrue(fable["canary_only"])

    def test_ollama_catalog_adds_uninstalled_fable_to_canary_lane(self):
        tags = {"models": [{"name": "llama3.1"}]}
        resp = MagicMock()
        resp.read.return_value = __import__("json").dumps(tags).encode()
        resp.__enter__.return_value = resp
        with patch.object(ollama_catalog.urllib.request, "urlopen", return_value=resp), \
             patch.dict(os.environ, {"ORCH_CANARY_ONLY_OLLAMA_MODELS": "oroboroslabs/claude-fable-5Q"}, clear=False):
            canary = ollama_catalog.candidates(include_canary_only=True)
        fable = next(c for c in canary if c["model"] == "oroboroslabs/claude-fable-5Q")
        self.assertTrue(fable["canary_only"])
        self.assertTrue(fable["not_installed"])

    def test_ollama_catalog_can_promote_community_claim_only_by_flag(self):
        with patch.dict(os.environ, {"ORCH_TRUST_COMMUNITY_CLAUDE_OLLAMA": "true"}, clear=False):
            self.assertEqual(ollama_catalog.infer_cap("sorc/qwen3.5-claude-4.6-opus:latest"), 10)

    def test_ollama_catalog_keeps_very_heavy_local_model_canary_only_on_low_ram_box(self):
        # codestral:22b needs 16GB (local_model_slots.RAM_GB); on a 24GB box that's not enough
        # headroom to load it during real agentic work without clamping the fleet to one lane.
        tags = {"models": [{"name": "codestral:22b"}, {"name": "llama3.1"}]}
        resp = MagicMock()
        resp.read.return_value = __import__("json").dumps(tags).encode()
        resp.__enter__.return_value = resp
        with patch.object(ollama_catalog.urllib.request, "urlopen", return_value=resp), \
             patch.object(resource_governor, "total_gb", return_value=24.0), \
             patch.dict(os.environ, {}, clear=False):
            production = ollama_catalog.candidates()
            canary = ollama_catalog.candidates(include_canary_only=True)
        self.assertFalse(any(c["model"] == "codestral:22b" for c in production))
        self.assertTrue(any(c["model"] == "llama3.1" for c in production))
        heavy = next(c for c in canary if c["model"] == "codestral:22b")
        self.assertTrue(heavy["canary_only"])

    def test_ollama_catalog_promotes_heavy_local_model_when_ram_headroom_is_sufficient(self):
        tags = {"models": [{"name": "codestral:22b"}]}
        resp = MagicMock()
        resp.read.return_value = __import__("json").dumps(tags).encode()
        resp.__enter__.return_value = resp
        with patch.object(ollama_catalog.urllib.request, "urlopen", return_value=resp), \
             patch.object(resource_governor, "total_gb", return_value=64.0), \
             patch.dict(os.environ, {}, clear=False):
            production = ollama_catalog.candidates()
        self.assertTrue(any(c["model"] == "codestral:22b" for c in production))

    def test_ollama_catalog_heavy_hot_lane_flag_overrides_ram_gate(self):
        tags = {"models": [{"name": "codestral:22b"}]}
        resp = MagicMock()
        resp.read.return_value = __import__("json").dumps(tags).encode()
        resp.__enter__.return_value = resp
        env = {"ORCH_TRUST_HEAVY_OLLAMA_HOT_LANE": "true"}
        with patch.object(ollama_catalog.urllib.request, "urlopen", return_value=resp), \
             patch.object(resource_governor, "total_gb", return_value=8.0), \
             patch.dict(os.environ, env, clear=False):
            production = ollama_catalog.candidates()
        self.assertTrue(any(c["model"] == "codestral:22b" for c in production))

    def test_ollama_catalog_heavy_model_stays_canary_only_when_ram_unknown(self):
        tags = {"models": [{"name": "codestral:22b"}]}
        resp = MagicMock()
        resp.read.return_value = __import__("json").dumps(tags).encode()
        resp.__enter__.return_value = resp
        with patch.object(ollama_catalog.urllib.request, "urlopen", return_value=resp), \
             patch.object(resource_governor, "total_gb", return_value=None), \
             patch.dict(os.environ, {}, clear=False):
            production = ollama_catalog.candidates()
        self.assertFalse(any(c["model"] == "codestral:22b" for c in production))

    def test_auto_coders_hot_lane_excludes_heavy_local_model_on_low_ram_box(self):
        with patch.object(ollama_catalog, "candidates", return_value=[
                {"provider": "local", "model": "llama3.1", "cap": 6, "tier": "free"},
             ]), \
             patch.object(agentic_coders, "_aider_available", return_value=True), \
             patch.object(model_gateway, "available", return_value=["local"]):
            coders = agentic_coders._auto_coders()

        def _cmd_has(coder, needle):
            return needle in str(coder.get("cmd") or "")

        self.assertTrue(any(_cmd_has(c, "llama3.1") for c in coders))
        self.assertFalse(any(_cmd_has(c, "codestral:22b") for c in coders))

    def test_model_catalog_can_choose_strongest_local_for_high_need(self):
        with patch.object(ollama_catalog, "candidates", return_value=[
                {"provider": "local", "model": "llama3.1", "cap": 6, "tier": "free"},
                {"provider": "local", "model": "opus-4.6-local", "cap": 10, "tier": "free"},
             ]), \
             patch.object(model_gateway, "available", return_value=["local"]):
            pick = __import__("model_catalog").choose("security", need=9)
        self.assertEqual(pick["model"], "opus-4.6-local")

    def test_model_catalog_uses_current_vendor_value_defaults(self):
        catalog = __import__("model_catalog")
        with patch.object(model_gateway, "available", return_value=["openai", "google", "deepseek", "claude"]), \
             patch.object(catalog, "_empirical_score", return_value=0.0):
            cheap = catalog.choose("review", need=5)
            hard = catalog.choose("security", need=9)
        self.assertIn(cheap["model"], {"gpt-5.4-nano", "gemini-2.5-flash-lite-preview-09-2025", "deepseek-v4-flash"})
        self.assertGreaterEqual(hard["cap"], 9)

    def test_model_catalog_ignores_deprecated_env_models(self):
        catalog = __import__("model_catalog")
        with patch.dict(os.environ, {"GEMINI_MODEL": "gemini-2.0-flash"}, clear=False), \
             patch.object(model_gateway, "available", return_value=["google"]):
            catalog = importlib.reload(catalog)
            with patch.object(catalog, "_empirical_score", return_value=0.0):
                models = [c["model"] for c in catalog.available()]
                pick = catalog.choose("plan", need=7)
        importlib.reload(catalog)
        self.assertNotIn("gemini-2.0-flash", models)
        self.assertEqual(pick["model"], "gemini-2.5-flash")

    def test_non_agentic_review_routes_to_external_before_claude_when_sparse(self):
        with patch.object(model_policy.mg, "available", return_value=["claude", "deepseek", "google", "openai"]), \
             patch.object(model_policy, "_least_used", return_value=None), \
             patch.object(model_policy, "_rr_next", return_value=0):
            provider, model, why = model_policy.choose("review", agentic=False, need=6)
        self.assertIn(provider, {"deepseek", "google", "openai"})
        self.assertNotEqual(provider, "claude")
        self.assertIn("non-agentic review", why)

    def test_complete_falls_back_to_next_provider(self):
        calls = []

        def fake_call(provider, model, prompt, project=None, timeout=90):
            calls.append((provider, model))
            if provider == "deepseek":
                raise RuntimeError("deepseek down")
            return {"text": "ok", "cost_usd": 0.01, "provider": provider, "model": model}

        with patch.object(model_gateway, "available", return_value=["deepseek", "google", "openai", "claude"]), \
             patch.object(model_gateway, "_call_provider", side_effect=fake_call):
            res = model_gateway.complete("deepseek", "deepseek-chat", "hello", record_op=False)

        self.assertEqual(res["provider"], "google")
        self.assertEqual(res["fallback_from"], "deepseek")
        self.assertEqual(calls[0][0], "deepseek")
        self.assertEqual(calls[1][0], "google")

    def test_complete_prefers_learned_route_when_quality_is_high(self):
        db = MagicMock()
        db.select.return_value = [{
            "provider": "deepseek",
            "model": "deepseek-chat",
            "avg_quality": 7.4,
        }]
        calls = []

        def fake_call(provider, model, prompt, project=None, timeout=90):
            calls.append((provider, model))
            return {"text": "ok", "cost_usd": 0.0, "provider": provider, "model": model}

        with patch.dict(os.environ, {"ORCH_USE_LEARNED_APP_ROUTES": "true"}, clear=False), \
             patch.object(model_gateway, "available", return_value=["claude", "deepseek"]), \
             patch.object(model_gateway, "_provider_allowed", return_value=True), \
             patch.dict(sys.modules, {"db": db}), \
             patch.dict(sys.modules, {"prompt_result_cache": None}), \
             patch.object(model_gateway, "_call_provider", side_effect=fake_call):
            res = model_gateway.complete("claude", "claude-haiku-4-5-20251001", "hello",
                                         project="orchestrator", operation="plan",
                                         task_class="plan", record_op=False)

        self.assertEqual(res["provider"], "deepseek")
        self.assertIn("learned", res["learned_route"])
        self.assertEqual(calls[0], ("deepseek", "deepseek-chat"))

    def test_complete_skips_low_quality_learned_route(self):
        db = MagicMock()
        db.select.return_value = [{
            "provider": "deepseek",
            "model": "deepseek-chat",
            "avg_quality": 4.0,
        }]

        with patch.dict(os.environ, {"ORCH_USE_LEARNED_APP_ROUTES": "true"}, clear=False), \
             patch.object(model_gateway, "available", return_value=["claude", "deepseek"]), \
             patch.object(model_gateway, "_provider_allowed", return_value=True), \
             patch.dict(sys.modules, {"db": db}), \
             patch.dict(sys.modules, {"prompt_result_cache": None}), \
             patch.object(model_gateway, "_call_provider", return_value={
                 "text": "ok", "cost_usd": 0.0, "provider": "claude",
                 "model": "claude-haiku-4-5-20251001",
             }):
            res = model_gateway.complete("claude", "claude-haiku-4-5-20251001", "hello",
                                         project="orchestrator", operation="plan",
                                         task_class="plan", record_op=False)

        self.assertEqual(res["provider"], "claude")
        self.assertNotIn("learned_route", res)

    def test_provider_for_model_handles_common_families(self):
        self.assertEqual(model_gateway.provider_for_model("gemini-2.0-flash"), "google")
        self.assertEqual(model_gateway.provider_for_model("deepseek-chat"), "deepseek")
        self.assertEqual(model_gateway.provider_for_model("gpt-4o-mini"), "openai")
        self.assertEqual(model_gateway.provider_for_model("claude-haiku-4-5"), "claude")

    def test_app_triage_records_actual_fallback_provider(self):
        rows = []
        db = MagicMock()
        db.insert.side_effect = lambda table, row, **kw: rows.append((table, row))
        with patch.object(app_triage, "db", db), \
             patch.object(app_triage, "route", return_value={
                 "provider": "deepseek", "model": "deepseek-chat",
                 "reason": "test", "source": "policy",
             }), \
             patch.object(app_triage.mg, "complete", return_value={
                 "provider": "google", "model": "gemini-2.0-flash",
                 "text": "ok", "cost_usd": 0,
             }):
            res = app_triage.run("orchestrator", "verify", "prompt", task_class="review")
        self.assertEqual(res["provider"], "google")
        self.assertEqual(rows[0][1]["provider"], "google")

    def test_agentic_coders_auto_register_paid_and_local_backends(self):
        env = {
            "ORCH_AUTO_AGENTIC_CODERS": "true",
            "ORCH_USE_PAID_AGENTIC_CREDITS": "true",
            "ORCH_PAID_AGENTIC_DAILY_USD": "25",
            "OLLAMA_MODEL": "llama3.1",
        }
        with patch.dict(os.environ, env, clear=False), \
             patch.object(agentic_coders, "_aider_available", return_value=True), \
             patch.object(agentic_coders, "_within_cap", return_value=True), \
             patch.object(agentic_coders, "_AIDER_OK", True), \
             patch("model_gateway.available", return_value=["claude", "local", "deepseek", "google", "openai"]):
            names = agentic_coders.available()
        self.assertIn("ollama", names)
        self.assertIn("deepseek", names)
        self.assertIn("gemini", names)
        self.assertIn("gpt", names)

    def test_aider_commands_are_headless_and_warning_suppressed(self):
        cmd = agentic_coders._aider_cmd("ollama/qwen3-coder:30b")
        self.assertIn("--no-show-model-warnings", cmd)
        self.assertIn("--no-check-model-accepts-settings", cmd)
        self.assertIn("--no-browser", cmd)
        self.assertIn("--yes-always", cmd)
        self.assertIn("--no-auto-commits", cmd)

    def test_legacy_aider_extra_command_is_normalized(self):
        cmd = "aider --model openai/gpt-4o-mini --yes --no-auto-commit --message {prompt}"
        out = agentic_coders._normalize_aider_cmd(cmd)
        self.assertIn("--yes-always", out)
        self.assertIn("--no-auto-commits", out)
        self.assertIn("--no-show-model-warnings", out)
        self.assertIn("--no-browser", out)
        self.assertNotIn("--no-auto-commit --", out)

    def test_aider_env_sets_ollama_api_base_and_suppresses_browser_warnings(self):
        env = agentic_coders._aider_env({"OLLAMA_HOST": "http://localhost:11434"})
        self.assertEqual(env["OLLAMA_API_BASE"], "http://localhost:11434")
        self.assertEqual(env["AIDER_SHOW_MODEL_WARNINGS"], "false")
        self.assertEqual(env["AIDER_GUI"], "false")

    def test_agentic_coders_register_multiple_ollama_models(self):
        env = {"ORCH_AUTO_AGENTIC_CODERS": "true", "ORCH_USE_PAID_AGENTIC_CREDITS": "false"}
        with patch.dict(os.environ, env, clear=False), \
             patch.object(agentic_coders, "_aider_available", return_value=True), \
             patch("model_gateway.available", return_value=["claude", "local"]), \
             patch.object(ollama_catalog, "candidates", return_value=[
                 {"provider": "local", "model": "opus-4.6-local", "cap": 10, "tier": "free"},
                 {"provider": "local", "model": "llama3.1", "cap": 6, "tier": "free"},
             ]):
            pool = [agentic_coders._spec(n) for n in agentic_coders.available()]
        self.assertTrue(any(c and c["cap"] == 10 and "opus-4.6-local" in (c.get("cmd") or "") for c in pool))

    def test_agentic_easy_work_can_route_to_non_claude(self):
        env = {"ORCH_EASY_OFFLOAD_SHARE": "1.0", "ORCH_AUTO_AGENTIC_CODERS": "true",
               "ORCH_TRUST_HEAVY_OLLAMA_HOT_LANE": "true"}  # hermetic: exclusion reads real RAM
        task = {"slug": "easy-docs", "kind": "docs", "prompt": "update docs", "deps": []}
        with patch.dict(os.environ, env, clear=False), \
             patch.object(agentic_coders, "_aider_available", return_value=True), \
             patch.object(agentic_coders, "_within_cap", return_value=True), \
             patch("model_gateway.available", return_value=["claude", "deepseek", "openai"]):
            self.assertNotEqual(agentic_coders.pick(task), "claude")

    def test_forced_canary_uses_target_coder_even_with_long_context(self):
        coders = [
            {"name": "claude", "cost": 1, "cap": 10},
            {"name": "gemini", "cmd": "aider --model gemini/gemini-2.0-flash --message {prompt}",
             "cost": 2, "cap": 6, "daily_usd": 25},
            {"name": "codex", "cmd": "codex exec {prompt}", "cost": 1, "cap": 8, "daily_usd": 0},
        ]
        task = {"slug": "canary-gemini-1", "kind": "canary", "prompt": "historical context " * 200,
                "force_coder": "gemini", "deps": []}
        with patch.object(agentic_coders, "_pool", return_value=coders), \
             patch.object(agentic_coders, "_within_cap", return_value=True), \
             patch.object(agentic_coders, "_allowed_by_terms", return_value=True), \
             patch.object(agentic_coders, "_heavy_ollama_saturated", return_value=False):
            self.assertEqual(agentic_coders.pick(task), "gemini")

    def test_forced_aider_resolves_to_non_claude_backend(self):
        coders = [
            {"name": "claude", "cmd": None, "cost": 1, "cap": 10, "daily_usd": 0},
            {"name": "ollama", "cmd": "aider --model ollama/qwen --message {prompt}",
             "cost": 0, "cap": 6, "daily_usd": 0},
        ]
        task = {"slug": "qafix-app-123", "kind": "bugfix", "prompt": "fix build",
                "force_coder": "aider", "deps": [], "_need": 8}
        with patch.object(agentic_coders, "_pool", return_value=coders), \
             patch.object(agentic_coders, "_within_cap", return_value=True), \
             patch.object(agentic_coders, "_allowed_by_terms", return_value=True), \
             patch.object(agentic_coders, "_heavy_ollama_saturated", return_value=False):
            self.assertEqual(agentic_coders.pick(task), "ollama")

    def test_forced_canary_bypasses_existing_branch_shortcut(self):
        self.assertTrue(runner_entrypoint._must_run_agent_for_evidence(
            {"slug": "recover-missing-branch-canary-gpt-1", "kind": "canary", "force_coder": "gpt"},
            "recover-missing-branch-canary-gpt-1",
        ))
        self.assertFalse(runner_entrypoint._must_run_agent_for_evidence(
            {"slug": "recover-missing-branch-buildfix-x", "kind": "bugfix", "force_coder": "gpt"},
            "recover-missing-branch-buildfix-x",
        ))

    def test_agentic_material_work_can_use_paid_credits_when_capable(self):
        env = {
            "ORCH_HARD_OFFLOAD_SHARE": "1.0",
            "ORCH_USE_PAID_AGENTIC_CREDITS": "true",
            "ORCH_AUTO_AGENTIC_CODERS": "true",
            "ORCH_SECOND_CODER": "",
            "ORCH_SECOND_CODER_CMD": "",
        }
        task = {"slug": "material-api", "kind": "build", "prompt": "build material endpoint", "material": True, "deps": []}
        with patch.dict(os.environ, env, clear=False), \
             patch.object(agentic_coders, "_aider_available", return_value=True), \
             patch.object(agentic_coders, "_within_cap", return_value=True), \
            patch("model_gateway.available", return_value=["claude", "openai"]):
            self.assertEqual(agentic_coders.pick(task), "gpt")

    def test_agentic_critical_work_does_not_drop_below_required_capability(self):
        env = {
            "ORCH_USE_PAID_AGENTIC_CREDITS": "true",
            "ORCH_AUTO_AGENTIC_CODERS": "true",
            "ORCH_CRITICAL_NON_CLAUDE_SHARE": "0",
            "ORCH_SECOND_CODER": "",
            "ORCH_SECOND_CODER_CMD": "",
        }
        task = {"slug": "critical-auth", "kind": "security", "prompt": "private key custody threat model", "deps": []}
        with patch.dict(os.environ, env, clear=False), \
             patch.object(agentic_coders, "_aider_available", return_value=True), \
            patch.object(agentic_coders, "_within_cap", return_value=True), \
             patch("model_gateway.available", return_value=["claude", "openai"]):
            picked = agentic_coders.pick(task)
            self.assertIn(picked, ("claude", "gpt"))
            self.assertGreaterEqual((agentic_coders._spec(picked) or {}).get("cap", 0), 9)

    def test_router_stats_scores_delivered_value_not_static_cost(self):
        rows = []
        for i in range(router_stats.MIN_SAMPLES):
            rows.append({"model": "cheap", "kind": "build", "integrated": i == 0,
                         "tests_passed": i < 4, "usd": 0.0, "wall_ms": 900000,
                         "attempts": 3, "slug": f"cheap-{i}"})
            rows.append({"model": "value", "kind": "build", "integrated": True,
                         "tests_passed": True, "usd": 0.05, "wall_ms": 60000,
                         "attempts": 1, "slug": f"value-{i}"})
        db = MagicMock()
        db.select.return_value = rows
        with patch.object(router_stats, "db", db), \
             patch.object(router_stats, "_CACHE", {"t": 0.0, "table": {}}):
            self.assertEqual(router_stats.best_coder("build", ["cheap", "value"]), "value")

    def test_runner_failover_prefers_local_non_claude(self):
        coders = [
            {"name": "claude", "cost": 1, "cap": 10},
            {"name": "codex", "cost": 1, "cap": 8},
            {"name": "ollama", "cost": 0, "cap": 9},
        ]
        with patch.object(agentic_coders, "_pool", return_value=coders), \
             patch.object(agentic_coders, "_within_cap", return_value=True), \
             patch.object(agentic_coders, "_allowed_by_terms", return_value=True), \
             patch.object(agentic_coders, "_task_sensitivity", return_value="standard"):
            self.assertEqual(runner_entrypoint._next_non_claude_coder({"prompt": "x"}), "ollama")
            self.assertEqual(runner_entrypoint._next_non_claude_coder({"prompt": "x"}, exclude={"ollama"}), "codex")

    def test_pick_skips_saturated_heavy_ollama_model(self):
        coders = [
            {"name": "claude", "cost": 1, "cap": 10},
            {"name": "ollama", "cmd": "aider --model ollama/qwen3-coder:30b --message {prompt}",
             "cost": 0, "cap": 9, "daily_usd": 0},
            {"name": "ollama-2", "cmd": "aider --model ollama/deepseek-coder-v2:16b --message {prompt}",
             "cost": 0, "cap": 8, "daily_usd": 0},
        ]
        task = {"slug": "hard-safe", "kind": "bugfix", "prompt": "fix build", "_need": 8}
        with patch.object(agentic_coders, "_pool", return_value=coders), \
             patch.object(agentic_coders, "_within_cap", return_value=True), \
             patch.object(agentic_coders, "_allowed_by_terms", return_value=True), \
             patch.object(agentic_coders, "_task_sensitivity", return_value="standard"), \
             patch.object(agentic_coders, "_heavy_running_counts", return_value={"qwen3-coder:30b": 2}), \
             patch.dict(os.environ, {"ORCH_HEAVY_OLLAMA_RUNNING_CAP": "1",
                                     "ORCH_HARD_OFFLOAD_SHARE": "1",
                                     "ORCH_USE_PAID_AGENTIC_CREDITS": "true"}, clear=False):
            self.assertEqual(agentic_coders.pick(task), "ollama-2")


if __name__ == "__main__":
    unittest.main()
