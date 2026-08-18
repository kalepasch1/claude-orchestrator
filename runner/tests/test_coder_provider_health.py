"""A coder whose vendor is out of credits must stop being selected.

OBSERVED. A canary burned attempt after attempt on:

    litellm.APIError: XaiException - Error code: 403 - 'Your team … has either used all
    available credits or reached its monthly spending limit.'
    Retrying in 4.0s … 8.0s … 16.0s … 32.0s

Those retries are aider's own loop (aider.models.RETRY_TIMEOUT = 60 — it retries ANY
exception until the window closes). LITELLM_NUM_RETRIES=1 does not bound it and there is
no env knob for it, so roughly a minute is burned per attempt on a 403 that cannot resolve
until someone buys credits.

The retry loop is not the thing to fight — SELECTING a dead vendor is. Nothing in the
coder pool consulted provider health, so the dead vendor stayed selectable forever.

The gate must fail OPEN: removing a working coder is a worse outage than the one it
prevents, so anything uncertain stays eligible.
"""
import os
import sys
import types
import unittest
from unittest import mock

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DIR)

import agentic_coders as ac  # noqa: E402

XAI = {"name": "grok", "cmd": "python3 -m aider --model xai/grok-3-mini-fast --yes"}
GEMINI = {"name": "gemini", "cmd": "python3 -m aider --model gemini/gemini-4.0-flash --yes"}
CLAUDE = {"name": "claude", "cmd": None}


def _sla(demoted):
    return types.SimpleNamespace(is_demoted=lambda p: p in demoted)


class ProviderExtractionTest(unittest.TestCase):
    def test_reads_the_vendor_from_the_model_argument(self):
        self.assertEqual(ac.coder_provider(XAI), "xai")
        self.assertEqual(ac.coder_provider(GEMINI), "gemini")

    def test_claude_is_recognised_without_a_model_argument(self):
        self.assertEqual(ac.coder_provider(CLAUDE), "claude")

    def test_ollama_style_local_models(self):
        self.assertEqual(
            ac.coder_provider({"name": "q", "cmd": "aider --model ollama/qwen2.5 --yes"}),
            "ollama")

    def test_a_bare_model_name_has_no_provider(self):
        self.assertEqual(ac.coder_provider({"name": "x", "cmd": "aider --model gpt-4o"}), "")

    def test_no_model_argument_at_all(self):
        self.assertEqual(ac.coder_provider({"name": "x", "cmd": "some-tool --run"}), "")

    def test_malformed_entries_do_not_raise(self):
        for bad in ({}, {"cmd": None}, {"cmd": 5}, {"name": None, "cmd": "--model "}):
            self.assertIsInstance(ac.coder_provider(bad), str)


class HealthGateTest(unittest.TestCase):
    def test_a_demoted_vendor_is_unhealthy(self):
        with mock.patch.dict(sys.modules, {"provider_failover_sla": _sla({"xai"})}):
            self.assertFalse(ac._provider_healthy(XAI))

    def test_other_vendors_are_unaffected(self):
        with mock.patch.dict(sys.modules, {"provider_failover_sla": _sla({"xai"})}):
            self.assertTrue(ac._provider_healthy(GEMINI))

    def test_claude_is_never_gated_out(self):
        # claude is the fallback of last resort; gating it would strand the queue
        with mock.patch.dict(sys.modules, {"provider_failover_sla": _sla({"claude"})}):
            self.assertTrue(ac._provider_healthy(CLAUDE))

    def test_unknown_provider_stays_eligible(self):
        with mock.patch.dict(sys.modules, {"provider_failover_sla": _sla({"xai"})}):
            self.assertTrue(ac._provider_healthy({"name": "x", "cmd": "tool --go"}))

    def test_fails_open_when_the_registry_raises(self):
        boom = types.SimpleNamespace(
            is_demoted=mock.MagicMock(side_effect=RuntimeError("registry down")))
        with mock.patch.dict(sys.modules, {"provider_failover_sla": boom}):
            self.assertTrue(ac._provider_healthy(XAI))

    def test_fails_open_when_the_registry_is_missing(self):
        with mock.patch.dict(sys.modules, {"provider_failover_sla": None}):
            self.assertTrue(ac._provider_healthy(XAI))

    def test_kill_switch_disables_the_gate(self):
        with mock.patch.dict(os.environ, {"ORCH_CODER_PROVIDER_HEALTH_GATE": "false"}), \
             mock.patch.dict(sys.modules, {"provider_failover_sla": _sla({"xai"})}):
            self.assertTrue(ac._provider_healthy(XAI))


class SelectionWiringTest(unittest.TestCase):
    """The gate has to be ON the eligibility filters, not merely importable."""

    def _source(self):
        with open(os.path.join(_DIR, "agentic_coders.py")) as fh:
            return fh.read()

    def test_every_within_cap_filter_also_checks_provider_health(self):
        src = self._source()
        self.assertEqual(src.count("_within_cap(c)"),
                         src.count("_within_cap(c) and _provider_healthy(c)"))

    def test_the_gate_is_applied_in_more_than_one_place(self):
        # selection happens through several branches; gating only one leaves holes
        self.assertGreaterEqual(
            self._source().count("_provider_healthy(c)"), 5)


if __name__ == "__main__":
    unittest.main()
