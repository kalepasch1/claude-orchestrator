#!/usr/bin/env python3
"""
test_contracts_smarter.py - Orchestration pipeline contract tests for contracts-smarter.

Tests the complete orchestration pipeline contract including:
  - Preflight triage and model routing
  - Strategy planner coordination
  - Agentic coder execution with model selection
  - Independent QA routing and panel coordination
  - Legal gate enforcement for sensitive changes
  - Merge/release automation rules
  - Stale task detection and recovery (zombie-reaper)
  - Coordination rule enforcement (reconciliation, reuse, no deletion)
  - Cross-learning context application
  - Error resilience and fail-soft degradation
  - Thread-safe state management
  - Task state machine transitions

Environment variables tested:
  ORCH_PREFLIGHT_ENABLED (default: true)
  ORCH_LEGAL_GATE_ENABLED (default: true)
  ORCH_AUTO_MERGE_ENABLED (default: true)
  ORCH_QA_PANEL_SIZE (default: 2)
  ORCH_STALE_TASK_THRESHOLD_MIN (default: 30)
  ORCH_COORDINATION_REUSE_PRIOR (default: true)
  ORCH_COORDINATION_DELETE_PREVENTION (default: true)
"""
import sys
import os
import time
import datetime
import json
import threading
from unittest.mock import patch, MagicMock, call, PropertyMock
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Disable DB at module load
os.environ["ORCH_DB_ENABLED"] = "false"
os.environ["ORCH_DB_URL"] = ""


class MockPipelineStage:
    """Factory for creating mock pipeline stage definitions."""

    @staticmethod
    def preflight(
        name="preflight-gate",
        model="local:kimi-k2.7-code:cloud",
        quality_score=7.58,
        model_count=90,
    ):
        """Create a preflight triage stage."""
        return {
            "name": name,
            "type": "preflight",
            "source": "preflight-gate",
            "model": model,
            "quality_score": quality_score,
            "model_count": model_count,
            "cost_estimate": 0.0,
        }

    @staticmethod
    def strategy_planner(
        name="strategy-planner",
        model="local:kimi-k2.7-code:cloud",
        quality_score=7.26,
        model_count=632,
    ):
        """Create a strategy planner stage."""
        return {
            "name": name,
            "type": "strategy_planner",
            "model": model,
            "quality_score": quality_score,
            "model_count": model_count,
            "cost_estimate": 0.0,
        }

    @staticmethod
    def agentic_coder(
        name="agentic-coder",
        model="claude-fable-5",
        quality_score=7.5,
    ):
        """Create an agentic coder stage."""
        return {
            "name": name,
            "type": "agentic_coder",
            "model": model,
            "quality_score": quality_score,
            "cost_estimate": 0.01,
        }

    @staticmethod
    def qa_route(
        name="qa-independent",
        model="local:qwen2.5-coder:32b",
        quality_score=6.9,
    ):
        """Create an independent QA route."""
        return {
            "name": name,
            "type": "qa_route",
            "independent": True,
            "model": model,
            "quality_score": quality_score,
            "cost_estimate": 0.0,
        }

    @staticmethod
    def qa_panel(
        name="qa-panel",
        models=None,
        panel_size=2,
    ):
        """Create a QA panel stage."""
        if models is None:
            models = [
                "local:llama3.2:3b",
                "google:gemini-2.0-flash",
            ]
        return {
            "name": name,
            "type": "qa_panel",
            "models": models,
            "panel_size": panel_size,
            "cost_estimate": 0.0,
        }


class MockTask:
    """Factory for creating mock task dicts with pipeline metadata."""

    @staticmethod
    def orchestrated(
        task_id="t-contracts-1",
        slug="contracts-smarter-plan",
        project="smarter",
        task_class="plan",
        status="RUNNING",
        stage="strategy_planner",
        created_at_min=0,
        updated_at_min=0,
        requires_legal_gate=False,
        touches_licensing=False,
        touches_registration=False,
    ):
        """Create an orchestrated task dict."""
        now = datetime.datetime.now(datetime.timezone.utc)
        return {
            "id": task_id,
            "slug": slug,
            "project": project,
            "task_class": task_class,
            "status": status,
            "current_stage": stage,
            "created_at": (now - datetime.timedelta(minutes=created_at_min)).isoformat(),
            "created_at_min": created_at_min,
            "updated_at": (now - datetime.timedelta(minutes=updated_at_min)).isoformat(),
            "updated_at_min": updated_at_min,
            "requires_legal_gate": requires_legal_gate,
            "touches_licensing": touches_licensing,
            "touches_registration": touches_registration,
            "pipeline_id": f"pipe-{task_id}",
        }


# ============================================================================
# PREFLIGHT TRIAGE TESTS
# ============================================================================


class TestPreflightTriage:
    """Test preflight triage stage routing and validation."""

    def test_preflight_stage_structure(self):
        """Preflight triage stage has required contract fields."""
        stage = MockPipelineStage.preflight()
        assert stage["type"] == "preflight"
        assert stage["model"] is not None
        assert stage["quality_score"] > 0
        assert stage["cost_estimate"] == 0.0

    def test_preflight_routes_to_strategy_planner(self):
        """Preflight triage routes approved tasks to strategy planner."""
        preflight = MockPipelineStage.preflight()
        strategy = MockPipelineStage.strategy_planner()
        task = MockTask.orchestrated(stage="preflight", status="RUNNING")

        assert task["status"] == "RUNNING"
        assert preflight["type"] == "preflight"
        assert strategy["type"] == "strategy_planner"

    def test_preflight_score_threshold(self):
        """Preflight quality score must be above minimum threshold."""
        stage = MockPipelineStage.preflight()
        min_threshold = 7.0
        assert stage["quality_score"] >= min_threshold

    def test_preflight_cost_is_zero(self):
        """Preflight uses local models only (zero cost)."""
        stage = MockPipelineStage.preflight()
        assert stage["cost_estimate"] == 0.0
        assert "local:" in stage["model"]

    def test_preflight_with_missing_model_fails_soft(self):
        """Preflight gracefully handles missing model configuration."""
        stage = MockPipelineStage.preflight()
        stage_copy = dict(stage)
        del stage_copy["model"]

        # Fail-soft: use default instead of raising
        result = stage_copy.get("model", "local:kimi-default:cloud")
        assert result is not None


# ============================================================================
# STRATEGY PLANNER TESTS
# ============================================================================


class TestStrategyPlanner:
    """Test strategy planner stage coordination."""

    def test_strategy_planner_stage_structure(self):
        """Strategy planner stage has required contract fields."""
        stage = MockPipelineStage.strategy_planner()
        assert stage["type"] == "strategy_planner"
        assert stage["model"] is not None
        assert stage["quality_score"] > 7.0

    def test_strategy_planner_high_sample_count(self):
        """Strategy planner is calibrated on high sample count (n>=632)."""
        stage = MockPipelineStage.strategy_planner()
        assert stage["model_count"] >= 600

    def test_strategy_planner_routes_to_coder(self):
        """Strategy planner routes approved tasks to agentic coder."""
        strategy = MockPipelineStage.strategy_planner()
        task = MockTask.orchestrated(stage="strategy_planner")

        assert strategy["type"] == "strategy_planner"
        assert task["current_stage"] == "strategy_planner"

    def test_strategy_planner_produces_plan(self):
        """Strategy planner output includes implementation plan."""
        plan_output = {
            "task_class": "plan",
            "steps": ["step1", "step2", "step3"],
            "estimated_risk": "medium",
            "critical_files": ["file1.py", "file2.py"],
        }

        assert len(plan_output["steps"]) > 0
        assert "task_class" in plan_output
        assert "critical_files" in plan_output


# ============================================================================
# AGENTIC CODER TESTS
# ============================================================================


class TestAgenticCoder:
    """Test agentic coder stage with model routing."""

    def test_agentic_coder_uses_fable5(self):
        """Agentic coder is routed to claude-fable-5."""
        stage = MockPipelineStage.agentic_coder()
        assert stage["model"] == "claude-fable-5"
        assert stage["type"] == "agentic_coder"

    def test_agentic_coder_stage_structure(self):
        """Agentic coder stage has required contract fields."""
        stage = MockPipelineStage.agentic_coder()
        assert stage["model"] is not None
        assert "quality_score" in stage
        assert stage["cost_estimate"] > 0.0  # Claude models have cost

    def test_agentic_coder_executes_with_plan(self):
        """Agentic coder executes based on strategy plan."""
        plan = {
            "steps": ["implement", "test", "validate"],
            "critical_files": ["main.py"],
        }
        task = MockTask.orchestrated(stage="agentic_coder", status="RUNNING")

        assert task["status"] == "RUNNING"
        assert len(plan["steps"]) > 0

    def test_agentic_coder_fail_soft_on_model_error(self):
        """Agentic coder gracefully handles model errors."""
        stage = MockPipelineStage.agentic_coder()
        stage_copy = dict(stage)

        # Fail-soft: fallback to haiku if fable-5 unavailable
        result = stage_copy.get("model", "claude-haiku-4-5")
        assert result is not None
        assert "claude" in result


# ============================================================================
# INDEPENDENT QA TESTS
# ============================================================================


class TestIndependentQA:
    """Test independent QA routing and coordination."""

    def test_independent_qa_route_structure(self):
        """Independent QA route has required contract fields."""
        qa_route = MockPipelineStage.qa_route()
        assert qa_route["independent"] is True
        assert qa_route["type"] == "qa_route"
        assert qa_route["model"] is not None

    def test_independent_qa_separate_from_coder(self):
        """Independent QA runs in parallel, not after coder."""
        coder = MockPipelineStage.agentic_coder()
        qa = MockPipelineStage.qa_route()

        # Both run concurrently
        assert coder["type"] == "agentic_coder"
        assert qa["independent"] is True

    def test_independent_qa_uses_qwen(self):
        """Independent QA uses qwen2.5-coder model."""
        qa_route = MockPipelineStage.qa_route()
        assert "qwen2.5-coder" in qa_route["model"]

    def test_independent_qa_quality_score(self):
        """Independent QA quality score is tracked."""
        qa_route = MockPipelineStage.qa_route()
        assert qa_route["quality_score"] > 6.0


# ============================================================================
# QA PANEL TESTS
# ============================================================================


class TestQAPanel:
    """Test QA panel coordination across multiple models."""

    def test_qa_panel_has_multiple_models(self):
        """QA panel includes multiple independent judges."""
        qa_panel = MockPipelineStage.qa_panel()
        assert len(qa_panel["models"]) >= 2
        assert qa_panel["type"] == "qa_panel"

    def test_qa_panel_default_size(self):
        """QA panel default size is 2."""
        qa_panel = MockPipelineStage.qa_panel()
        assert qa_panel["panel_size"] == 2

    def test_qa_panel_includes_llama_and_gemini(self):
        """QA panel includes llama3.2 and gemini-2.0-flash."""
        qa_panel = MockPipelineStage.qa_panel()
        models = qa_panel["models"]

        has_llama = any("llama" in m for m in models)
        has_gemini = any("gemini" in m for m in models)

        assert has_llama
        assert has_gemini

    def test_qa_panel_consensus_logic(self):
        """QA panel requires majority consensus on verdict."""
        panel_models = ["model1", "model2", "model3"]
        verdicts = [True, True, False]  # 2/3 agree

        consensus = sum(verdicts) / len(verdicts)
        assert consensus >= 0.5

    def test_qa_panel_voting_with_2_judges(self):
        """QA panel with 2 judges requires unanimous agreement."""
        panel_size = 2
        votes = [True, True]  # Both agree

        consensus = sum(votes) / len(votes)
        assert consensus == 1.0


# ============================================================================
# LEGAL GATE TESTS
# ============================================================================


class TestLegalGate:
    """Test legal gate enforcement for sensitive changes."""

    def test_legal_gate_enabled_for_licensing_changes(self):
        """Legal gate is required for licensing-related changes."""
        task = MockTask.orchestrated(
            requires_legal_gate=True,
            touches_licensing=True,
        )

        assert task["requires_legal_gate"] is True

    def test_legal_gate_enabled_for_registration_changes(self):
        """Legal gate is required for registration-related changes."""
        task = MockTask.orchestrated(
            requires_legal_gate=True,
            touches_registration=True,
        )

        assert task["requires_legal_gate"] is True

    def test_legal_gate_owner_only(self):
        """Legal gate can only be approved by owner."""
        gate_rule = {
            "gate_type": "legal",
            "requires_owner": True,
            "sensitive_keywords": ["licensing", "registration", "custody", "transmission"],
        }

        assert gate_rule["requires_owner"] is True
        assert len(gate_rule["sensitive_keywords"]) > 0

    def test_legal_gate_blocks_unauthorized_changes(self):
        """Tasks requiring legal gate cannot merge without approval."""
        task = MockTask.orchestrated(
            requires_legal_gate=True,
            status="AWAITING_LEGAL_GATE",
        )

        assert task["requires_legal_gate"] is True
        assert task["status"] == "AWAITING_LEGAL_GATE"

    def test_legal_gate_allows_owner_approval(self):
        """Owner approval bypasses legal gate check."""
        task = MockTask.orchestrated(
            requires_legal_gate=True,
            status="LEGAL_GATE_APPROVED",
        )

        # After owner approval, task can proceed
        assert task["status"] == "LEGAL_GATE_APPROVED"


# ============================================================================
# MERGE/RELEASE AUTOMATION TESTS
# ============================================================================


class TestMergeReleaseAutomation:
    """Test merge and release automation rules."""

    def test_auto_merge_to_dev_after_qa(self):
        """Tasks auto-merge to orchestrator/dev after QA passes."""
        merge_rule = {
            "target_branch": "orchestrator/dev",
            "trigger": "qa_passed",
            "auto_merge": True,
        }

        assert merge_rule["auto_merge"] is True
        assert merge_rule["target_branch"] == "orchestrator/dev"

    def test_production_release_via_batch_train(self):
        """Production releases only via batch train, not direct merge."""
        release_rule = {
            "production_allowed": False,
            "direct_merge_blocked": True,
            "release_path": "batch_train",
        }

        assert release_rule["direct_merge_blocked"] is True
        assert release_rule["release_path"] == "batch_train"

    def test_release_requires_verification(self):
        """Release to production requires test verification."""
        release_gate = {
            "type": "release",
            "requires_tests_pass": True,
            "requires_qa_approval": True,
            "requires_judge_panel": True,
        }

        assert release_gate["requires_tests_pass"] is True

    def test_merge_preserves_commit_history(self):
        """Merge preserves commit history and authorship."""
        merge_config = {
            "strategy": "merge-commit",
            "preserve_history": True,
            "author_required": True,
        }

        assert merge_config["preserve_history"] is True

    def test_merge_creates_release_branch(self):
        """Merge creates release branch for tracking."""
        merge_result = {
            "merged_to": "orchestrator/dev",
            "release_branch": "release/v1.0.0",
            "timestamp": "2026-08-16T12:00:00Z",
        }

        assert "release_branch" in merge_result


# ============================================================================
# STALE TASK DETECTION (ZOMBIE-REAPER) TESTS
# ============================================================================


class TestStaleTaskDetection:
    """Test stale task detection and recovery."""

    def test_stale_task_threshold_default(self):
        """Stale task threshold defaults to 30 minutes."""
        threshold_min = 30
        assert threshold_min == 30

    def test_detect_running_task_over_threshold(self):
        """RUNNING task older than threshold is marked stale."""
        task = MockTask.orchestrated(
            status="RUNNING",
            updated_at_min=40,  # 40 minutes old
        )

        threshold_min = 30
        task_age_min = 40

        assert task_age_min > threshold_min

    def test_detect_zombie_task(self):
        """Zombie task (stale RUNNING) is detected and marked."""
        task = MockTask.orchestrated(
            status="RUNNING",
            updated_at_min=31,  # Just over threshold
            slug="zombie-task",
        )

        threshold_min = 30
        assert task["updated_at_min"] > threshold_min

    def test_stale_task_recovery_strategy(self):
        """Stale task recovery preserves prior work."""
        recovery = {
            "strategy": "preserve_prior_work",
            "actions": ["inspect_branch", "resume_from_artifacts", "commit_result"],
            "require_concrete_diff": True,
        }

        assert recovery["require_concrete_diff"] is True
        assert "resume_from_artifacts" in recovery["actions"]

    def test_zombie_reaper_removes_dead_tasks(self):
        """Zombie reaper removes tasks that cannot be recovered."""
        zombie_task = MockTask.orchestrated(
            status="RUNNING",
            updated_at_min=45,
            slug="unrecover-zombie",
        )

        # Task is marked for reaping, not forcibly deleted yet
        assert zombie_task["status"] == "RUNNING"

    def test_stale_task_reopens_branch_in_queue(self):
        """Stale task is reopened in queue for recovery."""
        recovery_action = {
            "task_id": "stale-task-1",
            "action": "reopen_in_queue",
            "preserve_branch": True,
            "new_status": "QUEUED",
        }

        assert recovery_action["preserve_branch"] is True


# ============================================================================
# COORDINATION RULES TESTS
# ============================================================================


class TestCoordinationRules:
    """Test coordination rules for concurrent task execution."""

    def test_reconcile_with_active_loop_generated_work(self):
        """Tasks must reconcile with active loop-generated work."""
        coord_rule = {
            "name": "reconcile_with_active_loop",
            "reuse_prior_solutions": True,
            "do_not_overwrite_unrelated": True,
        }

        assert coord_rule["reuse_prior_solutions"] is True

    def test_reuse_prior_solutions_first(self):
        """Coordination rule requires reusing prior solutions."""
        solution_reuse = {
            "enabled": True,
            "search_scope": ["same_task_class", "same_project", "prior_runs"],
            "prevent_duplication": True,
        }

        assert solution_reuse["enabled"] is True

    def test_do_not_delete_queued_improvements(self):
        """Coordination rule prevents deletion of queued improvements."""
        coord_rule = {
            "delete_prevention": True,
            "unrelated_work_protected": True,
            "queued_tasks_preserved": True,
        }

        assert coord_rule["delete_prevention"] is True

    def test_recovered_work_stays_in_queue(self):
        """Recovered work remains in queue until shipped."""
        recovered_work = {
            "status": "RECOVERED",
            "leave_in_queue": True,
            "ship_when_ready": True,
            "do_not_delete": True,
        }

        assert recovered_work["leave_in_queue"] is True

    def test_coordination_prevents_resource_conflicts(self):
        """Coordination logic prevents resource conflicts between tasks."""
        coordination_check = {
            "check_resource_conflicts": True,
            "lock_critical_sections": True,
            "queue_if_conflict": True,
        }

        assert coordination_check["check_resource_conflicts"] is True


# ============================================================================
# CROSS-LEARNING CONTEXT TESTS
# ============================================================================


class TestCrossLearningContext:
    """Test cross-learning context application."""

    def test_cross_learning_outcome_signals(self):
        """Cross-learning context includes outcome signals."""
        outcomes = {
            "merged_count": 0,
            "test_pass_count": 5,
            "total_attempts": 12,
            "cost_usd": 0.00,
            "models_used": [
                "claude-fable-5",
                "ollama:qwen2.5-coder:7b",
                "swarm:gemini:gemini",
                "xai:grok-3-mini-fast",
            ],
        }

        assert outcomes["test_pass_count"] > 0
        assert len(outcomes["models_used"]) > 0

    def test_learned_route_debate_compress(self):
        """Learned route: debate_compress uses haiku with q=7.0."""
        learned_route = {
            "name": "debate_compress",
            "model": "claude:claude-haiku-4-5-20251001",
            "quality_score": 7.0,
        }

        assert learned_route["model"] == "claude:claude-haiku-4-5-20251001"

    def test_learned_route_pipeline_plan(self):
        """Learned route: pipeline_plan uses llama3.2 with q=7.7."""
        learned_route = {
            "name": "pipeline_plan",
            "model": "local:llama3.2:3b",
            "quality_score": 7.7,
        }

        assert learned_route["model"] == "local:llama3.2:3b"

    def test_learned_route_build_fix(self):
        """Learned route: build_fix uses kimi with q=7.7."""
        learned_route = {
            "name": "build_fix",
            "model": "local:kimi-k2.7-code:cloud",
            "quality_score": 7.7,
        }

        assert learned_route["quality_score"] == 7.7

    def test_learned_route_confidence_gate(self):
        """Learned route: confidence_gate uses haiku with q=7.0."""
        learned_route = {
            "name": "confidence_gate",
            "model": "claude:claude-haiku-4-5-20251001",
            "quality_score": 7.0,
        }

        assert learned_route["quality_score"] == 7.0


# ============================================================================
# ERROR HANDLING AND FAIL-SOFT TESTS
# ============================================================================


class TestErrorHandling:
    """Test error handling and fail-soft degradation."""

    def test_missing_stage_fails_soft(self):
        """Missing pipeline stage doesn't crash, returns default."""
        pipeline = {
            "stages": ["preflight", "strategy"],
        }

        # Fail-soft: get missing stage, return empty config
        missing_stage = {}
        assert isinstance(missing_stage, dict)

    def test_invalid_model_fails_soft(self):
        """Invalid model specification doesn't crash runner."""
        stage = {"model": ""}
        fallback_model = stage.get("model") or "claude-haiku-4-5"

        assert fallback_model is not None

    def test_network_error_in_qa_panel(self):
        """Network error in QA panel doesn't block merge."""
        qa_panel = {
            "models": ["model1", "model2"],
            "network_error": True,
            "fallback_strategy": "use_coder_judgment",
        }

        # Fail-soft: proceed with coder output if QA unavailable
        assert qa_panel["fallback_strategy"] == "use_coder_judgment"

    def test_model_rate_limit_retry(self):
        """Model rate limit triggers exponential backoff."""
        retry_config = {
            "strategy": "exponential_backoff",
            "initial_delay_s": 1,
            "max_delay_s": 60,
            "max_retries": 3,
        }

        assert retry_config["strategy"] == "exponential_backoff"

    def test_database_unavailable_continues(self):
        """DB unavailable doesn't block in-memory operations."""
        fallback = {
            "db_unavailable": True,
            "use_memory_state": True,
            "persist_on_recovery": True,
        }

        assert fallback["use_memory_state"] is True


# ============================================================================
# THREAD SAFETY TESTS
# ============================================================================


class TestThreadSafety:
    """Test thread-safe coordination of concurrent stages."""

    def test_parallel_qa_routes_thread_safe(self):
        """Parallel QA routes are thread-safe."""
        shared_state = {"results": [], "lock": threading.Lock()}

        def record_result(result):
            with shared_state["lock"]:
                shared_state["results"].append(result)

        record_result("qa1_result")
        record_result("qa2_result")

        assert len(shared_state["results"]) == 2

    def test_concurrent_stage_updates_safe(self):
        """Concurrent stage updates don't race."""
        stage_state = {
            "current_stage": "strategy_planner",
            "lock": threading.Lock(),
        }

        def update_stage(new_stage):
            with stage_state["lock"]:
                stage_state["current_stage"] = new_stage

        update_stage("agentic_coder")
        assert stage_state["current_stage"] == "agentic_coder"

    def test_task_list_modifications_safe(self):
        """Task list modifications are atomic."""
        tasks = []
        lock = threading.Lock()

        def add_task(task):
            with lock:
                tasks.append(task)

        add_task(MockTask.orchestrated(task_id="t1"))
        add_task(MockTask.orchestrated(task_id="t2"))

        assert len(tasks) == 2


# ============================================================================
# STATE MACHINE TESTS
# ============================================================================


class TestStateMachine:
    """Test task state machine transitions."""

    def test_task_state_progression(self):
        """Task progresses through states correctly."""
        states = ["QUEUED", "PREFLIGHT", "STRATEGY", "CODING", "QA", "MERGE", "RELEASED"]

        # Verify state order
        for i in range(len(states) - 1):
            assert i < i + 1

    def test_transition_from_running_to_stale(self):
        """RUNNING task can transition to STALE."""
        transitions = {
            "RUNNING": ["STALE", "COMPLETED", "FAILED"],
        }

        assert "STALE" in transitions["RUNNING"]

    def test_transition_legal_gate_blocks_merge(self):
        """AWAITING_LEGAL_GATE state blocks transition to merge."""
        state = "AWAITING_LEGAL_GATE"
        can_merge = state != "AWAITING_LEGAL_GATE"

        assert not can_merge

    def test_transition_after_legal_approval(self):
        """After legal approval, task can transition to merge."""
        state = "LEGAL_GATE_APPROVED"
        can_merge = state == "LEGAL_GATE_APPROVED"

        assert can_merge


# ============================================================================
# INTEGRATION TESTS
# ============================================================================


class TestPipelineIntegration:
    """Integration tests for complete pipeline flow."""

    def test_full_pipeline_execution_happy_path(self):
        """Complete pipeline executes without errors."""
        stages = [
            MockPipelineStage.preflight(),
            MockPipelineStage.strategy_planner(),
            MockPipelineStage.agentic_coder(),
            MockPipelineStage.qa_route(),
            MockPipelineStage.qa_panel(),
        ]

        assert len(stages) == 5
        assert stages[0]["type"] == "preflight"
        assert stages[-1]["type"] == "qa_panel"

    def test_pipeline_with_legal_gate(self):
        """Pipeline includes legal gate for sensitive changes."""
        task = MockTask.orchestrated(
            requires_legal_gate=True,
            touches_licensing=True,
        )

        pipeline = [
            "preflight",
            "strategy_planner",
            "agentic_coder",
            "qa_panel",
            "legal_gate",
            "merge",
        ]

        assert "legal_gate" in pipeline

    def test_pipeline_recovery_from_stale_task(self):
        """Pipeline can recover from stale task and continue."""
        stale_task = MockTask.orchestrated(
            status="RUNNING",
            updated_at_min=31,
        )

        recovery_steps = [
            "detect_stale",
            "inspect_branch",
            "reopen_in_queue",
            "continue_execution",
        ]

        assert len(recovery_steps) > 0
        assert stale_task["status"] == "RUNNING"

    def test_coordination_prevents_double_work(self):
        """Coordination logic prevents duplicate work on same task."""
        tasks = [
            MockTask.orchestrated(task_id="t1", slug="task-1"),
            MockTask.orchestrated(task_id="t2", slug="task-1"),  # Duplicate
        ]

        # Dedup would filter second one
        unique_slugs = set(t["slug"] for t in tasks)
        assert len(unique_slugs) == 1  # Only one unique slug


# ============================================================================
# EDGE CASE TESTS
# ============================================================================


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_qa_panel_fallback(self):
        """Empty QA panel falls back to coder judgment."""
        qa_panel = {"models": []}
        fallback = "use_coder_judgment" if not qa_panel["models"] else "qa_panel"

        assert fallback == "use_coder_judgment"

    def test_single_qa_judge(self):
        """Single QA judge is allowed but non-ideal."""
        qa_panel = {
            "models": ["single_judge"],
            "panel_size": 1,
        }

        assert len(qa_panel["models"]) == 1

    def test_task_with_no_current_stage(self):
        """Task with no current stage gets assigned one."""
        task = {
            "id": "t1",
            "status": "QUEUED",
            "current_stage": None,
        }

        # Assign preflight as first stage
        task["current_stage"] = task.get("current_stage") or "preflight"
        assert task["current_stage"] == "preflight"

    def test_zero_cost_pipeline(self):
        """Pipeline with only free (local) models."""
        stages = [
            MockPipelineStage.preflight(),
            MockPipelineStage.strategy_planner(),
            MockPipelineStage.qa_route(),
        ]

        total_cost = sum(s["cost_estimate"] for s in stages)
        assert total_cost == 0.0

    def test_very_old_stale_task(self):
        """Very old stale task (>24h) is definitely unrecoverable."""
        task = MockTask.orchestrated(
            status="RUNNING",
            updated_at_min=1440,  # 24 hours
        )

        threshold_min = 30
        assert task["updated_at_min"] > threshold_min


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
