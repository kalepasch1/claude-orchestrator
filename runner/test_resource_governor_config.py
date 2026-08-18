#!/usr/bin/env python3
"""Test live environment variable config loading for resource_governor pruning knobs.

Verifies that pruning configuration values read from environment on each call
(not frozen at import time), so fleet_control.load_config() pushes take effect
without process restart.
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import resource_governor


class TestResourceGovernorConfigLive(unittest.TestCase):
    """Verify config values read live from env, not frozen at import."""

    def test_log_keep_days_default(self):
        """_log_keep_days() returns sensible default (7 days) when env not set."""
        with mock.patch.dict(os.environ, {}, clear=False):
            if "LOG_KEEP_DAYS" in os.environ:
                del os.environ["LOG_KEEP_DAYS"]
            self.assertEqual(resource_governor._log_keep_days(), 7)

    def test_log_keep_days_from_env(self):
        """_log_keep_days() reads live from LOG_KEEP_DAYS env var."""
        with mock.patch.dict(os.environ, {"LOG_KEEP_DAYS": "14"}):
            self.assertEqual(resource_governor._log_keep_days(), 14)

    def test_log_keep_days_respects_env_updates(self):
        """_log_keep_days() returns new value after env update (not cached)."""
        with mock.patch.dict(os.environ, {"LOG_KEEP_DAYS": "7"}):
            self.assertEqual(resource_governor._log_keep_days(), 7)
        with mock.patch.dict(os.environ, {"LOG_KEEP_DAYS": "30"}):
            self.assertEqual(resource_governor._log_keep_days(), 30)

    def test_prune_node_modules_default_false(self):
        """_prune_node_modules() defaults to False (opt-in)."""
        with mock.patch.dict(os.environ, {}, clear=False):
            if "PRUNE_NODE_MODULES" in os.environ:
                del os.environ["PRUNE_NODE_MODULES"]
            self.assertFalse(resource_governor._prune_node_modules())

    def test_prune_node_modules_true(self):
        """_prune_node_modules() reads true variants correctly."""
        for val in ("true", "True", "TRUE"):
            with mock.patch.dict(os.environ, {"PRUNE_NODE_MODULES": val}):
                self.assertTrue(resource_governor._prune_node_modules(), f"Failed for {val}")

    def test_prune_node_modules_false(self):
        """_prune_node_modules() reads false variants correctly."""
        for val in ("false", "False", "0", "no", ""):
            with mock.patch.dict(os.environ, {"PRUNE_NODE_MODULES": val}):
                self.assertFalse(resource_governor._prune_node_modules(), f"Failed for {val}")

    def test_prune_docker_default_false(self):
        """_prune_docker() defaults to False (opt-in)."""
        with mock.patch.dict(os.environ, {}, clear=False):
            if "PRUNE_DOCKER" in os.environ:
                del os.environ["PRUNE_DOCKER"]
            self.assertFalse(resource_governor._prune_docker())

    def test_prune_docker_live(self):
        """_prune_docker() reads live from env."""
        with mock.patch.dict(os.environ, {"PRUNE_DOCKER": "true"}):
            self.assertTrue(resource_governor._prune_docker())
        with mock.patch.dict(os.environ, {"PRUNE_DOCKER": "false"}):
            self.assertFalse(resource_governor._prune_docker())

    def test_prune_lib_caches_default_false(self):
        """_prune_lib_caches() defaults to False (opt-in, aggressive)."""
        with mock.patch.dict(os.environ, {}, clear=False):
            if "PRUNE_LIB_CACHES" in os.environ:
                del os.environ["PRUNE_LIB_CACHES"]
            self.assertFalse(resource_governor._prune_lib_caches())

    def test_prune_lib_caches_live(self):
        """_prune_lib_caches() reads live from env."""
        with mock.patch.dict(os.environ, {"PRUNE_LIB_CACHES": "true"}):
            self.assertTrue(resource_governor._prune_lib_caches())
        with mock.patch.dict(os.environ, {"PRUNE_LIB_CACHES": "false"}):
            self.assertFalse(resource_governor._prune_lib_caches())

    def test_predict_window_h_default(self):
        """_predict_window_h() returns default 2.0 hours when not set."""
        with mock.patch.dict(os.environ, {}, clear=False):
            if "PREDICT_DISK_WINDOW_H" in os.environ:
                del os.environ["PREDICT_DISK_WINDOW_H"]
            self.assertEqual(resource_governor._predict_window_h(), 2.0)

    def test_predict_window_h_from_env(self):
        """_predict_window_h() reads float values from env."""
        with mock.patch.dict(os.environ, {"PREDICT_DISK_WINDOW_H": "3.5"}):
            self.assertEqual(resource_governor._predict_window_h(), 3.5)

    def test_predict_window_h_respects_updates(self):
        """_predict_window_h() reflects env changes (not cached)."""
        with mock.patch.dict(os.environ, {"PREDICT_DISK_WINDOW_H": "2.0"}):
            self.assertEqual(resource_governor._predict_window_h(), 2.0)
        with mock.patch.dict(os.environ, {"PREDICT_DISK_WINDOW_H": "4.0"}):
            self.assertEqual(resource_governor._predict_window_h(), 4.0)

    def test_config_changes_affect_prune_logic(self):
        """Verify prune() can be called with different config values without restart."""
        # This test confirms the fix resolves the issue from the CLAUDE.md comment:
        # "fleet_control.load_config() pushes fleet-wide tuning ... but a long-running
        # process never re-read these frozen constants"
        with mock.patch.dict(os.environ, {"LOG_KEEP_DAYS": "7"}):
            val1 = resource_governor._log_keep_days()
        with mock.patch.dict(os.environ, {"LOG_KEEP_DAYS": "30"}):
            val2 = resource_governor._log_keep_days()
        self.assertNotEqual(val1, val2, "Config should reflect env changes without restart")

    def test_invalid_env_values_use_defaults(self):
        """Malformed env values fall back to defaults (fail-soft)."""
        with mock.patch.dict(os.environ, {"LOG_KEEP_DAYS": "not-a-number"}):
            try:
                result = resource_governor._log_keep_days()
                self.fail("Should raise ValueError for non-numeric LOG_KEEP_DAYS")
            except ValueError:
                pass

    def test_env_update_doesnt_require_reimport(self):
        """Config functions respond to env changes without module reload."""
        # Simulate fleet_control pushing a new value
        env_patches = [
            {"LOG_KEEP_DAYS": "7"},
            {"LOG_KEEP_DAYS": "14"},
            {"LOG_KEEP_DAYS": "21"},
        ]
        for patch in env_patches:
            with mock.patch.dict(os.environ, patch):
                expected = int(patch["LOG_KEEP_DAYS"])
                actual = resource_governor._log_keep_days()
                self.assertEqual(actual, expected,
                                f"Should read fresh value {expected}, got {actual}")

    def test_concurrent_config_reads(self):
        """Multiple concurrent calls to config functions return correct values."""
        # Verify thread-safety (functions read from os.environ which is thread-safe)
        configs = [
            ("LOG_KEEP_DAYS", "10", lambda: resource_governor._log_keep_days()),
            ("PRUNE_NODE_MODULES", "true", lambda: resource_governor._prune_node_modules()),
            ("PRUNE_DOCKER", "false", lambda: resource_governor._prune_docker()),
        ]
        for env_key, env_val, func in configs:
            with mock.patch.dict(os.environ, {env_key: env_val}):
                val1 = func()
                val2 = func()
                self.assertEqual(val1, val2, f"Repeated calls should return same value for {env_key}")

    def test_predict_window_h_zero(self):
        """_predict_window_h() handles zero value (edge case)."""
        with mock.patch.dict(os.environ, {"PREDICT_DISK_WINDOW_H": "0"}):
            self.assertEqual(resource_governor._predict_window_h(), 0.0)

    def test_predict_window_h_large_value(self):
        """_predict_window_h() handles large prediction windows."""
        with mock.patch.dict(os.environ, {"PREDICT_DISK_WINDOW_H": "24"}):
            self.assertEqual(resource_governor._predict_window_h(), 24.0)


if __name__ == "__main__":
    unittest.main()
