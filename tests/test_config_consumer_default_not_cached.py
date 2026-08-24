"""load_config() must never cache a caller-supplied default.

The cache is keyed on the config key alone, so caching the fallback made one caller's
default visible to a different caller asking for the same key, and pinned a stale value
for a full TTL after a gateway blip had already resolved.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'runner'))

import config_consumer  # noqa: E402


class TestDefaultIsNotCached(unittest.TestCase):
    def setUp(self):
        self.key = "TEST_UNRESOLVED_KEY_FOR_CACHE"
        os.environ.pop(f"ORCH_{self.key}", None)
        config_consumer.invalidate_cache()
        self._saved_gateway = config_consumer.fleet_control
        config_consumer.fleet_control = None

    def tearDown(self):
        config_consumer.fleet_control = self._saved_gateway
        os.environ.pop(f"ORCH_{self.key}", None)
        config_consumer.invalidate_cache()

    def test_different_callers_get_their_own_default(self):
        self.assertEqual(config_consumer.load_config(self.key, "alpha"), "alpha")
        self.assertEqual(config_consumer.load_config(self.key, "beta"), "beta")

    def test_value_appearing_later_is_seen_immediately(self):
        # A miss must not pin the default for a TTL; once the value exists it wins.
        self.assertEqual(config_consumer.load_config(self.key, "fallback"), "fallback")
        os.environ[f"ORCH_{self.key}"] = "real-value"
        self.assertEqual(config_consumer.load_config(self.key, "fallback"), "real-value")

    def test_resolved_value_is_still_cached(self):
        os.environ[f"ORCH_{self.key}"] = "cached-me"
        self.assertEqual(config_consumer.load_config(self.key, ""), "cached-me")
        os.environ.pop(f"ORCH_{self.key}", None)
        # Still served from cache within the TTL — caching of real values is unchanged.
        self.assertEqual(config_consumer.load_config(self.key, ""), "cached-me")

    def test_empty_default_still_returns_empty(self):
        self.assertEqual(config_consumer.load_config(self.key, ""), "")

    def test_never_raises_on_bad_key(self):
        self.assertEqual(config_consumer.load_config(None, "d"), "d")
        self.assertEqual(config_consumer.load_config("", "d"), "d")


if __name__ == '__main__':
    unittest.main()
