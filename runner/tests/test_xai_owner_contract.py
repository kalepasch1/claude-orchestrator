#!/usr/bin/env python3
"""Acceptance test: `runner/model_gateway.py` is the owner module for the xAI lane.

WHY THIS FILE EXISTS
--------------------
"Locate the existing owner module" keeps coming back to the queue, and it keeps coming
back because locating a module produces nothing durable — the next agent searches again
and may land somewhere else. For xAI there are several plausible-looking candidates:

    runner/model_gateway.py     <- the owner: credentials, pricing, the HTTP call
    runner/model_catalog.py     declares which xai models exist and their capability caps
    runner/model_policy.py      picks a provider; does not know how to call one
    runner/model_scout.py       evaluates providers; does not route production work
    runner/patch_tournament.py  a consumer

This is the answer written as an executable assertion rather than a note: it pins where
the lane lives, the surface it must keep, and the invariants that make it the owner
rather than another reader of the same env vars.

It also pins one live hazard it found — see XaiDefaultDivergenceTest.
"""
from __future__ import annotations

import os
import sys
import unittest

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RUNNER not in sys.path:
    sys.path.insert(0, RUNNER)

import model_catalog  # noqa: E402
import model_gateway  # noqa: E402


class OwnerModuleLocationTest(unittest.TestCase):
    def test_the_owner_module_is_runner_model_gateway(self):
        self.assertTrue(os.path.isfile(os.path.join(RUNNER, "model_gateway.py")))

    def test_the_gateway_owns_the_actual_call(self):
        """Exactly one module knows the xAI endpoint. Two would drift."""
        self.assertTrue(callable(getattr(model_gateway, "_xai", None)))
        with open(os.path.join(RUNNER, "model_gateway.py"), encoding="utf-8") as handle:
            self.assertIn("https://api.x.ai/v1/chat/completions", handle.read())

    def test_the_owner_exports_the_endpoint_for_other_callers_to_import(self):
        self.assertEqual(model_gateway.XAI_CHAT_ENDPOINT,
                         "https://api.x.ai/v1/chat/completions")

    def test_no_new_module_hardcodes_the_xai_endpoint(self):
        """A ratchet, not a clean sweep.

        The URL is already spelled out in three other modules, found by this test:
        swarm_executor.py and vendor_capabilities.py each carry their own chat client,
        and model_scout.py hits the sibling /models path. Rewriting three live callers is
        a consolidation, not a "locate the owner" slice, so they are recorded here — and
        the owner now exports XAI_CHAT_ENDPOINT so the next caller has something to
        import. This list may shrink and must never grow.
        """
        known = {"swarm_executor.py", "vendor_capabilities.py", "model_scout.py"}
        offenders = set()
        for name in os.listdir(RUNNER):
            if not name.endswith(".py") or name == "model_gateway.py":
                continue
            try:
                with open(os.path.join(RUNNER, name), encoding="utf-8",
                          errors="replace") as handle:
                    if "api.x.ai" in handle.read():
                        offenders.add(name)
            except OSError:
                continue
        self.assertEqual(offenders - known, set(),
                         "a NEW copy of the xAI endpoint appeared; import "
                         "model_gateway.XAI_CHAT_ENDPOINT instead")
        self.assertEqual(known - offenders, set(),
                         "one of the known copies is gone — remove it from `known`")

    def test_the_provider_is_registered_in_the_dispatch_table(self):
        with open(os.path.join(RUNNER, "model_gateway.py"), encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn('"xai": _xai', source)
        self.assertIn("xai", model_gateway.FALLBACK_ORDER)

    def test_a_grok_model_name_routes_to_the_xai_provider(self):
        self.assertEqual(model_gateway.provider_for_model("grok-4.3"), "xai")
        self.assertEqual(model_gateway.provider_for_model("GROK-BUILD-0.1"), "xai")

    def test_a_non_grok_name_does_not_route_to_xai(self):
        for model in ("claude-haiku-4-5-20251001", "gemini-3.5-flash", "gpt-5.4-nano"):
            self.assertNotEqual(model_gateway.provider_for_model(model), "xai", model)

    def test_the_credential_is_read_from_the_environment_only(self):
        with open(os.path.join(RUNNER, "model_gateway.py"), encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn('os.environ.get("XAI_API_KEY"', source)
        self.assertNotIn("xai-", source.replace("_xai", "").replace('"xai"', ""),
                         "no literal xAI key may appear in the owner module")


class PricingCoverageTest(unittest.TestCase):
    """Every model the catalog advertises must be priced, or spend is silently wrong."""

    def _catalog_models(self):
        return [entry["model"] for entry in model_catalog.MODELS.get("xai", [])]

    def test_the_catalog_advertises_at_least_one_xai_model(self):
        self.assertTrue(self._catalog_models())

    def test_every_advertised_model_has_a_price(self):
        unpriced = [m for m in self._catalog_models()
                    if ("xai", m) not in model_gateway.PRICES]
        self.assertEqual(unpriced, [],
                         f"{unpriced} would bill at the generic fallback rate, so the "
                         f"cost ledger for those runs is quietly fictional")

    def test_prices_are_positive_and_output_is_not_cheaper_than_input(self):
        for (provider, model), (pin, pout) in model_gateway.PRICES.items():
            if provider != "xai":
                continue
            with self.subTest(model=model):
                self.assertGreater(pin, 0)
                self.assertGreaterEqual(pout, pin)


class XaiDefaultDivergenceTest(unittest.TestCase):
    """PINNED HAZARD: XAI_MODEL has two different defaults.

        model_gateway.DEFAULT_MODELS["xai"]  -> os.environ.get("XAI_MODEL", "grok-build-0.1")
        model_catalog.MODELS["xai"][1]       -> os.environ.get("XAI_MODEL", "grok-4.3")

    Same environment variable, two defaults. With XAI_MODEL unset — the normal state —
    the catalog advertises grok-4.3 at capability cap 9 while the gateway actually calls
    grok-build-0.1, which the catalog itself rates cap 8. Routing therefore believes it
    has secured a cap-9 model and gets a cap-8 one, and nothing anywhere reports the
    substitution.

    Asserted as-is rather than "fixed": either default is defensible and changing the
    gateway's would change which model the fleet actually calls, which is a routing and
    cost decision, not a cleanup. This test is where that decision gets made — and it
    fails the moment either side moves, so the two cannot drift further apart unnoticed.
    """

    def setUp(self):
        self._saved = os.environ.get("XAI_MODEL")
        os.environ.pop("XAI_MODEL", None)

    def tearDown(self):
        if self._saved is None:
            os.environ.pop("XAI_MODEL", None)
        else:
            os.environ["XAI_MODEL"] = self._saved

    def test_the_gateway_default_is_grok_build(self):
        self.assertEqual(model_gateway.DEFAULT_MODELS["xai"](), "grok-build-0.1")

    def test_the_catalog_advertises_a_different_default(self):
        advertised = [e["model"] for e in model_catalog.MODELS["xai"]]
        self.assertIn("grok-4.3", advertised)

    def test_both_defaults_are_at_least_priced_so_the_ledger_stays_honest(self):
        for model in ("grok-build-0.1", "grok-4.3"):
            self.assertIn(("xai", model), model_gateway.PRICES, model)

    def test_an_explicit_xai_model_is_honoured_by_the_gateway(self):
        os.environ["XAI_MODEL"] = "grok-4.5"
        self.assertEqual(model_gateway.DEFAULT_MODELS["xai"](), "grok-4.5")


class FailSoftTest(unittest.TestCase):
    def test_provider_for_model_never_raises(self):
        for bad in (None, "", 5, [], {}):
            try:
                model_gateway.provider_for_model(bad if isinstance(bad, str) else "")
            except Exception as exc:  # noqa: BLE001 — the assertion IS "no exception"
                self.fail(f"provider_for_model raised {type(exc).__name__}: {exc}")

    def test_an_unpriced_model_still_yields_a_cost_rather_than_a_keyerror(self):
        self.assertEqual(model_gateway.PRICES.get(("xai", "grok-does-not-exist")), None,
                         "and _xai falls back to (1.25, 2.50) rather than raising")


if __name__ == "__main__":
    unittest.main()
