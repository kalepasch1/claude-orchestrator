"""Tests for fleet_control — real-time config management via central DB."""
import os
import sys
import time
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

    def test_safe_key_accepts_all_safe_prefixes(self):
        safe_examples = [
            "ORCH_CANARY_ONLY_OLLAMA_MODELS", "ORCH_DEPRIORITIZE_CHURN",
            "MAX_PARALLEL_CEILING", "PER_TASK_GB", "RAM_FLOOR_GB", "RAM_LIMIT",
            "RELEASE_GATE", "QUEUE_DEPTH", "CONT_TIMEOUT", "JANITOR_INTERVAL",
            "REMEDIATION_CAP", "DEFAULT_TEST_CMD", "TASK_TIMEOUT_SECONDS",
            "ENABLE_SPECULATIVE", "SESSION_TTL", "ACCOUNT_COOLDOWN_SECONDS",
            "MERGE_STRATEGY", "DEPLOY_WINDOW", "INTEGRATE_KPI", "COST_CEILING",
        ]
        for k in safe_examples:
            self.assertTrue(fleet_control._safe_key(k), f"expected safe: {k}")

    def test_safe_key_rejects_all_deny_markers(self):
        deny_cases = [
            "ORCH_API_KEY", "ORCH_SECRET", "ORCH_TOKEN_REFRESH",
            "ORCH_PASSWORD_HASH", "ORCH_PWD_RESET", "ORCH_CREDENTIAL_STORE",
            "MAX_PARALLEL_KEY_ROTATION", "app_credential_name",
            "DB_PASSWORD", "REDIS_TOKEN", "AWS_SECRET_ACCESS_KEY",
        ]
        for k in deny_cases:
            self.assertFalse(fleet_control._safe_key(k), f"expected rejected: {k}")

    def test_safe_key_rejects_unknown_prefixes(self):
        unknown = ["HOME", "PATH", "USER", "SHELL", "MY_CUSTOM_VAR", "DB_HOST"]
        for k in unknown:
            self.assertFalse(fleet_control._safe_key(k), f"expected rejected: {k}")

    def test_safe_key_case_insensitive_deny(self):
        self.assertFalse(fleet_control._safe_key("ORCH_api_key"))
        self.assertFalse(fleet_control._safe_key("orch_Secret_token"))

    def test_safe_key_case_insensitive_prefix(self):
        self.assertTrue(fleet_control._safe_key("orch_auto_pull"))
        self.assertTrue(fleet_control._safe_key("max_parallel"))

    def test_all_target_done_when_expected_hosts_ack(self):
        fake_db = MagicMock()
        fake_db.select.side_effect = [
            [{
                "id": "ctrl-1",
                "target": "all",
                "action": "reload_config",
                "handled_by": ["mac1"],
                "params": {"expected_hosts": ["mac1", "mac2"]},
            }],
            [],
        ]

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


    def _make_db(self, old_value=None):
        fake_db = MagicMock()
        fake_db.select.return_value = [{"value": old_value}] if old_value is not None else []
        fake_db.insert.return_value = None
        return fake_db

    def test_update_fleet_config_emits_event_on_orch_key_change(self):
        fake_db = self._make_db(old_value="false")
        fake_ws = MagicMock()
        before_ms = int(time.time() * 1000)

        with patch.object(fleet_control, "db", fake_db), \
             patch.object(fleet_control, "_ws_server", fake_ws):
            fleet_control.update_fleet_config("ORCH_AUTO_PULL", "true")

        after_ms = int(time.time() * 1000)

        fake_ws.publish_event.assert_called_once()
        channel, payload = fake_ws.publish_event.call_args.args
        self.assertEqual(channel, "config/*")
        self.assertEqual(payload["event_type"], "config_changed")
        self.assertEqual(payload["key"], "ORCH_AUTO_PULL")
        self.assertEqual(payload["old_value"], "false")
        self.assertEqual(payload["new_value"], "true")
        self.assertEqual(payload["publisher"], "fleet_control")
        self.assertGreaterEqual(payload["timestamp"], before_ms)
        self.assertLessEqual(payload["timestamp"], after_ms + 100)

    def test_update_fleet_config_emits_event_when_key_is_new(self):
        fake_db = self._make_db(old_value=None)
        fake_ws = MagicMock()

        with patch.object(fleet_control, "db", fake_db), \
             patch.object(fleet_control, "_ws_server", fake_ws):
            fleet_control.update_fleet_config("ORCH_EXTRA_CODERS", "3")

        fake_ws.publish_event.assert_called_once()
        _, payload = fake_ws.publish_event.call_args.args
        self.assertIsNone(payload["old_value"])
        self.assertEqual(payload["new_value"], "3")

    def test_update_fleet_config_no_event_for_non_orch_key(self):
        fake_db = self._make_db(old_value="4")
        fake_ws = MagicMock()

        with patch.object(fleet_control, "db", fake_db), \
             patch.object(fleet_control, "_ws_server", fake_ws):
            fleet_control.update_fleet_config("MAX_PARALLEL", "8")

        fake_ws.publish_event.assert_not_called()

    def test_update_fleet_config_no_event_when_value_unchanged(self):
        fake_db = self._make_db(old_value="true")
        fake_ws = MagicMock()

        with patch.object(fleet_control, "db", fake_db), \
             patch.object(fleet_control, "_ws_server", fake_ws):
            fleet_control.update_fleet_config("ORCH_AUTO_PULL", "true")

        fake_ws.publish_event.assert_not_called()

    def test_update_fleet_config_no_event_without_ws_server(self):
        fake_db = self._make_db(old_value="false")

        with patch.object(fleet_control, "db", fake_db), \
             patch.object(fleet_control, "_ws_server", None):
            row = fleet_control.update_fleet_config("ORCH_AUTO_PULL", "true")

        self.assertEqual(row["key"], "ORCH_AUTO_PULL")
        self.assertEqual(row["value"], "true")

    def test_update_fleet_config_rejects_unsafe_key(self):
        with self.assertRaises(ValueError):
            fleet_control.update_fleet_config("OPENAI_API_KEY", "sk-abc")


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
