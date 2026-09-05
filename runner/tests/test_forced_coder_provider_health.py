"""A `force_coder` pin must not outrank provider liveness.

OBSERVED (canary-gemini-25 build slices, five attempts each). The tasks carried
`force_coder = "xai…"` while xai answered every call with:

    litellm.APIError: XaiException - Error code: 403 - 'Your team … has either used
    all available credits or reached its monthly spending limit.'

`_provider_healthy` already existed and the demote registry already knew xai was
down — but the forced-coder fast path in `_pick_raw` returned the pin *before* any
health filter ran. Every other branch of the selector filters on `_provider_healthy`;
that one did not, so a pinned dead vendor was re-selected on every attempt and each
attempt paid aider's full 60-second retry window for a 403 that cannot resolve until
someone buys credits.

A pin is a routing preference, not an override of liveness. When the pinned coder's
provider is demoted the pin is dropped and normal selection runs. The gate still fails
OPEN, so a coder whose vendor cannot be determined keeps its pin.
"""
import os
import re
import sys
import types
import unittest
from unittest import mock

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DIR)

import agentic_coders as ac  # noqa: E402


def _sla(demoted):
    return types.SimpleNamespace(is_demoted=lambda p: p in demoted)


def _pool_with(*coders):
    return list(coders)


HEALTHY = {"name": "gemini", "cmd": "aider --model gemini/gemini-4.0-flash --yes",
           "cost": 2, "cap": 9}
DEAD = {"name": "grok", "cmd": "aider --model xai/grok-3-mini-fast --yes",
        "cost": 2, "cap": 9}
LOCAL = {"name": "ollama-q", "cmd": "aider --model ollama/qwen2.5-coder --yes",
         "cost": 0, "cap": 9}


class ForcedCoderHealthGateTest(unittest.TestCase):
    """Behavioural: the pin loses to a demoted provider."""

    def _pick(self, forced, pool, demoted):
        task = {"force_coder": forced, "slug": "canary-gemini-25-fix-build-config",
                "kind": "build", "prompt": "fix the build configuration"}
        with mock.patch.object(ac, "_pool", lambda: _pool_with(*pool)), \
             mock.patch.dict(sys.modules, {"provider_failover_sla": _sla(demoted)}):
            return ac._pick_raw(task)

    def test_a_pinned_dead_provider_is_not_returned(self):
        picked = self._pick("grok", [DEAD, HEALTHY, LOCAL], {"xai"})
        self.assertNotEqual(picked, "grok")

    def test_the_work_still_goes_somewhere(self):
        picked = self._pick("grok", [DEAD, HEALTHY, LOCAL], {"xai"})
        self.assertTrue(picked, "dropping a dead pin must not strand the task")

    def test_a_pinned_healthy_provider_is_still_honoured(self):
        picked = self._pick("grok", [DEAD, HEALTHY, LOCAL], {"openai"})
        self.assertEqual(picked, "grok")

    def test_an_undeterminable_provider_keeps_its_pin(self):
        # fail-open: removing a working coder is worse than the outage it prevents
        odd = {"name": "mystery", "cmd": "somecli run {prompt}", "cost": 1, "cap": 9}
        picked = self._pick("mystery", [odd, HEALTHY], {"xai", "openai", "google"})
        self.assertEqual(picked, "mystery")

    def test_the_kill_switch_restores_the_old_behaviour(self):
        with mock.patch.dict(os.environ, {"ORCH_CODER_PROVIDER_HEALTH_GATE": "false"}):
            picked = self._pick("grok", [DEAD, HEALTHY, LOCAL], {"xai"})
        self.assertEqual(picked, "grok")

    def test_a_demoted_pin_does_not_raise(self):
        # fail-soft: selection must never wedge the runner, even with an empty pool
        try:
            self._pick("grok", [DEAD], {"xai"})
        except Exception as e:  # noqa: BLE001 — the point of the assertion
            self.fail(f"selection raised on a fully-dead pool: {e!r}")


class ForcedCoderWiringTest(unittest.TestCase):
    """Source-level: the gate must be ON the forced path, not merely importable."""

    def _source(self):
        with open(os.path.join(_DIR, "agentic_coders.py")) as fh:
            return fh.read()

    def test_the_forced_branch_consults_provider_health(self):
        src = self._source()
        start = src.find('forced = str(task.get("force_coder")')
        self.assertGreater(start, -1, "forced-coder branch not found")
        branch = src[start:start + 2500]
        self.assertIn("_provider_healthy(fc)", branch,
                      "the force_coder fast path must filter on provider health")

    def test_the_health_check_precedes_every_return_of_the_pin(self):
        src = self._source()
        start = src.find('forced = str(task.get("force_coder")')
        branch = src[start:start + 2500]
        gate = branch.find("_provider_healthy(fc)")
        self.assertGreater(gate, -1)
        for m in re.finditer(r"return (?:forced|\"claude\")", branch):
            self.assertGreater(m.start(), gate,
                               "a pin is returned before the health gate runs")


if __name__ == "__main__":
    unittest.main()
