#!/usr/bin/env python3
"""Pricing configuration loaded by the economic scheduler.

Acceptance for this slice: the module loads config from env or defaults, the
returned dict carries the expected keys, and mocking the consumer works.

Everything here is pure — no DB, no network. runner/test_economic_scheduler.py
covers the scheduler itself; this file covers the config contract it depends on.
"""
import os
import sys
import unittest
from unittest import mock

RUNNER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner")
sys.path.insert(0, RUNNER)

import pricing_config  # noqa: E402


class LoadPricingConfigTests(unittest.TestCase):
    def setUp(self):
        pricing_config.invalidate()
        self.addCleanup(pricing_config.invalidate)

    def test_load_pricing_config(self):
        """The named acceptance test: mock the consumer, verify the keys."""
        consumer = mock.Mock(name="economic_scheduler_consumer")

        with mock.patch.dict(os.environ, {}, clear=False):
            for var in (pricing_config.ENV_TIERS, pricing_config.ENV_RATE_LIMITS, pricing_config.ENV_TTL):
                os.environ.pop(var, None)
            config = pricing_config.load_pricing_config()
            consumer(config)

        for key in pricing_config.REQUIRED_KEYS:
            self.assertIn(key, config)
        self.assertEqual(config["tiers"], pricing_config.DEFAULT_TIERS)
        self.assertEqual(config["rate_limits"], pricing_config.DEFAULT_RATE_LIMITS)
        self.assertEqual(config["ttl_seconds"], pricing_config.DEFAULT_TTL_SECONDS)

        # The mock stands in for the scheduler: it received the real table.
        consumer.assert_called_once_with(config)
        self.assertEqual(consumer.call_args[0][0]["ttl_seconds"], pricing_config.DEFAULT_TTL_SECONDS)

    def test_env_overrides_are_honoured(self):
        env = {
            pricing_config.ENV_TIERS: '{"free": 0, "team": 499.5}',
            pricing_config.ENV_RATE_LIMITS: '{"free": 50, "team": 25000}',
            pricing_config.ENV_TTL: "900",
        }
        with mock.patch.dict(os.environ, env):
            config = pricing_config.load_pricing_config()

        self.assertEqual(config["tiers"], {"free": 0.0, "team": 499.5})
        self.assertEqual(config["rate_limits"], {"free": 50, "team": 25000})
        self.assertEqual(config["ttl_seconds"], 900)

    def test_a_bad_override_degrades_only_its_own_key(self):
        """Fail-soft, and scoped: one malformed value must not blank the table."""
        env = {
            pricing_config.ENV_TIERS: "{not json",
            pricing_config.ENV_RATE_LIMITS: '{"free": 50}',
            pricing_config.ENV_TTL: "-1",
        }
        with mock.patch.dict(os.environ, env):
            config = pricing_config.load_pricing_config()

        self.assertEqual(config["tiers"], pricing_config.DEFAULT_TIERS)          # fell back
        self.assertEqual(config["rate_limits"], {"free": 50})                    # survived
        self.assertEqual(config["ttl_seconds"], pricing_config.DEFAULT_TTL_SECONDS)  # rejected <= 0

    def test_it_never_raises_and_always_returns_every_key(self):
        for bad in ("[]", '"scalar"', "{}", "   ", "null"):
            with mock.patch.dict(os.environ, {pricing_config.ENV_TIERS: bad}):
                config = pricing_config.load_pricing_config()
            for key in pricing_config.REQUIRED_KEYS:
                self.assertIn(key, config, f"missing {key} for override {bad!r}")
            self.assertEqual(config["tiers"], pricing_config.DEFAULT_TIERS)

    def test_the_caller_cannot_mutate_the_cache(self):
        """Pinned on the refresh=False path on purpose.

        With refresh=True every call rebuilds the table, so a shallow copy looks
        correct and the test passes for the wrong reason. The cached path is
        where a shallow copy actually leaks — and it is the hot-loop path.
        """
        first = pricing_config.load_pricing_config(refresh=False)
        first["tiers"]["injected"] = 1.0
        first["rate_limits"]["injected"] = 99
        second = pricing_config.load_pricing_config(refresh=False)
        self.assertNotIn("injected", second["tiers"])
        self.assertNotIn("injected", second["rate_limits"])


if __name__ == "__main__":
    unittest.main()
