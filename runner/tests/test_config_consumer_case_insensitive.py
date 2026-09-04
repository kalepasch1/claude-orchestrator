#!/usr/bin/env python3
"""Regression tests recovered from the stale orch-config-consumption patch.

The defect: config_consumer._ConfigConsumer.get() read `f"ORCH_{key}"` verbatim
while fleet_control.get_fleet_config() reads `f"ORCH_{key}".upper()`. A
lower/mixed-case key therefore resolved through one path and silently returned
the default through the other, so a fleet-wide config push could appear to apply
on one code path and be ignored on another.

These assert the two paths AGREE, which is the property that actually matters.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config_consumer  # noqa: E402
import fleet_control  # noqa: E402


class _EnvMixin(unittest.TestCase):
    def setEnv(self, name, value):
        self.addCleanup(self._restore, name, os.environ.get(name))
        os.environ[name] = value

    @staticmethod
    def _restore(name, previous):
        if previous is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = previous


class CaseInsensitiveLookupTests(_EnvMixin):
    def setUp(self):
        self.consumer = config_consumer._ConfigConsumer()

    def test_lowercase_key_resolves_against_uppercase_env(self):
        self.setEnv("ORCH_MAX_PARALLEL", "7")
        self.assertEqual(self.consumer.get("max_parallel"), "7")

    def test_mixed_case_key_resolves(self):
        self.setEnv("ORCH_MAX_PARALLEL", "7")
        self.assertEqual(self.consumer.get("Max_Parallel"), "7")

    def test_uppercase_key_still_resolves(self):
        self.setEnv("ORCH_MAX_PARALLEL", "7")
        self.assertEqual(self.consumer.get("MAX_PARALLEL"), "7")

    def test_agrees_with_fleet_control(self):
        # The whole point of the fix: one key, two code paths, same answer.
        self.setEnv("ORCH_EXTRA_CODERS", "3")
        for key in ("extra_coders", "Extra_Coders", "EXTRA_CODERS"):
            self.assertEqual(self.consumer.get(key),
                             fleet_control.get_fleet_config(key),
                             f"paths disagree for key {key!r}")

    def test_verbatim_non_upper_env_var_still_works(self):
        # Fallback branch: an existing exactly-cased variable must not regress.
        self.setEnv("ORCH_lower_only", "kept")
        self.assertEqual(self.consumer.get("lower_only"), "kept")

    def test_missing_key_returns_default(self):
        os.environ.pop("ORCH_DEFINITELY_ABSENT", None)
        self.assertEqual(self.consumer.get("definitely_absent", "fallback"), "fallback")

    def test_whitespace_only_value_returns_default(self):
        self.setEnv("ORCH_BLANKISH", "   ")
        self.assertEqual(self.consumer.get("blankish", "fallback"), "fallback")

    def test_fail_soft_on_bad_input(self):
        for bad in (None, "", 123, object()):
            self.assertEqual(self.consumer.get(bad, "d"), "d")
            self.assertEqual(self.consumer._env_lookup(bad), "")


class TypedGettersInheritTheFixTests(_EnvMixin):
    """get_int/get_bool/get_float delegate to get(), so they must inherit it."""

    def setUp(self):
        self.consumer = config_consumer._ConfigConsumer()

    def test_get_int_lowercase_key(self):
        self.setEnv("ORCH_POOL_SIZE", "12")
        self.assertEqual(self.consumer.get_int("pool_size", 1), 12)

    def test_get_bool_lowercase_key(self):
        self.setEnv("ORCH_AUTO_PULL", "true")
        self.assertTrue(self.consumer.get_bool("auto_pull", False))

    def test_get_float_lowercase_key(self):
        self.setEnv("ORCH_RAM_FLOOR_GB", "2.5")
        self.assertAlmostEqual(self.consumer.get_float("ram_floor_gb", 0.0), 2.5)

    def test_typed_getters_fall_back_on_garbage(self):
        self.setEnv("ORCH_POOL_SIZE", "not-a-number")
        self.assertEqual(self.consumer.get_int("pool_size", 4), 4)
        self.setEnv("ORCH_RAM_FLOOR_GB", "not-a-float")
        self.assertAlmostEqual(self.consumer.get_float("ram_floor_gb", 1.5), 1.5)


class ModuleLevelDelegationTests(_EnvMixin):
    """Module-level singleton pattern: config_consumer.get -> _consumer.get."""

    def test_module_get_is_case_insensitive(self):
        self.setEnv("ORCH_MAX_PARALLEL", "9")
        self.assertEqual(config_consumer.get("max_parallel"), "9")

    def test_module_typed_getters(self):
        self.setEnv("ORCH_POOL_SIZE", "6")
        self.setEnv("ORCH_AUTO_PULL", "yes")
        self.setEnv("ORCH_RAM_FLOOR_GB", "3.25")
        self.assertEqual(config_consumer.get_int("pool_size", 0), 6)
        self.assertTrue(config_consumer.get_bool("auto_pull", False))
        self.assertAlmostEqual(config_consumer.get_float("ram_floor_gb", 0.0), 3.25)


if __name__ == "__main__":
    unittest.main()
