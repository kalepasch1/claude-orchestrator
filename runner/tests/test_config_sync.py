import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config_sync


class CurrentHashTest(unittest.TestCase):
    def test_returns_consistent_hash_for_same_data(self):
        rows = [{"key": "A", "value": "1"}, {"key": "B", "value": "2"}]
        with patch.object(config_sync.db, "select", return_value=rows):
            h1 = config_sync.current_hash()
            h2 = config_sync.current_hash()
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), 16)

    def test_returns_different_hash_for_different_data(self):
        with patch.object(config_sync.db, "select", return_value=[{"key": "A", "value": "1"}]):
            h1 = config_sync.current_hash()
        with patch.object(config_sync.db, "select", return_value=[{"key": "A", "value": "2"}]):
            h2 = config_sync.current_hash()
        self.assertNotEqual(h1, h2)

    def test_handles_db_error(self):
        with patch.object(config_sync.db, "select", side_effect=Exception("down")):
            h = config_sync.current_hash()
        self.assertEqual(len(h), 16)


class SyncTest(unittest.TestCase):
    def setUp(self):
        config_sync._state._hash = ""
        config_sync._state._snapshot = {}
        config_sync._state._callbacks = []

    def test_dry_run_does_not_apply(self):
        rows = [{"key": "ORCH_QUEUE_ELIMINATION", "value": "false"}]
        with patch.object(config_sync.db, "select", return_value=rows), \
             patch.object(config_sync, "current_hash", return_value="abc123"):
            result = config_sync.sync(dry_run=True)
        self.assertNotIn("ORCH_QUEUE_ELIMINATION", os.environ.get("ORCH_QUEUE_ELIMINATION", ""))
        self.assertEqual(result["hash"], "abc123")

    def test_detects_drift(self):
        config_sync._state._hash = "old_hash"
        with patch.object(config_sync.db, "select", return_value=[]), \
             patch.object(config_sync, "current_hash", return_value="new_hash"):
            result = config_sync.sync()
        self.assertTrue(result["drift"])

    def test_no_drift_when_hash_matches(self):
        config_sync._state._hash = "same"
        with patch.object(config_sync.db, "select", return_value=[]), \
             patch.object(config_sync, "current_hash", return_value="same"):
            result = config_sync.sync()
        self.assertFalse(result["drift"])

    def test_callback_fires_on_change(self):
        changes = []
        config_sync.on_change(lambda k, o, n: changes.append((k, o, n)))
        rows = [{"key": "ORCH_QUEUE_ELIMINATION", "value": "true"}]
        with patch.object(config_sync.db, "select", return_value=rows), \
             patch.object(config_sync, "current_hash", return_value="x"):
            config_sync.sync()
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0][0], "ORCH_QUEUE_ELIMINATION")


class HotReloadKeysTest(unittest.TestCase):
    def test_hot_reload_keys_are_all_strings(self):
        for key in config_sync.HOT_RELOAD_KEYS:
            self.assertIsInstance(key, str)

    def test_restart_keys_not_in_hot_reload(self):
        overlap = config_sync.HOT_RELOAD_KEYS & config_sync.RESTART_REQUIRED_KEYS
        self.assertEqual(overlap, set())


if __name__ == "__main__":
    unittest.main()
