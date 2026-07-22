"""
Regression tests for confidential routing controls.
All provider calls are mocked; no network.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import model_gateway
import model_policy
import privacy


class EnvCase(unittest.TestCase):
    def setUp(self):
        self._env = dict(os.environ)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)


class TestConfidentialRouting(EnvCase):
    def test_confidential_mode_disables_provider_fallback(self):
        os.environ["ORCH_CONFIDENTIAL_MODE"] = "true"
        calls = []
        orig_call = model_gateway._call_provider
        orig_avail = model_gateway.available
        try:
            model_gateway.available = lambda: ["openai", "local"]

            def fake_call(provider, model, prompt, project=None, timeout=90):
                calls.append(provider)
                raise RuntimeError("primary unavailable")

            model_gateway._call_provider = fake_call
            res = model_gateway.complete("openai", "gpt-4o-mini", "confidential prompt")
            self.assertEqual(calls, [])
            self.assertEqual(res["provider"], "openai")
            self.assertIn("no provider allowed", res.get("error", ""))
        finally:
            model_gateway._call_provider = orig_call
            model_gateway.available = orig_avail

    def test_non_confidential_mode_can_fallback(self):
        os.environ.pop("ORCH_CONFIDENTIAL_MODE", None)
        os.environ["ORCH_USE_LEARNED_APP_ROUTES"] = "false"
        calls = []
        orig_call = model_gateway._call_provider
        orig_avail = model_gateway.available
        try:
            model_gateway.available = lambda: ["openai", "local"]

            def fake_call(provider, model, prompt, project=None, timeout=90):
                calls.append(provider)
                if provider == "openai":
                    raise RuntimeError("primary unavailable")
                return {"text": "ok", "cost_usd": 0, "provider": provider, "model": model}

            model_gateway._call_provider = fake_call
            res = model_gateway.complete("openai", "gpt-4o-mini", "routine prompt")
            self.assertEqual(calls, ["openai", "local"])
            self.assertEqual(res["provider"], "local")
        finally:
            model_gateway._call_provider = orig_call
            model_gateway.available = orig_avail


class TestModelPolicy(EnvCase):
    def test_diversification_defaults_off(self):
        os.environ.pop("ORCH_DIVERSIFY_MODELS", None)
        os.environ.pop("ORCH_CONFIDENTIAL_MODE", None)
        orig_avail = model_policy.mg.available
        try:
            model_policy.mg.available = lambda: ["local", "openai", "claude"]
            picks = [model_policy.choose("review", agentic=False, need=5)[0] for _ in range(4)]
            self.assertEqual(picks, ["local", "local", "local", "local"])
        finally:
            model_policy.mg.available = orig_avail

    def test_privacy_sensitivity_flags_ip(self):
        self.assertEqual(privacy.sensitivity("unreleased roadmap and pricing model"), "confidential")
        self.assertEqual(privacy.sensitivity("fix a typo in docs"), "standard")


if __name__ == "__main__":
    unittest.main(verbosity=2)
