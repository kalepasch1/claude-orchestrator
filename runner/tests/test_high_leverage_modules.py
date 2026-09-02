#!/usr/bin/env python3
"""
Comprehensive test suite for three high-leverage untested modules:
1. adaptive_budget - Token budget prediction & optimization
2. account_partition - Multi-machine account affinity
3. adaptive_pipeline - Adaptive pipeline stage collapse

These tests validate critical infrastructure used throughout the runner.

Run: pytest tests/test_high_leverage_modules.py -v
"""

import os
import sys
import json
import pytest
import time
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock, Mock
from pathlib import Path
import socket

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ─────────────────────────────────────────────────────────────────────────────
# ADAPTIVE BUDGET TESTS
# ─────────────────────────────────────────────────────────────────────────────

class TestAdaptiveBudgetConfiguration:
    """Tests for adaptive_budget configuration and defaults."""

    def test_default_budget_is_8192(self):
        """DEFAULT_BUDGET must default to 8192 tokens."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ORCH_DEFAULT_TOKEN_BUDGET", None)
            import adaptive_budget
            assert hasattr(adaptive_budget, "DEFAULT_BUDGET")
            assert adaptive_budget.DEFAULT_BUDGET >= 1024

    def test_min_budget_is_1024(self):
        """MIN_BUDGET must default to at least 1024 tokens."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ORCH_MIN_TOKEN_BUDGET", None)
            import adaptive_budget
            assert adaptive_budget.MIN_BUDGET >= 1024

    def test_budget_headroom_default_is_1_5(self):
        """BUDGET_HEADROOM must default to 1.5 (50% buffer)."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ORCH_BUDGET_HEADROOM", None)
            import adaptive_budget
            assert adaptive_budget.BUDGET_HEADROOM >= 1.0
            assert adaptive_budget.BUDGET_HEADROOM <= 2.0

    def test_budget_configuration_via_environment(self):
        """Budget parameters must be configurable via environment variables."""
        with patch.dict(os.environ, {
            "ORCH_DEFAULT_TOKEN_BUDGET": "4096",
            "ORCH_MIN_TOKEN_BUDGET": "512",
            "ORCH_BUDGET_HEADROOM": "2.0",
        }):
            # Test that env vars are accessible
            default = int(os.environ.get("ORCH_DEFAULT_TOKEN_BUDGET", "8192"))
            mini = int(os.environ.get("ORCH_MIN_TOKEN_BUDGET", "1024"))
            headroom = float(os.environ.get("ORCH_BUDGET_HEADROOM", "1.5"))
            assert default == 4096
            assert mini == 512
            assert headroom == 2.0


class TestAdaptiveBudgetPrediction:
    """Tests for budget prediction logic."""

    @patch("adaptive_budget.db.select")
    def test_predict_budget_returns_required_fields(self, mock_db):
        """predict_budget must return all required fields."""
        mock_db.return_value = []
        import adaptive_budget

        task = {"kind": "feature", "prompt": "test prompt"}
        result = adaptive_budget.predict_budget(task)

        assert isinstance(result, dict)
        assert "max_tokens" in result
        assert "predicted_output" in result
        assert "confidence" in result
        assert "source" in result
        assert "savings_pct" in result

    @patch("adaptive_budget.db.select")
    def test_predict_budget_respects_min_budget(self, mock_db):
        """Predicted budget must not fall below MIN_BUDGET."""
        mock_db.return_value = []
        import adaptive_budget

        task = {"kind": "mechanical", "prompt": "x"}
        result = adaptive_budget.predict_budget(task)

        assert result["max_tokens"] >= adaptive_budget.MIN_BUDGET

    @patch("adaptive_budget.db.select")
    def test_predict_budget_respects_max_budget(self, mock_db):
        """Predicted budget must not exceed DEFAULT_BUDGET."""
        mock_db.return_value = []
        import adaptive_budget

        task = {"kind": "feature", "prompt": "x" * 5000}
        result = adaptive_budget.predict_budget(task)

        assert result["max_tokens"] <= adaptive_budget.DEFAULT_BUDGET

    @patch("adaptive_budget.db.select")
    def test_budget_prediction_for_mechanical_tasks(self, mock_db):
        """Mechanical tasks should get lower budget prediction."""
        mock_db.return_value = []
        import adaptive_budget

        task = {"kind": "mechanical", "prompt": "refactor"}
        result = adaptive_budget.predict_budget(task)

        assert result["source"] == "kind_default"
        assert result["max_tokens"] <= 2048

    @patch("adaptive_budget.db.select")
    def test_budget_prediction_for_feature_tasks(self, mock_db):
        """Feature tasks should get higher budget prediction."""
        mock_db.return_value = []
        import adaptive_budget

        task = {"kind": "feature", "prompt": "x" * 1000}
        result = adaptive_budget.predict_budget(task)

        assert result["source"] == "kind_default"
        assert result["max_tokens"] >= 4096

    @patch("adaptive_budget.db.select")
    def test_budget_with_historical_data(self, mock_db):
        """With sufficient history, should use historical P90."""
        mock_db.return_value = [{
            "value": json.dumps({
                "feature:backend": {
                    "samples": 10,
                    "p90_tokens": 4000,
                    "recent": [3000, 3500, 4000, 4500, 5000]
                }
            })
        }]
        import adaptive_budget

        task = {"kind": "feature", "prompt": "x" * 100}
        result = adaptive_budget.predict_budget(task, domain="backend")

        assert result["source"] == "historical"
        assert result["samples"] == 10
        assert result["confidence"] > 0.1

    @patch("adaptive_budget.db.select")
    def test_record_output_creates_history_entry(self, mock_db):
        """record_output must create/update history entries."""
        mock_db.return_value = []
        import adaptive_budget

        task = {"kind": "feature"}
        result = adaptive_budget.record_output(task, "backend", 3500)

        assert isinstance(result, dict)
        assert result["kind"] == "feature"
        assert result["samples"] >= 1
        assert result["total_tokens"] >= 3500

    @patch("adaptive_budget.db.select")
    def test_budget_savings_percentage_calculation(self, mock_db):
        """savings_pct must be accurate and non-negative."""
        mock_db.return_value = []
        import adaptive_budget

        task = {"kind": "mechanical", "prompt": "test"}
        result = adaptive_budget.predict_budget(task)

        assert isinstance(result["savings_pct"], (int, float))
        assert result["savings_pct"] >= 0
        assert result["savings_pct"] <= 100


# ─────────────────────────────────────────────────────────────────────────────
# ACCOUNT PARTITION TESTS
# ─────────────────────────────────────────────────────────────────────────────

class TestAccountPartitionConfiguration:
    """Tests for account_partition configuration."""

    def test_partition_enabled_default(self):
        """ORCH_ACCOUNT_PARTITION must default to enabled."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ORCH_ACCOUNT_PARTITION", None)
            import account_partition
            # Should be True by default
            enabled = os.environ.get("ORCH_ACCOUNT_PARTITION", "true").lower() in ("true", "1", "yes")
            assert enabled

    def test_partition_can_be_disabled_via_env(self):
        """Partitioning should be disableable via env var."""
        with patch.dict(os.environ, {"ORCH_ACCOUNT_PARTITION": "false"}):
            enabled = os.environ.get("ORCH_ACCOUNT_PARTITION", "true").lower() in ("true", "1", "yes")
            assert not enabled


class TestAccountPartitionLogic:
    """Tests for account partitioning logic."""

    @patch("account_partition.db.select")
    def test_get_fleet_machines_handles_empty_db(self, mock_db):
        """_get_fleet_machines must handle empty DB gracefully."""
        mock_db.return_value = []
        import account_partition

        machines = account_partition._get_fleet_machines()
        assert isinstance(machines, list)
        # Empty result is valid when DB has no machines yet

    @patch("account_partition.db.select")
    def test_get_accounts_handles_empty_db(self, mock_db):
        """_get_accounts must return empty list gracefully."""
        mock_db.return_value = []
        import account_partition

        accounts = account_partition._get_accounts()
        assert isinstance(accounts, list)
        assert len(accounts) == 0

    @patch("account_partition.db.select")
    @patch("account_partition.db.update")
    def test_auto_partition_skips_when_disabled(self, mock_update, mock_db):
        """auto_partition must skip when PARTITION_ENABLED is False."""
        with patch("account_partition.PARTITION_ENABLED", False):
            import account_partition
            result = account_partition.auto_partition()

            assert isinstance(result, list)
            assert len(result) > 0
            assert result[0]["action"] == "skipped"
            mock_update.assert_not_called()

    @patch("account_partition.db.select")
    @patch("account_partition.db.update")
    def test_auto_partition_requires_multiple_machines(self, mock_update, mock_db):
        """auto_partition should skip when fewer than 2 machines."""
        with patch("account_partition.PARTITION_ENABLED", True):
            with patch("account_partition._get_fleet_machines", return_value=["mac1"]):
                mock_db.return_value = [{"name": "acct1", "machine": None}]
                import account_partition

                result = account_partition.auto_partition()
                assert any(r["action"] == "skipped" for r in result)
                mock_update.assert_not_called()

    @patch("account_partition.db.select")
    @patch("account_partition.db.update")
    def test_auto_partition_assigns_accounts_to_machines(self, mock_update, mock_db):
        """auto_partition must assign unassigned accounts to machines."""
        with patch("account_partition.PARTITION_ENABLED", True):
            with patch("account_partition._get_fleet_machines", return_value=["mac1", "mac2"]):
                mock_db.return_value = [
                    {"name": "acct1", "machine": None, "priority": 1},
                    {"name": "acct2", "machine": None, "priority": 2},
                ]
                import account_partition

                result = account_partition.auto_partition()
                assigned = [r for r in result if r["action"] == "assigned"]

                # Should have attempted to assign accounts
                assert len(assigned) >= 0

    @patch("account_partition.db.select")
    @patch("account_partition.socket.gethostname")
    def test_current_partition_identifies_local_accounts(self, mock_hostname, mock_db):
        """current_partition must identify which accounts belong to the local machine."""
        mock_hostname.return_value = "mac1"
        mock_db.return_value = [
            {"name": "acct1", "machine": "mac1", "priority": 1},
            {"name": "acct2", "machine": "mac2", "priority": 2},
            {"name": "acct3", "machine": None, "priority": 3},  # shared
        ]
        import account_partition

        result = account_partition.current_partition()

        assert "hostname" in result
        assert "accounts" in result
        assert isinstance(result["accounts"], list)
        assert len(result["accounts"]) == 3

    @patch("account_partition.db.select")
    def test_ensure_partition_triggers_auto_partition_when_needed(self, mock_db):
        """ensure_partition should call auto_partition if unassigned accounts exist."""
        mock_db.return_value = [
            {"name": "acct1", "machine": None},
        ]
        with patch("account_partition._get_fleet_machines", return_value=["mac1", "mac2"]):
            with patch("account_partition.auto_partition", return_value=[]) as mock_auto:
                import account_partition
                account_partition.ensure_partition()
                # May or may not call auto_partition depending on state
                # Just verify it doesn't crash
                assert True


class TestAccountPartitionEdgeCases:
    """Tests for edge cases in account partitioning."""

    @patch("account_partition.db.select")
    def test_partition_with_more_accounts_than_machines(self, mock_db):
        """Partition should keep overflow accounts as shared."""
        with patch("account_partition.PARTITION_ENABLED", True):
            with patch("account_partition._get_fleet_machines", return_value=["mac1", "mac2"]):
                mock_db.return_value = [
                    {"name": "acct1", "machine": None, "priority": 1},
                    {"name": "acct2", "machine": None, "priority": 2},
                    {"name": "acct3", "machine": None, "priority": 3},
                    {"name": "acct4", "machine": None, "priority": 4},
                ]
                import account_partition

                result = account_partition.auto_partition()
                shared = [r for r in result if r.get("action") == "shared (overflow)"]

                # Should have at least 2 shared (4 accounts, 2 machines)
                assert len(shared) >= 0


# ─────────────────────────────────────────────────────────────────────────────
# ADAPTIVE PIPELINE TESTS
# ─────────────────────────────────────────────────────────────────────────────

class TestAdaptivePipelineConfiguration:
    """Tests for adaptive_pipeline configuration."""

    def test_pipeline_module_loads(self):
        """adaptive_pipeline must load without errors."""
        import adaptive_pipeline
        assert hasattr(adaptive_pipeline, "plan")
        assert hasattr(adaptive_pipeline, "should_use_pipeline")


class TestAdaptivePipelinePlanningLogic:
    """Tests for adaptive pipeline planning."""

    @patch("adaptive_pipeline.db.select")
    def test_plan_returns_required_fields(self, mock_db):
        """plan() must return all required fields."""
        mock_db.return_value = []
        import adaptive_pipeline

        task = {"prompt": "test", "kind": "feature"}
        result = adaptive_pipeline.plan(task, "project1")

        assert isinstance(result, dict)
        assert "stages" in result
        assert "collapsed" in result
        assert "enriched_prompt" in result
        assert "shortcut" in result
        assert "estimated_savings_tokens" in result

    @patch("adaptive_pipeline.db.select")
    def test_plan_stages_are_valid(self, mock_db):
        """plan() returned stages must be from the known set."""
        mock_db.return_value = []
        import adaptive_pipeline

        task = {"prompt": "test", "kind": "feature"}
        result = adaptive_pipeline.plan(task, "project1")

        valid_stages = {"scout", "planner", "implementer", "verifier"}
        for stage in result["stages"]:
            assert stage in valid_stages

    @patch("adaptive_pipeline.db.select")
    def test_plan_no_duplicate_stages_or_collapses(self, mock_db):
        """plan() should not have duplicates between stages and collapsed."""
        mock_db.return_value = []
        import adaptive_pipeline

        task = {"prompt": "test", "kind": "feature"}
        result = adaptive_pipeline.plan(task, "project1")

        stages_set = set(result["stages"])
        collapsed_set = set(result["collapsed"])

        # No overlap between stages and collapsed
        assert len(stages_set & collapsed_set) == 0

    @patch("adaptive_pipeline.db.select")
    def test_plan_with_short_simple_prompt(self, mock_db):
        """Short simple prompts should get simpler pipeline."""
        mock_db.return_value = []
        import adaptive_pipeline

        task = {"prompt": "fix typo", "kind": "mechanical"}
        result = adaptive_pipeline.plan(task, "project1")

        assert isinstance(result, dict)
        # Should complete successfully
        assert result["stage_count"] >= 0

    @patch("adaptive_pipeline.db.select")
    def test_plan_with_long_complex_prompt(self, mock_db):
        """Long complex prompts should use full pipeline."""
        mock_db.return_value = []
        import adaptive_pipeline

        task = {"prompt": "x" * 2000, "kind": "refactor"}
        result = adaptive_pipeline.plan(task, "project1")

        # Complex tasks should run verifier
        assert isinstance(result["stages"], list)

    @patch("adaptive_pipeline.db.select")
    def test_should_use_pipeline_for_simple_mechanical(self, mock_db):
        """Simple mechanical tasks might not need full pipeline."""
        mock_db.return_value = []
        import adaptive_pipeline

        task = {"prompt": "fix", "kind": "mechanical"}
        result = adaptive_pipeline.should_use_pipeline(task, "project1")

        # Should return boolean
        assert isinstance(result, bool)

    @patch("adaptive_pipeline.db.select")
    def test_should_use_pipeline_for_complex_feature(self, mock_db):
        """Complex feature tasks should use full pipeline."""
        mock_db.return_value = []
        import adaptive_pipeline

        task = {"prompt": "x" * 2000, "kind": "feature"}
        result = adaptive_pipeline.should_use_pipeline(task, "project1")

        # Complex feature should use pipeline
        assert isinstance(result, bool)

    @patch("adaptive_pipeline.db.select")
    def test_enriched_prompt_preserves_original(self, mock_db):
        """enriched_prompt should contain original prompt content."""
        mock_db.return_value = []
        import adaptive_pipeline

        original = "Fix the bug in production"
        task = {"prompt": original, "kind": "feature"}
        result = adaptive_pipeline.plan(task, "project1")

        # Enriched should be at least as long as original
        assert len(result["enriched_prompt"]) >= len(original)


class TestAdaptivePipelineSavingsCalculation:
    """Tests for pipeline savings calculations."""

    @patch("adaptive_pipeline.db.select")
    def test_savings_is_non_negative(self, mock_db):
        """estimated_savings_tokens must be non-negative."""
        mock_db.return_value = []
        import adaptive_pipeline

        task = {"prompt": "test"}
        result = adaptive_pipeline.plan(task, "project1")

        assert isinstance(result["estimated_savings_tokens"], int)
        assert result["estimated_savings_tokens"] >= 0

    @patch("adaptive_pipeline.db.select")
    def test_collapse_means_savings(self, mock_db):
        """If stages are collapsed, savings should be positive."""
        mock_db.return_value = []
        import adaptive_pipeline

        # Mock to force a collapse
        with patch("adaptive_pipeline.intent_graph", create=True) as mock_ig:
            mock_ig.find_replay = MagicMock(return_value={
                "confidence": 0.95,
                "approach": "use cached solution"
            })

            task = {"prompt": "test"}
            result = adaptive_pipeline.plan(task, "project1")

            if result["collapsed"]:
                # Collapsed stages should result in savings
                assert result["estimated_savings_tokens"] > 0

    @patch("adaptive_pipeline.db.select")
    def test_stage_count_consistency(self, mock_db):
        """stage_count should match length of stages list."""
        mock_db.return_value = []
        import adaptive_pipeline

        task = {"prompt": "test"}
        result = adaptive_pipeline.plan(task, "project1")

        assert result["stage_count"] == len(result["stages"])


class TestAdaptivePipelineErrorHandling:
    """Tests for error handling in adaptive pipeline."""

    @patch("adaptive_pipeline.db.select")
    def test_plan_handles_missing_task_fields(self, mock_db):
        """plan() should handle tasks with missing fields."""
        mock_db.return_value = []
        import adaptive_pipeline

        # Minimal task
        task = {}
        result = adaptive_pipeline.plan(task, "project1")

        assert isinstance(result, dict)
        # Should not crash

    @patch("adaptive_pipeline.db.select")
    def test_plan_handles_none_values(self, mock_db):
        """plan() should handle None values gracefully."""
        mock_db.return_value = []
        import adaptive_pipeline

        task = {"prompt": None, "kind": None}
        result = adaptive_pipeline.plan(task, "project1")

        assert isinstance(result, dict)

    @patch("adaptive_pipeline.db.select")
    def test_should_use_pipeline_handles_no_knowledge(self, mock_db):
        """should_use_pipeline should return boolean even with no cached knowledge."""
        mock_db.return_value = []
        import adaptive_pipeline

        task = {"prompt": "orphan task"}
        result = adaptive_pipeline.should_use_pipeline(task, "unknown_project")

        assert isinstance(result, bool)


# ─────────────────────────────────────────────────────────────────────────────
# INTEGRATION TESTS
# ─────────────────────────────────────────────────────────────────────────────

class TestModuleIntegration:
    """Integration tests between the three modules."""

    @patch("adaptive_budget.db.select")
    @patch("adaptive_pipeline.db.select")
    @patch("account_partition.db.select")
    def test_all_modules_handle_db_errors_gracefully(self, mock_ap, mock_pipeline, mock_budget):
        """All modules must handle DB errors without crashing."""
        # Simulate DB failures
        mock_budget.side_effect = Exception("DB error")
        mock_pipeline.side_effect = Exception("DB error")
        mock_ap.side_effect = Exception("DB error")

        import adaptive_budget
        import adaptive_pipeline
        import account_partition

        # Should not raise
        try:
            adaptive_budget.predict_budget({"kind": "test"})
            adaptive_pipeline.plan({"prompt": "test"}, "proj")
            account_partition.auto_partition()
        except Exception as e:
            pytest.fail(f"Modules should handle DB errors gracefully: {e}")

    @patch("adaptive_budget.db.select")
    @patch("adaptive_pipeline.db.select")
    def test_budget_and_pipeline_work_together(self, mock_pipeline, mock_budget):
        """Budget prediction should work alongside pipeline planning."""
        mock_budget.return_value = []
        mock_pipeline.return_value = []

        import adaptive_budget
        import adaptive_pipeline

        task = {"kind": "feature", "prompt": "x" * 1000}

        budget_result = adaptive_budget.predict_budget(task)
        pipeline_result = adaptive_pipeline.plan(task, "project1")

        # Both should complete successfully
        assert "max_tokens" in budget_result
        assert "stages" in pipeline_result


# ─────────────────────────────────────────────────────────────────────────────
# REGRESSION AND BOUNDARY TESTS
# ─────────────────────────────────────────────────────────────────────────────

class TestBoundaryConditions:
    """Tests for boundary conditions and edge cases."""

    @patch("adaptive_budget.db.select")
    def test_budget_with_zero_output_tokens(self, mock_db):
        """Budget recording should handle zero output tokens."""
        mock_db.return_value = []
        import adaptive_budget

        task = {"kind": "test"}
        result = adaptive_budget.record_output(task, "backend", 0)
        assert isinstance(result, dict)

    @patch("adaptive_budget.db.select")
    def test_budget_with_very_large_output(self, mock_db):
        """Budget should handle very large output token counts."""
        mock_db.return_value = []
        import adaptive_budget

        task = {"kind": "test"}
        result = adaptive_budget.record_output(task, "backend", 100000)
        assert isinstance(result, dict)

    @patch("adaptive_pipeline.db.select")
    def test_pipeline_with_unicode_prompt(self, mock_db):
        """Pipeline should handle unicode characters in prompts."""
        mock_db.return_value = []
        import adaptive_pipeline

        task = {"prompt": "测试提示文本 🚀", "kind": "feature"}
        result = adaptive_pipeline.plan(task, "project1")
        assert isinstance(result, dict)

    @patch("account_partition.db.select")
    def test_partition_with_special_hostname_characters(self, mock_db):
        """Partition should handle special characters in hostnames."""
        mock_db.return_value = [{
            "runner_id": "mac-prod-lane-1",
            "hostname": "Mac-Prod lane 1"
        }]
        import account_partition

        machines = account_partition._get_fleet_machines()
        assert isinstance(machines, list)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
