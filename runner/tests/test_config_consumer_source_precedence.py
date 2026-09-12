#!/usr/bin/env python3
"""Narrow regression check: load_config() source precedence after the transplant.

`runner/config_consumer.load_config` reads from four sources in a fixed order:

    fleet_control gateway  ->  direct db.select (last resort)  ->  ORCH_ env  ->  default

That ordering is the *only* thing the config-consumption transplant changed, and it is
the one thing the existing suites do not pin. `test_config_consumer_knobs.py` covers the
TTL/eviction knobs, `test_orch_config_consumption_owner.py` covers the gateway seam and
the degrade-to-env path, and `test_config_consumption.py` covers coercion — none of them
assert that an earlier source *wins over* a later one that is also populated. Invert any
two steps and every one of those files still passes while the fleet silently reads stale
env values instead of the pushed fleet_config value.

Deliberately narrow: only load_config's source selection. No coercion, no caching
behaviour beyond the invalidation needed to isolate each case.
"""
from __future__ import annotations

import os
import sys
import types
import unittest

RUNNER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RUNNER_DIR not in sys.path:
    sys.path.insert(0, RUNNER_DIR)

import config_consumer  # noqa: E402  — path set up above

KEY = "PRECEDENCE_PROBE"
ENV_KEY = f"ORCH_{KEY}"


def _gateway(value, calls=None):
    """A stand-in fleet_control whose get_fleet_config returns ``value``."""
    module = types.ModuleType("fleet_control_stub")

    def get_fleet_config(key, default=""):
        if calls is not None:
            calls.append(key)
        return value

    module.get_fleet_config = get_fleet_config
    return module


def _db(value, calls=None):
    """A stand-in `db` module whose select() returns one fleet_config row."""
    module = types.ModuleType("db")

    def select(table, params=None):
        if calls is not None:
            calls.append(table)
        return [{"value": value}] if value is not None else []

    module.select = select
    return module


class LoadConfigSourcePrecedenceTest(unittest.TestCase):
    def setUp(self):
        self._saved_gateway = config_consumer.fleet_control
        self._saved_db = sys.modules.get("db")
        self._saved_env = os.environ.get(ENV_KEY)
        config_consumer.invalidate_cache()

    def tearDown(self):
        config_consumer.fleet_control = self._saved_gateway
        if self._saved_db is None:
            sys.modules.pop("db", None)
        else:
            sys.modules["db"] = self._saved_db
        if self._saved_env is None:
            os.environ.pop(ENV_KEY, None)
        else:
            os.environ[ENV_KEY] = self._saved_env
        config_consumer.invalidate_cache()

    def _read(self, default="the-default"):
        config_consumer.invalidate_cache()
        return config_consumer.load_config(KEY, default)

    def test_gateway_value_beats_db_env_and_default(self):
        config_consumer.fleet_control = _gateway("from-gateway")
        sys.modules["db"] = _db("from-db")
        os.environ[ENV_KEY] = "from-env"
        self.assertEqual(self._read(), "from-gateway")

    def test_gateway_is_not_shadowed_by_env(self):
        config_consumer.fleet_control = _gateway("from-gateway")
        sys.modules.pop("db", None)
        os.environ[ENV_KEY] = "from-env"
        self.assertEqual(self._read(), "from-gateway")

    def test_db_last_resort_beats_env_when_gateway_is_empty(self):
        config_consumer.fleet_control = _gateway("")
        sys.modules["db"] = _db("from-db")
        os.environ[ENV_KEY] = "from-env"
        self.assertEqual(self._read(), "from-db")

    def test_env_wins_when_neither_gateway_nor_db_has_a_value(self):
        config_consumer.fleet_control = _gateway("")
        sys.modules["db"] = _db(None)
        os.environ[ENV_KEY] = "from-env"
        self.assertEqual(self._read(), "from-env")

    def test_default_wins_when_every_source_is_empty(self):
        config_consumer.fleet_control = _gateway("")
        sys.modules["db"] = _db(None)
        os.environ.pop(ENV_KEY, None)
        self.assertEqual(self._read(), "the-default")

    def test_db_is_not_consulted_when_the_gateway_answers(self):
        db_calls: list = []
        config_consumer.fleet_control = _gateway("from-gateway")
        sys.modules["db"] = _db("from-db", calls=db_calls)
        self._read()
        self.assertEqual(db_calls, [], "gateway answered; the direct db read must be skipped")

    def test_gateway_is_consulted_before_anything_else(self):
        gateway_calls: list = []
        config_consumer.fleet_control = _gateway("from-gateway", calls=gateway_calls)
        os.environ[ENV_KEY] = "from-env"
        self._read()
        self.assertEqual(gateway_calls, [KEY])

    def test_a_raising_gateway_degrades_instead_of_propagating(self):
        broken = types.ModuleType("fleet_control_broken")

        def boom(key, default=""):
            raise RuntimeError("gateway down")

        broken.get_fleet_config = boom
        config_consumer.fleet_control = broken
        sys.modules["db"] = _db(None)
        os.environ[ENV_KEY] = "from-env"
        self.assertEqual(self._read(), "from-env")

    def test_a_raising_db_degrades_instead_of_propagating(self):
        broken = types.ModuleType("db")

        def boom(table, params=None):
            raise RuntimeError("db down")

        broken.select = boom
        config_consumer.fleet_control = _gateway("")
        sys.modules["db"] = broken
        os.environ[ENV_KEY] = "from-env"
        self.assertEqual(self._read(), "from-env")

    def test_whitespace_only_source_values_do_not_win(self):
        config_consumer.fleet_control = _gateway("   ")
        sys.modules["db"] = _db("  ")
        os.environ[ENV_KEY] = "from-env"
        self.assertEqual(self._read(), "from-env")


if __name__ == "__main__":
    unittest.main()
