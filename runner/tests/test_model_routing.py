import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_gateway
import model_policy
import app_triage


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

    def test_non_agentic_review_routes_to_external_before_claude_when_sparse(self):
        with patch.object(model_policy.mg, "available", return_value=["claude", "deepseek", "google", "openai"]), \
             patch.object(model_policy, "_least_used", return_value=None), \
             patch.object(model_policy, "_rr_next", return_value=0):
            provider, model, why = model_policy.choose("review", agentic=False, need=6)
        self.assertEqual(provider, "deepseek")
        self.assertEqual(model, "deepseek-chat")
        self.assertIn("rotating", why)

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


if __name__ == "__main__":
    unittest.main()
