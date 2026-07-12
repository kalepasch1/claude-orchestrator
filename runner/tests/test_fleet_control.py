"""Tests for fleet_control — real-time config management via central DB."""
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Stub out db and kill_switch before importing fleet_control
_db_mod = types.ModuleType("db")
_db_mod.select = lambda *a, **kw: []
_db_mod.insert = lambda *a, **kw: None
_db_mod.update = lambda *a, **kw: None
sys.modules.setdefault("db", _db_mod)

_ks_mod = types.ModuleType("kill_switch")
_ks_mod.pause = lambda **kw: None
_ks_mod.resume = lambda **kw: None
_ks_mod.is_paused = lambda *a: False
sys.modules.setdefault("kill_switch", _ks_mod)

import fleet_control


class TestSafeKey(unittest.TestCase):
    """Config keys must be filtered: safe prefixes only, no secrets."""

    def test_orch_prefix_allowed(self):
        self.assertTrue(fleet_control._safe_key("ORCH_MAX_PARALLEL"))

    def test_max_parallel_allowed(self):
        self.assertTrue(fleet_control._safe_key("MAX_PARALLEL"))

    def test_secret_denied(self):
        self.assertFalse(fleet_control._safe_key("ORCH_API_SECRET"))

    def test_key_denied(self):
        self.assertFalse(fleet_control._safe_key("ANTHROPIC_API_KEY"))

    def test_token_denied(self):
        self.assertFalse(fleet_control._safe_key("SUPABASE_TOKEN"))

    def test_password_denied(self):
        self.assertFalse(fleet_control._safe_key("DB_PASSWORD"))

    def test_arbitrary_key_denied(self):
        self.assertFalse(fleet_control._safe_key("RANDOM_STUFF"))

    def test_deploy_prefix_allowed(self):
        self.assertTrue(fleet_control._safe_key("DEPLOY_CANARY_PCT"))

    def test_cost_prefix_allowed(self):
        self.assertTrue(fleet_control._safe_key("COST_CEILING_USD"))


class TestLoadConfig(unittest.TestCase):
    """load_config applies safe keys from fleet_config rows into env."""

    def test_load_config_returns_int(self):
        """load_config always returns an int count, even on error."""
        result = fleet_control.load_config()
        self.assertIsInstance(result, int)


if __name__ == "__main__":
    unittest.main()
