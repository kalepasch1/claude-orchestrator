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


class TestSafeKeyEdgeCases(unittest.TestCase):
    """Additional edge-case coverage for the config key safety filter."""

    def test_empty_string_denied(self):
        self.assertFalse(fleet_control._safe_key(""))

    def test_case_insensitive_deny(self):
        """Deny markers work regardless of key casing."""
        self.assertFalse(fleet_control._safe_key("orch_secret_value"))
        self.assertFalse(fleet_control._safe_key("Orch_Token_Refresh"))

    def test_credential_denied(self):
        self.assertFalse(fleet_control._safe_key("ORCH_CREDENTIAL_STORE"))

    def test_pwd_denied(self):
        self.assertFalse(fleet_control._safe_key("ORCH_PWD_HASH"))

    def test_enable_prefix_allowed(self):
        self.assertTrue(fleet_control._safe_key("ENABLE_PROACTIVE_LOOPS"))

    def test_session_prefix_allowed(self):
        self.assertTrue(fleet_control._safe_key("SESSION_TIMEOUT_SEC"))

    def test_merge_prefix_allowed(self):
        self.assertTrue(fleet_control._safe_key("MERGE_AUTO_APPROVE"))

    def test_queue_prefix_allowed(self):
        self.assertTrue(fleet_control._safe_key("QUEUE_MAX_DEPTH"))

    def test_ram_prefix_allowed(self):
        self.assertTrue(fleet_control._safe_key("RAM_FLOOR_GB"))

    def test_integrate_prefix_allowed(self):
        self.assertTrue(fleet_control._safe_key("INTEGRATE_SLACK_WEBHOOK"))

    def test_release_prefix_allowed(self):
        self.assertTrue(fleet_control._safe_key("RELEASE_TRAIN_INTERVAL"))


class TestHostAliases(unittest.TestCase):
    """_host_aliases returns the hostname with and without .local suffix."""

    def test_aliases_include_hostname(self):
        aliases = fleet_control._host_aliases()
        self.assertIn(fleet_control.HOST, aliases)
        self.assertIsInstance(aliases, set)
        self.assertTrue(len(aliases) >= 2)

    def test_local_suffix_toggled(self):
        aliases = fleet_control._host_aliases()
        if fleet_control.HOST.endswith(".local"):
            self.assertIn(fleet_control.HOST[:-6], aliases)
        else:
            self.assertIn(fleet_control.HOST + ".local", aliases)


class TestTargetMatches(unittest.TestCase):
    """_target_matches handles 'all' and host-specific targets."""

    def test_all_always_matches(self):
        self.assertTrue(fleet_control._target_matches("all"))

    def test_own_hostname_matches(self):
        self.assertTrue(fleet_control._target_matches(fleet_control.HOST))

    def test_random_host_no_match(self):
        self.assertFalse(fleet_control._target_matches("nonexistent-host-xyz-99"))


class TestControlDone(unittest.TestCase):
    """_control_done logic for 'all' vs single-host targets."""

    def test_single_target_always_done(self):
        self.assertTrue(fleet_control._control_done("myhost", [], {}))

    def test_all_target_no_expected_not_done(self):
        self.assertFalse(fleet_control._control_done("all", ["h1"], {}))

    def test_all_target_expected_met(self):
        self.assertTrue(fleet_control._control_done(
            "all", ["h1", "h2"], {"expected_hosts": ["h1", "h2"]}))

    def test_all_target_expected_not_met(self):
        self.assertFalse(fleet_control._control_done(
            "all", ["h1"], {"expected_hosts": ["h1", "h2"]}))
