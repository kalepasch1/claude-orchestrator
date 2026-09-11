"""Acceptance tests for counterfactual replay runner.

Tests the core re_run_cached_decisions() function with scenarios:
- Identical model/data (expect changed=False)
- Updated model (expect ≥1 changed=True)
- Empty cache (expect graceful no-op)
"""

import pytest
from src.orchestrator.runners.counterfactual import (
    re_run_cached_decisions,
    ModelConfig,
    DataConfig,
)
from src.orchestrator.policies import DefaultPolicy, DecisionContext, PolicyDecision
from src.orchestrator.runners.replay_runner import ReplayRecord


class TestReRunCachedDecisions:
    """Tests for re_run_cached_decisions() function."""

    def test_empty_cache_returns_empty_list(self, monkeypatch):
        """Re-running with empty cache returns graceful no-op."""
        def mock_load_history(self, limit=10, days_back=7):
            self.records = []
            return 0

        monkeypatch.setattr(
            "src.orchestrator.runners.replay_runner.ReplayRunner.load_history",
            mock_load_history
        )

        models = ModelConfig(model_id="test-model-v1")
        data = DataConfig()
        result = re_run_cached_decisions([], models, data)

        assert result == []
        assert isinstance(result, list)

    def test_identical_model_returns_no_changes(self, monkeypatch):
        """Re-running with identical model/data returns changed=False."""
        def mock_load_history(self, limit=10, days_back=7):
            self.records = [
                ReplayRecord(
                    task_id="task-001",
                    past_decision="route-a",
                    past_policy="default_roundrobin",
                    task_data={"project_id": "proj1"},
                    available_routes=["route-a", "route-b"],
                    recorded_at="2026-01-01T00:00:00",
                ),
            ]
            return 1

        def mock_run_replay(self):
            # Simulate replay with same decision
            from src.orchestrator.runners.replay_runner import DivergenceReport
            return [
                DivergenceReport(
                    task_id="task-001",
                    diverged=False,
                    past_decision="route-a",
                    current_decision="route-a",
                    past_policy="default_roundrobin",
                    current_policy="default_roundrobin",
                    confidence_shift=0.0,
                    reason="Decision stable",
                    timestamp="2026-01-01T00:00:01",
                ),
            ]

        monkeypatch.setattr(
            "src.orchestrator.runners.replay_runner.ReplayRunner.load_history",
            mock_load_history
        )
        monkeypatch.setattr(
            "src.orchestrator.runners.replay_runner.ReplayRunner.run_replay",
            mock_run_replay
        )

        models = ModelConfig(model_id="test-model-v1")
        data = DataConfig()
        result = re_run_cached_decisions(["task-001"], models, data)

        assert len(result) == 1
        assert result[0].diverged is False
        assert result[0].past_decision == "route-a"
        assert result[0].current_decision == "route-a"

    def test_updated_model_detects_changed_decision(self, monkeypatch):
        """Re-running with updated model detects changed decisions."""
        def mock_load_history(self, limit=10, days_back=7):
            self.records = [
                ReplayRecord(
                    task_id="task-002",
                    past_decision="route-a",
                    past_policy="default_roundrobin",
                    task_data={"project_id": "proj2"},
                    available_routes=["route-a", "route-b", "route-c"],
                    recorded_at="2026-01-01T00:00:00",
                ),
            ]
            return 1

        def mock_run_replay(self):
            # Simulate replay with different decision
            from src.orchestrator.runners.replay_runner import DivergenceReport
            return [
                DivergenceReport(
                    task_id="task-002",
                    diverged=True,
                    past_decision="route-a",
                    current_decision="route-b",
                    past_policy="default_roundrobin",
                    current_policy="default_roundrobin",
                    confidence_shift=0.1,
                    reason="Model version changed route from route-a to route-b",
                    timestamp="2026-01-01T00:00:01",
                ),
            ]

        monkeypatch.setattr(
            "src.orchestrator.runners.replay_runner.ReplayRunner.load_history",
            mock_load_history
        )
        monkeypatch.setattr(
            "src.orchestrator.runners.replay_runner.ReplayRunner.run_replay",
            mock_run_replay
        )

        models = ModelConfig(model_id="test-model-v2")
        data = DataConfig()
        result = re_run_cached_decisions(["task-002"], models, data)

        assert len(result) == 1
        assert result[0].diverged is True
        assert result[0].past_decision == "route-a"
        assert result[0].current_decision == "route-b"
        assert result[0].confidence_shift > 0

    def test_model_config_requires_model_id(self):
        """ModelConfig raises ValueError if model_id is missing."""
        with pytest.raises(ValueError, match="model_id is required"):
            ModelConfig(model_id="")

    def test_returns_divergence_report_objects(self, monkeypatch):
        """Function returns proper DivergenceReport objects."""
        def mock_load_history(self, limit=10, days_back=7):
            self.records = [
                ReplayRecord(
                    task_id="task-003",
                    past_decision="route-x",
                    past_policy="affinity_based",
                    task_data={"project_id": "proj3"},
                    available_routes=["route-x", "route-y"],
                    recorded_at="2026-01-01T00:00:00",
                ),
            ]
            return 1

        def mock_run_replay(self):
            from src.orchestrator.runners.replay_runner import DivergenceReport
            return [
                DivergenceReport(
                    task_id="task-003",
                    diverged=False,
                    past_decision="route-x",
                    current_decision="route-x",
                    past_policy="affinity_based",
                    current_policy="affinity_based",
                    confidence_shift=0.0,
                    reason="Decision stable",
                    timestamp="2026-01-01T00:00:01",
                ),
            ]

        monkeypatch.setattr(
            "src.orchestrator.runners.replay_runner.ReplayRunner.load_history",
            mock_load_history
        )
        monkeypatch.setattr(
            "src.orchestrator.runners.replay_runner.ReplayRunner.run_replay",
            mock_run_replay
        )

        models = ModelConfig(model_id="test-model")
        data = DataConfig()
        result = re_run_cached_decisions([], models, data)

        assert len(result) == 1
        report = result[0]
        assert hasattr(report, "task_id")
        assert hasattr(report, "diverged")
        assert hasattr(report, "past_decision")
        assert hasattr(report, "current_decision")
        assert hasattr(report, "timestamp")
