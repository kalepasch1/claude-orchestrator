#!/usr/bin/env python3
"""
contracts_smarter.py — Orchestration pipeline contract system for contracts-smarter task.

Implements contract structures, validation, and management for the orchestration
pipeline. Follows module-level singleton pattern with fail-soft error handling.
"""

import os
import sys
import json
import threading
from typing import Dict, Any, List, Optional, Tuple
from enum import Enum
from dataclasses import dataclass, field, asdict
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import db
except ImportError:
    db = None


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
    pool_location: str
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


# --- Module-Level Singleton Pattern ---

class _ContractManager:
    """Thread-safe singleton for contract management."""

    def __init__(self):
        self._contracts: Dict[str, OrchestrationContract] = {}
        self._lock = threading.Lock()

    def get_contract(self, task_slug: str) -> Optional[OrchestrationContract]:
        """Retrieve contract by task slug. Returns None on error."""
        try:
            with self._lock:
                return self._contracts.get(task_slug)
        except Exception:
            return None

    def set_contract(self, task_slug: str, contract: OrchestrationContract) -> None:
        """Store contract. Fails silently on error."""
        try:
            with self._lock:
                self._contracts[task_slug] = contract
        except Exception:
            pass

    def invalidate(self, task_slug: str) -> None:
        """Remove contract from cache."""
        try:
            with self._lock:
                self._contracts.pop(task_slug, None)
        except Exception:
            pass

    def stats(self) -> Dict[str, Any]:
        """Return manager statistics."""
        try:
            with self._lock:
                return {
                    "cached_contracts": len(self._contracts),
                    "slugs": list(self._contracts.keys()),
                }
        except Exception:
            return {"cached_contracts": 0, "slugs": []}


# Module-level singleton instance
_contract_manager = _ContractManager()


# --- Public API Functions ---

def get_contract(task_slug: str) -> Optional[OrchestrationContract]:
    """Get contract by task slug. Delegates to singleton."""
    return _contract_manager.get_contract(task_slug)


def set_contract(task_slug: str, contract: OrchestrationContract) -> None:
    """Set contract for task slug. Delegates to singleton."""
    _contract_manager.set_contract(task_slug, contract)


def invalidate_contract(task_slug: str) -> None:
    """Remove contract from cache."""
    _contract_manager.invalidate(task_slug)


def load_contracts_smarter_contract() -> OrchestrationContract:
    """
    Load the contracts-smarter orchestration contract.
    Returns contract with all required configuration for the task.
    """
    preflight_triage_route = RouteConfig(
        route_name="preflight_triage",
        provider=ModelProvider.LOCAL,
        model_id="kimi-k2.7-code",
        pool_location="cloud",
        quality_score=7.58,
        token_cost=0.0,
        sample_count=90,
    )

    strategy_planner_route = RouteConfig(
        route_name="strategy_planner",
        provider=ModelProvider.LOCAL,
        model_id="kimi-k2.7-code",
        pool_location="cloud",
        quality_score=7.26,
        token_cost=0.0,
        sample_count=632,
    )

    independent_qa_route = RouteConfig(
        route_name="independent_qa",
        provider=ModelProvider.LOCAL,
        model_id="qwen2.5-coder:32b",
        pool_location="local",
        quality_score=6.9,
        token_cost=0.0,
        sample_count=1,
    )

    qa_panel_routes = [
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
            model_id="gemini-2.5-flash",
            pool_location="cloud",
            quality_score=7.1,
            token_cost=0.01,
        ),
    ]

    qa_rate_config = QARateConfiguration(
        independent_route=independent_qa_route,
        qa_panel=qa_panel_routes,
        parallel_execution=True,
    )

    legal_gate = PipelineGate(
        gate_type=GateType.LEGAL,
        condition="owner_only when change involves licensing/registration/custody/transmission/advice or requires secret",
        owner_only=True,
        escalation_required=True,
    )

    outcome_signals = OutcomeSignal(
        merged_count=0,
        test_pass_count=5,
        total_cost=0.0,
        models_used=[
            "claude-fable-5",
            "ollama/qwen2.5-coder:7b",
            "gemini-2.5-flash",
            "grok-3-mini-fast",
        ],
        timestamp="2026-08-18T00:00:00Z",
    )

    learned_routes = [
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

    contract = OrchestrationContract(
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

    return contract


def validate_contract(contract: OrchestrationContract) -> Tuple[bool, str]:
    """
    Validate orchestration contract. Returns (is_valid, error_message).
    Fails soft: returns False with message instead of raising.
    """
    if not contract:
        return False, "Contract is None"

    try:
        if not contract.task_slug:
            return False, "task_slug is required"

        if not contract.agentic_coder_model:
            return False, "agentic_coder_model is required"

        if contract.need_count <= 0:
            return False, "need_count must be positive"

        if contract.legal_gate.quality_score is None:
            pass

        if not contract.qa_rate_config:
            return False, "qa_rate_config is required"

        return True, ""

    except Exception as e:
        return False, f"Validation error: {str(e)[:100]}"


def contract_to_dict(contract: OrchestrationContract) -> Dict[str, Any]:
    """
    Convert contract to dictionary for JSON serialization.
    Converts enums to their string values.
    """
    if not contract:
        return {}

    try:
        data = asdict(contract)

        if isinstance(contract.source, SourceType):
            data["source"] = contract.source.value
        if isinstance(contract.task_class, TaskClass):
            data["task_class"] = contract.task_class.value
        if isinstance(contract.merge_target, ReleaseTarget):
            data["merge_target"] = contract.merge_target.value

        if contract.coordination_rules:
            data["coordination_rules"] = [r.value for r in contract.coordination_rules]

        if contract.preflight_triage_route:
            route_data = asdict(contract.preflight_triage_route)
            if isinstance(contract.preflight_triage_route.provider, ModelProvider):
                route_data["provider"] = contract.preflight_triage_route.provider.value
            data["preflight_triage_route"] = route_data

        if contract.strategy_planner_route:
            route_data = asdict(contract.strategy_planner_route)
            if isinstance(contract.strategy_planner_route.provider, ModelProvider):
                route_data["provider"] = contract.strategy_planner_route.provider.value
            data["strategy_planner_route"] = route_data

        if contract.qa_rate_config:
            qa_data = {
                "parallel_execution": contract.qa_rate_config.parallel_execution,
            }
            if contract.qa_rate_config.independent_route:
                ind_route = asdict(contract.qa_rate_config.independent_route)
                if isinstance(contract.qa_rate_config.independent_route.provider, ModelProvider):
                    ind_route["provider"] = contract.qa_rate_config.independent_route.provider.value
                qa_data["independent_route"] = ind_route

            if contract.qa_rate_config.qa_panel:
                qa_panel = []
                for route in contract.qa_rate_config.qa_panel:
                    route_data = asdict(route)
                    if isinstance(route.provider, ModelProvider):
                        route_data["provider"] = route.provider.value
                    qa_panel.append(route_data)
                qa_data["qa_panel"] = qa_panel

            data["qa_rate_config"] = qa_data

        if contract.legal_gate:
            gate_data = asdict(contract.legal_gate)
            if isinstance(contract.legal_gate.gate_type, GateType):
                gate_data["gate_type"] = contract.legal_gate.gate_type.value
            data["legal_gate"] = gate_data

        if contract.outcome_signals:
            sig_data = asdict(contract.outcome_signals)
            data["outcome_signals"] = sig_data

        if contract.learned_routes:
            routes = []
            for route in contract.learned_routes:
                route_data = asdict(route)
                if isinstance(route.provider, ModelProvider):
                    route_data["provider"] = route.provider.value
                routes.append(route_data)
            data["learned_routes"] = routes

        return data

    except Exception:
        return {}


def contract_stats() -> Dict[str, Any]:
    """Get contract manager statistics."""
    return _contract_manager.stats()
