#!/usr/bin/env python3
"""Fleet config consumption: key spelling, and cache invalidation on push.

Two defects in the read path from fleet_config to a running runner:

1. `config_consumer.load_config("FOO")` read the fleet_config table with
   `key=eq.FOO`, but CLAUDE.md requires fleet-wide rows to be STORED prefixed
   ("ORCH_FOO") — that prefix is what makes them fleet-pushable. Every correctly
   written row therefore missed on the last-resort direct read and fell silently
   through to env, which is indistinguishable from "the key is not set".

2. `fleet_control.update_fleet_config()` wrote the new value and published a
   ConfigChanged event, but never invalidated the local read-through cache, so the
   process that made the push kept serving the OLD value for up to
   ORCH_CONFIG_CACHE_TTL_SEC.

Proof: python3 -m pytest runner/tests/test_config_consumption_key_prefix.py -q
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config_consumer  # noqa: E402


class TestKeyCandidates(unittest.TestCase):
    def test_bare_key_tries_prefixed_first(self):
        self.assertEqual(config_consumer._key_candidates("FOO"), ("ORCH_FOO", "FOO"))

    def test_prefixed_key_is_never_double_prefixed(self):
        candidates = config_consumer._key_candidates("ORCH_FOO")
        self.assertEqual(candidates[0], "ORCH_FOO")
        self.assertNotIn("ORCH_ORCH_FOO", candidates)

    def test_prefixed_key_also_tries_the_bare_spelling(self):
        self.assertIn("FOO", config_consumer._key_candidates("ORCH_FOO"))

    def test_whitespace_is_trimmed(self):
        self.assertEqual(config_consumer._key_candidates("  FOO "), ("ORCH_FOO", "FOO"))

    def test_bare_prefix_alone_does_not_produce_an_empty_key(self):
        self.assertEqual(config_consumer._key_candidates("ORCH_"), ("ORCH_",))

    def test_junk_keys_yield_nothing_rather_than_raising(self):
        for bad in (None, "", "   ", 7, [], {}):
            self.assertEqual(config_consumer._key_candidates(bad), (), bad)


class TestPrefixedRowIsFound(unittest.TestCase):
    """The regression: a row stored the documented way must be readable."""

    def setUp(self):
        config_consumer.invalidate_cache()
        for key in ("ORCH_PREFIX_PROBE", "ORCH_ORCH_PREFIX_PROBE"):
            os.environ.pop(key, None)
        self.addCleanup(config_consumer.invalidate_cache)

    def _fake_db(self, stored_key, stored_value):
        class _DB:
            @staticmethod
            def select(table, params=None):
                if table != "fleet_config":
                    return []
                wanted = (params or {}).get("key", "").replace("eq.", "")
                return [{"value": stored_value}] if wanted == stored_key else []
        return _DB

    def _load(self, stored_key, stored_value, asked):
        fake = self._fake_db(stored_key, stored_value)
        with patch.object(config_consumer, "fleet_control", None), \
             patch.dict(sys.modules, {"db": fake}):
            return config_consumer.load_config(asked, default="unset")

    def test_prefixed_row_is_found_when_caller_asks_bare(self):
        self.assertEqual(
            self._load("ORCH_PREFIX_PROBE", "from-fleet", "PREFIX_PROBE"), "from-fleet")

    def test_bare_row_is_still_found_when_caller_asks_bare(self):
        self.assertEqual(
            self._load("PREFIX_PROBE", "from-fleet", "PREFIX_PROBE"), "from-fleet")

    def test_prefixed_row_is_found_when_caller_asks_prefixed(self):
        self.assertEqual(
            self._load("ORCH_PREFIX_PROBE", "from-fleet", "ORCH_PREFIX_PROBE"), "from-fleet")

    def test_missing_row_still_falls_back_to_the_default(self):
        self.assertEqual(self._load("SOMETHING_ELSE", "x", "PREFIX_PROBE"), "unset")

    def test_a_raising_db_does_not_propagate(self):
        class _Boom:
            @staticmethod
            def select(table, params=None):
                raise RuntimeError("db down")
        with patch.object(config_consumer, "fleet_control", None), \
             patch.dict(sys.modules, {"db": _Boom}):
            self.assertEqual(
                config_consumer.load_config("PREFIX_PROBE", default="unset"), "unset")


class TestInvalidationCoversBothSpellings(unittest.TestCase):
    def setUp(self):
        config_consumer.invalidate_cache()
        self.addCleanup(config_consumer.invalidate_cache)

    def test_invalidating_the_prefixed_key_drops_the_bare_cache_entry(self):
        config_consumer._consumer._cache["SPELLING"] = ("old", 9e9)
        config_consumer.invalidate_cache("ORCH_SPELLING")
        self.assertNotIn("SPELLING", config_consumer._consumer._cache)

    def test_invalidating_the_bare_key_drops_the_prefixed_cache_entry(self):
        config_consumer._consumer._cache["ORCH_SPELLING"] = ("old", 9e9)
        config_consumer.invalidate_cache("SPELLING")
        self.assertNotIn("ORCH_SPELLING", config_consumer._consumer._cache)

    def test_unrelated_keys_survive(self):
        config_consumer._consumer._cache["OTHER"] = ("keep", 9e9)
        config_consumer.invalidate_cache("SPELLING")
        self.assertIn("OTHER", config_consumer._consumer._cache)

    def test_invalidate_all_still_clears_everything(self):
        config_consumer._consumer._cache["A"] = ("x", 9e9)
        config_consumer._consumer._cache["B"] = ("y", 9e9)
        config_consumer.invalidate_cache()
        self.assertEqual(config_consumer._consumer._cache, {})

    def test_junk_key_does_not_raise(self):
        config_consumer.invalidate_cache(object())


class TestPushInvalidatesTheLocalCache(unittest.TestCase):
    """A fleet-wide push must take effect on the host that made it."""

    def setUp(self):
        config_consumer.invalidate_cache()
        self.addCleanup(config_consumer.invalidate_cache)

    def test_update_fleet_config_invalidates_the_consumer_cache(self):
        import fleet_control
        config_consumer._consumer._cache["ORCH_PUSH_PROBE"] = ("stale", 9e9)
        with patch.object(fleet_control.db, "insert", return_value=None), \
             patch.object(fleet_control.db, "select", return_value=[]):
            fleet_control.update_fleet_config("ORCH_PUSH_PROBE", "fresh")
        self.assertNotIn("ORCH_PUSH_PROBE", config_consumer._consumer._cache)

    def test_a_broken_consumer_does_not_fail_the_write(self):
        import fleet_control
        with patch.object(fleet_control.db, "insert", return_value=None), \
             patch.object(fleet_control.db, "select", return_value=[]), \
             patch.object(config_consumer, "invalidate_cache",
                          side_effect=RuntimeError("boom")):
            row = fleet_control.update_fleet_config("ORCH_PUSH_PROBE", "fresh")
        self.assertEqual(row["value"], "fresh")


if __name__ == "__main__":
    unittest.main()
