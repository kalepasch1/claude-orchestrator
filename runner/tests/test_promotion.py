#!/usr/bin/env python3
"""Tests for promotion.py — preview-to-prod promotion + rollback."""
import os, sys, unittest, threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import promotion


class TestPromoteSuccess(unittest.TestCase):
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


class TestRollbackOnFailure(unittest.TestCase):
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


class TestPromotionValidation(unittest.TestCase):
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


class TestConcurrentPromotion(unittest.TestCase):
    """Test concurrent promotion handling."""

    def test_concurrent_promotion_blocked(self):
        promotion._promotion_lock.acquire()
        try:
            with self.assertRaises(promotion.ConcurrentPromotionError):
                promotion.promote_preview_to_prod({"project_id": "x"})
        finally:
            promotion._promotion_lock.release()


class TestSnapshotAndHelpers(unittest.TestCase):
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
