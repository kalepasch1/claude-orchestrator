#!/usr/bin/env python3
"""
test_db_query_optimization.py - Unit tests for database query optimizations (0062 migration).

Tests:
- Queue depth estimation: validates fast estimation vs exact count
- Project cache refresh: ensures cache TTL and fallback behavior
- Query plan validation: confirms indexes are used effectively

SEAM NOTE (2026-08-24). Every stub below was `@patch("db.select")` /
`@patch("db._queue_depth_estimate")` — string targets, which mock resolves through
`sys.modules["db"]` at call time. runner/test_canary_ollama_23.py used to run
`patch.dict(sys.modules, {"db": MagicMock()})` inside five concurrent threads, and
patch.dict restores by clearing and re-filling the dict; interleaved restores left that
MagicMock parked in sys.modules for the rest of the session. From then on these
decorators patched the leftover mock while the REAL db module ran unpatched — six tests
here failed, and `_queue_depth_estimate` / `_refresh_projects_cache` were reaching for a
live database. `patch.object(db, ...)` binds to the module object this file already
imported, so the stub lands on the same object under test no matter what else the suite
does to sys.modules, and no test can fall through to the network.
"""
import unittest
import time
import os
from unittest.mock import patch
import sys

# Add runner to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import db


class TestQueueDepthEstimation(unittest.TestCase):
    """Test fast queue depth estimation using LIMIT instead of COUNT."""

    @patch.object(db, "select")
    def test_estimation_under_ceiling(self, mock_select):
        """When queue is under ceiling, estimation returns correct depth."""
        # Mock select to return 50 rows (under ceiling of 800)
        mock_select.return_value = [{"id": f"task-{i}"} for i in range(50)]

        is_over, depth = db._queue_depth_estimate(800)

        self.assertFalse(is_over, "Queue should not be over ceiling")
        self.assertEqual(depth, 50, "Depth should be 50")
        mock_select.assert_called_once()

    @patch.object(db, "select")
    def test_estimation_over_ceiling(self, mock_select):
        """When queue exceeds ceiling, estimation short-circuits early."""
        # Mock select to return 801 rows (over ceiling of 800)
        mock_select.return_value = [{"id": f"task-{i}"} for i in range(801)]

        is_over, depth = db._queue_depth_estimate(800)

        self.assertTrue(is_over, "Queue should be over ceiling")
        self.assertGreater(depth, 800, "Depth should be > 800")

    @patch.object(db, "select")
    def test_estimation_failure_fallback(self, mock_select):
        """On query error, fallback is safe (assume queue OK).

        PRODUCT BUG FIXED, TEST CORRECTED (runner/db.py:1137). This used to assert
        `depth == 800` — "Should return ceiling as fallback depth" — and that value was the
        bug, not the contract. `_queue_depth_block` throws the `is_over` flag away and
        re-derives the verdict from the cached depth alone (`depth < ceiling` -> admit), so a
        fallback depth OF the ceiling refused every non-exempt insert for a whole cache TTL
        every time the database was briefly unreachable, logging "QUEUED depth 800 >= ceiling
        800" with no measurement behind it. The test asserted fail-soft in the flag nobody
        reads while pinning fail-CLOSED in the number everybody reads. The no-measurement
        depth is now 0, the only value that cannot block.
        """
        mock_select.side_effect = Exception("DB connection failed")

        is_over, depth = db._queue_depth_estimate(800)

        self.assertFalse(is_over, "Should fail-soft (assume queue OK on error)")
        self.assertEqual(depth, 0, "no measurement must not masquerade as a full queue")

    @patch.object(db, "select")
    def test_an_unreachable_database_does_not_freeze_admission(self, mock_select):
        """The end-to-end shape of the bug above: the gate must still admit ordinary work.

        Asserted through _queue_depth_block rather than the estimate alone, because the
        estimate's return value only matters via this caller.
        """
        mock_select.side_effect = Exception("DB connection failed")
        db._QUEUE_DEPTH_CACHE["at"] = 0.0
        db._QUEUE_DEPTH_CACHE["depth"] = 0

        blocked = db._queue_depth_block({"slug": "improve-some-churn", "project_id": "proj-1"})

        self.assertFalse(blocked, "a db blip must not become a fleet-wide write freeze")

    @patch.object(db, "select")
    def test_estimation_uses_limit_not_count(self, mock_select):
        """Verify that estimation uses SELECT with LIMIT, not COUNT."""
        mock_select.return_value = []

        db._queue_depth_estimate(100)

        # The params dict is the second POSITIONAL argument: select("tasks", {...}).
        # This used to read `mock_select.call_args[0][1] if mock_select.call_args[0] else {}`,
        # which degraded to an empty dict when select was never called — and an empty dict
        # would then fail on `assertIn`, but only after hiding WHY. Unpack it outright so a
        # missing call is reported as a missing call.
        table, params = mock_select.call_args.args
        self.assertEqual(table, "tasks")
        self.assertIn("limit", params, "Should use LIMIT in query")
        self.assertEqual(params["limit"], "101", "LIMIT should be ceiling + 1")
        self.assertEqual(params["state"], "eq.QUEUED", "Should filter by QUEUED state")
        self.assertNotIn("count", str(params).lower(),
                         "estimation must not fall back to an exact COUNT")


class TestProjectCaching(unittest.TestCase):
    """Test project list caching for claim_task() optimization."""

    def setUp(self):
        """Reset cache before each test."""
        db._cached_projects_list = []
        db._PROJECT_CACHE_TIME["at"] = 0.0
        db._PROJECT_CACHE_TIME.pop("_cached_projects", None)

    @patch.object(db, "select")
    def test_project_cache_refresh(self, mock_select):
        """First refresh populates cache from DB."""
        mock_select.return_value = [
            {"id": "proj-1", "name": "apparently", "priority": 1},
            {"id": "proj-2", "name": "beethoven", "priority": 4},
        ]

        db._refresh_projects_cache()

        self.assertEqual(len(db._cached_projects_list), 2, "Cache should have 2 projects")
        self.assertEqual(db._cached_projects_list[0]["name"], "apparently")

    @patch.object(db, "select")
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

    @patch.object(db, "select")
    def test_project_cache_expires(self, mock_select):
        """Cache is refreshed after TTL expires."""
        mock_select.return_value = [{"id": "proj-1", "name": "apparently"}]

        # Set cache as old (>300s)
        db._PROJECT_CACHE_TIME["at"] = time.time() - 400
        before = db._PROJECT_CACHE_TIME["at"]

        db._refresh_projects_cache()

        # This used to assert only `mock_select.called`, which stays true even if the
        # refresh threw the rows away or never re-stamped the clock — in which case every
        # subsequent call would re-query forever. Assert the refresh actually landed.
        self.assertTrue(mock_select.called, "Should query DB after TTL expired")
        self.assertEqual(db._cached_projects_list, mock_select.return_value,
                         "the refreshed rows must replace the stale cache")
        self.assertGreater(db._PROJECT_CACHE_TIME["at"], before,
                           "the TTL clock must be re-stamped, or the cache never holds")

    @patch.object(db, "select")
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

    @patch.object(db, "_queue_depth_estimate")
    def test_queue_depth_block_uses_estimate(self, mock_estimate):
        """_queue_depth_block should use estimation for fast rejection."""
        mock_estimate.return_value = (False, 100)  # Under ceiling

        row = {"slug": "test-task", "project_id": "proj-1"}
        result = db._queue_depth_block(row)

        self.assertFalse(result, "Should allow when under ceiling")
        mock_estimate.assert_called()
        self.assertEqual(mock_estimate.call_args.args[0], db._max_queue_depth(),
                         "the estimate must be taken against the configured ceiling")

    @patch.object(db, "_queue_depth_estimate")
    def test_queue_depth_block_refuses_when_over_ceiling(self, mock_estimate):
        """The allow path was tested and the refuse path was not — so nothing here ever
        exercised the decision the estimate exists to make. A non-exempt task must be
        blocked once the sampled depth reaches the ceiling."""
        ceiling = db._max_queue_depth()
        mock_estimate.return_value = (True, ceiling + 1)

        result = db._queue_depth_block({"slug": "test-task", "project_id": "proj-1"})

        self.assertTrue(result, "Should refuse a non-exempt insert at/over the ceiling")

    @patch.object(db, "_queue_depth_estimate")
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

    @patch.object(db, "_queue_depth_estimate")
    def test_queue_depth_block_operator_origin(self, mock_estimate):
        """Operator-origin tasks should never be blocked."""
        mock_estimate.return_value = (True, 1000)  # Over ceiling

        row = {"slug": "test", "submitted_by": "kalepasch1"}
        result = db._queue_depth_block(row)

        self.assertFalse(result, "Operator-origin tasks should be exempt")

    @patch.object(db, "_queue_depth_estimate")
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

        self.assertEqual(first_call_count, 1, "the first call must take a fresh sample")
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
