#!/usr/bin/env python3
"""Tests for config_event_publisher.py"""
import os, sys, unittest, types
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_select_returns = []
db_stub = types.ModuleType("db")
db_stub.select = lambda *a, **kw: list(_select_returns)
db_stub.update = lambda *a, **kw: None
db_stub.insert = lambda *a, **kw: None
sys.modules["db"] = db_stub

import config_event_publisher as cep


class TestSafeKey(unittest.TestCase):
    def test_orch_prefix(self):
        self.assertTrue(cep._safe_key("ORCH_MARGINAL_DECAY"))
    def test_max_parallel(self):
        self.assertTrue(cep._safe_key("MAX_PARALLEL_TASKS"))
    def test_deny_secret(self):
        self.assertFalse(cep._safe_key("ORCH_SECRET_VALUE"))
    def test_deny_token(self):
        self.assertFalse(cep._safe_key("ORCH_API_TOKEN"))
    def test_deny_password(self):
        self.assertFalse(cep._safe_key("ORCH_PASSWORD"))
    def test_unknown_prefix(self):
        self.assertFalse(cep._safe_key("RANDOM_THING"))

class TestDetectChanges(unittest.TestCase):
    def setUp(self):
        global _select_returns
        cep.invalidate()
        _select_returns = []

    def test_first_run(self):
        global _select_returns
        _select_returns = [{"key": "ORCH_FOO", "value": "bar"}]
        changes = cep.detect_changes()
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["key"], "ORCH_FOO")
        self.assertIsNone(changes[0]["old_value"])

    def test_no_change(self):
        global _select_returns
        _select_returns = [{"key": "ORCH_FOO", "value": "bar"}]
        cep.detect_changes()
        changes = cep.detect_changes()
        self.assertEqual(len(changes), 0)

    def test_value_change(self):
        global _select_returns
        _select_returns = [{"key": "ORCH_FOO", "value": "bar"}]
        cep.detect_changes()
        _select_returns = [{"key": "ORCH_FOO", "value": "baz"}]
        changes = cep.detect_changes()
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["old_value"], "bar")
        self.assertEqual(changes[0]["value"], "baz")

    def test_deletion(self):
        global _select_returns
        _select_returns = [{"key": "ORCH_FOO", "value": "bar"}]
        cep.detect_changes()
        _select_returns = []
        changes = cep.detect_changes()
        self.assertEqual(len(changes), 1)
        self.assertIsNone(changes[0]["value"])

    def test_secrets_filtered(self):
        global _select_returns
        _select_returns = [{"key": "ORCH_SECRET_KEY", "value": "x"}]
        changes = cep.detect_changes()
        self.assertEqual(len(changes), 0)


class TestPublish(unittest.TestCase):
    def setUp(self):
        cep.invalidate()

    def test_disabled(self):
        os.environ["ORCH_CONFIG_EVENTS_ENABLED"] = "false"
        r = cep.publish_changes([{"key": "ORCH_X", "value": "1"}])
        self.assertFalse(r.get("enabled", True))
        os.environ["ORCH_CONFIG_EVENTS_ENABLED"] = "true"

    def test_no_changes(self):
        r = cep.publish_changes([])
        self.assertEqual(r["published"], 0)

    def test_fails_soft_without_supabase(self):
        os.environ.pop("SUPABASE_URL", None)
        os.environ.pop("SUPABASE_SERVICE_KEY", None)
        r = cep.publish_changes([{"key": "ORCH_X", "value": "1"}])
        self.assertEqual(r["published"], 0)
        self.assertEqual(r["failed"], 1)

class TestSnapshotStats(unittest.TestCase):
    def test_snapshot_empty(self):
        cep.invalidate()
        self.assertEqual(cep.snapshot(), {})

    def test_stats(self):
        cep.invalidate()
        s = cep.stats()
        self.assertEqual(s["snapshot_size"], 0)

if __name__ == "__main__":
    unittest.main()
