#!/usr/bin/env python3
"""load_config() must consume fleet config THROUGH the fleet_control gateway.

CLAUDE.md is explicit: fleet-wide configuration is applied via the in-process
gateway (fleet_control.py), not ad-hoc reads of the fleet_config table.
config_consumer.load_config() used to call db.select("fleet_config", ...) directly,
which bypassed the gateway's guards and left callers with no seam to patch.

The code now prefers the gateway and keeps the direct read only as a last resort.
Nothing asserted on that ordering, so the bypass could silently return without any
test failing. These are the narrowest assertions that pin it down:

  1. when the gateway answers, db is never touched;
  2. when the gateway is absent or empty, the direct read still rescues the value;
  3. a raising gateway degrades to env instead of propagating (fail-soft).
"""
import os
import sys
import types
import unittest
from unittest.mock import patch

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RUNNER)

import config_consumer as cc  # noqa: E402


def _fake_gateway(value=None, boom=False):
    mod = types.SimpleNamespace()
    mod.calls = []

    def get_fleet_config(key, default=""):
        mod.calls.append(key)
        if boom:
            raise RuntimeError("gateway down")
        return value if value is not None else default

    mod.get_fleet_config = get_fleet_config
    return mod


class _SpyDb:
    """Stand-in for the db module; records whether the direct read happened."""

    def __init__(self, rows=None):
        self.rows = rows or []
        self.selects = []

    def select(self, table, params):
        self.selects.append((table, params))
        return self.rows


class LoadConfigPrefersGatewayTest(unittest.TestCase):

    def setUp(self):
        cc.invalidate_cache()
        self.addCleanup(cc.invalidate_cache)

    def _run(self, gateway, db_rows=None, env=None):
        spy = _SpyDb(db_rows)
        environ = {k: v for k, v in os.environ.items()
                   if not k.startswith("ORCH_")}
        environ.update(env or {})
        with patch.dict(os.environ, environ, clear=True), \
                patch.object(cc, "fleet_control", gateway), \
                patch.dict(sys.modules, {"db": spy}):
            return cc.load_config("SOME_KEY", "fallback"), spy

    def test_gateway_value_wins_and_db_is_never_touched(self):
        """THE REGRESSION: a direct fleet_config read that bypasses the gateway."""
        gw = _fake_gateway("from-gateway")
        value, spy = self._run(gw, db_rows=[{"value": "from-db"}])
        self.assertEqual(value, "from-gateway")
        self.assertEqual(gw.calls, ["SOME_KEY"])
        self.assertEqual(spy.selects, [], "db.select must not run once the gateway answered")

    def test_gateway_value_is_stripped(self):
        value, _ = self._run(_fake_gateway("  spaced  "))
        self.assertEqual(value, "spaced")

    def test_direct_read_is_the_last_resort_when_gateway_is_absent(self):
        value, spy = self._run(None, db_rows=[{"value": "from-db"}])
        self.assertEqual(value, "from-db")
        self.assertEqual(len(spy.selects), 1)
        self.assertEqual(spy.selects[0][0], "fleet_config")

    def test_direct_read_runs_when_gateway_returns_empty(self):
        gw = _fake_gateway("")
        value, spy = self._run(gw, db_rows=[{"value": "from-db"}])
        self.assertEqual(value, "from-db")
        self.assertEqual(gw.calls, ["SOME_KEY"])

    def test_raising_gateway_is_fail_soft_and_falls_through_to_env(self):
        gw = _fake_gateway(boom=True)
        value, _ = self._run(gw, db_rows=[], env={"ORCH_SOME_KEY": "from-env"})
        self.assertEqual(value, "from-env")

    def test_default_survives_when_every_source_is_empty(self):
        value, _ = self._run(_fake_gateway(""), db_rows=[])
        self.assertEqual(value, "fallback")


if __name__ == "__main__":
    unittest.main()
