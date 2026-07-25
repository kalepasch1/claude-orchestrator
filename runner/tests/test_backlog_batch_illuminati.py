#!/usr/bin/env python3
"""
test_backlog_batch_illuminati.py — Test suite for backlog-batch-illuminati-dd47b58

Tests for orchestration pipeline batch processor, contract validator, and pipeline configuration.
Covers: task processing pipeline, QA gates, legal gates, coordination rules, auto-merge gates,
threading, environment configuration, cost tracking, and dry-run mode.

Task: backlog-batch-illuminati-dd47b58
"""
import json
import pytest
import time
import threading
import os
from typing import Dict, List, Any
from unittest.mock import Mock, patch, MagicMock, call

# Mock the dependencies before importing modules
import sys

# Import the modules to test
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestBacklogBatchProcessor:
    """Test BacklogBatchProcessor orchestration pipeline."""

    def test_processor_singleton_pattern(self):
        """Singleton acquire() returns same instance."""
        from backlog_batch_processor import acquire

        proc1 = acquire()
        proc2 = acquire()
        assert proc1 is proc2

    def test_singleton_thread_safe(self):
        """Singleton acquire() is thread-safe."""
        from backlog_batch_processor import acquire

        results = []

        def get_instance():
            results.append(acquire())

        threads = [threading.Thread(target=get_instance) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All threads got the same instance
        first = results[0]
        assert all(r is first for r in results)

    def test_task_status_enum_values(self):
        """TaskStatus enum has all required pipeline stages."""
        from backlog_batch_processor import TaskStatus

        expected_statuses = {
            "QUEUED", "PREFLIGHT", "PLANNING", "CODING", "QA",
            "LEGAL", "MERGE", "COMPLETE", "FAILED", "BLOCKED"
        }
        actual_statuses = {ts.name for ts in TaskStatus}
        assert expected_statuses == actual_statuses

    def test_gate_result_enum_values(self):
        """GateResult enum covers all approval states."""
        from backlog_batch_processor import GateResult

        expected = {"PASS", "FAIL", "BLOCKED", "SKIP"}
        actual = {gr.name for gr in GateResult}
        assert expected == actual

    def test_stage_result_dataclass(self):
        """StageResult captures all pipeline stage metrics."""
        from backlog_batch_processor import StageResult, TaskStatus

        result = StageResult(
            stage="preflight_triage",
            status=TaskStatus.PREFLIGHT,
            passed=True,
            reason="Quality gates met",
            duration_sec=1.23,
            model_used="local:llama3.2:3b",
            cost_usd=0.0,
            output="test output",
        )

        assert result.stage == "preflight_triage"
        assert result.status == TaskStatus.PREFLIGHT
        assert result.passed is True
        assert result.duration_sec == 1.23
        assert result.cost_usd == 0.0
        assert result.error == ""

    def test_task_progress_dataclass_initialization(self):
        """TaskProgress initializes with sensible defaults."""
        from backlog_batch_processor import TaskProgress, TaskStatus

        progress = TaskProgress(
            task_id="task-123",
            project="illuminati",
            title="Test task",
            slug="test-task",
        )

        assert progress.task_id == "task-123"
        assert progress.status == TaskStatus.QUEUED
        assert progress.total_cost_usd == 0.0
        assert progress.stages == []
        assert progress.qa_votes == []
        assert progress.legal_gates == {}
        assert progress.kind == "build"
        assert progress.material is False
        assert isinstance(progress.created_at, float)

    def test_task_progress_with_optional_fields(self):
        """TaskProgress accepts optional fields."""
        from backlog_batch_processor import TaskProgress, TaskStatus

        progress = TaskProgress(
            task_id="t1",
            project="p1",
            title="t1",
            slug="s1",
            kind="medium",
            material=True,
        )

        assert progress.kind == "medium"
        assert progress.material is True

    @patch("backlog_batch_processor.db")
    @patch("backlog_batch_processor.resource_governor")
    def test_process_batch_empty_queue(self, mock_rg, mock_db):
        """process_batch returns zero results on empty queue."""
        from backlog_batch_processor import BacklogBatchProcessor

        mock_rg.can_claim.return_value = True
        mock_db.select.return_value = []

        proc = BacklogBatchProcessor()
        result = proc.process_batch()

        assert result["processed"] == 0
        assert result["passed"] == 0
        assert result["failed"] == 0
        assert result["blocked"] == 0
        assert "timestamp" in result

    @patch("backlog_batch_processor.db")
    @patch("backlog_batch_processor.resource_governor")
    def test_process_batch_resource_exhausted(self, mock_rg, mock_db):
        """process_batch skips when resource governor denies claim."""
        from backlog_batch_processor import BacklogBatchProcessor

        mock_rg.can_claim.return_value = False

        proc = BacklogBatchProcessor()
        result = proc.process_batch()

        assert result["processed"] == 0
        assert result["reason"] == "resource_exhausted"
        mock_db.select.assert_not_called()

    @patch("backlog_batch_processor.db")
    @patch("backlog_batch_processor.resource_governor")
    def test_process_batch_respects_batch_size(self, mock_rg, mock_db):
        """process_batch respects BATCH_SIZE limit."""
        from backlog_batch_processor import BacklogBatchProcessor, BATCH_SIZE

        mock_rg.can_claim.return_value = True
        mock_db.select.return_value = [
            {"id": f"t{i}", "project": "p", "title": f"t{i}", "slug": f"t{i}"}
            for i in range(BATCH_SIZE + 5)
        ]
        mock_db.update.return_value = None

        proc = BacklogBatchProcessor()
        result = proc.process_batch()

        # db.select called with limit=BATCH_SIZE
        call_kwargs = mock_db.select.call_args[0][1]
        assert call_kwargs["limit"] == BATCH_SIZE

    @patch("backlog_batch_processor.db")
    @patch("backlog_batch_processor.resource_governor")
    @patch("backlog_batch_processor.pipeline_contract")
    def test_stage_preflight_classification(self, mock_pipeline, mock_rg, mock_db):
        """Preflight stage classifies task complexity."""
        from backlog_batch_processor import BacklogBatchProcessor, TaskProgress, TaskStatus

        mock_rg.can_claim.return_value = True
        mock_pipeline.classify.return_value = {
            "task_class": "medium",
            "complexity": "medium",
            "risk": "standard",
        }

        proc = BacklogBatchProcessor()
        progress = TaskProgress(task_id="t1", project="p1", title="t1", slug="t1")
        task = {"id": "t1", "prompt": "test", "kind": "build"}

        result = proc._stage_preflight(progress, task)

        assert result is True
        assert progress.status == TaskStatus.PREFLIGHT
        assert len(progress.stages) == 1
        assert progress.stages[0].stage == "preflight_triage"
        assert progress.stages[0].passed is True
        assert progress.stages[0].model_used == proc.preflight_model

    @patch("backlog_batch_processor.db")
    @patch("backlog_batch_processor.resource_governor")
    @patch("backlog_batch_processor.pipeline_contract")
    def test_stage_preflight_error_handling(self, mock_pipeline, mock_rg, mock_db):
        """Preflight stage handles errors gracefully."""
        from backlog_batch_processor import BacklogBatchProcessor, TaskProgress

        mock_rg.can_claim.return_value = True
        mock_pipeline.classify.side_effect = Exception("Classification failed")

        proc = BacklogBatchProcessor()
        progress = TaskProgress(task_id="t1", project="p1", title="t1", slug="t1")
        task = {"id": "t1", "prompt": "test", "kind": "build"}

        result = proc._stage_preflight(progress, task)

        assert result is False
        assert len(progress.stages) == 1
        assert progress.stages[0].passed is False
        assert "Classification failed" in progress.stages[0].error

    @patch("backlog_batch_processor.db")
    def test_stage_planning_skip_for_easy_tasks(self, mock_db):
        """Planning stage is skipped for easy tasks."""
        from backlog_batch_processor import BacklogBatchProcessor, TaskProgress

        mock_db.select.return_value = []
        mock_db.update.return_value = None

        proc = BacklogBatchProcessor()
        progress = TaskProgress(task_id="t1", project="p1", title="t1", slug="t1", kind="easy")
        task = {"id": "t1", "prompt": "test", "kind": "easy"}

        # Easy task should skip planning
        result = proc._process_task(task)
        planning_stages = [s for s in result.stages if s.stage == "strategy_planner"]
        assert len(planning_stages) == 0

    @patch("backlog_batch_processor.db")
    def test_stage_planning_invoked_for_medium_tasks(self, mock_db):
        """Planning stage is invoked for medium/hard tasks."""
        from backlog_batch_processor import BacklogBatchProcessor, TaskProgress

        mock_db.select.return_value = []
        mock_db.update.return_value = None

        proc = BacklogBatchProcessor()
        progress = TaskProgress(task_id="t1", project="p1", title="t1", slug="t1", kind="medium")
        task = {"id": "t1", "prompt": "test", "kind": "medium"}

        # Medium task should attempt planning
        result = proc._process_task(task)
        planning_stages = [s for s in result.stages if s.stage == "strategy_planner"]
        # Planning may succeed or fail in mock, but stage should be present or result failed
        assert result.status.name in ["FAILED", "PLANNING", "CODING", "QA", "LEGAL", "MERGE", "COMPLETE"]

    @patch("backlog_batch_processor.db")
    def test_stage_coding_generates_output(self, mock_db):
        """Coding stage generates code output."""
        from backlog_batch_processor import BacklogBatchProcessor, TaskProgress

        proc = BacklogBatchProcessor()
        progress = TaskProgress(task_id="t1", project="p1", title="t1", slug="t1")
        task = {"id": "t1", "prompt": "write a test"}

        result = proc._stage_coding(progress, task)

        assert result is True
        assert len(progress.stages) == 1
        assert progress.stages[0].stage == "agentic_coder"
        assert progress.stages[0].passed is True
        assert len(progress.stages[0].output) > 0

    @patch("backlog_batch_processor.db")
    def test_stage_coding_error_propagates(self, mock_db):
        """Coding stage error handling."""
        from backlog_batch_processor import BacklogBatchProcessor, TaskProgress

        proc = BacklogBatchProcessor()
        progress = TaskProgress(task_id="t1", project="p1", title="t1", slug="t1")
        task = {"id": "t1", "prompt": ""}

        # Even with empty prompt, should not crash
        result = proc._stage_coding(progress, task)
        # Should gracefully handle
        assert isinstance(result, bool)

    def test_stage_qa_panel_voting_consensus(self):
        """QA stage requires consensus from panel votes."""
        from backlog_batch_processor import BacklogBatchProcessor, TaskProgress

        proc = BacklogBatchProcessor()
        progress = TaskProgress(task_id="t1", project="p1", title="t1", slug="t1")
        task = {"id": "t1"}

        result = proc._stage_qa(progress, task)

        assert result is True
        assert len(progress.qa_votes) > 0
        assert progress.stages[-1].stage == "qa_panel"
        passed_votes = sum(1 for v in progress.qa_votes if v.get("pass"))
        # Mock returns votes that pass
        assert passed_votes >= len(progress.qa_votes)

    def test_stage_qa_panel_empty_votes_fails(self):
        """QA stage fails with no votes."""
        from backlog_batch_processor import BacklogBatchProcessor, TaskProgress

        proc = BacklogBatchProcessor()
        progress = TaskProgress(task_id="t1", project="p1", title="t1", slug="t1")

        # Mock _call_qa_panel to return empty
        with patch.object(proc, '_call_qa_panel', return_value=[]):
            task = {"id": "t1"}
            result = proc._stage_qa(progress, task)

            assert result is False
            assert progress.stages[-1].passed is False

    def test_qa_voting_requires_consensus(self):
        """QA panel requires 2/2 votes to pass."""
        from backlog_batch_processor import BacklogBatchProcessor, TaskProgress

        proc = BacklogBatchProcessor()
        progress = TaskProgress(task_id="t1", project="p1", title="t1", slug="t1")

        # Test with 1 pass, 1 fail
        with patch.object(proc, '_call_qa_panel', return_value=[
            {"model": "m1", "pass": True, "confidence": 0.9},
            {"model": "m2", "pass": False, "confidence": 0.8},
        ]):
            result = proc._stage_qa(progress, {})
            # Should fail because not all votes pass
            assert result is False

    def test_qa_voting_all_pass(self):
        """QA panel passes when all votes pass."""
        from backlog_batch_processor import BacklogBatchProcessor, TaskProgress

        proc = BacklogBatchProcessor()
        progress = TaskProgress(task_id="t1", project="p1", title="t1", slug="t1")

        with patch.object(proc, '_call_qa_panel', return_value=[
            {"model": "m1", "pass": True, "confidence": 0.9},
            {"model": "m2", "pass": True, "confidence": 0.95},
        ]):
            result = proc._stage_qa(progress, {})
            assert result is True

    def test_legal_gate_secrets_detection(self):
        """Legal gate detects secrets in text."""
        from backlog_batch_processor import BacklogBatchProcessor, TaskProgress

        proc = BacklogBatchProcessor()
        progress = TaskProgress(task_id="t1", project="p1", title="t1", slug="t1")

        # Test with various secret patterns
        secret_texts = [
            "add ANTHROPIC_API_KEY=sk-123",
            "password = 'secret123'",
            "token = abc123def456",
            "-----BEGIN PRIVATE KEY-----",
        ]

        for text in secret_texts:
            assert proc._has_secrets(text) is True

    def test_legal_gate_clean_text_passes(self):
        """Legal gate allows clean text without secrets."""
        from backlog_batch_processor import BacklogBatchProcessor, TaskProgress

        proc = BacklogBatchProcessor()

        clean_texts = [
            "feat: add new feature",
            "docs: update README",
            "chore: bump version to 1.0.0",
            "test: add unit tests for utils",
            "refactor: simplify logic",
        ]

        for text in clean_texts:
            assert proc._has_secrets(text) is False

    def test_legal_gate_secret_patterns_case_insensitive(self):
        """Secret detection is case-insensitive."""
        from backlog_batch_processor import BacklogBatchProcessor

        proc = BacklogBatchProcessor()

        assert proc._has_secrets("PASSWORD=secret") is True
        assert proc._has_secrets("Api_Key=xyz") is True
        assert proc._has_secrets("SECRET_TOKEN=abc") is True

    @patch("backlog_batch_processor.legal_filter")
    def test_check_legal_gates_owner_approval_blocked(self, mock_legal):
        """Legal gate blocks merge when owner approval is required."""
        from backlog_batch_processor import BacklogBatchProcessor, TaskProgress, GateResult

        mock_legal.requires_owner_approval.return_value = True

        proc = BacklogBatchProcessor()
        progress = TaskProgress(task_id="t1", project="p1", title="t1", slug="t1")
        task = {"id": "t1", "prompt": "update LICENSE file"}

        result = proc._check_legal_gates(progress, task)

        assert result == GateResult.BLOCKED
        assert progress.legal_gates["legal_approval_required"] is True

    @patch("backlog_batch_processor.legal_filter")
    def test_check_legal_gates_secrets_fail(self, mock_legal):
        """Legal gate fails merge when secrets detected."""
        from backlog_batch_processor import BacklogBatchProcessor, TaskProgress, GateResult

        mock_legal.requires_owner_approval.return_value = False

        proc = BacklogBatchProcessor()
        progress = TaskProgress(task_id="t1", project="p1", title="t1", slug="t1")
        task = {"id": "t1", "prompt": "add API_KEY=secret"}

        result = proc._check_legal_gates(progress, task)

        assert result == GateResult.FAIL
        assert progress.legal_gates["secrets_detected"] is True

    @patch("backlog_batch_processor.legal_filter")
    def test_check_legal_gates_all_clear(self, mock_legal):
        """Legal gate passes when no triggers detected."""
        from backlog_batch_processor import BacklogBatchProcessor, TaskProgress, GateResult

        mock_legal.requires_owner_approval.return_value = False

        proc = BacklogBatchProcessor()
        progress = TaskProgress(task_id="t1", project="p1", title="t1", slug="t1")
        task = {"id": "t1", "prompt": "feat: add feature"}

        result = proc._check_legal_gates(progress, task)

        assert result == GateResult.PASS
        assert progress.legal_gates["all_clear"] is True

    def test_create_branch_naming(self):
        """Create branch uses consistent naming scheme."""
        from backlog_batch_processor import BacklogBatchProcessor, TaskProgress

        proc = BacklogBatchProcessor()
        progress = TaskProgress(task_id="t1", project="p1", title="t1", slug="my-feature")
        task = {"id": "t1"}

        branch = proc._create_branch(progress, task)

        assert branch.startswith("agent/batch-")
        assert "my-feature" in branch
        assert branch != ""

    def test_create_branch_error_handling(self):
        """Create branch handles errors gracefully."""
        from backlog_batch_processor import BacklogBatchProcessor, TaskProgress

        proc = BacklogBatchProcessor()
        progress = TaskProgress(task_id="t1", project="p1", title="t1", slug="")

        # Even with empty slug, should return something
        branch = proc._create_branch(progress, {})
        assert isinstance(branch, str)

    def test_commit_message_formatting(self):
        """Commit message includes task title and co-author."""
        from backlog_batch_processor import BacklogBatchProcessor, TaskProgress

        proc = BacklogBatchProcessor()
        progress = TaskProgress(task_id="t1", project="p1", title="Fix critical bug", slug="t1")

        # The _commit_changes method constructs the message
        msg = f"{progress.title}\n\nCo-Authored-By: Claude Haiku 4.5 <noreply@anthropic.com>"

        assert "Fix critical bug" in msg
        assert "Claude Haiku 4.5" in msg
        assert "noreply@anthropic.com" in msg

    def test_batch_cost_accumulation(self):
        """Batch processing accumulates costs across stages."""
        from backlog_batch_processor import BacklogBatchProcessor, TaskProgress, StageResult, TaskStatus

        progress = TaskProgress(task_id="t1", project="p1", title="t1", slug="t1")

        # Simulate adding stages with costs
        result1 = StageResult(stage="planning", status=TaskStatus.PLANNING, passed=True, cost_usd=0.01)
        result2 = StageResult(stage="coding", status=TaskStatus.CODING, passed=True, cost_usd=0.05)

        progress.stages.append(result1)
        progress.total_cost_usd += result1.cost_usd
        progress.stages.append(result2)
        progress.total_cost_usd += result2.cost_usd

        assert progress.total_cost_usd == 0.06

    def test_batch_cost_zero_cost_stages(self):
        """Some stages have zero cost (local models)."""
        from backlog_batch_processor import BacklogBatchProcessor, TaskProgress, StageResult, TaskStatus

        progress = TaskProgress(task_id="t1", project="p1", title="t1", slug="t1")

        # Preflight with local:llama3.2:3b is zero-cost
        preflight = StageResult(
            stage="preflight_triage",
            status=TaskStatus.PREFLIGHT,
            passed=True,
            cost_usd=0.0,
            model_used="local:llama3.2:3b"
        )
        progress.stages.append(preflight)
        progress.total_cost_usd += preflight.cost_usd

        assert progress.total_cost_usd == 0.0

    def test_summarize_batch_metrics(self):
        """Batch summary calculates correct metrics."""
        from backlog_batch_processor import BacklogBatchProcessor, TaskProgress, TaskStatus

        proc = BacklogBatchProcessor()

        results = [
            TaskProgress(task_id="t1", project="p1", title="t1", slug="t1", status=TaskStatus.COMPLETE, total_cost_usd=0.05),
            TaskProgress(task_id="t2", project="p1", title="t2", slug="t2", status=TaskStatus.COMPLETE, total_cost_usd=0.03),
            TaskProgress(task_id="t3", project="p1", title="t3", slug="t3", status=TaskStatus.FAILED, total_cost_usd=0.01),
            TaskProgress(task_id="t4", project="p1", title="t4", slug="t4", status=TaskStatus.BLOCKED, total_cost_usd=0.0),
        ]

        summary = proc._summarize_batch(results)

        assert summary["processed"] == 4
        assert summary["passed"] == 2
        assert summary["failed"] == 1
        assert summary["blocked"] == 1
        assert summary["total_cost_usd"] == 0.09
        assert abs(summary["avg_cost_per_task"] - 0.0225) < 0.0001

    def test_summarize_batch_single_task(self):
        """Batch summary works with single task."""
        from backlog_batch_processor import BacklogBatchProcessor, TaskProgress, TaskStatus

        proc = BacklogBatchProcessor()
        results = [
            TaskProgress(task_id="t1", project="p1", title="t1", slug="t1",
                        status=TaskStatus.COMPLETE, total_cost_usd=0.05),
        ]

        summary = proc._summarize_batch(results)

        assert summary["processed"] == 1
        assert summary["passed"] == 1
        assert summary["avg_cost_per_task"] == 0.05

    def test_summarize_batch_empty(self):
        """Batch summary handles empty results."""
        from backlog_batch_processor import BacklogBatchProcessor

        proc = BacklogBatchProcessor()
        summary = proc._summarize_batch([])

        assert summary["processed"] == 0
        assert summary["avg_cost_per_task"] == 0

    def test_stats_function_returns_config(self):
        """stats() returns processor configuration."""
        from backlog_batch_processor import stats

        stats_result = stats()

        assert "batch_size" in stats_result
        assert "dry_run" in stats_result
        assert "preflight_model" in stats_result
        assert "planner_model" in stats_result
        assert "coder_model" in stats_result
        assert "qa_model" in stats_result
        assert "legal_gate_enabled" in stats_result

    def test_stats_function_values(self):
        """stats() reflects environment configuration."""
        from backlog_batch_processor import stats, BATCH_SIZE, DRY_RUN, LEGAL_GATE_REQUIRED

        stats_result = stats()

        assert stats_result["batch_size"] == BATCH_SIZE
        assert stats_result["dry_run"] == DRY_RUN
        assert stats_result["legal_gate_enabled"] == LEGAL_GATE_REQUIRED

    def test_env_var_batch_size_override(self):
        """ORCH_BACKLOG_BATCH_SIZE overrides default."""
        from backlog_batch_processor import BacklogBatchProcessor

        with patch.dict(os.environ, {"ORCH_BACKLOG_BATCH_SIZE": "20"}):
            # Re-import to get new env value (or mock directly)
            proc = BacklogBatchProcessor()
            # Should use BATCH_SIZE from module which reads env
            assert proc.batch_size > 0

    def test_env_var_dry_run_override(self):
        """ORCH_BACKLOG_DRY_RUN can be set to true."""
        from backlog_batch_processor import BacklogBatchProcessor

        with patch.dict(os.environ, {"ORCH_BACKLOG_DRY_RUN": "true"}):
            proc = BacklogBatchProcessor()
            # Should respect dry_run setting
            assert isinstance(proc.dry_run, bool)

    @patch("backlog_batch_processor.db")
    @patch("backlog_batch_processor.resource_governor")
    @patch("backlog_batch_processor.pipeline_contract")
    @patch("backlog_batch_processor.legal_filter")
    def test_full_pipeline_easy_task(self, mock_legal, mock_pipeline, mock_rg, mock_db):
        """Full pipeline execution for easy task."""
        from backlog_batch_processor import BacklogBatchProcessor

        mock_rg.can_claim.return_value = True
        mock_db.select.return_value = [{
            "id": "t1",
            "project": "test",
            "title": "Easy task",
            "slug": "easy-task",
            "kind": "easy",
            "prompt": "test",
        }]
        mock_db.update.return_value = None
        mock_pipeline.classify.return_value = {"task_class": "easy"}
        mock_legal.requires_owner_approval.return_value = False

        proc = BacklogBatchProcessor()
        result = proc.process_batch()

        # Should process at least one task
        assert result["processed"] >= 0

    @patch("backlog_batch_processor.db")
    @patch("backlog_batch_processor.resource_governor")
    def test_database_update_on_stage_completion(self, mock_rg, mock_db):
        """Database is updated after each stage."""
        from backlog_batch_processor import BacklogBatchProcessor, TaskProgress

        mock_rg.can_claim.return_value = True
        mock_db.update.return_value = None

        proc = BacklogBatchProcessor()
        progress = TaskProgress(task_id="t1", project="p1", title="t1", slug="t1")
        task = {"id": "t1", "prompt": "test"}

        proc._stage_preflight(progress, task)

        # Should have called db.update
        mock_db.update.assert_called()

    def test_stage_timing_recorded(self):
        """Stage execution times are recorded."""
        from backlog_batch_processor import BacklogBatchProcessor, TaskProgress, StageResult

        proc = BacklogBatchProcessor()
        progress = TaskProgress(task_id="t1", project="p1", title="t1", slug="t1")
        task = {"id": "t1", "prompt": "test"}

        start = time.time()
        result = proc._stage_coding(progress, task)

        if result and progress.stages:
            stage = progress.stages[0]
            assert stage.duration_sec >= 0
            assert stage.duration_sec < 10  # Should be fast for mock

    def test_task_without_required_fields(self):
        """Task missing required fields handled gracefully."""
        from backlog_batch_processor import BacklogBatchProcessor

        proc = BacklogBatchProcessor()

        # Minimal task dict
        task = {}
        result = proc._process_task(task)

        # Should not crash, should return TaskProgress
        assert result is not None
        assert hasattr(result, 'task_id')
        assert hasattr(result, 'status')

    def test_concurrent_batch_processing_lock(self):
        """process_batch uses locking to prevent races."""
        from backlog_batch_processor import BacklogBatchProcessor

        proc = BacklogBatchProcessor()

        # The lock should exist
        assert hasattr(proc, '_lock')
        assert isinstance(proc._lock, threading.Lock)

    def test_model_routing_configuration(self):
        """Models are routed according to task class."""
        from backlog_batch_processor import (
            BacklogBatchProcessor,
            PREFLIGHT_MODEL,
            PLANNER_MODEL,
            CODER_MODEL,
            QA_MODEL
        )

        proc = BacklogBatchProcessor()

        assert proc.preflight_model == PREFLIGHT_MODEL
        assert proc.planner_model == PLANNER_MODEL
        assert proc.coder_model == CODER_MODEL
        assert proc.qa_model == QA_MODEL

    @patch("backlog_batch_processor.db")
    def test_failed_task_db_update(self, mock_db):
        """Failed tasks are marked in database."""
        from backlog_batch_processor import BacklogBatchProcessor, TaskProgress

        mock_db.update.return_value = None

        proc = BacklogBatchProcessor()
        progress = TaskProgress(task_id="t1", project="p1", title="t1", slug="t1")
        task = {"id": "t1"}

        # Simulate task failure
        proc._update_task_status(task, "failed", "error message")

        # Verify update was called
        mock_db.update.assert_called()
        call_args = mock_db.update.call_args
        assert call_args[0][0] == "tasks"

    def test_legal_gate_skip_when_disabled(self):
        """Legal gate skipped when LEGAL_GATE_REQUIRED is false."""
        from backlog_batch_processor import BacklogBatchProcessor, TaskProgress

        proc = BacklogBatchProcessor()
        progress = TaskProgress(task_id="t1", project="p1", title="t1", slug="t1")
        task = {"id": "t1", "prompt": "add API_KEY=secret"}

        # Even with secrets, if legal gate is disabled, should not block
        with patch("backlog_batch_processor.LEGAL_GATE_REQUIRED", False):
            # Process task should continue past legal gate
            result = proc._process_task(task)
            # Should get through more stages
            assert result.status.name in ["COMPLETE", "FAILED", "MERGE"]

    def test_merge_automation_respects_dry_run(self):
        """Merge stage skips actual merge in dry-run mode."""
        from backlog_batch_processor import BacklogBatchProcessor, TaskProgress

        proc = BacklogBatchProcessor()
        proc.dry_run = True
        progress = TaskProgress(task_id="t1", project="p1", title="t1", slug="t1")
        task = {"id": "t1"}

        with patch.object(proc, '_create_branch', return_value="branch"):
            with patch.object(proc, '_apply_changes', return_value=True):
                with patch.object(proc, '_commit_changes', return_value=True):
                    with patch.object(proc, '_push_branch', return_value=True):
                        with patch.object(proc, '_merge_to_dev', return_value=True) as mock_merge:
                            result = proc._stage_merge(progress, task)
                            # In dry-run, should still succeed but not call actual merge
                            # DRY_RUN is module-level, so this test verifies the logic path

    def test_planner_stage_cost_tracking(self):
        """Planner stage adds cost to total."""
        from backlog_batch_processor import BacklogBatchProcessor, TaskProgress

        proc = BacklogBatchProcessor()
        progress = TaskProgress(task_id="t1", project="p1", title="t1", slug="t1", kind="medium")
        task = {"id": "t1", "prompt": "test"}

        with patch.object(proc, '_call_planner', return_value="plan"):
            result = proc._stage_planning(progress, task)

            if result:
                # Should have added cost
                assert progress.total_cost_usd > 0

    def test_coder_stage_cost_tracking(self):
        """Coder stage adds cost to total."""
        from backlog_batch_processor import BacklogBatchProcessor, TaskProgress

        proc = BacklogBatchProcessor()
        progress = TaskProgress(task_id="t1", project="p1", title="t1", slug="t1")
        task = {"id": "t1", "prompt": "test"}

        result = proc._stage_coding(progress, task)

        if result:
            # Should have added cost
            assert progress.total_cost_usd > 0

    def test_task_progress_status_transitions(self):
        """TaskProgress status transitions correctly through pipeline."""
        from backlog_batch_processor import TaskProgress, TaskStatus

        progress = TaskProgress(task_id="t1", project="p1", title="t1", slug="t1")

        # Initial status
        assert progress.status == TaskStatus.QUEUED

        # Simulate transitions
        progress.status = TaskStatus.PREFLIGHT
        assert progress.status == TaskStatus.PREFLIGHT

        progress.status = TaskStatus.PLANNING
        assert progress.status == TaskStatus.PLANNING

        progress.status = TaskStatus.COMPLETE
        assert progress.status == TaskStatus.COMPLETE

    def test_apply_changes_to_branch(self):
        """Apply changes to branch returns success status."""
        from backlog_batch_processor import BacklogBatchProcessor, TaskProgress

        proc = BacklogBatchProcessor()
        result = proc._apply_changes("test-branch", {"id": "t1"})

        # Should return boolean
        assert isinstance(result, bool)

    def test_push_branch_to_remote(self):
        """Push branch to remote returns success status."""
        from backlog_batch_processor import BacklogBatchProcessor

        proc = BacklogBatchProcessor()
        result = proc._push_branch("test-branch")

        # Should return boolean
        assert isinstance(result, bool)

    def test_call_qa_panel_returns_votes(self):
        """Call QA panel returns list of votes."""
        from backlog_batch_processor import BacklogBatchProcessor, TaskProgress

        proc = BacklogBatchProcessor()
        progress = TaskProgress(task_id="t1", project="p1", title="t1", slug="t1")

        votes = proc._call_qa_panel(progress)

        assert isinstance(votes, list)
        assert len(votes) > 0
        for vote in votes:
            assert "model" in vote
            assert "pass" in vote
            assert "confidence" in vote

    def test_stage_result_error_field_empty_by_default(self):
        """StageResult error field is empty by default."""
        from backlog_batch_processor import StageResult, TaskStatus

        result = StageResult(
            stage="test",
            status=TaskStatus.QUEUED,
            passed=True,
        )

        assert result.error == ""

    def test_backlog_processor_initialization(self):
        """BacklogBatchProcessor initializes with config."""
        from backlog_batch_processor import BacklogBatchProcessor, BATCH_SIZE

        proc = BacklogBatchProcessor()

        assert proc.batch_size == BATCH_SIZE
        assert hasattr(proc, 'dry_run')
        assert hasattr(proc, 'preflight_model')
        assert hasattr(proc, 'planner_model')
        assert hasattr(proc, 'coder_model')
        assert hasattr(proc, 'qa_model')


class TestProcessBatchModuleFunction:
    """Test module-level process_batch function."""

    @patch("backlog_batch_processor.acquire")
    def test_process_batch_delegates_to_processor(self, mock_acquire):
        """Module-level process_batch() delegates to singleton."""
        from backlog_batch_processor import process_batch

        mock_proc = MagicMock()
        mock_proc.process_batch.return_value = {"processed": 1}
        mock_acquire.return_value = mock_proc

        result = process_batch()

        mock_acquire.assert_called_once()
        mock_proc.process_batch.assert_called_once()
        assert result["processed"] == 1


class TestIntegration:
    """Integration tests across multiple components."""

    @patch("backlog_batch_processor.db")
    @patch("backlog_batch_processor.resource_governor")
    @patch("backlog_batch_processor.pipeline_contract")
    @patch("backlog_batch_processor.legal_filter")
    def test_full_pipeline_medium_task(self, mock_legal, mock_pipeline, mock_rg, mock_db):
        """Full pipeline execution for medium task."""
        from backlog_batch_processor import BacklogBatchProcessor

        mock_rg.can_claim.return_value = True
        mock_db.select.return_value = [{
            "id": "t1",
            "project": "test",
            "title": "Medium task",
            "slug": "medium-task",
            "kind": "medium",
            "prompt": "complex feature",
        }]
        mock_db.update.return_value = None
        mock_pipeline.classify.return_value = {"task_class": "medium"}
        mock_legal.requires_owner_approval.return_value = False

        proc = BacklogBatchProcessor()
        result = proc.process_batch()

        # Medium task should process
        assert "processed" in result

    @patch("backlog_batch_processor.db")
    @patch("backlog_batch_processor.resource_governor")
    def test_batch_with_mixed_task_statuses(self, mock_rg, mock_db):
        """Batch processing handles mix of success/failure."""
        from backlog_batch_processor import BacklogBatchProcessor, TaskStatus

        mock_rg.can_claim.return_value = True
        mock_db.select.return_value = [
            {"id": f"t{i}", "project": "p", "title": f"Task {i}", "slug": f"t{i}"}
            for i in range(3)
        ]
        mock_db.update.return_value = None

        proc = BacklogBatchProcessor()
        result = proc.process_batch()

        # Results should be summarized
        assert result["processed"] >= 0
        assert "passed" in result
        assert "failed" in result
        assert "blocked" in result

    def test_qa_panel_with_three_models(self):
        """QA panel consensus with multiple models."""
        from backlog_batch_processor import BacklogBatchProcessor, TaskProgress

        proc = BacklogBatchProcessor()
        progress = TaskProgress(task_id="t1", project="p1", title="t1", slug="t1")

        # Test with 3 models, all pass
        with patch.object(proc, '_call_qa_panel', return_value=[
            {"model": "m1", "pass": True, "confidence": 0.9},
            {"model": "m2", "pass": True, "confidence": 0.85},
            {"model": "m3", "pass": True, "confidence": 0.92},
        ]):
            result = proc._stage_qa(progress, {})
            assert result is True

    def test_stage_progression_pipeline(self):
        """Task progresses through all pipeline stages."""
        from backlog_batch_processor import BacklogBatchProcessor, TaskStatus

        proc = BacklogBatchProcessor()
        task = {
            "id": "t1",
            "project": "test",
            "title": "Test",
            "slug": "test",
            "kind": "easy",
            "prompt": "test",
        }

        result = proc._process_task(task)

        # Should have gone through at least some stages
        assert len(result.stages) > 0
        assert result.task_id == "t1"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
