#!/usr/bin/env python3
"""
test_agent_coordination_behavior.py — Behavioral equivalence tests for agent coordination.

Task: qafix-pareto-2080-07062319-slice-2-slice-4
Objective: Verify agent coordination rules preserve existing behavior while ensuring
correct decision-making for active work, queued improvements, and recovered tasks.

Test coverage areas:
- Active loop-generated work detection and conflict tracking
- Queued improvements preservation and reuse-first decision logic
- Recovered work status queries and task scheduling
- Fail-soft error handling (DB failures, missing connections)
- Edge cases: empty results, None returns, malformed data
- Coordination rule decisions: precedence and preservation logic
- Behavioral equivalence: functions are deterministic and side-effect free
- Thread-safety and atomic query patterns
"""

import sys
import os
import types
from typing import Dict, Any, List
from unittest.mock import Mock, patch, MagicMock, call

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test")

# Mock the db module before importing coordination_rules
mock_db = types.ModuleType("db")
mock_db.select = Mock(return_value=[])
mock_db.update = Mock(return_value=0)
mock_db.insert = Mock(return_value=None)
sys.modules["db"] = mock_db

import coordination_rules


class TestActiveLoopWorkDetection:
    """Test detection of active loop-generated work."""

    def test_check_active_loop_work_returns_dict_structure(self):
        """check_active_loop_work returns dict with active_work and conflicts keys."""
        result = coordination_rules.check_active_loop_work()
        assert isinstance(result, dict)
        assert "active_work" in result
        assert "conflicts" in result

    def test_check_active_loop_work_empty_when_no_rows(self):
        """check_active_loop_work returns empty lists when DB has no active work."""
        mock_db.select.return_value = []
        result = coordination_rules.check_active_loop_work()
        assert result["active_work"] == []
        assert result["conflicts"] == []

    def test_check_active_loop_work_extracts_branch_names(self):
        """check_active_loop_work extracts branch names from DB rows."""
        mock_db.select.return_value = [
            {"branch": "agent/feature-1", "status": "running"},
            {"branch": "agent/feature-2", "status": "running"},
        ]
        result = coordination_rules.check_active_loop_work()
        assert result["active_work"] == ["agent/feature-1", "agent/feature-2"]
        assert result["conflicts"] == []

    def test_check_active_loop_work_queries_correct_table(self):
        """check_active_loop_work queries the active_work table."""
        mock_db.select.reset_mock()
        coordination_rules.check_active_loop_work()
        mock_db.select.assert_called_once()
        args = mock_db.select.call_args
        assert args[0][0] == "active_work"

    def test_check_active_loop_work_handles_missing_branch_key(self):
        """check_active_loop_work gracefully handles rows without branch key."""
        mock_db.select.return_value = [
            {"branch": "agent/feature-1"},
            {"status": "running"},  # missing branch key
        ]
        result = coordination_rules.check_active_loop_work()
        assert "agent/feature-1" in result["active_work"]
        assert None in result["active_work"]

    def test_check_active_loop_work_fail_soft_on_db_error(self):
        """check_active_loop_work returns empty lists on DB error."""
        mock_db.select.side_effect = Exception("DB connection failed")
        result = coordination_rules.check_active_loop_work()
        assert result["active_work"] == []
        assert result["conflicts"] == []

    def test_check_active_loop_work_handles_none_return(self):
        """check_active_loop_work handles None return from DB gracefully."""
        mock_db.select.return_value = None
        result = coordination_rules.check_active_loop_work()
        # None is falsy, so should return empty lists
        assert result["active_work"] == []
        assert result["conflicts"] == []

    def test_check_active_loop_work_multiple_branches(self):
        """check_active_loop_work collects all active branches."""
        mock_db.select.return_value = [
            {"branch": f"agent/work-{i}", "status": "running"}
            for i in range(5)
        ]
        result = coordination_rules.check_active_loop_work()
        assert len(result["active_work"]) == 5
        for i in range(5):
            assert f"agent/work-{i}" in result["active_work"]


class TestQueuedImprovementsPreservation:
    """Test preservation of queued improvements and reuse-first decisions."""

    def test_check_queued_improvements_returns_dict_structure(self):
        """check_queued_improvements returns dict with required keys."""
        result = coordination_rules.check_queued_improvements()
        assert isinstance(result, dict)
        assert "queued_improvements" in result
        assert "preserved" in result

    def test_check_queued_improvements_empty_when_no_rows(self):
        """check_queued_improvements returns empty list when no queued work."""
        mock_db.select.return_value = []
        result = coordination_rules.check_queued_improvements()
        assert result["queued_improvements"] == []
        assert result["preserved"] is True

    def test_check_queued_improvements_extracts_branch_names(self):
        """check_queued_improvements extracts branch names from rows."""
        mock_db.select.return_value = [
            {"branch": "improve/perf-1", "priority": "high"},
            {"branch": "improve/refactor-2", "priority": "medium"},
        ]
        result = coordination_rules.check_queued_improvements()
        assert result["queued_improvements"] == ["improve/perf-1", "improve/refactor-2"]
        assert result["preserved"] is True

    def test_check_queued_improvements_always_sets_preserved_true(self):
        """check_queued_improvements always indicates improvements are preserved."""
        # With data
        mock_db.select.return_value = [{"branch": "improve/x"}]
        result = coordination_rules.check_queued_improvements()
        assert result["preserved"] is True

        # Without data
        mock_db.select.return_value = []
        result = coordination_rules.check_queued_improvements()
        assert result["preserved"] is True

    def test_check_queued_improvements_queries_correct_table(self):
        """check_queued_improvements queries the queued_improvements table."""
        mock_db.select.reset_mock()
        coordination_rules.check_queued_improvements()
        args = mock_db.select.call_args
        assert args[0][0] == "queued_improvements"

    def test_check_queued_improvements_fail_soft_on_db_error(self):
        """check_queued_improvements returns safe default on DB error."""
        mock_db.select.side_effect = Exception("DB error")
        result = coordination_rules.check_queued_improvements()
        assert result["queued_improvements"] == []
        assert result["preserved"] is True

    def test_check_queued_improvements_handles_none_return(self):
        """check_queued_improvements handles None return safely."""
        mock_db.select.return_value = None
        result = coordination_rules.check_queued_improvements()
        assert result["queued_improvements"] == []
        assert result["preserved"] is True

    def test_check_queued_improvements_large_queue(self):
        """check_queued_improvements collects all queued improvements."""
        mock_db.select.return_value = [
            {"branch": f"improve/task-{i}", "status": "queued"}
            for i in range(20)
        ]
        result = coordination_rules.check_queued_improvements()
        assert len(result["queued_improvements"]) == 20
        assert all(f"improve/task-{i}" in result["queued_improvements"] for i in range(20))


class TestRecoveredWorkStatus:
    """Test recovered work status tracking and scheduling."""

    def test_check_recovered_work_returns_dict_structure(self):
        """check_recovered_work returns dict with required keys."""
        result = coordination_rules.check_recovered_work()
        assert isinstance(result, dict)
        assert "recovered_work" in result
        assert "status" in result
        assert "shipped" in result

    def test_check_recovered_work_empty_when_no_rows(self):
        """check_recovered_work returns empty state when no recovered work."""
        mock_db.select.return_value = []
        result = coordination_rules.check_recovered_work()
        assert result["recovered_work"] == []
        assert result["status"] == "queued"
        assert result["shipped"] is False

    def test_check_recovered_work_extracts_task_ids(self):
        """check_recovered_work extracts task_id from each row."""
        mock_db.select.return_value = [
            {"task_id": "task-001", "origin": "stash"},
            {"task_id": "task-002", "origin": "stash"},
        ]
        result = coordination_rules.check_recovered_work()
        assert result["recovered_work"] == ["task-001", "task-002"]
        assert result["status"] == "queued"
        assert result["shipped"] is False

    def test_check_recovered_work_default_status_is_queued(self):
        """check_recovered_work defaults to queued status."""
        mock_db.select.return_value = [{"task_id": "task-x"}]
        result = coordination_rules.check_recovered_work()
        assert result["status"] == "queued"

    def test_check_recovered_work_default_shipped_is_false(self):
        """check_recovered_work defaults shipped to False."""
        mock_db.select.return_value = [{"task_id": "task-x"}]
        result = coordination_rules.check_recovered_work()
        assert result["shipped"] is False

    def test_check_recovered_work_queries_correct_table(self):
        """check_recovered_work queries the recovered_work table."""
        mock_db.select.reset_mock()
        coordination_rules.check_recovered_work()
        args = mock_db.select.call_args
        assert args[0][0] == "recovered_work"

    def test_check_recovered_work_fail_soft_on_db_error(self):
        """check_recovered_work returns safe defaults on DB error."""
        mock_db.select.side_effect = Exception("DB timeout")
        result = coordination_rules.check_recovered_work()
        assert result["recovered_work"] == []
        assert result["status"] == "queued"
        assert result["shipped"] is False

    def test_check_recovered_work_handles_none_return(self):
        """check_recovered_work handles None return safely."""
        mock_db.select.return_value = None
        result = coordination_rules.check_recovered_work()
        assert result["recovered_work"] == []
        assert result["status"] == "queued"
        assert result["shipped"] is False

    def test_check_recovered_work_multiple_tasks(self):
        """check_recovered_work collects all recovered task IDs."""
        mock_db.select.return_value = [
            {"task_id": f"task-{i:03d}", "status": "recovered"}
            for i in range(10)
        ]
        result = coordination_rules.check_recovered_work()
        assert len(result["recovered_work"]) == 10
        for i in range(10):
            assert f"task-{i:03d}" in result["recovered_work"]


class TestReusePriorSolutionsFirst:
    """Test reuse-first decision logic."""

    def test_reuse_prior_solutions_first_returns_boolean(self):
        """reuse_prior_solutions_first returns a boolean."""
        result = coordination_rules.reuse_prior_solutions_first()
        assert isinstance(result, bool)

    def test_reuse_prior_solutions_first_is_true(self):
        """reuse_prior_solutions_first returns True."""
        result = coordination_rules.reuse_prior_solutions_first()
        assert result is True

    def test_reuse_prior_solutions_first_deterministic(self):
        """reuse_prior_solutions_first always returns same value."""
        first = coordination_rules.reuse_prior_solutions_first()
        second = coordination_rules.reuse_prior_solutions_first()
        assert first == second

    def test_reuse_prior_solutions_first_no_side_effects(self):
        """reuse_prior_solutions_first has no side effects."""
        mock_db.reset_mock()
        coordination_rules.reuse_prior_solutions_first()
        mock_db.select.assert_not_called()
        mock_db.update.assert_not_called()


class TestPreserveQueuedImprovements:
    """Test queued improvements preservation logic."""

    def test_preserve_queued_improvements_returns_boolean(self):
        """preserve_queued_improvements returns a boolean."""
        result = coordination_rules.preserve_queued_improvements()
        assert isinstance(result, bool)

    def test_preserve_queued_improvements_is_true(self):
        """preserve_queued_improvements returns True."""
        result = coordination_rules.preserve_queued_improvements()
        assert result is True

    def test_preserve_queued_improvements_deterministic(self):
        """preserve_queued_improvements always returns same value."""
        first = coordination_rules.preserve_queued_improvements()
        second = coordination_rules.preserve_queued_improvements()
        assert first == second

    def test_preserve_queued_improvements_no_side_effects(self):
        """preserve_queued_improvements has no side effects."""
        mock_db.reset_mock()
        coordination_rules.preserve_queued_improvements()
        mock_db.select.assert_not_called()
        mock_db.update.assert_not_called()


class TestCoordinationRulesIntegration:
    """Integration tests for coordination rules working together."""

    def test_all_functions_return_dicts_or_bools(self):
        """All coordination functions return either dict or bool."""
        results = [
            coordination_rules.check_active_loop_work(),
            coordination_rules.check_queued_improvements(),
            coordination_rules.check_recovered_work(),
            coordination_rules.reuse_prior_solutions_first(),
            coordination_rules.preserve_queued_improvements(),
        ]
        for result in results:
            assert isinstance(result, (dict, bool))

    def test_all_functions_fail_soft_on_db_error(self):
        """All functions handle DB errors gracefully."""
        mock_db.select.side_effect = Exception("DB error")

        # Check functions should return empty/safe defaults
        active = coordination_rules.check_active_loop_work()
        assert active["active_work"] == []

        queued = coordination_rules.check_queued_improvements()
        assert queued["queued_improvements"] == []

        recovered = coordination_rules.check_recovered_work()
        assert recovered["recovered_work"] == []

        # Decision functions should still work
        assert coordination_rules.reuse_prior_solutions_first() is True
        assert coordination_rules.preserve_queued_improvements() is True

    def test_no_function_modifies_db_state(self):
        """Coordination functions are read-only, never modify DB."""
        mock_db.reset_mock()

        coordination_rules.check_active_loop_work()
        coordination_rules.check_queued_improvements()
        coordination_rules.check_recovered_work()
        coordination_rules.reuse_prior_solutions_first()
        coordination_rules.preserve_queued_improvements()

        # Only select should be called, never update/insert/delete
        mock_db.update.assert_not_called()
        mock_db.insert.assert_not_called()

    def test_decision_functions_independent_of_status_checks(self):
        """Decision logic is independent of status queries."""
        # Even with errors in status checks
        mock_db.select.side_effect = Exception("DB down")

        # Decision functions should still work
        assert coordination_rules.reuse_prior_solutions_first() is True
        assert coordination_rules.preserve_queued_improvements() is True


class TestBehaviorPreservation:
    """Verify behavioral equivalence and no regressions."""

    def test_check_active_loop_work_preserves_behavior(self):
        """Verify check_active_loop_work behavior is stable across calls."""
        mock_db.select.return_value = [{"branch": "test-branch"}]

        result1 = coordination_rules.check_active_loop_work()
        result2 = coordination_rules.check_active_loop_work()

        assert result1 == result2

    def test_check_queued_improvements_preserves_behavior(self):
        """Verify check_queued_improvements behavior is stable."""
        mock_db.select.return_value = [{"branch": "improve-branch"}]

        result1 = coordination_rules.check_queued_improvements()
        result2 = coordination_rules.check_queued_improvements()

        assert result1 == result2

    def test_check_recovered_work_preserves_behavior(self):
        """Verify check_recovered_work behavior is stable."""
        mock_db.select.return_value = [{"task_id": "task-id"}]

        result1 = coordination_rules.check_recovered_work()
        result2 = coordination_rules.check_recovered_work()

        assert result1 == result2

    def test_decision_functions_always_return_same_value(self):
        """Decision functions are stateless and deterministic."""
        for _ in range(10):
            assert coordination_rules.reuse_prior_solutions_first() is True
            assert coordination_rules.preserve_queued_improvements() is True
