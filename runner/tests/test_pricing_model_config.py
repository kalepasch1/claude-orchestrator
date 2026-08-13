#!/usr/bin/env python3
"""Pricing MODEL configuration for the economic scheduler's revenue prediction.

The price table says what a plan costs. The model says how a customer is charged
at all — flat, tiered, or metered usage — which is a different question and one
revenue prediction cannot answer without.
"""
import json
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pricing_config as pc  # noqa: E402


def _clean_env(**overrides):
    env = {k: v for k, v in os.environ.items() if not k.startswith("ORCH_PRICING_MODEL")}
    env.update(overrides)
    return env


class DefaultsTest(unittest.TestCase):

    def setUp(self):
        pc.invalidate()

    def tearDown(self):
        pc.invalidate()

    def test_returns_every_required_key(self):
        with patch.dict(os.environ, _clean_env(), clear=True):
            cfg = pc.load_pricing_model_config()
        for key in pc.MODEL_REQUIRED_KEYS:
            self.assertIn(key, cfg)

    def test_default_shapes_match_the_spec(self):
        with patch.dict(os.environ, _clean_env(), clear=True):
            cfg = pc.load_pricing_model_config()
        self.assertEqual(cfg["flat"], {"rate": 0.0})
        self.assertEqual(cfg["tiered"], {"tiers": []})
        self.assertEqual(cfg["usage_based"], {"rates": {}})

    def test_default_model_is_flat(self):
        with patch.dict(os.environ, _clean_env(), clear=True):
            self.assertEqual(pc.load_pricing_model_config()["model"], pc.MODEL_FLAT)

    def test_unconfigured_fleet_predicts_no_revenue(self):
        """A zero default is a deliberate refusal to invent a number."""
        with patch.dict(os.environ, _clean_env(), clear=True):
            name, sub = pc.active_pricing_model()
        self.assertEqual(name, pc.MODEL_FLAT)
        self.assertEqual(sub["rate"], 0.0)


class OverrideTest(unittest.TestCase):

    def setUp(self):
        pc.invalidate()

    def tearDown(self):
        pc.invalidate()

    def test_model_name_override(self):
        with patch.dict(os.environ, _clean_env(ORCH_PRICING_MODEL="usage_based"), clear=True):
            self.assertEqual(pc.load_pricing_model_config()["model"], "usage_based")

    def test_model_name_is_case_insensitive(self):
        with patch.dict(os.environ, _clean_env(ORCH_PRICING_MODEL="  TIERED "), clear=True):
            self.assertEqual(pc.load_pricing_model_config()["model"], "tiered")

    def test_unknown_model_falls_back_to_the_default(self):
        with patch.dict(os.environ, _clean_env(ORCH_PRICING_MODEL="barter"), clear=True):
            self.assertEqual(pc.load_pricing_model_config()["model"], pc.DEFAULT_PRICING_MODEL)

    def test_flat_rate_override(self):
        with patch.dict(os.environ,
                        _clean_env(ORCH_PRICING_MODEL_FLAT=json.dumps({"rate": 49.0})),
                        clear=True):
            self.assertEqual(pc.load_pricing_model_config()["flat"]["rate"], 49.0)

    def test_tiered_override(self):
        tiers = {"tiers": [{"up_to": 100, "rate": 0.0}, {"up_to": None, "rate": 199.0}]}
        with patch.dict(os.environ,
                        _clean_env(ORCH_PRICING_MODEL_TIERED=json.dumps(tiers)), clear=True):
            self.assertEqual(pc.load_pricing_model_config()["tiered"], tiers)

    def test_usage_based_override(self):
        rates = {"rates": {"api_call": 0.001, "gb_stored": 0.02}}
        with patch.dict(os.environ,
                        _clean_env(ORCH_PRICING_MODEL_USAGE_BASED=json.dumps(rates)), clear=True):
            self.assertEqual(pc.load_pricing_model_config()["usage_based"], rates)

    def test_active_model_returns_the_selected_sub_config(self):
        rates = {"rates": {"api_call": 0.001}}
        with patch.dict(os.environ,
                        _clean_env(ORCH_PRICING_MODEL="usage_based",
                                   ORCH_PRICING_MODEL_USAGE_BASED=json.dumps(rates)),
                        clear=True):
            name, sub = pc.active_pricing_model()
        self.assertEqual(name, "usage_based")
        self.assertEqual(sub, rates)


class FailSoftTest(unittest.TestCase):

    def setUp(self):
        pc.invalidate()

    def tearDown(self):
        pc.invalidate()

    def test_malformed_json_falls_back_for_that_key_only(self):
        """One bad override must not blank the other two models."""
        with patch.dict(os.environ,
                        _clean_env(ORCH_PRICING_MODEL_FLAT="{not json",
                                   ORCH_PRICING_MODEL_USAGE_BASED=json.dumps({"rates": {"x": 1}})),
                        clear=True):
            cfg = pc.load_pricing_model_config()
        self.assertEqual(cfg["flat"], {"rate": 0.0})
        self.assertEqual(cfg["usage_based"], {"rates": {"x": 1}})

    def test_json_array_where_an_object_was_required_falls_back(self):
        with patch.dict(os.environ, _clean_env(ORCH_PRICING_MODEL_TIERED="[1,2,3]"), clear=True):
            self.assertEqual(pc.load_pricing_model_config()["tiered"], {"tiers": []})

    def test_blank_override_is_treated_as_absent(self):
        with patch.dict(os.environ, _clean_env(ORCH_PRICING_MODEL_FLAT="   "), clear=True):
            self.assertEqual(pc.load_pricing_model_config()["flat"], {"rate": 0.0})

    def test_never_raises_even_when_the_store_is_broken(self):
        with patch.object(pc._store, "load_model", side_effect=RuntimeError("boom")):
            cfg = pc.load_pricing_model_config()
        for key in pc.MODEL_REQUIRED_KEYS:
            self.assertIn(key, cfg)
        self.assertEqual(cfg["model"], pc.DEFAULT_PRICING_MODEL)

    def test_active_pricing_model_survives_a_corrupt_config(self):
        name, sub = pc.active_pricing_model({"model": "barter"})
        self.assertEqual(name, pc.DEFAULT_PRICING_MODEL)
        self.assertEqual(sub, {})


class IsolationTest(unittest.TestCase):
    """The cached copy must not be reachable through a returned object."""

    def setUp(self):
        pc.invalidate()

    def tearDown(self):
        pc.invalidate()

    def test_mutating_a_returned_config_does_not_poison_the_cache(self):
        with patch.dict(os.environ, _clean_env(), clear=True):
            first = pc.load_pricing_model_config(refresh=True)
            first["flat"]["rate"] = 999.0
            first["tiered"]["tiers"].append("junk")
            second = pc.load_pricing_model_config(refresh=False)
        self.assertEqual(second["flat"]["rate"], 0.0)
        self.assertEqual(second["tiered"]["tiers"], [])

    def test_refresh_picks_up_a_fleet_pushed_change_without_restart(self):
        with patch.dict(os.environ, _clean_env(), clear=True):
            self.assertEqual(pc.load_pricing_model_config()["flat"]["rate"], 0.0)
        with patch.dict(os.environ,
                        _clean_env(ORCH_PRICING_MODEL_FLAT=json.dumps({"rate": 12.0})),
                        clear=True):
            self.assertEqual(pc.load_pricing_model_config(refresh=True)["flat"]["rate"], 12.0)

    def test_invalidate_clears_the_model_cache_too(self):
        with patch.dict(os.environ, _clean_env(), clear=True):
            pc.load_pricing_model_config()
        pc.invalidate()
        self.assertIsNone(pc._store._cached_model)


class PriceTableStillWorksTest(unittest.TestCase):
    """The pre-existing table contract must be untouched by this addition."""

    def test_table_keys_unchanged(self):
        cfg = pc.load_pricing_config()
        for key in pc.REQUIRED_KEYS:
            self.assertIn(key, cfg)

    def test_table_and_model_are_independent(self):
        with patch.dict(os.environ, _clean_env(ORCH_PRICING_MODEL="usage_based"), clear=True):
            self.assertEqual(pc.load_pricing_config()["tiers"], pc.DEFAULT_TIERS)


if __name__ == "__main__":
    unittest.main()
