#!/usr/bin/env python3
"""
Acceptance test: `runner/config_consumer.py` is the owner module for
orch-config-consumption.

WHY THIS FILE EXISTS
--------------------
The task "locate the existing owner module for orch-config-consumption" keeps coming
back to the queue, and it keeps coming back because locating a module produces nothing
durable — the next agent has to search again and may land somewhere else. This repo has
several plausible-looking candidates:

    runner/config_consumer.py          <- the owner
    runner/config_applier.py           writes config, does not consume it
    runner/config_drift.py             compares config, does not consume it
    runner/fleet_control.py            the DB gateway config_consumer reads THROUGH
    runner/test_fleet_config_consumption.py

so "which one owns consumption" is a real question with a wrong answer available. This
test is the answer, written as an executable assertion instead of a note: it pins the
module path, the public surface every caller depends on, and the two properties that
make it the owner rather than just another reader — it is fail-soft, and it goes through
the gateway seam rather than talking to the database itself.

If someone moves or renames the owner, this fails and names the new expectation. That is
the whole point: the location becomes a contract instead of a rediscovery.
"""
from __future__ import annotations

import inspect
import os
import sys
import unittest

RUNNER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RUNNER_DIR not in sys.path:
    sys.path.insert(0, RUNNER_DIR)

import config_consumer  # noqa: E402  — path set up above


# The public surface callers import. Recorded here so a silent removal is a test
# failure rather than an AttributeError somewhere downstream at runtime.
EXPECTED_API = (
    "load_all",
    "get",
    "get_int",
    "get_bool",
    "get_float",
    "load_config",
    "invalidate_cache",
)


class OwnerModuleLocationTest(unittest.TestCase):
    """The module exists, at the expected path, in the expected package."""

    def test_owner_module_is_runner_config_consumer(self):
        expected = os.path.join(RUNNER_DIR, "config_consumer.py")
        self.assertTrue(os.path.isfile(expected),
                        f"owner module for orch-config-consumption missing at {expected}")
        self.assertEqual(os.path.abspath(config_consumer.__file__), os.path.abspath(expected))

    def test_owner_module_is_importable_without_initialisation(self):
        """No setup call, no DB, no env — importing must be enough to use it."""
        self.assertEqual(config_consumer.get("", "fallback"), "fallback")


class OwnerModulePublicApiTest(unittest.TestCase):
    """The surface that makes it the owner rather than an incidental helper."""

    def test_exposes_every_expected_function(self):
        for name in EXPECTED_API:
            with self.subTest(function=name):
                self.assertTrue(hasattr(config_consumer, name),
                                f"config_consumer.{name} is missing")
                self.assertTrue(callable(getattr(config_consumer, name)))

    def test_accessors_are_module_level_delegates_to_one_singleton(self):
        """Module-level functions delegate to a single shared consumer instance.

        This is the repo's singleton-delegation convention, and it is what makes cache
        invalidation observable across callers — two instances would mean two caches.
        """
        self.assertTrue(hasattr(config_consumer, "_consumer"))
        for name in ("get", "get_int", "get_bool", "get_float", "load_config"):
            with self.subTest(function=name):
                source = inspect.getsource(getattr(config_consumer, name))
                self.assertIn("_consumer.", source,
                              f"{name} does not delegate to the shared consumer")


class OwnerModuleBehaviourTest(unittest.TestCase):
    """The two properties the owner is required to guarantee."""

    def setUp(self):
        self._saved = dict(os.environ)
        config_consumer.invalidate_cache()

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._saved)
        config_consumer.invalidate_cache()

    def test_reads_orch_prefixed_environment(self):
        os.environ["ORCH_ACCEPTANCE_PROBE"] = "located"
        self.assertEqual(config_consumer.get("ACCEPTANCE_PROBE"), "located")

    def test_type_coercion_falls_back_instead_of_raising(self):
        os.environ["ORCH_ACCEPTANCE_BAD_INT"] = "not-a-number"
        self.assertEqual(config_consumer.get_int("ACCEPTANCE_BAD_INT", 7), 7)
        self.assertEqual(config_consumer.get_float("ACCEPTANCE_BAD_INT", 1.5), 1.5)

    def test_is_fail_soft_on_missing_keys(self):
        """Never raises. A config read that can throw turns every caller into a risk."""
        for call in (lambda: config_consumer.get("ACCEPTANCE_ABSENT", "d"),
                     lambda: config_consumer.get_int("ACCEPTANCE_ABSENT", 1),
                     lambda: config_consumer.get_bool("ACCEPTANCE_ABSENT", True),
                     lambda: config_consumer.get_float("ACCEPTANCE_ABSENT", 2.0),
                     lambda: config_consumer.load_config("ACCEPTANCE_ABSENT", "d")):
            with self.subTest(call=call):
                try:
                    call()
                except Exception as exc:  # noqa: BLE001 — the assertion IS "no exception"
                    self.fail(f"owner module raised {type(exc).__name__}: {exc}")

    def test_db_reads_go_through_the_fleet_control_seam(self):
        """load_config() must not talk to the database directly.

        The gateway is patchable, which is what lets the whole fleet run offline; a
        direct client here would make config consumption untestable and un-degradable.
        """
        self.assertTrue(hasattr(config_consumer, "fleet_control"),
                        "the fleet_control seam is gone; load_config can no longer degrade")
        source = inspect.getsource(config_consumer)
        self.assertNotIn("import psycopg", source)
        self.assertNotIn("create_client(", source)

    def test_load_config_degrades_to_env_when_gateway_is_unavailable(self):
        saved = config_consumer.fleet_control
        try:
            config_consumer.fleet_control = None
            config_consumer.invalidate_cache()
            os.environ["ORCH_ACCEPTANCE_DEGRADE"] = "env-value"
            self.assertEqual(config_consumer.load_config("ACCEPTANCE_DEGRADE"), "env-value")
            self.assertEqual(
                config_consumer.load_config("ACCEPTANCE_ABSENT_ENTIRELY", "fallback"),
                "fallback")
        finally:
            config_consumer.fleet_control = saved
            config_consumer.invalidate_cache()


if __name__ == "__main__":
    unittest.main()
