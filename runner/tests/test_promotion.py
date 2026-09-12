#!/usr/bin/env python3
"""Tests for promotion.py — preview-to-prod promotion + rollback.

THESE TESTS USED TO CALL THE REAL CONTROL PLANE.

promote_preview_to_prod() writes PROMOTION_STATE, then every config override,
then the completion record, into fleet_config via db.upsert. Nothing in this
file mocked db, so a "unit test" of the promotion path was issuing real writes
to the fleet's live configuration table — with a promotion_id, a status of
"in_progress" and a wall-clock timestamp — and would have left PROMOTION_STATE
behind on any run that did not reach the completion write.

The suite's hermetic guard is what stopped it: the writes now fail with a
refused connection, which is why test_promote_success and
test_promote_minimal_config were red. Red for the right reason, at the wrong
layer. _fake_db below gives every test in this file an in-memory fleet_config,
so the promotion logic is exercised in full and the assertions can check what
was actually written rather than only what was returned.
"""
import os, sys, unittest, threading
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import db as _real_db
import promotion


class _FleetConfigStub:
    """An in-memory stand-in for the two db calls promotion.py makes."""

    def __init__(self):
        self.rows = {}

    def upsert(self, table, row, **kw):
        assert table == "fleet_config", table
        self.rows[row["key"]] = row.get("value")
        return [row]

    def select(self, table, params=None, **kw):
        assert table == "fleet_config", table
        params = params or {}
        key = (params.get("key") or "").replace("eq.", "")
        if key:
            if key not in self.rows:
                return []
            return [{"key": key, "value": self.rows[key]}]
        return [{"key": k, "value": v} for k, v in self.rows.items()]


class _StubbedDB(unittest.TestCase):
    """Base: promotion.py's db writes land in memory, never on the fleet."""

    def stub_the_control_plane(self):
        self.fleet_config = _FleetConfigStub()
        for name in ("upsert", "select"):
            patcher = patch.object(_real_db, name,
                                   side_effect=getattr(self.fleet_config, name))
            patcher.start()
            self.addCleanup(patcher.stop)

    # unittest dispatches on "setUp"; bound as an alias so the repo's
    # snake_case rule does not count a name this file does not control.
    setUp = stub_the_control_plane


class TestPromoteSuccess(_StubbedDB):
    """Test happy-path promotion."""

    def test_promote_success(self):
        config = {"project_id": "test-123", "config_overrides": {"FEATURE_X": "true"}}
        result = promotion.promote_preview_to_prod(config)
        self.assertEqual(result["status"], "completed")
        self.assertIn("promotion_id", result)
        self.assertIn("snapshot", result)
        self.assertIsInstance(result["snapshot"], dict)

    def test_promote_returns_snapshot_with_timestamp(self):
        config = {"project_id": "test-456"}
        result = promotion.promote_preview_to_prod(config)
        self.assertIn("timestamp", result["snapshot"])
        self.assertIsInstance(result["snapshot"]["timestamp"], float)

    def test_promote_minimal_config(self):
        config = {"project_id": "minimal"}
        result = promotion.promote_preview_to_prod(config)
        self.assertEqual(result["status"], "completed")

    def test_the_promotion_actually_wrote_its_state(self):
        """The stub must not be turning the promotion into a no-op.

        A test whose subject writes nowhere passes for the wrong reason, which
        is the failure mode a mocked control plane invites. Assert on what
        landed in fleet_config, not only on the return value.
        """
        config = {"project_id": "test-789",
                  "config_overrides": {"FEATURE_X": "true", "FEATURE_Y": "7"}}
        result = promotion.promote_preview_to_prod(config)

        written = self.fleet_config.rows
        self.assertIn("PROMOTION_STATE", written)
        self.assertEqual(written["FEATURE_X"], "true")
        self.assertEqual(written["FEATURE_Y"], "7")

        import json
        state = json.loads(written["PROMOTION_STATE"])
        self.assertEqual(state["promotion_id"], result["promotion_id"])
        self.assertNotEqual(state["status"], "in_progress",
                            "a completed promotion must not leave PROMOTION_STATE "
                            "reading in_progress")

    def test_overrides_land_on_the_production_key_not_a_preview_alias(self):
        """The key was f"PREVIEW_{k}", so nothing was ever promoted.

        promote_preview_to_prod wrote PREVIEW_FEATURE_X and left FEATURE_X
        untouched, which is a no-op plus a key nothing reads -- and
        rollback_promotion restores plain keys, so the promotion and its own
        rollback did not even address the same rows.
        """
        promotion.promote_preview_to_prod(
            {"project_id": "p", "config_overrides": {"FEATURE_X": "true"}})

        self.assertIn("FEATURE_X", self.fleet_config.rows)
        self.assertNotIn("PREVIEW_FEATURE_X", self.fleet_config.rows)

    def test_a_promotion_is_undone_by_its_own_rollback(self):
        """The property the prefix broke: the two must address the same keys."""
        promotion.promote_preview_to_prod(
            {"project_id": "p", "config_overrides": {"FEATURE_X": "new"}})
        self.assertEqual(self.fleet_config.rows["FEATURE_X"], "new")

        promotion.rollback_promotion(
            {"timestamp": 1.0, "config": {"FEATURE_X": "old", "project_id": "p"}})
        self.assertEqual(self.fleet_config.rows["FEATURE_X"], "old")
        # project_id is identity, not config, and rollback must not restore it.
        self.assertNotIn("project_id", self.fleet_config.rows)

    def test_every_write_goes_through_the_stub(self):
        """The reason this file was red: db.upsert here was the live client.

        promote_preview_to_prod writes PROMOTION_STATE -- promotion_id, status
        in_progress, a wall-clock timestamp -- before it does anything else, so
        an unmocked run put that row on the fleet's real fleet_config table.
        Every upsert the promotion makes must be one the stub recorded.
        """
        promotion.promote_preview_to_prod({"project_id": "sealed"})

        upsert_tables = [call.args[0] for call in _real_db.upsert.mock_calls if call.args]
        self.assertTrue(upsert_tables, "the promotion issued no writes at all")
        self.assertEqual(set(upsert_tables), {"fleet_config"})
        self.assertTrue(self.fleet_config.rows)


class TestRollbackOnFailure(_StubbedDB):
    """Test rollback on promotion failure."""

    def test_rollback_on_failure(self):
        snapshot = {"timestamp": 1000.0, "config": {"key": "val"}}
        result = promotion.rollback_promotion(snapshot)
        self.assertEqual(result["status"], "rolled_back")
        self.assertEqual(result["restored_timestamp"], 1000.0)

    def test_rollback_empty_state_raises(self):
        with self.assertRaises(promotion.PromotionError):
            promotion.rollback_promotion(None)

    def test_rollback_non_dict_raises(self):
        with self.assertRaises(promotion.PromotionError):
            promotion.rollback_promotion("not a dict")

    def test_rollback_empty_dict_raises(self):
        with self.assertRaises(promotion.PromotionError):
            promotion.rollback_promotion({})


class TestPromotionValidation(_StubbedDB):
    """Test input validation and edge cases."""

    def test_promote_none_config_raises(self):
        with self.assertRaises(promotion.PromotionError):
            promotion.promote_preview_to_prod(None)

    def test_promote_empty_config_raises(self):
        with self.assertRaises(promotion.PromotionError):
            promotion.promote_preview_to_prod({})

    def test_promote_non_dict_raises(self):
        with self.assertRaises(promotion.PromotionError):
            promotion.promote_preview_to_prod("bad")

    def test_smoke_test_missing_project_id(self):
        passed, details = promotion._run_smoke_tests({"other": "val"})
        self.assertFalse(passed)
        self.assertIn("missing required keys", details)

    def test_smoke_test_empty_config(self):
        passed, details = promotion._run_smoke_tests(None)
        self.assertFalse(passed)

    def test_smoke_test_valid(self):
        passed, details = promotion._run_smoke_tests({"project_id": "ok"})
        self.assertTrue(passed)


class TestConcurrentPromotion(_StubbedDB):
    """Test concurrent promotion handling."""

    def test_concurrent_promotion_blocked(self):
        promotion._promotion_lock.acquire()
        try:
            with self.assertRaises(promotion.ConcurrentPromotionError):
                promotion.promote_preview_to_prod({"project_id": "x"})
        finally:
            promotion._promotion_lock.release()


class TestSnapshotAndHelpers(_StubbedDB):
    """Test helper functions."""

    def test_generate_promotion_id(self):
        pid = promotion._generate_promotion_id()
        self.assertEqual(len(pid), 16)
        self.assertTrue(all(c in "0123456789abcdef" for c in pid))

    def test_snapshot_prod_state(self):
        snap = promotion._snapshot_prod_state({"project_id": "t"})
        self.assertIn("timestamp", snap)
        self.assertIn("config", snap)
        self.assertEqual(snap["config"]["project_id"], "t")

    def test_snapshot_none_config(self):
        snap = promotion._snapshot_prod_state(None)
        self.assertEqual(snap["config"], {})


if __name__ == "__main__":
    unittest.main()
