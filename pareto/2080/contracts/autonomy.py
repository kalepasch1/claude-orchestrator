"""Pareto 2080 Autonomy Stack — shared interface/type/schema definitions.

Pure contracts: dataclasses, Protocols, TypedDicts with docstrings.
NO implementation logic. All designs are regulatory-posture-agnostic.
Execution actions are gateable behind one-click approval.
Fail-soft-friendly: optional fields, sensible defaults.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, List, Protocol, runtime_checkable
from enum import Enum
import time


# --- (1) AuthorityBudget & TrustRatchet ---

class AuthorityTier(Enum):
    """Graduated authority tiers."""
    APPROVAL_ONLY = "approval_only"  # $0, one-click required
    CAPPED = "capped"                # $500 default cap
    UNLIMITED_WITH_RECEIPTS = "unlimited_with_receipts"


@dataclass
class AuthorityBudget:
    """Graduated spending/action authority for an autonomous agent."""
    tier: AuthorityTier = AuthorityTier.APPROVAL_ONLY
    cap_usd: float = 0.0
    holder_id: str = ""
    description: str = ""


@runtime_checkable
class TrustRatchet(Protocol):
    """Protocol for advancing/reversing trust tiers."""
    def advance(self, budget: AuthorityBudget) -> AuthorityBudget: ...
    def reverse(self, budget: AuthorityBudget) -> AuthorityBudget: ...


@runtime_checkable
class ReverseTrustRatchet(Protocol):
    """Aging-parent takeover: reverse trust delegation."""
    def takeover(self, budget: AuthorityBudget, guardian_id: str) -> AuthorityBudget: ...
    def release(self, budget: AuthorityBudget) -> AuthorityBudget: ...


# --- (2) Receipt & ReceiptStore ---

@dataclass
class Receipt:
    """Signed, plain-language receipt for any autonomous action."""
    explanation: str = ""
    amount_saved: float = 0.0
    action: str = ""
    timestamp: float = field(default_factory=time.time)
    signature: str = ""


@runtime_checkable
class ReceiptStore(Protocol):
    """Protocol for storing and retrieving receipts."""
    def store(self, receipt: Receipt) -> str: ...
    def retrieve(self, receipt_id: str) -> Optional[Receipt]: ...
    def list_all(self, holder_id: str) -> List[Receipt]: ...


# --- (3) LifeStateMachine, GoalCompileResult, ConfidenceBand ---

@dataclass
class ConfidenceBand:
    """Monte Carlo confidence band (p10/p50/p90)."""
    p10: float = 0.0
    p50: float = 0.0
    p90: float = 0.0


@dataclass
class ReplanReceipt:
    """Receipt for a replan event in the life state machine."""
    reason: str = ""
    old_goal: str = ""
    new_goal: str = ""
    timestamp: float = field(default_factory=time.time)


@dataclass
class DeviationInterrupt:
    """Interrupt raised when life trajectory deviates from plan."""
    goal_id: str = ""
    deviation_pct: float = 0.0
    message: str = ""
    confidence: Optional[ConfidenceBand] = None


@dataclass
class GoalCompileResult:
    """Result of compiling a life goal into an actionable plan."""
    goal_id: str = ""
    success: bool = False
    confidence: Optional[ConfidenceBand] = None
    steps: List[str] = field(default_factory=list)
    replan_receipt: Optional[ReplanReceipt] = None


@dataclass
class LifeStateMachine:
    """State machine tracking life goals and transitions."""
    current_state: str = "idle"
    goal_id: str = ""
    compile_result: Optional[GoalCompileResult] = None
    deviations: List[DeviationInterrupt] = field(default_factory=list)


# --- (4) RegimeOracle ---

@dataclass
class RegimeEvent:
    """Jurisdiction rule-change event."""
    jurisdiction: str = ""
    rule_id: str = ""
    description: str = ""
    effective_date: str = ""
    timestamp: float = field(default_factory=time.time)


@runtime_checkable
class RegimeOracle(Protocol):
    """Consumer protocol for jurisdiction rule-change events."""
    def get_events(self, jurisdiction: str) -> List[RegimeEvent]: ...
    def subscribe(self, jurisdiction: str, callback: str) -> None: ...


# --- (5) HouseholdPassport ---

@dataclass
class HouseholdPassport:
    """Passport identifying household members and authority mesh."""
    household_id: str = ""
    member_id: str = ""
    guardian_of: List[str] = field(default_factory=list)
    authority_type: str = "member"  # member, guardian, dependent
    mesh_roles: List[str] = field(default_factory=list)


# --- (6) NegotiationOutcome & KAnonymityGate ---

@dataclass
class NegotiationOutcome:
    """Outcome of a crowd-exchange negotiation."""
    deal_id: str = ""
    accepted: bool = False
    counterparty_id: str = ""
    terms: str = ""
    amount: float = 0.0


@runtime_checkable
class KAnonymityGate(Protocol):
    """Protocol ensuring k-anonymity in crowd exchanges."""
    def check(self, data: dict, k: int) -> bool: ...
    def anonymize(self, data: dict, k: int) -> dict: ...


# --- (7) AuditBundle & ComplianceBinder ---

@dataclass
class AuditBundle:
    """Bundle of receipts and actions for audit purposes."""
    bundle_id: str = ""
    receipts: List[Receipt] = field(default_factory=list)
    period_start: str = ""
    period_end: str = ""
    notes: str = ""


@dataclass
class ComplianceBinder:
    """Compliance binder aggregating audit bundles."""
    binder_id: str = ""
    jurisdiction: str = ""
    bundles: List[AuditBundle] = field(default_factory=list)
    status: str = "draft"
