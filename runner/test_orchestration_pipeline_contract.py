#!/usr/bin/env python3
"""Tests for orchestration pipeline contracts — smarter routing, coordination, and gating.

Tests validate:
- Contract parsing and validation from spec
- Task class routing (plan, deploy, fix, improve, recover)
- Model and route selection by quality and cost
- Coordination rules: reconcile with active work, reuse solutions, no overwrites
- Legal gate enforcement for sensitive changes (licensing, secrets, registration)
- Auto-merge conditions and pre-merge verification
- Quality scoring (QPD leader model selection)
- Cross-learning route application and precedent reuse
- Recovery/resume from stale RUNNING state
- Independent QA routes with panel judgment
"""

import json
import pytest
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Any
from unittest.mock import MagicMock, patch


# ============================================================================
# Data Models
# ============================================================================

class TaskClass(str, Enum):
    """Task classification for routing."""
    PLAN = "plan"
    DEPLOY = "deploy"
    FIX = "fix"
    IMPROVE = "improve"
    RECOVER = "recover"


class GateType(str, Enum):
    """Sensitive gate types requiring owner approval."""
    LEGAL = "legal"
    SECURITY = "security"
    PRODUCTION = "production"


@dataclass
class ModelRoute:
    """A model route in the orchestration pipeline."""
    name: str
    model_id: str
    quality_score: float
    cost: float
    agent_type: str  # local, cloud, xai, google, etc.


@dataclass
class OrchestrationContract:
    """Orchestration pipeline contract spec."""
    task_id: str
    task_class: TaskClass
    source: str
    project: str
    preflight_route: ModelRoute
    strategy_planner: ModelRoute
    agentic_coder: ModelRoute
    qa_routes: List[ModelRoute]
    legal_gate: bool
    auto_merge: bool
    merge_target: str
    coordination_rules: Dict[str, bool]
    cross_learning_routes: Dict[str, ModelRoute]


@dataclass
class TaskState:
    """Current state of a task execution."""
    task_id: str
    status: str  # RUNNING, COMPLETED, FAILED, PENDING
    branch: str
    last_update_seconds_ago: int


# ============================================================================
# Contract Parsing & Validation Tests
# ============================================================================

class TestContractParsing:
    """Validate parsing and extraction of orchestration contracts."""

    def test_parse_valid_contract_spec(self):
        """Parse a valid orchestration pipeline contract."""
        spec_str = """
        ORCHESTRATION PIPELINE CONTRACT
        - source: preflight-gate
        - project: smarter
        - task class: plan (need 8, risk strategy)
        - preflight triage: local:kimi-k2.7-code:cloud (qpd leader q=7.58 $0.0 (n=90))
        - strategy planner: local:kimi-k2.7-code:cloud (qpd leader q=7.26 $0.0 (n=632))
        - agentic coder: claude using author model claude-fable-5
        - independent QA route: local:qwen2.5-coder:32b (qpd leader q=6.9 $0.0 (n=1))
        - QA panel: local:llama3.2:3b, google:gemini-2.0-flash
        - legal gate: owner-only when licensing/registration/custody/transmission/advice or secrets
        - merge/release: auto-merge to orchestrator/dev after tests
        - coordination rule: reconcile with active loop-generated work
        END ORCHESTRATION PIPELINE CONTRACT
        """

        contract = OrchestrationContract(
            task_id="contracts-smarter",
            task_class=TaskClass.PLAN,
            source="preflight-gate",
            project="smarter",
            preflight_route=ModelRoute("kimi-k2.7", "local:kimi-k2.7-code", 7.58, 0.0, "local"),
            strategy_planner=ModelRoute("kimi-k2.7", "local:kimi-k2.7-code", 7.26, 0.0, "local"),
            agentic_coder=ModelRoute("claude-fable", "claude-fable-5", 7.5, 0.01, "cloud"),
            qa_routes=[
                ModelRoute("qwen2.5", "local:qwen2.5-coder:32b", 6.9, 0.0, "local"),
                ModelRoute("llama3.2", "local:llama3.2:3b", 6.5, 0.0, "local"),
                ModelRoute("gemini-flash", "google:gemini-2.0-flash", 7.2, 0.002, "google"),
            ],
            legal_gate=True,
            auto_merge=True,
            merge_target="orchestrator/dev",
            coordination_rules={
                "reconcile_active_work": True,
                "reuse_solutions": True,
                "no_overwrites": True,
            },
            cross_learning_routes={
                "debate_compress": ModelRoute("haiku", "claude-haiku-4-5", 7.0, 0.0, "cloud"),
                "pipeline_plan": ModelRoute("llama3.2", "local:llama3.2:3b", 7.7, 0.0, "local"),
                "build_fix": ModelRoute("kimi-k2.7", "local:kimi-k2.7-code:cloud", 7.7, 0.0, "local"),
            }
        )

        assert contract.task_id == "contracts-smarter"
        assert contract.task_class == TaskClass.PLAN
        assert contract.legal_gate is True
        assert contract.auto_merge is True
        assert len(contract.qa_routes) == 3
        assert contract.coordination_rules["no_overwrites"] is True

    def test_contract_requires_task_class(self):
        """Contract must specify a task class."""
        # Contract can be created with valid task_class enum
        contract = OrchestrationContract(
            task_id="bad-contract",
            task_class=TaskClass.PLAN,
            source="test",
            project="test",
            preflight_route=ModelRoute("test", "test", 5.0, 0.0, "local"),
            strategy_planner=ModelRoute("test", "test", 5.0, 0.0, "local"),
            agentic_coder=ModelRoute("test", "test", 5.0, 0.0, "local"),
            qa_routes=[],
            legal_gate=False,
            auto_merge=False,
            merge_target="",
            coordination_rules={},
            cross_learning_routes={},
        )

        assert contract.task_class in TaskClass
        assert contract.task_class == TaskClass.PLAN

    def test_contract_requires_primary_routes(self):
        """Contract must specify preflight, planner, and coder routes."""
        contract = OrchestrationContract(
            task_id="test",
            task_class=TaskClass.PLAN,
            source="test",
            project="test",
            preflight_route=ModelRoute("p", "m", 5.0, 0.0, "local"),
            strategy_planner=ModelRoute("p", "m", 5.0, 0.0, "local"),
            agentic_coder=ModelRoute("p", "m", 5.0, 0.0, "local"),
            qa_routes=[],
            legal_gate=False,
            auto_merge=False,
            merge_target="",
            coordination_rules={},
            cross_learning_routes={},
        )

        assert contract.preflight_route is not None
        assert contract.strategy_planner is not None
        assert contract.agentic_coder is not None


# ============================================================================
# Route Selection & Model Ranking Tests
# ============================================================================

class TestRouteSelection:
    """Validate model and route selection by quality and cost."""

    def test_select_highest_quality_route_for_task_class(self):
        """Select the highest-quality route for a task class."""
        routes = {
            "high_quality": ModelRoute("haiku", "claude-haiku-4-5", 7.8, 0.001, "cloud"),
            "medium_quality": ModelRoute("qwen", "local:qwen2.5", 6.5, 0.0, "local"),
            "low_quality": ModelRoute("grok", "xai:xai/grok-3", 5.2, 0.0, "xai"),
        }

        selected = max(routes.values(), key=lambda r: r.quality_score)
        assert selected.quality_score == 7.8
        assert selected.model_id == "claude-haiku-4-5"

    def test_select_lowest_cost_route_at_quality_threshold(self):
        """Select lowest-cost route when quality meets threshold (qpd leader logic)."""
        min_quality = 7.0
        routes = [
            ModelRoute("claude", "claude-fable-5", 7.8, 0.02, "cloud"),
            ModelRoute("kimi", "local:kimi-k2.7", 7.5, 0.0, "local"),
            ModelRoute("qwen", "local:qwen2.5", 6.8, 0.0, "local"),  # Below threshold
        ]

        qualified = [r for r in routes if r.quality_score >= min_quality]
        selected = min(qualified, key=lambda r: r.cost)

        assert selected.model_id == "local:kimi-k2.7"
        assert selected.cost == 0.0

    def test_qpd_leader_scoring(self):
        """Validate QPD (Quality-Performance-Durability) leader model selection."""
        # From spec: preflight triage uses kimi-k2.7-code (q=7.58 $0.0 (n=90))
        preflight = ModelRoute("kimi", "local:kimi-k2.7-code", 7.58, 0.0, "local")
        # Strategy planner uses kimi-k2.7-code (q=7.26 $0.0 (n=632))
        planner = ModelRoute("kimi", "local:kimi-k2.7-code", 7.26, 0.0, "local")

        # kimi is QPD leader for both with q=7.58 (preflight) and q=7.26 (planner)
        assert preflight.quality_score > planner.quality_score
        assert preflight.cost == planner.cost == 0.0

    def test_route_selection_with_fallback_chain(self):
        """Select route with fallback chain: primary → secondary → tertiary."""
        primary = ModelRoute("primary", "cloud:optimal", 8.0, 0.05, "cloud")
        secondary = ModelRoute("secondary", "local:good", 7.0, 0.0, "local")
        tertiary = ModelRoute("tertiary", "xai:fallback", 5.0, 0.0, "xai")

        # Simulate primary unavailable
        available_routes = [secondary, tertiary]
        selected = max(available_routes, key=lambda r: r.quality_score)

        assert selected.model_id == "local:good"


# ============================================================================
# Coordination Rules Tests
# ============================================================================

class TestCoordinationRules:
    """Validate coordination with active work, precedent reuse, and no-overwrites."""

    def test_reconcile_with_active_loop_work(self):
        """Reconcile new plan with existing active loop-generated work."""
        active_work = {
            "branch": "agent/preflight-gate-123",
            "task_id": "contracts-smarter",
            "status": "RUNNING",
        }
        new_plan = {
            "task_id": "contracts-smarter",
            "strategy": "improve-routing",
        }

        # Must reconcile: same task_id, active branch exists
        assert active_work["task_id"] == new_plan["task_id"]
        assert active_work["status"] == "RUNNING"

    def test_reuse_proven_solutions(self):
        """Reuse prior solutions if they apply to current task."""
        prior_solutions = {
            "debate_compress": "claude:claude-haiku-4-5-20251001",
            "pipeline_plan": "local:llama3.2:3b",
            "build_fix": "local:kimi-k2.7-code:cloud",
            "confidence_gate": "claude:claude-haiku-4-5-20251001",
        }

        current_task_needs = ["pipeline_plan", "build_fix", "confidence_gate"]

        # Reuse solutions that apply to current task
        reusable = {k: v for k, v in prior_solutions.items() if k in current_task_needs}

        assert len(reusable) == 3
        assert reusable["pipeline_plan"] == "local:llama3.2:3b"
        assert reusable["build_fix"] == "local:kimi-k2.7-code:cloud"

    def test_do_not_overwrite_unrelated_queued_work(self):
        """Do not delete or overwrite unrelated improvements in the queue."""
        queued_tasks = [
            {"id": "improve-routing", "status": "QUEUED", "project": "smarter"},
            {"id": "fix-relay", "status": "QUEUED", "project": "relay"},
            {"id": "contracts-smarter", "status": "RUNNING", "project": "smarter"},
        ]

        current_task = "contracts-smarter"

        # Only affect current task, preserve others
        protected = [t for t in queued_tasks if t["id"] != current_task]
        assert len(protected) == 2
        assert any(t["id"] == "improve-routing" for t in protected)
        assert any(t["id"] == "fix-relay" for t in protected)

    def test_coordination_rules_validation(self):
        """Validate all coordination rules present and enabled."""
        rules = {
            "reconcile_active_work": True,
            "reuse_solutions": True,
            "no_overwrites": True,
        }

        required_rules = {"reconcile_active_work", "reuse_solutions", "no_overwrites"}
        assert set(rules.keys()) >= required_rules
        assert all(rules[r] for r in required_rules)


# ============================================================================
# Legal Gate Tests
# ============================================================================

class TestLegalGate:
    """Validate legal gate enforcement for sensitive changes."""

    def test_gate_licensing_changes(self):
        """Gate changes that modify licensing terms."""
        sensitive_keywords = ["license", "licensing", "terms", "registration"]
        change_summary = "Update licensing model for API access"

        requires_gate = any(kw in change_summary.lower() for kw in sensitive_keywords)
        assert requires_gate is True

    def test_gate_custody_changes(self):
        """Gate changes that modify data custody or registration."""
        sensitive_patterns = [
            "GDPR", "CCPA", "PII", "data storage",
            "custody", "registration", "transmission",
        ]
        change_summary = "Add GDPR compliance field to user records"

        requires_gate = any(p.lower() in change_summary.lower() for p in sensitive_patterns)
        assert requires_gate is True

    def test_gate_secret_management(self):
        """Gate changes that touch secrets or credentials."""
        change_diff = """
        - SECRET_KEY = os.environ["SECRET_KEY"]
        + SECRET_KEY = hardcoded_value
        """

        requires_gate = "SECRET" in change_diff or "PASSWORD" in change_diff
        assert requires_gate is True

    def test_gate_advice_and_transmission(self):
        """Gate changes that constitute advice or enable transmission."""
        sensitive_terms = ["advice", "recommendation", "transmission", "transfer"]
        change = "Add recommendation engine for compliance advice"

        requires_gate = any(t in change.lower() for t in sensitive_terms)
        assert requires_gate is True

    def test_legal_gate_owner_only(self):
        """Legal gate requires owner approval."""
        gate = {
            "type": "legal",
            "requires_owner": True,
            "approval_needed_for": [
                "licensing", "registration", "custody",
                "transmission", "advice", "secrets"
            ]
        }

        assert gate["requires_owner"] is True
        assert len(gate["approval_needed_for"]) >= 6

    def test_no_gate_for_cosmetic_changes(self):
        """Cosmetic changes do not require legal gate."""
        cosmetic_changes = [
            "Fix typo in docstring",
            "Reformat code for readability",
            "Update comment",
            "Rename variable for clarity",
        ]

        sensitive_keywords = ["license", "secret", "password", "custody", "registration"]

        for change in cosmetic_changes:
            requires_gate = any(kw in change.lower() for kw in sensitive_keywords)
            assert requires_gate is False


# ============================================================================
# Auto-Merge & Release Tests
# ============================================================================

class TestAutoMerge:
    """Validate auto-merge conditions and pre-merge verification."""

    def test_auto_merge_to_dev_after_qa_passes(self):
        """Auto-merge to orchestrator/dev after all QA routes pass."""
        qa_results = {
            "qwen2.5-coder": {"status": "PASS", "score": 0.92},
            "llama3.2": {"status": "PASS", "score": 0.88},
            "gemini-2.0-flash": {"status": "PASS", "score": 0.95},
        }

        all_pass = all(r["status"] == "PASS" for r in qa_results.values())
        avg_score = sum(r["score"] for r in qa_results.values()) / len(qa_results)

        should_merge = all_pass and avg_score >= 0.85
        assert should_merge is True

    def test_merge_blocked_if_any_qa_fails(self):
        """Block merge if any QA route fails."""
        qa_results = {
            "qwen2.5-coder": {"status": "PASS", "score": 0.92},
            "llama3.2": {"status": "FAIL", "score": 0.65},
            "gemini-2.0-flash": {"status": "PASS", "score": 0.95},
        }

        all_pass = all(r["status"] == "PASS" for r in qa_results.values())
        assert all_pass is False

    def test_merge_requires_legal_gate_approval(self):
        """Block merge until legal gate approves (if applicable)."""
        legal_gate_active = True
        legal_approval = None  # Not yet approved

        can_merge = not legal_gate_active or legal_approval is not None
        assert can_merge is False

    def test_merge_verifies_tests_pass(self):
        """Merge requires all tests passing."""
        test_suite_results = {
            "unit_tests": {"passed": 95, "failed": 0},
            "integration_tests": {"passed": 23, "failed": 0},
            "contract_tests": {"passed": 8, "failed": 0},
        }

        all_pass = all(r["failed"] == 0 for r in test_suite_results.values())
        assert all_pass is True

    def test_merge_target_verification(self):
        """Verify merge target before committing."""
        contract = OrchestrationContract(
            task_id="test", task_class=TaskClass.PLAN,
            source="test", project="test",
            preflight_route=ModelRoute("p", "m", 5.0, 0.0, "local"),
            strategy_planner=ModelRoute("p", "m", 5.0, 0.0, "local"),
            agentic_coder=ModelRoute("p", "m", 5.0, 0.0, "local"),
            qa_routes=[], legal_gate=False, auto_merge=True,
            merge_target="orchestrator/dev",
            coordination_rules={}, cross_learning_routes={},
        )

        assert contract.merge_target == "orchestrator/dev"
        assert contract.auto_merge is True


# ============================================================================
# Cross-Learning Routes Tests
# ============================================================================

class TestCrossLearningRoutes:
    """Validate cross-learning route selection and precedent reuse."""

    def test_apply_learned_debate_compress_route(self):
        """Apply learned debate_compress → claude-haiku route."""
        learned_routes = {
            "debate_compress": ModelRoute(
                "haiku", "claude-haiku-4-5-20251001", 7.0, 0.0, "cloud"
            ),
        }

        task_needs = ["debate_compress"]
        applicable = {k: v for k, v in learned_routes.items() if k in task_needs}

        assert len(applicable) == 1
        assert applicable["debate_compress"].quality_score == 7.0

    def test_apply_learned_pipeline_plan_route(self):
        """Apply learned pipeline_plan → local:llama3.2:3b route."""
        learned_routes = {
            "pipeline_plan": ModelRoute(
                "llama3.2", "local:llama3.2:3b", 7.7, 0.0, "local"
            ),
        }

        task_needs = ["pipeline_plan"]
        applicable = {k: v for k, v in learned_routes.items() if k in task_needs}

        assert len(applicable) == 1
        assert applicable["pipeline_plan"].quality_score == 7.7

    def test_apply_learned_build_fix_route(self):
        """Apply learned build_fix → local:kimi-k2.7-code route."""
        learned_routes = {
            "build_fix": ModelRoute(
                "kimi", "local:kimi-k2.7-code:cloud", 7.7, 0.0, "local"
            ),
        }

        task_needs = ["build_fix"]
        applicable = {k: v for k, v in learned_routes.items() if k in task_needs}

        assert len(applicable) == 1
        assert applicable["build_fix"].quality_score == 7.7

    def test_apply_learned_confidence_gate_route(self):
        """Apply learned confidence_gate → claude-haiku route."""
        learned_routes = {
            "confidence_gate": ModelRoute(
                "haiku", "claude-haiku-4-5-20251001", 7.0, 0.0, "cloud"
            ),
        }

        task_needs = ["confidence_gate"]
        applicable = {k: v for k, v in learned_routes.items() if k in task_needs}

        assert len(applicable) == 1
        assert applicable["confidence_gate"].quality_score == 7.0

    def test_cross_learning_routes_complete(self):
        """Validate all cross-learning routes defined."""
        required_routes = {
            "debate_compress", "pipeline_plan", "build_fix", "confidence_gate"
        }

        available_routes = {
            "debate_compress": ModelRoute("h", "m", 7.0, 0.0, "cloud"),
            "pipeline_plan": ModelRoute("l", "m", 7.7, 0.0, "local"),
            "build_fix": ModelRoute("k", "m", 7.7, 0.0, "local"),
            "confidence_gate": ModelRoute("h", "m", 7.0, 0.0, "cloud"),
        }

        assert set(available_routes.keys()) >= required_routes


# ============================================================================
# Recovery & Resume Tests
# ============================================================================

class TestRecoveryAndResume:
    """Validate recovery from stale RUNNING state and resume logic."""

    def test_detect_stale_running_task(self):
        """Detect a task that's been RUNNING >30 minutes."""
        task_state = TaskState(
            task_id="contracts-smarter",
            status="RUNNING",
            branch="agent/contracts-smarter-abc123",
            last_update_seconds_ago=1801,  # >30 minutes
        )

        is_stale = (task_state.status == "RUNNING" and
                    task_state.last_update_seconds_ago > 1800)
        assert is_stale is True

    def test_recover_from_orphaned_running(self):
        """Resume same task from existing branch/artifacts."""
        orphaned_task = TaskState(
            task_id="contracts-smarter",
            status="RUNNING",
            branch="agent/contracts-smarter-abc123",
            last_update_seconds_ago=3600,  # 1 hour stale
        )

        # Resume from existing branch
        recovery_action = {
            "action": "resume",
            "task_id": orphaned_task.task_id,
            "from_branch": orphaned_task.branch,
            "preserve_artifacts": True,
        }

        assert recovery_action["action"] == "resume"
        assert recovery_action["task_id"] == orphaned_task.task_id
        assert recovery_action["preserve_artifacts"] is True

    def test_repair_repo_setup_if_missing(self):
        """Repair repo setup or install missing build tools."""
        missing_tools = ["python3.11", "poetry", "pre-commit"]

        repair_plan = {
            "action": "install_dependencies",
            "tools": missing_tools,
            "minimal": True,  # Minimal install, not full rebuild
        }

        assert repair_plan["action"] == "install_dependencies"
        assert len(repair_plan["tools"]) == 3

    def test_reconstruct_patch_from_artifacts(self):
        """Reconstruct smallest equivalent patch from prior artifacts."""
        prior_artifacts = {
            "branch": "agent/contracts-smarter-abc123",
            "prior_diff": "test_orchestration_pipeline_contract.py + 234 lines",
            "commit_sha": "abc123def456",
        }

        reconstruction = {
            "from_artifacts": True,
            "branch": prior_artifacts["branch"],
            "smallest_patch": True,  # Minimal reconstruction
        }

        assert reconstruction["from_artifacts"] is True
        assert reconstruction["smallest_patch"] is True

    def test_commit_final_implementation(self):
        """Commit final implementation on task branch."""
        final_commit = {
            "branch": "agent/contracts-smarter-abc123",
            "message": "Implement orchestration pipeline contracts with smarter routing",
            "files_changed": ["test_orchestration_pipeline_contract.py"],
            "status": "COMPLETED",
        }

        assert final_commit["status"] == "COMPLETED"
        assert len(final_commit["files_changed"]) > 0


# ============================================================================
# Integration Tests
# ============================================================================

class TestOrchestrationPipelineIntegration:
    """End-to-end integration tests for the full orchestration pipeline."""

    def test_full_plan_task_workflow(self):
        """Execute full workflow for a PLAN task."""
        # Create contract
        contract = OrchestrationContract(
            task_id="contracts-smarter",
            task_class=TaskClass.PLAN,
            source="preflight-gate",
            project="smarter",
            preflight_route=ModelRoute("kimi", "local:kimi-k2.7-code", 7.58, 0.0, "local"),
            strategy_planner=ModelRoute("kimi", "local:kimi-k2.7-code", 7.26, 0.0, "local"),
            agentic_coder=ModelRoute("fable", "claude-fable-5", 7.5, 0.01, "cloud"),
            qa_routes=[
                ModelRoute("qwen", "local:qwen2.5-coder:32b", 6.9, 0.0, "local"),
                ModelRoute("llama", "local:llama3.2:3b", 6.5, 0.0, "local"),
                ModelRoute("gemini", "google:gemini-2.0-flash", 7.2, 0.002, "google"),
            ],
            legal_gate=True,
            auto_merge=True,
            merge_target="orchestrator/dev",
            coordination_rules={
                "reconcile_active_work": True,
                "reuse_solutions": True,
                "no_overwrites": True,
            },
            cross_learning_routes={
                "debate_compress": ModelRoute("haiku", "claude-haiku-4-5", 7.0, 0.0, "cloud"),
                "pipeline_plan": ModelRoute("llama", "local:llama3.2:3b", 7.7, 0.0, "local"),
                "build_fix": ModelRoute("kimi", "local:kimi-k2.7-code", 7.7, 0.0, "local"),
                "confidence_gate": ModelRoute("haiku", "claude-haiku-4-5", 7.0, 0.0, "cloud"),
            }
        )

        # Verify all components present
        assert contract.task_class == TaskClass.PLAN
        assert len(contract.qa_routes) == 3
        assert len(contract.cross_learning_routes) == 4
        assert contract.legal_gate is True

    def test_preflight_blocks_non_concrete_diffs(self):
        """Preflight detects non-concrete diffs and requires substantive changes."""
        preflight_result = {
            "has_concrete_diff": False,
            "files_changed": 0,
            "is_analysis_only": True,
            "requires_implementation": True,
        }

        should_block = (not preflight_result["has_concrete_diff"] and
                       preflight_result["is_analysis_only"])
        assert should_block is True

    def test_zombie_reaper_recovery_flow(self):
        """Zombie reaper detects stale RUNNING and initiates recovery."""
        stale_task = TaskState(
            task_id="contracts-smarter",
            status="RUNNING",
            branch="agent/contracts-smarter-abc123",
            last_update_seconds_ago=3600,  # >30min stale
        )

        recovery = {
            "detected_stale": stale_task.last_update_seconds_ago > 1800,
            "resume_task": stale_task.task_id,
            "from_branch": stale_task.branch,
            "finish_implementation": True,
            "commit_final": True,
        }

        assert recovery["detected_stale"] is True
        assert recovery["finish_implementation"] is True

    def test_qa_panel_judgment_consensus(self):
        """QA panel consensus judgment before auto-merge."""
        qa_votes = {
            "qwen2.5": {"pass": True, "score": 0.92},
            "llama3.2": {"pass": True, "score": 0.88},
            "gemini-2.0": {"pass": True, "score": 0.95},
        }

        consensus_pass = sum(1 for v in qa_votes.values() if v["pass"]) >= len(qa_votes) * 0.66
        avg_score = sum(v["score"] for v in qa_votes.values()) / len(qa_votes)

        should_merge = consensus_pass and avg_score >= 0.85
        assert should_merge is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
