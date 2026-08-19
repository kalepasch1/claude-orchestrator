#!/usr/bin/env python3
"""Test fleet_config consumption via gateway with fail-soft error handling.

Tests verify that:
1. Configuration reads flow through fleet_control gateway, not direct env/db access
2. Environment variables (ORCH_* prefix) take precedence
3. Missing config returns sensible defaults without raising
4. Database errors are swallowed (fail-soft)
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fleet_control
import resource_medic
import write_guard


class TestFleetControlGateway(unittest.TestCase):
    """Verify get_fleet_config is the gateway for all config consumption."""

    def test_get_fleet_config_with_env_set(self):
        """Environment variable (ORCH_*) is returned when set."""
        with mock.patch.dict(os.environ, {"ORCH_TEST_KEY": "env_value"}):
            result = fleet_control.get_fleet_config("TEST_KEY", "default")
            self.assertEqual(result, "env_value")

    def test_get_fleet_config_with_env_missing(self):
        """Default is returned when env variable is missing."""
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ORCH_TEST_KEY", None)
            result = fleet_control.get_fleet_config("TEST_KEY", "default_value")
            self.assertEqual(result, "default_value")

    def test_get_fleet_config_fails_soft_on_bad_key(self):
        """Invalid key types return default without raising."""
        result = fleet_control.get_fleet_config(None, "default")
        self.assertEqual(result, "default")
        result = fleet_control.get_fleet_config(123, "default")
        self.assertEqual(result, "default")

    def test_get_fleet_config_trims_whitespace(self):
        """Values are trimmed; empty strings become default."""
        with mock.patch.dict(os.environ, {"ORCH_SPACE_KEY": "  "}, clear=False):
            result = fleet_control.get_fleet_config("SPACE_KEY", "fallback")
            self.assertEqual(result, "fallback")

    def test_get_fleet_config_empty_string_default(self):
        """Default empty string is used when not specified."""
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ORCH_MISSING", None)
            result = fleet_control.get_fleet_config("MISSING")
            self.assertEqual(result, "")


class TestResourceMedicConfigConsumption(unittest.TestCase):
    """Verify resource_medic uses fleet_control gateway."""

    def test_get_medic_config_delegates_to_gateway(self):
        """_get_medic_config wraps fleet_control.get_fleet_config."""
        with mock.patch.dict(os.environ, {"ORCH_MEDIC_TEST": "42"}, clear=False):
            result = resource_medic._get_medic_config("MEDIC_TEST", "10")
            self.assertEqual(result, "42")

    def test_get_medic_config_returns_default_on_missing(self):
        """_get_medic_config returns default when env is missing."""
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ORCH_MEDIC_TEST2", None)
            result = resource_medic._get_medic_config("MEDIC_TEST2", "99")
            self.assertEqual(result, "99")

    def test_set_fleet_config_via_gateway(self):
        """_set_fleet_config uses fleet_control.update_fleet_config."""
        with mock.patch("fleet_control.update_fleet_config") as mock_update:
            resource_medic._set_fleet_config("MAX_PARALLEL", 8)
            mock_update.assert_called_once_with("MAX_PARALLEL", 8)

    def test_set_fleet_config_fails_soft_on_error(self):
        """_set_fleet_config returns False on gateway error without raising."""
        with mock.patch("fleet_control.update_fleet_config", side_effect=ValueError("unsafe key")):
            result = resource_medic._set_fleet_config("UNSAFE_KEY", "value")
            self.assertFalse(result)

    def test_set_fleet_config_returns_true_on_success(self):
        """_set_fleet_config returns True when gateway succeeds."""
        with mock.patch("fleet_control.update_fleet_config"):
            result = resource_medic._set_fleet_config("ORCH_SAFE_KEY", "value")
            self.assertTrue(result)


class TestWriteGuardConfigConsumption(unittest.TestCase):
    """Verify write_guard uses fleet_control gateway."""

    def test_enabled_reads_from_gateway(self):
        """enabled() consults ORCH_WRITE_GUARD via fleet_control."""
        with mock.patch.dict(os.environ, {"ORCH_WRITE_GUARD": "off"}, clear=False):
            result = write_guard.enabled()
            self.assertFalse(result)

    def test_enabled_defaults_to_true(self):
        """enabled() returns True when ORCH_WRITE_GUARD is missing."""
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ORCH_WRITE_GUARD", None)
            result = write_guard.enabled()
            self.assertTrue(result)

    def test_enabled_fails_soft_on_error(self):
        """enabled() returns True (fail-closed) if gateway raises."""
        with mock.patch("fleet_control.get_fleet_config", side_effect=Exception("db error")):
            result = write_guard.enabled()
            self.assertTrue(result)

    def test_test_dirs_reads_from_gateway(self):
        """test_dirs() consults ORCH_WRITE_GUARD_TEST_DIRS via fleet_control."""
        with mock.patch.dict(os.environ, {"ORCH_WRITE_GUARD_TEST_DIRS": "a,b,c"}, clear=False):
            result = write_guard.test_dirs()
            self.assertEqual(result, ("a", "b", "c"))

    def test_test_dirs_returns_defaults_on_missing(self):
        """test_dirs() returns DEFAULT_TEST_DIRS when config is missing."""
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ORCH_WRITE_GUARD_TEST_DIRS", None)
            result = write_guard.test_dirs()
            self.assertEqual(result, write_guard.DEFAULT_TEST_DIRS)

    def test_test_dirs_fails_soft_on_error(self):
        """test_dirs() returns DEFAULT_TEST_DIRS if gateway raises."""
        with mock.patch("fleet_control.get_fleet_config", side_effect=Exception("db error")):
            result = write_guard.test_dirs()
            self.assertEqual(result, write_guard.DEFAULT_TEST_DIRS)

    def test_test_dirs_strips_whitespace(self):
        """test_dirs() trims and normalizes directory names."""
        with mock.patch.dict(os.environ, {"ORCH_WRITE_GUARD_TEST_DIRS": " a/ , b , /c/"}, clear=False):
            result = write_guard.test_dirs()
            self.assertEqual(result, ("a", "b", "c"))


class TestConfigPrefixConvention(unittest.TestCase):
    """Verify all fleet config reads use ORCH_* prefix."""

    def test_resource_medic_uses_orch_prefix(self):
        """resource_medic config keys become ORCH_MEDIC_* in fleet_config."""
        with mock.patch("fleet_control.get_fleet_config") as mock_get:
            mock_get.return_value = "5"
            resource_medic._get_medic_config("TEST", "default")
            # gateway is called with unprefixed key, it adds ORCH_ internally
            mock_get.assert_called_with("TEST", "default")

    def test_write_guard_uses_orch_prefix(self):
        """write_guard config keys become ORCH_WRITE_GUARD* in fleet_config."""
        with mock.patch("fleet_control.get_fleet_config") as mock_get:
            mock_get.return_value = "on"
            write_guard.enabled()
            mock_get.assert_called_with("WRITE_GUARD", "on")


if __name__ == "__main__":
    unittest.main()
