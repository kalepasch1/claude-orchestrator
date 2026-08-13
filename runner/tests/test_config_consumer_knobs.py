#!/usr/bin/env python3
"""config_consumer's own knobs must obey the contract config_consumer sells.

The module promises "never raises" and "fleet-pushable ORCH_ config". Its own two
knobs broke both promises: ORCH_CONFIG_CACHE_TTL_SEC was cast with a bare float()
inside __init__ — which runs at import via the module-level singleton — so a
malformed value raised ValueError and took down every importer; and once read it was
frozen for the life of the process, so a fleet push of the TTL changed nothing. The
cache itself was unbounded.
"""
import importlib
import os
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RUNNER)

import config_consumer as cc  # noqa: E402


def _clean(**overrides):
    env = {k: v for k, v in os.environ.items() if not k.startswith("ORCH_CONFIG_CACHE")}
    env.update(overrides)
    return env


class ImportIsFailSoftTest(unittest.TestCase):

    def _import_with(self, value):
        env = dict(os.environ)
        env["ORCH_CONFIG_CACHE_TTL_SEC"] = value
        env["PYTHONPATH"] = RUNNER
        return subprocess.run(
            [sys.executable, "-c", "import config_consumer; print('imported')"],
            capture_output=True, text=True, env=env, timeout=120)

    def test_malformed_ttl_does_not_break_the_import(self):
        """THE REGRESSION: this used to raise ValueError at import time."""
        proc = self._import_with("abc")
        self.assertEqual(proc.returncode, 0, proc.stderr[-800:])
        self.assertIn("imported", proc.stdout)

    def test_empty_ttl_does_not_break_the_import(self):
        proc = self._import_with("   ")
        self.assertEqual(proc.returncode, 0, proc.stderr[-800:])

    def test_negative_ttl_does_not_break_the_import(self):
        proc = self._import_with("-5")
        self.assertEqual(proc.returncode, 0, proc.stderr[-800:])

    def test_reimport_is_still_clean_with_a_good_value(self):
        proc = self._import_with("30")
        self.assertEqual(proc.returncode, 0, proc.stderr[-800:])


class KnobParsingTest(unittest.TestCase):

    def test_valid_ttl_is_used(self):
        with patch.dict(os.environ, _clean(ORCH_CONFIG_CACHE_TTL_SEC="12.5"), clear=True):
            self.assertEqual(cc._consumer._cache_ttl_sec, 12.5)

    def test_malformed_ttl_falls_back_to_the_default(self):
        with patch.dict(os.environ, _clean(ORCH_CONFIG_CACHE_TTL_SEC="abc"), clear=True):
            self.assertEqual(cc._consumer._cache_ttl_sec, cc.DEFAULT_CACHE_TTL_SEC)

    def test_negative_ttl_falls_back_to_the_default(self):
        with patch.dict(os.environ, _clean(ORCH_CONFIG_CACHE_TTL_SEC="-1"), clear=True):
            self.assertEqual(cc._consumer._cache_ttl_sec, cc.DEFAULT_CACHE_TTL_SEC)

    def test_absent_ttl_uses_the_default(self):
        with patch.dict(os.environ, _clean(), clear=True):
            self.assertEqual(cc._consumer._cache_ttl_sec, cc.DEFAULT_CACHE_TTL_SEC)

    def test_ttl_is_reread_so_a_fleet_push_takes_effect_without_restart(self):
        with patch.dict(os.environ, _clean(ORCH_CONFIG_CACHE_TTL_SEC="5"), clear=True):
            self.assertEqual(cc._consumer._cache_ttl_sec, 5.0)
        with patch.dict(os.environ, _clean(ORCH_CONFIG_CACHE_TTL_SEC="900"), clear=True):
            self.assertEqual(cc._consumer._cache_ttl_sec, 900.0)

    def test_max_entries_knob(self):
        with patch.dict(os.environ, _clean(ORCH_CONFIG_CACHE_MAX_ENTRIES="7"), clear=True):
            self.assertEqual(cc._consumer._cache_max_entries, 7)

    def test_malformed_max_entries_falls_back(self):
        with patch.dict(os.environ, _clean(ORCH_CONFIG_CACHE_MAX_ENTRIES="lots"), clear=True):
            self.assertEqual(cc._consumer._cache_max_entries, cc.DEFAULT_CACHE_MAX_ENTRIES)

    def test_zero_max_entries_falls_back(self):
        with patch.dict(os.environ, _clean(ORCH_CONFIG_CACHE_MAX_ENTRIES="0"), clear=True):
            self.assertEqual(cc._consumer._cache_max_entries, cc.DEFAULT_CACHE_MAX_ENTRIES)


class CacheBoundTest(unittest.TestCase):

    def setUp(self):
        cc.invalidate_cache()

    def tearDown(self):
        cc.invalidate_cache()

    def _fill(self, n):
        now = time.time()
        with cc._consumer._lock:
            for i in range(n):
                cc._consumer._cache[f"k{i:04d}"] = (str(i), now + i)

    def test_cache_is_bounded(self):
        with patch.dict(os.environ, _clean(ORCH_CONFIG_CACHE_MAX_ENTRIES="5"), clear=True):
            self._fill(20)
            with cc._consumer._lock:
                cc._consumer._evict_locked()
            self.assertLessEqual(len(cc._consumer._cache), 5)

    def test_eviction_drops_the_oldest_first(self):
        with patch.dict(os.environ, _clean(ORCH_CONFIG_CACHE_MAX_ENTRIES="3"), clear=True):
            self._fill(6)
            with cc._consumer._lock:
                cc._consumer._evict_locked()
            self.assertEqual(sorted(cc._consumer._cache), ["k0003", "k0004", "k0005"])

    def test_no_eviction_below_the_limit(self):
        with patch.dict(os.environ, _clean(ORCH_CONFIG_CACHE_MAX_ENTRIES="100"), clear=True):
            self._fill(4)
            with cc._consumer._lock:
                cc._consumer._evict_locked()
            self.assertEqual(len(cc._consumer._cache), 4)


class InvalidateTest(unittest.TestCase):

    def setUp(self):
        cc.invalidate_cache()

    def tearDown(self):
        cc.invalidate_cache()

    def _seed(self):
        now = time.time()
        with cc._consumer._lock:
            cc._consumer._cache.update({"a": ("1", now), "b": ("2", now)})

    def test_invalidate_one_key_leaves_the_rest(self):
        self._seed()
        cc.invalidate_cache("a")
        self.assertNotIn("a", cc._consumer._cache)
        self.assertIn("b", cc._consumer._cache)

    def test_invalidate_all_still_works(self):
        self._seed()
        cc.invalidate_cache()
        self.assertEqual(cc._consumer._cache, {})

    def test_invalidating_an_unknown_key_is_a_no_op(self):
        self._seed()
        cc.invalidate_cache("nope")
        self.assertEqual(len(cc._consumer._cache), 2)


class ExistingContractTest(unittest.TestCase):
    """Nothing above may change what callers already rely on."""

    def test_typed_getters_still_work(self):
        with patch.dict(os.environ, {"ORCH_X_INT": "7", "ORCH_X_BOOL": "yes",
                                     "ORCH_X_FLOAT": "1.5", "ORCH_X_STR": " v "}):
            self.assertEqual(cc.get_int("X_INT"), 7)
            self.assertTrue(cc.get_bool("X_BOOL"))
            self.assertEqual(cc.get_float("X_FLOAT"), 1.5)
            self.assertEqual(cc.get("X_STR"), "v")

    def test_getters_never_raise_on_garbage(self):
        with patch.dict(os.environ, {"ORCH_BAD": "not-a-number"}):
            self.assertEqual(cc.get_int("BAD", 3), 3)
            self.assertEqual(cc.get_float("BAD", 2.5), 2.5)

    def test_load_config_caches_and_honours_the_ttl(self):
        cc.invalidate_cache()
        with patch.dict(os.environ, _clean(ORCH_MYKEY="from-env",
                                           ORCH_CONFIG_CACHE_TTL_SEC="900"), clear=True), \
             patch.object(cc, "fleet_control", None):
            self.assertEqual(cc.load_config("MYKEY", "fallback"), "from-env")
            self.assertIn("MYKEY", cc._consumer._cache)
        cc.invalidate_cache()

    def test_zero_ttl_means_every_read_is_fresh(self):
        cc.invalidate_cache()
        with patch.dict(os.environ, _clean(ORCH_CONFIG_CACHE_TTL_SEC="0"), clear=True):
            self.assertEqual(cc._consumer._cache_ttl_sec, 0.0)
        cc.invalidate_cache()


if __name__ == "__main__":
    unittest.main()
