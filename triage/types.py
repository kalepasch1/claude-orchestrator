from __future__ import annotations
import enum, os
from dataclasses import dataclass, field
from typing import Any, List, Literal, Optional

ORCH_TRIAGE_MAX_REPORT_AGE_DAYS = os.environ.get("ORCH_TRIAGE_MAX_REPORT_AGE_DAYS", "90")
ORCH_TRIAGE_ESCALATION_WINDOW_HOURS = os.environ.get("ORCH_TRIAGE_ESCALATION_WINDOW_HOURS", "72")
ORCH_TRIAGE_MIN_EVIDENCE_GRADE = os.environ.get("ORCH_TRIAGE_MIN_EVIDENCE_GRADE", "Single-observation")
ORCH_TRIAGE_STAKING_POOL_SIZE = os.environ.get("ORCH_TRIAGE_STAKING_POOL_SIZE", "100")
ORCH_TRIAGE_CAPTURE_TIMEOUT_SEC = os.environ.get("ORCH_TRIAGE_CAPTURE_TIMEOUT_SEC", "90")

EvidenceGrade = Literal["Documented", "Corroborated-pattern", "Single-observation"]
EVIDENCE_GRADE_ORDER: dict[str, int] = {"Documented": 0, "Corroborated-pattern": 1, "Single-observation": 2}

@dataclass
class RiskReport:
    subject_id: str; reporter_id: str; evidence_grade: EvidenceGrade; summary: str
    details: str = ""; witnesses: List[str] = field(default_factory=list); severity: int = 1
    timestamp: Optional[str] = None; id: Optional[str] = None

@dataclass
class GoldEndorsement:
    subject_id: str; endorser_id: str; evidence_grade: EvidenceGrade; summary: str
    details: str = ""; timestamp: Optional[str] = None; id: Optional[str] = None

class PropositionKind(enum.Enum):
    CREDENTIAL_ACTION = "CREDENTIAL_ACTION"
    PERFORMANCE_PERCENTILE = "PERFORMANCE_PERCENTILE"
    UNIT_SAFETY_SCORE_DIRECTION = "UNIT_SAFETY_SCORE_DIRECTION"
    RETENTION_RISK = "RETENTION_RISK"

@dataclass
class Stake:
    staker_id: str; proposition_id: str; amount: float = 1.0
    direction: Literal["FOR", "AGAINST"] = "FOR"; timestamp: Optional[str] = None

class StakeOutcome(enum.Enum):
    CONFIRMED = "CONFIRMED"; CONTRADICTED = "CONTRADICTED"; UNRESOLVED = "UNRESOLVED"

@dataclass
class Proposition:
    id: str; kind: PropositionKind; subject_id: str; statement: str
    stakes: List[Stake] = field(default_factory=list); outcome: Optional[StakeOutcome] = None
    timestamp: Optional[str] = None

@dataclass
class MarketImpliedRiskScore:
    subject_id: str; score: float = 0.0; confidence: float = 0.0; contributing_propositions: int = 0

@dataclass
class CalibrationLedgerEntry:
    staker_id: str; proposition_id: str; outcome: StakeOutcome
    credibility_delta: float = 0.0; new_credibility: float = 1.0; timestamp: Optional[str] = None

class FlagState(enum.Enum):
    OPEN = "OPEN"; ACKNOWLEDGED = "ACKNOWLEDGED"; REMEDIATION_IN_PROGRESS = "REMEDIATION_IN_PROGRESS"
    RESOLVED = "RESOLVED"; ESCALATED = "ESCALATED"

@dataclass
class EmployerFlag:
    id: str; subject_id: str; employer_id: str; substantiation_threshold: float = 0.7
    remediation_pathway: str = ""; clock_deadline: Optional[str] = None; state: FlagState = FlagState.OPEN

class EscalationChannel(enum.Enum):
    INTERNAL = "INTERNAL"; REGULATORY = "REGULATORY"; LEGAL = "LEGAL"; PUBLIC = "PUBLIC"

@dataclass
class EvidencePack:
    flag_id: str; reports: List[RiskReport] = field(default_factory=list)
    endorsements: List[GoldEndorsement] = field(default_factory=list)
    employer_inaction_interval: float = 0.0; channel: EscalationChannel = EscalationChannel.INTERNAL
    assembled_at: Optional[str] = None

@dataclass
class FeeSplit:
    recruiter_id: str; employer_id: str; candidate_id: str; fee_percentage: float = 0.0
    guarantee_band: Optional["GuaranteeBand"] = None

@dataclass
class GuaranteeBand:
    min_days: int = 0; max_days: int = 90; refund_percentage: float = 100.0

@dataclass
class UnitSafetyScore:
    unit_id: str; score: float = 0.0; report_count: int = 0; endorsement_count: int = 0
    trend: Literal["improving", "stable", "declining"] = "stable"

class League(enum.Enum):
    BRONZE = "BRONZE"; SILVER = "SILVER"; GOLD = "GOLD"; PLATINUM = "PLATINUM"

class GuardianTier(enum.Enum):
    WATCHER = "WATCHER"; GUARDIAN = "GUARDIAN"; SENTINEL = "SENTINEL"; CHAMPION = "CHAMPION"

@dataclass
class RetaliationSignal:
    reporter_id: str; subject_id: str; signal_type: str = ""; severity: int = 1
    evidence: str = ""; timestamp: Optional[str] = None
