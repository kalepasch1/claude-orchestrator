#!/usr/bin/env python3
"""Tests for config_policy_engine.py"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import config_policy_engine as cpe


class TestIsSafeConfigKey(unittest.TestCase):
    def test_safe_orch_prefix(self):
        self.assertTrue(cpe.is_safe_config_key("ORCH_MAX_WORKERS"))

    def test_safe_max_parallel(self):
        self.assertTrue(cpe.is_safe_config_key("MAX_PARALLEL"))

    def test_safe_sb_service_url(self):
        # SB_SERVICE_URL does NOT match safe prefixes → should be rejected
        self.assertFalse(cpe.is_safe_config_key("SB_SERVICE_URL"))

    def test_reject_api_key(self):
        self.assertFalse(cpe.is_safe_config_key("ANTHROPIC_API_KEY"))

    def test_reject_secret(self):
        self.assertFalse(cpe.is_safe_config_key("ORCH_SECRET_THING"))

    def test_reject_token(self):
        self.assertFalse(cpe.is_safe_config_key("SUPABASE_TOKEN"))

    def test_reject_password(self):
        self.assertFalse(cpe.is_safe_config_key("DB_PASSWORD"))

    def test_reject_credential(self):
        self.assertFalse(cpe.is_safe_config_key("MY_CREDENTIAL"))

    def test_empty_string(self):
        self.assertFalse(cpe.is_safe_config_key(""))

    def test_none(self):
        self.assertFalse(cpe.is_safe_config_key(None))

    def test_case_insensitive_deny(self):
        self.assertFalse(cpe.is_safe_config_key("orch_api_key_rotation"))

    def test_safe_cost_prefix(self):
        self.assertTrue(cpe.is_safe_config_key("COST_BUDGET_DAILY"))

    def test_safe_deploy_prefix(self):
        self.assertTrue(cpe.is_safe_config_key("DEPLOY_CANARY_PCT"))

    def test_safe_enable_prefix(self):
        self.assertTrue(cpe.is_safe_config_key("ENABLE_AUTO_MERGE"))

    def test_random_key_rejected(self):
        self.assertFalse(cpe.is_safe_config_key("RANDOM_THING"))


class TestValidateValue(unittest.TestCase):
    def test_normal_value(self):
        ok, _ = cpe.validate_value("hello")
        self.assertTrue(ok)

    def test_none_value(self):
        ok, reason = cpe.validate_value(None)
        self.assertFalse(ok)
        self.assertIn("None", reason)

    def test_too_long(self):
        ok, reason = cpe.validate_value("x" * 5000)
        self.assertFalse(ok)
        self.assertIn("exceeds", reason)

    def test_control_chars(self):
        ok, reason = cpe.validate_value("hello\x00world")
        self.assertFalse(ok)
        self.assertIn("control", reason)

    def test_numeric_value(self):
        ok, _ = cpe.validate_value(42)
        self.assertTrue(ok)


class TestValidateBatch(unittest.TestCase):
    def test_all_valid(self):
        entries = [{"key": "ORCH_X", "value": "1"}, {"key": "COST_Y", "value": "2"}]
        result = cpe.validate_batch(entries)
        self.assertTrue(result["valid"])
        self.assertEqual(len(result["rejected"]), 0)

    def test_mixed(self):
        entries = [
            {"key": "ORCH_OK", "value": "1"},
            {"key": "API_KEY", "value": "secret"},
        ]
        result = cpe.validate_batch(entries)
        self.assertFalse(result["valid"])
        self.assertEqual(len(result["rejected"]), 1)

    def test_empty(self):
        result = cpe.validate_batch([])
        self.assertTrue(result["valid"])

    def test_none(self):
        result = cpe.validate_batch(None)
        self.assertTrue(result["valid"])


class TestValidateAndFilter(unittest.TestCase):
    def test_filters_correctly(self):
        entries = [
            {"key": "ORCH_A", "value": "1"},
            {"key": "SECRET_B", "value": "2"},
            {"key": "COST_C", "value": "3"},
        ]
        valid, rejected = cpe.validate_and_filter(entries)
        self.assertEqual(len(valid), 2)
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0]["key"], "SECRET_B")


if __name__ == "__main__":
    unittest.main()
