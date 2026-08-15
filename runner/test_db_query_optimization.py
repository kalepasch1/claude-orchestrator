#!/usr/bin/env python3
"""
test_db_query_optimization.py - Unit tests for database query optimizations (0062 migration).

Tests:
- Queue depth estimation: validates fast estimation vs exact count
- Project cache refresh: ensures cache TTL and fallback behavior
- Query plan validation: confirms indexes are used effectively
"""
import unittest
import time
import os
from unittest.mock import patch, MagicMock
import sys

# Add runner to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import db


class TestQueueDepthEstimation(unittest.TestCase):
    """Test fast queue depth estimation using LIMIT instead of COUNT."""

    @patch("db.select")
    def test_estimation_under_ceiling(self, mock_select):
        """When queue is under ceiling, estimation returns correct depth."""
        # Mock select to return 50 rows (under ceiling of 800)
        mock_select.return_value = [{"id": f"task-{i}"} for i in range(50)]

        is_over, depth = db._queue_depth_estimate(800)

        self.assertFalse(is_over, "Queue should not be over ceiling")
        self.assertEqual(depth, 50, "Depth should be 50")
        mock_select.assert_called_once()

    @patch("db.select")
    def test_estimation_over_ceiling(self, mock_select):
        """When queue exceeds ceiling, estimation short-circuits early."""
        # Mock select to return 801 rows (over ceiling of 800)
        mock_select.return_value = [{"id": f"task-{i}"} for i in range(801)]

        is_over, depth = db._queue_depth_estimate(800)

        self.assertTrue(is_over, "Queue should be over ceiling")
        self.assertGreater(depth, 800, "Depth should be > 800")

    @patch("db.select")
    def test_estimation_failure_fallback(self, mock_select):
        """On query error, fallback is safe (assume queue OK)."""
        mock_select.side_effect = Exception("DB connection failed")

        is_over, depth = db._queue_depth_estimate(800)

        self.assertFalse(is_over, "Should fail-soft (assume queue OK on error)")
        self.assertEqual(depth, 800, "Should return ceiling as fallback depth")

    @patch("db.select")
    def test_estimation_uses_limit_not_count(self, mock_select):
        """Verify that estimation uses SELECT with LIMIT, not COUNT."""
        mock_select.return_value = []

        db._queue_depth_estimate(100)

        # Check that select was called with params containing limit
        call_kwargs = mock_select.call_args[0][1] if mock_select.call_args[0] else {}
        self.assertIn("limit", call_kwargs, "Should use LIMIT in query")
        self.assertEqual(call_kwargs["limit"], "101", "LIMIT should be ceiling + 1")
        self.assertEqual(call_kwargs["state"], "eq.QUEUED", "Should filter by QUEUED state")


class TestProjectCaching(unittest.TestCase):
    """Test project list caching for claim_task() optimization."""

    def setUp(self):
        """Reset cache before each test."""
        db._cached_projects_list = []
        db._PROJECT_CACHE_TIME["at"] = 0.0
        db._PROJECT_CACHE_TIME.pop("_cached_projects", None)

    @patch("db.select")
    def test_project_cache_refresh(self, mock_select):
        """First refresh populates cache from DB."""
        mock_select.return_value = [
            {"id": "proj-1", "name": "apparently", "priority": 1},
            {"id": "proj-2", "name": "beethoven", "priority": 4},
        ]

        db._refresh_projects_cache()

        self.assertEqual(len(db._cached_projects_list), 2, "Cache should have 2 projects")
        self.assertEqual(db._cached_projects_list[0]["name"], "apparently")

    @patch("db.select")
    def test_project_cache_ttl_respected(self, mock_select):
        """Cache is not refreshed before TTL expires."""
        mock_select.return_value = [{"id": "proj-1", "name": "apparently"}]

        # First refresh
        db._refresh_projects_cache()
        call_count_1 = mock_select.call_count

        # Immediate second refresh should use cache
        db._refresh_projects_cache()
        call_count_2 = mock_select.call_count

        self.assertEqual(call_count_1, call_count_2, "Should not re-query within TTL")

    @patch("db.select")
    def test_project_cache_expires(self, mock_select):
        """Cache is refreshed after TTL expires."""
        mock_select.return_value = [{"id": "proj-1", "name": "apparently"}]

        # Set cache as old (>300s)
        db._PROJECT_CACHE_TIME["at"] = time.time() - 400

        db._refresh_projects_cache()

        self.assertTrue(mock_select.called, "Should query DB after TTL expired")

    @patch("db.select")
    def test_project_cache_fallback_on_error(self, mock_select):
        """On error, stale cache is preserved."""
        # Set up initial cache
        db._cached_projects_list = [{"id": "proj-1", "name": "apparently"}]
        db._PROJECT_CACHE_TIME["at"] = time.time() - 400  # Expired

        # Mock error
        mock_select.side_effect = Exception("DB down")

        db._refresh_projects_cache()

        # Cache should still be there (not cleared on error)
        self.assertEqual(len(db._cached_projects_list), 1)


class TestQueueDepthBlockOptimization(unittest.TestCase):
    """Test _queue_depth_block integration with fast estimation."""

    def setUp(self):
        """Reset state before each test."""
        db._QUEUE_DEPTH_CACHE["at"] = 0.0
        db._QUEUE_DEPTH_CACHE["depth"] = 0

    @patch("db._queue_depth_estimate")
    def test_queue_depth_block_uses_estimate(self, mock_estimate):
        """_queue_depth_block should use estimation for fast rejection."""
        mock_estimate.return_value = (False, 100)  # Under ceiling

        row = {"slug": "test-task", "project_id": "proj-1"}
        result = db._queue_depth_block(row)

        self.assertFalse(result, "Should allow when under ceiling")
        mock_estimate.assert_called()

    @patch("db._queue_depth_estimate")
    def test_queue_depth_block_exempt_prefixes(self, mock_estimate):
        """Tasks with exempt prefixes should never be blocked."""
        mock_estimate.return_value = (True, 1000)  # Over ceiling

        # These prefixes are always exempt
        for prefix in db._EXEMPT_SLUG_PREFIXES:
            row = {"slug": f"{prefix}test-task"}
            result = db._queue_depth_block(row)
            self.assertFalse(result, f"Prefix {prefix} should be exempt")

        # Estimation should never be called for exempt tasks
        mock_estimate.assert_not_called()

    @patch("db._queue_depth_estimate")
    def test_queue_depth_block_operator_origin(self, mock_estimate):
        """Operator-origin tasks should never be blocked."""
        mock_estimate.return_value = (True, 1000)  # Over ceiling

        row = {"slug": "test", "submitted_by": "kalepasch1"}
        result = db._queue_depth_block(row)

        self.assertFalse(result, "Operator-origin tasks should be exempt")

    @patch("db._queue_depth_estimate")
    def test_queue_depth_block_cache_ttl(self, mock_estimate):
        """Cache should respect TTL before re-estimating."""
        mock_estimate.return_value = (False, 100)

        # First call
        row = {"slug": "test-task"}
        db._queue_depth_block(row)
        first_call_count = mock_estimate.call_count

        # Immediate second call should use cache
        db._queue_depth_block(row)
        second_call_count = mock_estimate.call_count

        self.assertEqual(first_call_count, second_call_count, "Should use cache within TTL")


class TestIndexCreation(unittest.TestCase):
    """Validate that migration 0062 creates all required indexes."""

    def test_migration_file_exists(self):
        """Verify that 0062_optimize_fleet_config_queries.sql was created."""
        migration_path = os.path.join(
            os.path.dirname(__file__), "..", "supabase", "migrations",
            "0062_optimize_fleet_config_queries.sql"
        )
        self.assertTrue(os.path.exists(migration_path),
                       f"Migration file should exist at {migration_path}")

    def test_migration_contains_indexes(self):
        """Verify migration includes all critical indexes."""
        migration_path = os.path.join(
            os.path.dirname(__file__), "..", "supabase", "migrations",
            "0062_optimize_fleet_config_queries.sql"
        )
        with open(migration_path, 'r') as f:
            content = f.read()

        required_indexes = [
            "tasks_state_created_idx",
            "tasks_state_project_idx",
            "tasks_state_updated_idx",
            "tasks_project_slug_state_idx",
            "fleet_control_open_target_idx",
            "controls_scope_project_idx",
        ]

        for idx_name in required_indexes:
            self.assertIn(idx_name, content, f"Migration should create index {idx_name}")


if __name__ == "__main__":
    unittest.main()
