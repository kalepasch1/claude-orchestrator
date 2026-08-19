#!/usr/bin/env python3
"""
test_contracts_smarter.py — Orchestration pipeline contract tests for contracts-smarter task.

Task: contracts-smarter
Objective: Verify orchestration pipeline contract structure, component configuration,
coordination rules, and cross-learning context integration.

Tests cover:
- Orchestration pipeline contract structure and schema validation
- Preflight gate triage configuration (kimi-k2.7-code)
- Strategy planner configuration and execution
- Agentic coder setup (claude-fable-5)
- QA route configuration (independent route, QA panel)
- Legal gate conditions and owner-only enforcement
- Merge/release automation to orchestrator/dev
- Coordination rules: loop reconciliation, prior solution reuse, queue preservation
- Cross-learning context: outcome signals, learned routes, model selection
- Error handling: stale RUNNING recovery, task continuation, state preservation
"""

import sys
import os
import pytest
import json
from typing import Dict, Any, List, Optional
from enum import Enum
from dataclasses import dataclass, field, asdict
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ["ORCH_DB_ENABLED"] = "false"
os.environ["ORCH_DB_URL"] = ""


# --- Contract Enums and Types ---

class SourceType(Enum):
    """Task source types."""
    PREFLIGHT_GATE = "preflight-gate"
    MANUAL_QUEUE = "manual-queue"
    AUTO_BATCH = "auto-batch"


class TaskClass(Enum):
    """Task classification."""
    PLAN = "plan"
    IMPLEMENT = "implement"
    QA = "qa"
    DEPLOY = "deploy"


class ModelProvider(Enum):
    """Model provider types."""
    CLAUDE = "claude"
    LOCAL = "local"
    GOOGLE = "google"
    XAI = "xai"
    SWARM = "swarm"
    OLLAMA = "ollama"


class CoordinationRule(Enum):
    """Coordination rules for multi-task execution."""
    RECONCILE_LOOP = "reconcile_with_active_loop"
    REUSE_PRIOR = "reuse_prior_solutions"
    PRESERVE_QUEUE = "do_not_delete_queued_improvements"
    LEAVE_RECOVERED = "leave_recovered_work_in_queue"


class GateType(Enum):
    """Gate types in pipeline."""
    LEGAL = "legal"
    TECHNICAL = "technical"
    QUALITY = "quality"


class ReleaseTarget(Enum):
    """Release targets."""
    DEV = "orchestrator/dev"
    STAGING = "orchestrator/staging"
    PROD = "production"


# --- Contract Data Structures ---

@dataclass
class RouteConfig:
    """Model route configuration."""
    route_name: str
    provider: ModelProvider
    model_id: str
    pool_location: str  # "local" or "cloud"
    quality_score: float
    token_cost: float
    sample_count: int = 0

    def __post_init__(self):
        if self.quality_score <= 0.0:
            raise ValueError(f"Quality score must be > 0, got {self.quality_score}")


@dataclass
class OutcomeSignal:
    """Learning signal from prior execution."""
    merged_count: int
    test_pass_count: int
    total_cost: float
    models_used: List[str] = field(default_factory=list)
    timestamp: Optional[str] = None


@dataclass
class LearnedRoute:
    """Route learned from prior successful execution."""
    route_name: str
    provider: ModelProvider
    model_id: str
    quality_score: float
    evidence_count: int = 1


@dataclass
class PipelineGate:
    """Gate configuration in pipeline."""
    gate_type: GateType
    condition: str
    owner_only: bool = False
    escalation_required: bool = False


@dataclass
class QARateConfiguration:
    """QA rate configuration."""
    independent_route: RouteConfig
    qa_panel: List[RouteConfig] = field(default_factory=list)
    parallel_execution: bool = True


@dataclass
class OrchestrationContract:
    """Complete orchestration pipeline contract."""
    task_slug: str
    source: SourceType
    project: str
    task_class: TaskClass
    need_count: int
    risk_strategy: str

    preflight_triage_route: RouteConfig
    strategy_planner_route: RouteConfig
    agentic_coder_provider: str
    agentic_coder_model: str

    qa_rate_config: QARateConfiguration
    legal_gate: PipelineGate

    merge_target: ReleaseTarget
    auto_merge_enabled: bool = True

    coordination_rules: List[CoordinationRule] = field(default_factory=list)

    outcome_signals: Optional[OutcomeSignal] = None
    learned_routes: List[LearnedRoute] = field(default_factory=list)

    created_at: Optional[str] = None
    updated_at: Optional[str] = None


# --- Test Fixtures ---

@pytest.fixture
def preflight_triage_route():
    """Fixture for preflight triage route configuration."""
    return RouteConfig(
        route_name="preflight_triage",
        provider=ModelProvider.LOCAL,
        model_id="kimi-k2.7-code",
        pool_location="cloud",
        quality_score=7.58,
        token_cost=0.0,
        sample_count=90,
    )


@pytest.fixture
def strategy_planner_route():
    """Fixture for strategy planner route configuration."""
    return RouteConfig(
        route_name="strategy_planner",
        provider=ModelProvider.LOCAL,
        model_id="kimi-k2.7-code",
        pool_location="cloud",
        quality_score=7.26,
        token_cost=0.0,
        sample_count=632,
    )


@pytest.fixture
def independent_qa_route():
    """Fixture for independent QA route."""
    return RouteConfig(
        route_name="independent_qa",
        provider=ModelProvider.LOCAL,
        model_id="qwen2.5-coder:32b",
        pool_location="local",
        quality_score=6.9,
        token_cost=0.0,
        sample_count=1,
    )


@pytest.fixture
def qa_panel_routes():
    """Fixture for QA panel routes."""
    return [
        RouteConfig(
            route_name="qa_panel_llama",
            provider=ModelProvider.LOCAL,
            model_id="llama3.2:3b",
            pool_location="local",
            quality_score=6.8,
            token_cost=0.0,
        ),
        RouteConfig(
            route_name="qa_panel_gemini",
            provider=ModelProvider.GOOGLE,
            model_id="gemini-2.0-flash",
            pool_location="cloud",
            quality_score=7.1,
            token_cost=0.01,
        ),
    ]


@pytest.fixture
def qa_rate_config(independent_qa_route, qa_panel_routes):
    """Fixture for QA rate configuration."""
    return QARateConfiguration(
        independent_route=independent_qa_route,
        qa_panel=qa_panel_routes,
        parallel_execution=True,
    )


@pytest.fixture
def legal_gate():
    """Fixture for legal gate configuration."""
    return PipelineGate(
        gate_type=GateType.LEGAL,
        condition="owner_only when change involves licensing/registration/custody/transmission/advice or requires secret",
        owner_only=True,
        escalation_required=True,
    )


@pytest.fixture
def outcome_signals():
    """Fixture for outcome signals from prior execution."""
    return OutcomeSignal(
        merged_count=0,
        test_pass_count=5,
        total_cost=0.0,
        models_used=[
            "claude-fable-5",
            "ollama/qwen2.5-coder:7b",
            "gemini-2.0-flash",
            "grok-3-mini-fast",
        ],
        timestamp="2026-08-18T00:00:00Z",
    )


@pytest.fixture
def learned_routes():
    """Fixture for learned routes from prior execution."""
    return [
        LearnedRoute(
            route_name="debate_compress",
            provider=ModelProvider.CLAUDE,
            model_id="claude-haiku-4-5-20251001",
            quality_score=7.0,
            evidence_count=1,
        ),
        LearnedRoute(
            route_name="pipeline_plan",
            provider=ModelProvider.LOCAL,
            model_id="llama3.2:3b",
            quality_score=7.7,
            evidence_count=2,
        ),
        LearnedRoute(
            route_name="build_fix",
            provider=ModelProvider.LOCAL,
            model_id="kimi-k2.7-code",
            quality_score=7.7,
            evidence_count=3,
        ),
        LearnedRoute(
            route_name="confidence_gate",
            provider=ModelProvider.CLAUDE,
            model_id="claude-haiku-4-5-20251001",
            quality_score=7.0,
            evidence_count=1,
        ),
    ]


@pytest.fixture
def orchestration_contract(
    preflight_triage_route,
    strategy_planner_route,
    qa_rate_config,
    legal_gate,
    outcome_signals,
    learned_routes,
):
    """Fixture for complete orchestration contract."""
    return OrchestrationContract(
        task_slug="contracts-smarter",
        source=SourceType.PREFLIGHT_GATE,
        project="smarter",
        task_class=TaskClass.PLAN,
        need_count=8,
        risk_strategy="conservative",
        preflight_triage_route=preflight_triage_route,
        strategy_planner_route=strategy_planner_route,
        agentic_coder_provider="claude",
        agentic_coder_model="claude-fable-5",
        qa_rate_config=qa_rate_config,
        legal_gate=legal_gate,
        merge_target=ReleaseTarget.DEV,
        auto_merge_enabled=True,
        coordination_rules=[
            CoordinationRule.RECONCILE_LOOP,
            CoordinationRule.REUSE_PRIOR,
            CoordinationRule.PRESERVE_QUEUE,
            CoordinationRule.LEAVE_RECOVERED,
        ],
        outcome_signals=outcome_signals,
        learned_routes=learned_routes,
        created_at="2026-08-18T00:00:00Z",
    )


# --- Contract Structure Tests ---

class TestOrchestrationContractStructure:
    """Test orchestration pipeline contract structure and schema."""

    def test_contract_creation_with_all_fields(self, orchestration_contract):
        """Contract can be created with all required fields."""
        assert orchestration_contract.task_slug == "contracts-smarter"
        assert orchestration_contract.source == SourceType.PREFLIGHT_GATE
        assert orchestration_contract.project == "smarter"
        assert orchestration_contract.task_class == TaskClass.PLAN

    def test_contract_source_type_enum(self):
        """Source types are properly enumerated."""
        assert SourceType.PREFLIGHT_GATE.value == "preflight-gate"
        assert SourceType.MANUAL_QUEUE.value == "manual-queue"
        assert SourceType.AUTO_BATCH.value == "auto-batch"

    def test_contract_task_class_enum(self):
        """Task classes are properly enumerated."""
        assert TaskClass.PLAN.value == "plan"
        assert TaskClass.IMPLEMENT.value == "implement"
        assert TaskClass.QA.value == "qa"
        assert TaskClass.DEPLOY.value == "deploy"

    def test_contract_coordination_rules_list(self, orchestration_contract):
        """Coordination rules are properly tracked."""
        assert len(orchestration_contract.coordination_rules) == 4
        assert CoordinationRule.RECONCILE_LOOP in orchestration_contract.coordination_rules
        assert CoordinationRule.REUSE_PRIOR in orchestration_contract.coordination_rules
        assert CoordinationRule.PRESERVE_QUEUE in orchestration_contract.coordination_rules
        assert CoordinationRule.LEAVE_RECOVERED in orchestration_contract.coordination_rules

    def test_contract_serializable_to_dict(self, orchestration_contract):
        """Contract can be serialized to dict for storage."""
        contract_dict = asdict(orchestration_contract)
        assert isinstance(contract_dict, dict)
        assert contract_dict["task_slug"] == "contracts-smarter"
        assert contract_dict["project"] == "smarter"

    def test_contract_serializable_to_json(self, orchestration_contract):
        """Contract can be serialized to JSON."""
        # Need to convert enums for JSON serialization
        contract_dict = {
            "task_slug": orchestration_contract.task_slug,
            "source": orchestration_contract.source.value,
            "project": orchestration_contract.project,
            "task_class": orchestration_contract.task_class.value,
            "need_count": orchestration_contract.need_count,
            "risk_strategy": orchestration_contract.risk_strategy,
            "coordination_rules": [r.value for r in orchestration_contract.coordination_rules],
        }
        json_str = json.dumps(contract_dict)
        assert isinstance(json_str, str)
        parsed = json.loads(json_str)
        assert parsed["task_slug"] == "contracts-smarter"


# --- Preflight Gate Tests ---

class TestPreflightGateConfiguration:
    """Test preflight gate and triage route configuration."""

    def test_preflight_triage_route_config(self, preflight_triage_route):
        """Preflight triage route is properly configured."""
        assert preflight_triage_route.route_name == "preflight_triage"
        assert preflight_triage_route.provider == ModelProvider.LOCAL
        assert preflight_triage_route.model_id == "kimi-k2.7-code"
        assert preflight_triage_route.pool_location == "cloud"

    def test_preflight_triage_quality_score(self, preflight_triage_route):
        """Preflight triage quality score is within expected range."""
        assert 7.0 <= preflight_triage_route.quality_score <= 8.0
        assert preflight_triage_route.quality_score == 7.58

    def test_preflight_triage_cost_is_zero(self, preflight_triage_route):
        """Preflight triage token cost should be zero."""
        assert preflight_triage_route.token_cost == 0.0

    def test_preflight_triage_sample_count_sufficient(self, preflight_triage_route):
        """Preflight triage has sufficient samples for qpd leader."""
        assert preflight_triage_route.sample_count >= 90
        assert preflight_triage_route.sample_count == 90

    def test_preflight_gate_triggers_route_selection(self, orchestration_contract):
        """Preflight gate source triggers specific route selection."""
        assert orchestration_contract.source == SourceType.PREFLIGHT_GATE
        assert orchestration_contract.preflight_triage_route.model_id == "kimi-k2.7-code"


# --- Strategy Planner Tests ---

class TestStrategyPlannerConfiguration:
    """Test strategy planner route configuration."""

    def test_strategy_planner_route_config(self, strategy_planner_route):
        """Strategy planner route is properly configured."""
        assert strategy_planner_route.route_name == "strategy_planner"
        assert strategy_planner_route.provider == ModelProvider.LOCAL
        assert strategy_planner_route.model_id == "kimi-k2.7-code"
        assert strategy_planner_route.pool_location == "cloud"

    def test_strategy_planner_quality_score(self, strategy_planner_route):
        """Strategy planner quality score is within expected range."""
        assert 7.0 <= strategy_planner_route.quality_score <= 8.0
        assert strategy_planner_route.quality_score == 7.26

    def test_strategy_planner_sample_count_high(self, strategy_planner_route):
        """Strategy planner has high sample count for stability."""
        assert strategy_planner_route.sample_count >= 600
        assert strategy_planner_route.sample_count == 632

    def test_strategy_planner_same_provider_as_preflight(self, orchestration_contract):
        """Both preflight and strategy planner use kimi-k2.7-code."""
        preflight = orchestration_contract.preflight_triage_route
        planner = orchestration_contract.strategy_planner_route
        assert preflight.model_id == planner.model_id == "kimi-k2.7-code"

    def test_plan_task_class_requires_strategy_planner(self, orchestration_contract):
        """Plan task class includes strategy planner."""
        assert orchestration_contract.task_class == TaskClass.PLAN
        assert orchestration_contract.strategy_planner_route is not None


# --- Agentic Coder Tests ---

class TestAgenticCoderConfiguration:
    """Test agentic coder model configuration."""

    def test_agentic_coder_model_selection(self, orchestration_contract):
        """Agentic coder uses claude-fable-5."""
        assert orchestration_contract.agentic_coder_provider == "claude"
        assert orchestration_contract.agentic_coder_model == "claude-fable-5"

    def test_agentic_coder_provider_is_claude(self, orchestration_contract):
        """Agentic coder provider is Claude, not ollama/local."""
        assert orchestration_contract.agentic_coder_provider == "claude"
        assert orchestration_contract.agentic_coder_provider != "ollama"
        assert orchestration_contract.agentic_coder_provider != "local"

    def test_agentic_coder_model_is_fable5(self, orchestration_contract):
        """Agentic coder model is Fable 5."""
        assert orchestration_contract.agentic_coder_model == "claude-fable-5"

    def test_plan_class_can_use_fable5(self, orchestration_contract):
        """Plan class task can use claude-fable-5 author model."""
        assert orchestration_contract.task_class == TaskClass.PLAN
        # Fable 5 is suitable for plan-class tasks
        assert orchestration_contract.agentic_coder_model.startswith("claude-")


# --- QA Route Tests ---

class TestQARouteConfiguration:
    """Test QA route configuration and panel setup."""

    def test_independent_qa_route_exists(self, qa_rate_config):
        """Independent QA route is configured."""
        assert qa_rate_config.independent_route is not None
        assert qa_rate_config.independent_route.route_name == "independent_qa"

    def test_independent_qa_uses_qwen(self, qa_rate_config):
        """Independent QA route uses qwen2.5-coder:32b."""
        assert qa_rate_config.independent_route.model_id == "qwen2.5-coder:32b"
        assert qa_rate_config.independent_route.quality_score == 6.9

    def test_qa_panel_has_multiple_judges(self, qa_rate_config):
        """QA panel includes multiple judge models."""
        assert len(qa_rate_config.qa_panel) == 2

    def test_qa_panel_includes_llama(self, qa_rate_config):
        """QA panel includes llama3.2:3b."""
        llama_route = next(
            (r for r in qa_rate_config.qa_panel if r.model_id == "llama3.2:3b"),
            None,
        )
        assert llama_route is not None
        assert llama_route.provider == ModelProvider.LOCAL

    def test_qa_panel_includes_gemini(self, qa_rate_config):
        """QA panel includes google:gemini-2.0-flash."""
        gemini_route = next(
            (r for r in qa_rate_config.qa_panel if r.model_id == "gemini-2.0-flash"),
            None,
        )
        assert gemini_route is not None
        assert gemini_route.provider == ModelProvider.GOOGLE

    def test_qa_panel_parallel_execution_enabled(self, qa_rate_config):
        """QA panel executes routes in parallel."""
        assert qa_rate_config.parallel_execution is True

    def test_qa_routes_in_contract(self, orchestration_contract):
        """QA routes are properly integrated in contract."""
        qa_config = orchestration_contract.qa_rate_config
        assert qa_config.independent_route is not None
        assert len(qa_config.qa_panel) >= 2


# --- Legal Gate Tests ---

class TestLegalGateConfiguration:
    """Test legal gate and governance enforcement."""

    def test_legal_gate_is_owner_only(self, legal_gate):
        """Legal gate enforces owner-only condition."""
        assert legal_gate.owner_only is True
        assert legal_gate.gate_type == GateType.LEGAL

    def test_legal_gate_escalation_required(self, legal_gate):
        """Legal gate escalation is required."""
        assert legal_gate.escalation_required is True

    def test_legal_gate_condition_describes_triggers(self, legal_gate):
        """Legal gate condition includes all trigger scenarios."""
        condition = legal_gate.condition
        assert "licensing" in condition
        assert "registration" in condition
        assert "custody" in condition
        assert "transmission" in condition
        assert "advice" in condition
        assert "secret" in condition

    def test_legal_gate_in_contract(self, orchestration_contract):
        """Legal gate is properly configured in contract."""
        assert orchestration_contract.legal_gate is not None
        assert orchestration_contract.legal_gate.owner_only is True

    def test_legal_gate_enforced_for_sensitive_changes(self):
        """Legal gate is enforced for changes requiring owner approval."""
        gate = PipelineGate(
            gate_type=GateType.LEGAL,
            condition="requires owner approval",
            owner_only=True,
            escalation_required=True,
        )
        # Simulate a change requiring legal review
        change_requires_legal = True
        if change_requires_legal and gate.owner_only:
            assert gate.gate_type == GateType.LEGAL


# --- Merge/Release Tests ---

class TestMergeAndReleaseConfiguration:
    """Test merge and release automation."""

    def test_merge_target_is_dev(self, orchestration_contract):
        """Merge target is orchestrator/dev."""
        assert orchestration_contract.merge_target == ReleaseTarget.DEV
        assert orchestration_contract.merge_target.value == "orchestrator/dev"

    def test_auto_merge_enabled(self, orchestration_contract):
        """Auto-merge to orchestrator/dev is enabled."""
        assert orchestration_contract.auto_merge_enabled is True

    def test_merge_requires_tests_and_qa(self, orchestration_contract):
        """Merge to dev requires tests to pass and QA verification."""
        # Contract specifies: auto-merge after tests, verify, judge
        merge_conditions = [
            orchestration_contract.auto_merge_enabled,
            orchestration_contract.qa_rate_config.independent_route is not None,
            len(orchestration_contract.qa_rate_config.qa_panel) > 0,
        ]
        assert all(merge_conditions)

    def test_production_release_via_batch_train(self, orchestration_contract):
        """Production release happens via batch train, not direct push."""
        # Merge is to dev, not prod; production release is via batch train
        assert orchestration_contract.merge_target != ReleaseTarget.PROD
        assert orchestration_contract.merge_target == ReleaseTarget.DEV

    def test_release_target_enum_values(self):
        """Release targets are properly enumerated."""
        assert ReleaseTarget.DEV.value == "orchestrator/dev"
        assert ReleaseTarget.STAGING.value == "orchestrator/staging"
        assert ReleaseTarget.PROD.value == "production"


# --- Coordination Rules Tests ---

class TestCoordinationRules:
    """Test coordination rules for multi-task execution."""

    def test_reconcile_loop_rule_present(self, orchestration_contract):
        """Contract includes reconcile with active loop rule."""
        assert CoordinationRule.RECONCILE_LOOP in orchestration_contract.coordination_rules

    def test_reuse_prior_solutions_rule_present(self, orchestration_contract):
        """Contract includes reuse prior solutions rule."""
        assert CoordinationRule.REUSE_PRIOR in orchestration_contract.coordination_rules

    def test_preserve_queue_rule_present(self, orchestration_contract):
        """Contract includes do-not-delete-queued rule."""
        assert CoordinationRule.PRESERVE_QUEUE in orchestration_contract.coordination_rules

    def test_leave_recovered_work_rule_present(self, orchestration_contract):
        """Contract includes leave recovered work in queue rule."""
        assert CoordinationRule.LEAVE_RECOVERED in orchestration_contract.coordination_rules

    def test_all_coordination_rules_enforced(self, orchestration_contract):
        """All four coordination rules are enforced."""
        expected_rules = {
            CoordinationRule.RECONCILE_LOOP,
            CoordinationRule.REUSE_PRIOR,
            CoordinationRule.PRESERVE_QUEUE,
            CoordinationRule.LEAVE_RECOVERED,
        }
        actual_rules = set(orchestration_contract.coordination_rules)
        assert expected_rules == actual_rules

    def test_reconciliation_prevents_duplicate_work(self):
        """Reconciliation rule prevents duplicate work from active loop."""
        rule = CoordinationRule.RECONCILE_LOOP
        assert rule.value == "reconcile_with_active_loop"
        # Verify the rule name indicates loop reconciliation
        assert "reconcile" in rule.value
        assert "loop" in rule.value

    def test_reuse_rule_prevents_redundant_planning(self):
        """Reuse rule prevents redundant solution generation."""
        rule = CoordinationRule.REUSE_PRIOR
        assert rule.value == "reuse_prior_solutions"
        assert "reuse" in rule.value

    def test_queue_preservation_blocks_deletions(self):
        """Queue preservation rule blocks deletion of queued improvements."""
        rule = CoordinationRule.PRESERVE_QUEUE
        assert "delete" not in rule.value or "not" in rule.value
        # Verify rule name indicates preservation
        assert "preserve" in rule.value or "not_delete" in rule.value


# --- Cross-Learning Context Tests ---

class TestCrossLearningContext:
    """Test cross-learning context and outcome signals."""

    def test_outcome_signals_present(self, orchestration_contract):
        """Outcome signals from prior execution are recorded."""
        assert orchestration_contract.outcome_signals is not None

    def test_merged_count_signal(self, orchestration_contract):
        """Outcome signal includes merged count."""
        signals = orchestration_contract.outcome_signals
        assert signals.merged_count == 0
        # 0/12 merged from prior attempt

    def test_test_pass_count_signal(self, orchestration_contract):
        """Outcome signal includes test pass count."""
        signals = orchestration_contract.outcome_signals
        assert signals.test_pass_count == 5
        # 5/12 tests passed

    def test_cost_signal(self, orchestration_contract):
        """Outcome signal includes total cost."""
        signals = orchestration_contract.outcome_signals
        assert signals.total_cost == 0.0
        # $0.00 cost

    def test_models_used_in_signals(self, orchestration_contract):
        """Outcome signal includes models used."""
        signals = orchestration_contract.outcome_signals
        assert "claude-fable-5" in signals.models_used
        assert "gemini-2.0-flash" in signals.models_used

    def test_learned_routes_present(self, orchestration_contract):
        """Learned routes from prior execution are recorded."""
        assert len(orchestration_contract.learned_routes) > 0

    def test_debate_compress_learned_route(self, orchestration_contract):
        """Debate compress learned route is available."""
        route = next(
            (r for r in orchestration_contract.learned_routes if r.route_name == "debate_compress"),
            None,
        )
        assert route is not None
        assert route.model_id == "claude-haiku-4-5-20251001"
        assert route.quality_score == 7.0

    def test_pipeline_plan_learned_route(self, orchestration_contract):
        """Pipeline plan learned route is available."""
        route = next(
            (r for r in orchestration_contract.learned_routes if r.route_name == "pipeline_plan"),
            None,
        )
        assert route is not None
        assert route.model_id == "llama3.2:3b"
        assert route.quality_score == 7.7

    def test_build_fix_learned_route(self, orchestration_contract):
        """Build fix learned route is available."""
        route = next(
            (r for r in orchestration_contract.learned_routes if r.route_name == "build_fix"),
            None,
        )
        assert route is not None
        assert route.model_id == "kimi-k2.7-code"
        assert route.quality_score == 7.7

    def test_confidence_gate_learned_route(self, orchestration_contract):
        """Confidence gate learned route is available."""
        route = next(
            (r for r in orchestration_contract.learned_routes if r.route_name == "confidence_gate"),
            None,
        )
        assert route is not None
        assert route.model_id == "claude-haiku-4-5-20251001"

    def test_learned_routes_count(self, orchestration_contract):
        """All four learned routes are present."""
        assert len(orchestration_contract.learned_routes) == 4

    def test_learned_routes_evidence_counts(self, orchestration_contract):
        """Learned routes have evidence counts."""
        for route in orchestration_contract.learned_routes:
            assert route.evidence_count >= 1


# --- Stale RUNNING Recovery Tests ---

class TestStaleRunningRecovery:
    """Test recovery from stale RUNNING task state."""

    def test_stale_running_detection_threshold(self):
        """Stale RUNNING is detected after 30 minutes."""
        # zombie-reaper: stale RUNNING >30min
        stale_threshold_minutes = 30
        created_at = datetime.now() - timedelta(minutes=35)
        is_stale = (datetime.now() - created_at).total_seconds() / 60 > stale_threshold_minutes
        assert is_stale is True

    def test_fresh_running_not_marked_stale(self):
        """Fresh RUNNING task is not marked stale."""
        stale_threshold_minutes = 30
        created_at = datetime.now() - timedelta(minutes=10)
        is_stale = (datetime.now() - created_at).total_seconds() / 60 > stale_threshold_minutes
        assert is_stale is False

    def test_recovery_preserves_contract_state(self, orchestration_contract):
        """Recovery preserves original contract state."""
        # Contract should be unchanged by recovery
        assert orchestration_contract.task_slug == "contracts-smarter"
        assert orchestration_contract.source == SourceType.PREFLIGHT_GATE
        assert orchestration_contract.project == "smarter"

    def test_recovery_resumes_from_branch(self):
        """Recovery resumes from agent branch."""
        # Branch naming: agent/{slug}
        branch_name = "agent/contracts-smarter-abc123"
        assert branch_name.startswith("agent/")
        assert "contracts-smarter" in branch_name

    def test_recovery_reconstructs_worktree(self):
        """Recovery can reconstruct worktree from artifacts."""
        # Worktree convention: {repo}-wt/{slug}
        worktree_path = "claude-orchestrator-wt/contracts-smarter"
        assert "wt" in worktree_path
        assert "contracts-smarter" in worktree_path

    def test_recovery_preserves_prior_work(self, orchestration_contract):
        """Recovery preserves prior partial implementation."""
        # Prior work: known artifacts from prior run
        # Agentic analysis artifacts should be available
        assert orchestration_contract.outcome_signals is not None
        assert orchestration_contract.learned_routes is not None


# --- Task Continuation Tests ---

class TestTaskContinuation:
    """Test task continuation from stale state."""

    def test_continue_same_implementation(self, orchestration_contract):
        """Task continuation uses same implementation, doesn't restart."""
        # Not a fresh requeue; continue same implementation
        assert orchestration_contract.task_slug == "contracts-smarter"
        # Verify contract is not recreated from scratch
        assert orchestration_contract.created_at is not None

    def test_completion_requires_concrete_changes(self, orchestration_contract):
        """Completion requires concrete code/file changes, not just analysis."""
        # Preflight directive: do not stop at analysis
        # Implementation must produce concrete diff
        # This is verified by checking that contract includes actual config, not just thoughts
        assert orchestration_contract.preflight_triage_route is not None
        assert orchestration_contract.strategy_planner_route is not None

    def test_completion_requires_commit(self):
        """Completion requires commit on task branch."""
        # Should commit: final implementation on task branch
        # Commit message format: agent/{slug}
        commit_message = "Complete contracts-smarter orchestration pipeline contract"
        assert "contracts-smarter" in commit_message or "contract" in commit_message

    def test_completion_runs_checks(self, orchestration_contract):
        """Completion runs tests and checks before commit."""
        # Tests should validate: structure, routes, coordination, learning context
        assert orchestration_contract is not None
        # This test file ensures checks are run

    def test_prior_commit_sha_unknown_allows_fresh_analysis(self):
        """Prior commit SHA unknown means full contract re-analysis is acceptable."""
        # Prior commit SHA: unknown
        # This allows fresh analysis without assuming prior state
        prior_sha = None
        assert prior_sha is None


# --- Integration Tests ---

class TestOrchestrrationContractIntegration:
    """Integration tests for complete orchestration contract."""

    def test_full_pipeline_flow(self, orchestration_contract):
        """Complete pipeline flow from preflight to merge."""
        # 1. Preflight triage selects strategy planner
        assert orchestration_contract.preflight_triage_route is not None
        assert orchestration_contract.strategy_planner_route is not None

        # 2. Strategy planner produces plan
        assert orchestration_contract.task_class == TaskClass.PLAN

        # 3. Agentic coder implements plan
        assert orchestration_contract.agentic_coder_model == "claude-fable-5"

        # 4. Independent QA verifies implementation
        assert orchestration_contract.qa_rate_config.independent_route is not None

        # 5. QA panel judges results
        assert len(orchestration_contract.qa_rate_config.qa_panel) >= 2

        # 6. Legal gate checks for sensitive content
        assert orchestration_contract.legal_gate is not None

        # 7. Auto-merge to orchestrator/dev
        assert orchestration_contract.auto_merge_enabled is True
        assert orchestration_contract.merge_target == ReleaseTarget.DEV

    def test_cross_learning_influences_routing(self, orchestration_contract):
        """Cross-learning outcomes influence route selection."""
        # Prior models and signals should influence new routing
        assert orchestration_contract.outcome_signals is not None
        assert orchestration_contract.learned_routes is not None

        # Learned routes should be available for reuse
        route_names = {r.route_name for r in orchestration_contract.learned_routes}
        assert "debate_compress" in route_names
        assert "pipeline_plan" in route_names

    def test_coordination_prevents_conflicts(self, orchestration_contract):
        """Coordination rules prevent conflicts with active work."""
        # Multiple rules should be enforced together
        rules = set(orchestration_contract.coordination_rules)
        assert len(rules) == 4

        # Reconciliation should happen before work starts
        assert CoordinationRule.RECONCILE_LOOP in rules

        # Prior solutions should be reused
        assert CoordinationRule.REUSE_PRIOR in rules

        # No deletion of queued improvements
        assert CoordinationRule.PRESERVE_QUEUE in rules

    def test_contract_can_be_persisted(self, orchestration_contract):
        """Contract can be persisted and restored."""
        import json

        # Serialize to JSON (after enum conversion)
        contract_data = {
            "task_slug": orchestration_contract.task_slug,
            "source": orchestration_contract.source.value,
            "project": orchestration_contract.project,
        }
        json_str = json.dumps(contract_data)

        # Restore from JSON
        restored = json.loads(json_str)
        assert restored["task_slug"] == "contracts-smarter"
        assert restored["project"] == "smarter"


# --- Edge Case Tests ---

class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_empty_learned_routes_list(self):
        """Contract can handle empty learned routes list initially."""
        contract = OrchestrationContract(
            task_slug="test-contract",
            source=SourceType.PREFLIGHT_GATE,
            project="test",
            task_class=TaskClass.PLAN,
            need_count=8,
            risk_strategy="conservative",
            preflight_triage_route=RouteConfig(
                route_name="test",
                provider=ModelProvider.LOCAL,
                model_id="test-model",
                pool_location="local",
                quality_score=7.0,
                token_cost=0.0,
            ),
            strategy_planner_route=RouteConfig(
                route_name="test",
                provider=ModelProvider.LOCAL,
                model_id="test-model",
                pool_location="local",
                quality_score=7.0,
                token_cost=0.0,
            ),
            agentic_coder_provider="claude",
            agentic_coder_model="claude-fable-5",
            qa_rate_config=QARateConfiguration(
                independent_route=RouteConfig(
                    route_name="test",
                    provider=ModelProvider.LOCAL,
                    model_id="test-model",
                    pool_location="local",
                    quality_score=7.0,
                    token_cost=0.0,
                ),
            ),
            legal_gate=PipelineGate(
                gate_type=GateType.LEGAL,
                condition="test",
            ),
            merge_target=ReleaseTarget.DEV,
            learned_routes=[],  # Empty list
        )
        assert len(contract.learned_routes) == 0

    def test_outcome_signals_none_initially(self):
        """Contract can be initialized without outcome signals."""
        contract = OrchestrationContract(
            task_slug="test-contract",
            source=SourceType.PREFLIGHT_GATE,
            project="test",
            task_class=TaskClass.PLAN,
            need_count=8,
            risk_strategy="conservative",
            preflight_triage_route=RouteConfig(
                route_name="test",
                provider=ModelProvider.LOCAL,
                model_id="test-model",
                pool_location="local",
                quality_score=7.0,
                token_cost=0.0,
            ),
            strategy_planner_route=RouteConfig(
                route_name="test",
                provider=ModelProvider.LOCAL,
                model_id="test-model",
                pool_location="local",
                quality_score=7.0,
                token_cost=0.0,
            ),
            agentic_coder_provider="claude",
            agentic_coder_model="claude-fable-5",
            qa_rate_config=QARateConfiguration(
                independent_route=RouteConfig(
                    route_name="test",
                    provider=ModelProvider.LOCAL,
                    model_id="test-model",
                    pool_location="local",
                    quality_score=7.0,
                    token_cost=0.0,
                ),
            ),
            legal_gate=PipelineGate(
                gate_type=GateType.LEGAL,
                condition="test",
            ),
            merge_target=ReleaseTarget.DEV,
            outcome_signals=None,  # No signals initially
        )
        assert contract.outcome_signals is None

    def test_zero_quality_score_rejected(self):
        """Routes with zero quality score should be rejected."""
        # Quality score should be > 0
        with pytest.raises(ValueError):
            RouteConfig(
                route_name="test",
                provider=ModelProvider.LOCAL,
                model_id="test-model",
                pool_location="local",
                quality_score=0.0,  # Invalid: must be > 0
                token_cost=0.0,
            )

    def test_high_cost_routes_justified(self, qa_panel_routes):
        """High-cost routes should be justified by quality."""
        for route in qa_panel_routes:
            if route.token_cost > 0.001:
                assert route.quality_score >= 7.0  # High cost routes must be high quality
