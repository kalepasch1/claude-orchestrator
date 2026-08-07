"""WAVE C — codegen + platform spine + pipeline structure: shared contracts module.

Authoritative spec: ``IMPROVEMENTS_MASTER_UNQUEUED_2026-07-31.md`` Parts 4, 6 and 7.

This module is CONTRACTS ONLY. It carries dataclasses, enums, and ``Protocol``
signatures that the Wave-C sibling shards implement against; it deliberately holds
no engine behaviour. Conventions follow ``runner/barks_contracts.py``:

* module-level singleton-free, dependency-free (stdlib only) so any shard can import it,
* fail-soft ``Result`` wrapper — contract helpers never raise on bad input,
* ``ORCH_``-prefixed env-var config so keys are fleet-pushable and hold no secrets.

See ``docs/wave-c-contracts.md`` for the narrative description.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# ORCH_-prefixed config constants (env-var based, no secrets)
# ---------------------------------------------------------------------------
#: Similarity floor for transplanting a proven organ (Part 4 raised this to 0.55).
ORCH_WAVEC_TRANSPLANT_MIN_SIMILARITY = float(
    os.environ.get("ORCH_WAVEC_TRANSPLANT_MIN_SIMILARITY", "0.55")
)
#: Precedent match at or above this auto-resolves an approval card (Part 5/6 spine).
ORCH_WAVEC_PRECEDENT_AUTO_APPROVE = float(
    os.environ.get("ORCH_WAVEC_PRECEDENT_AUTO_APPROVE", "0.9")
)
#: Merge unit for Part 7 initiative-level integration ("initiative" or "branch").
ORCH_WAVEC_MERGE_UNIT = os.environ.get("ORCH_WAVEC_MERGE_UNIT", "initiative")
#: Days of look-ahead the renewal annuity engine schedules (Part 6).
ORCH_WAVEC_RENEWAL_HORIZON_DAYS = int(
    os.environ.get("ORCH_WAVEC_RENEWAL_HORIZON_DAYS", "365")
)


# ---------------------------------------------------------------------------
# Fail-soft Result wrapper (mirrors runner/barks_contracts.Result)
# ---------------------------------------------------------------------------
@dataclass(init=False)
class Result:
    """Fail-soft wrapper with ``value`` and legacy ``data`` compatibility."""

    ok: bool
    value: Any
    error: str

    def __init__(self, ok: bool = False, value: Any = None, error: str = "", data: Any = None):
        self.ok = ok
        self.value = value if data is None else data
        self.error = error

    @property
    def data(self) -> Any:
        return self.value

    @data.setter
    def data(self, value: Any) -> None:
        self.value = value


def ok(value: Any = None) -> Result:
    """Fail-soft success constructor."""
    return Result(ok=True, value=value, error="")


def err(message: Any = "") -> Result:
    """Fail-soft failure constructor. Never raises, even on non-string input."""
    try:
        text = str(message or "")
    except Exception:  # pragma: no cover - defensive, str() on exotic objects
        text = "unknown error"
    return Result(ok=False, value=None, error=text)


# ===========================================================================
# PART 4 — SELF-SERVICE CODE GENERATOR
# ===========================================================================
class Disposition(Enum):
    """Terminal state of a generated shard, recorded in the disposition ledger."""

    PENDING = "PENDING"
    MERGED = "MERGED"
    SUPERSEDED = "SUPERSEDED"
    REJECTED = "REJECTED"
    ABANDONED = "ABANDONED"


@dataclass
class TransplantCandidate:
    """A proven merged diff offered as an organ to transplant into a new shard."""

    source_slug: str = ""
    source_project: str = ""
    diff_sha: str = ""
    similarity: float = 0.0
    touched_files: List[str] = field(default_factory=list)
    #: True only when ``similarity >= ORCH_WAVEC_TRANSPLANT_MIN_SIMILARITY``.
    eligible: bool = False


@dataclass
class DispositionLedgerEntry:
    """One immutable row of the disposition ledger — 'never grow tumors' audit trail."""

    task_slug: str = ""
    project: str = ""
    branch: str = ""
    disposition: Disposition = Disposition.PENDING
    transplanted_from: str = ""
    similarity: float = 0.0
    rationale: str = ""
    recorded_at: str = ""


@dataclass
class ContractFirstSpec:
    """Contract-first generation payload: the verify gate IS the spec.

    A shard emits the failing test and the type signatures BEFORE any body is
    filled in, so the generator has an executable definition of done.
    """

    task_slug: str = ""
    #: Path -> source of the failing test(s) that must go green.
    failing_tests: Dict[str, str] = field(default_factory=dict)
    #: Path -> declared signatures / stubs with no bodies.
    type_signatures: Dict[str, str] = field(default_factory=dict)
    verify_cmd: str = ""


@dataclass
class GoldenPathTemplate:
    """Per-vertical template distilled from top-decile merged shards."""

    vertical: str = ""
    name: str = ""
    #: Ordered relative paths the template expects a shard to produce.
    file_scaffold: List[str] = field(default_factory=list)
    conventions: List[str] = field(default_factory=list)
    distilled_from: List[str] = field(default_factory=list)


@dataclass
class StrategyContext:
    """Approved tribunal strategy carried into every shard.

    Code is born compliant-by-design for the chosen structure (e.g. a sweepstakes
    entry strategy natively generates AMOE flows and per-state gates).
    """

    strategy_id: str = ""
    structure: str = ""
    jurisdictions: List[str] = field(default_factory=list)
    required_flows: List[str] = field(default_factory=list)
    prohibited_patterns: List[str] = field(default_factory=list)
    approved_by: str = ""


@dataclass
class CodeGenRequest:
    """Input to the self-service code generator."""

    task_slug: str = ""
    project: str = ""
    goal: str = ""
    template: Optional[GoldenPathTemplate] = None
    strategy: Optional[StrategyContext] = None
    transplants: List[TransplantCandidate] = field(default_factory=list)


@dataclass
class CodeGenResult:
    """Output of the self-service code generator."""

    task_slug: str = ""
    spec: Optional[ContractFirstSpec] = None
    touched_files: List[str] = field(default_factory=list)
    verify_passed: bool = False
    ledger_entry: Optional[DispositionLedgerEntry] = None
    notes: str = ""


@runtime_checkable
class CodeGenerator(Protocol):
    """Contract every Part-4 generator implementation satisfies."""

    def propose_transplants(self, request: CodeGenRequest) -> Result:
        """-> Result[value=List[TransplantCandidate]] ranked, similarity-gated."""

    def emit_contract_first(self, request: CodeGenRequest) -> Result:
        """-> Result[value=ContractFirstSpec] failing test + signatures, no bodies."""

    def generate(self, request: CodeGenRequest, spec: ContractFirstSpec) -> Result:
        """-> Result[value=CodeGenResult] fill against the spec until verify is green."""


@runtime_checkable
class DispositionLedger(Protocol):
    """Append-only record of what was generated and how it ended."""

    def record(self, entry: DispositionLedgerEntry) -> Result:
        """Append one entry. Fail-soft: returns ``err`` rather than raising."""

    def history(self, project: str = "", limit: int = 100) -> Result:
        """-> Result[value=List[DispositionLedgerEntry]] newest first."""


# ===========================================================================
# PART 6 — CROSS-APP / PLATFORM (matter spine, exposure flywheel, renewals)
# ===========================================================================
class MatterStage(Enum):
    """Lifecycle of one matter record on the spine."""

    INTAKE = "intake"
    TRIAGE = "triage"
    LICENSING = "licensing"
    FILINGS = "filings"
    VIDEO = "video"
    NEWSLETTERS = "newsletters"
    CLOSED = "closed"


class MatterView(Enum):
    """Three views of one truth — never three sources of truth."""

    INBOX = "inbox"
    PORTAL = "portal"
    EXPOSURE = "exposure"


@dataclass
class MatterRecord:
    """The matter spine. Every cross-app surface keys to this single record."""

    matter_id: str = ""
    project: str = ""
    title: str = ""
    stage: MatterStage = MatterStage.INTAKE
    owner_label: str = ""
    #: Foreign keys into per-surface tables, keyed by surface name.
    linked_artifacts: Dict[str, List[str]] = field(default_factory=dict)
    expected_loss_usd: float = 0.0
    created_at: str = ""
    updated_at: str = ""


@dataclass
class ExposureRecord:
    """One quantified exposure attached to a matter."""

    exposure_id: str = ""
    matter_id: str = ""
    risk_class: str = ""
    expected_loss_usd: float = 0.0
    #: True when a Tomorrow instrument can currently absorb this exposure.
    hedgeable: bool = False
    hedge_instrument_id: str = ""
    #: Set when ``hedgeable`` is False — feeds the instrument foundry as demand.
    foundry_request_id: str = ""


@dataclass
class HedgeFlywheelMetric:
    """Exposure-to-hedge flywheel: product-gap tracker, demand signal, investor stat."""

    as_of: str = ""
    total_expected_loss_usd: float = 0.0
    hedgeable_expected_loss_usd: float = 0.0
    #: hedgeable / total, 0.0 when total is 0 (fail-soft, never divides by zero).
    hedgeable_pct: float = 0.0
    unhedgeable_top_risk_classes: List[str] = field(default_factory=list)
    trend_delta_pct: float = 0.0


@dataclass
class RenewalScheduleEntry:
    """Renewal annuity engine: every filing schedules its own follow-on calendar."""

    renewal_id: str = ""
    matter_id: str = ""
    source_filing_id: str = ""
    kind: str = ""  # "renewal" | "report" | "attestation"
    due_at: str = ""
    lead_days: int = 30
    #: Wired to the ambient monitor; False until the monitor confirms the watch.
    monitor_armed: bool = False


@runtime_checkable
class MatterSpine(Protocol):
    """Contract for the single matter record every app view reads from."""

    def upsert(self, matter: MatterRecord) -> Result:
        """-> Result[value=MatterRecord] idempotent on ``matter_id``."""

    def view(self, matter_id: str, view: MatterView) -> Result:
        """-> Result[value=Dict[str, Any]] one projection of the same record."""

    def link(self, matter_id: str, surface: str, artifact_id: str) -> Result:
        """Attach a per-surface artifact. Missing matter -> ``err``, never raises."""


@runtime_checkable
class ExposureFlywheel(Protocol):
    """Contract for the exposure-to-hedge metric and its foundry feed."""

    def record_exposure(self, exposure: ExposureRecord) -> Result:
        """Persist one quantified exposure."""

    def metric(self, project: str = "", as_of: str = "") -> Result:
        """-> Result[value=HedgeFlywheelMetric]."""

    def feed_foundry(self, exposure: ExposureRecord) -> Result:
        """Route an unhedgeable exposure to the instrument foundry as demand."""


@runtime_checkable
class RenewalEngine(Protocol):
    """Contract for the renewal annuity engine."""

    def schedule_for_filing(self, matter_id: str, filing_id: str) -> Result:
        """-> Result[value=List[RenewalScheduleEntry]] derived from the filing type."""

    def due_within(self, days: int = ORCH_WAVEC_RENEWAL_HORIZON_DAYS) -> Result:
        """-> Result[value=List[RenewalScheduleEntry]] soonest first."""


# ===========================================================================
# PART 7 — PIPELINE STRUCTURE (initiative-level integration, disposition memory)
# ===========================================================================
class InitiativeState(Enum):
    """Merge unit = initiative, not branch."""

    OPEN = "open"
    READY = "ready"
    JUDGING = "judging"
    MERGED = "merged"
    CLOSED = "closed"


@dataclass
class Initiative:
    """A coherent changeset judged as ONE unit, collapsing thousands of decisions."""

    initiative_id: str = ""
    project: str = ""
    title: str = ""
    state: InitiativeState = InitiativeState.OPEN
    #: Task slugs whose branches roll up into this initiative.
    member_slugs: List[str] = field(default_factory=list)
    branches: List[str] = field(default_factory=list)
    #: All members must be pushed before the initiative can be judged.
    complete: bool = False


@dataclass
class InitiativeMergeCard:
    """One card a human (or the judge) decides for the whole initiative."""

    initiative_id: str = ""
    summary: str = ""
    combined_diffstat: Dict[str, int] = field(default_factory=dict)
    verify_passed: bool = False
    conflicts: List[str] = field(default_factory=list)
    decision: str = ""  # "" | "merge" | "hold" | "close"
    rationale: str = ""


@dataclass
class DispositionMemoryEntry:
    """Branch closures train dedupe + planner so duplicate work stops being GENERATED."""

    task_slug: str = ""
    project: str = ""
    disposition: Disposition = Disposition.PENDING
    #: Embedding/summary key the planner dedupes against before emitting new work.
    dedupe_key: str = ""
    reason: str = ""
    #: Slugs that were suppressed because they matched this memory.
    suppressed_slugs: List[str] = field(default_factory=list)


@runtime_checkable
class InitiativeIntegrator(Protocol):
    """Contract for Part-7 initiative-level integration."""

    def group(self, project: str, task_slugs: List[str]) -> Result:
        """-> Result[value=Initiative] roll member branches into one merge unit."""

    def build_card(self, initiative_id: str) -> Result:
        """-> Result[value=InitiativeMergeCard] one judgeable card per initiative."""

    def decide(self, initiative_id: str, decision: str, rationale: str = "") -> Result:
        """Apply a merge/hold/close decision to the whole initiative."""


@runtime_checkable
class DispositionMemory(Protocol):
    """Contract for the planner-facing memory of what was already tried."""

    def remember(self, entry: DispositionMemoryEntry) -> Result:
        """Persist one closure so the planner can suppress its duplicates."""

    def should_suppress(self, dedupe_key: str) -> Result:
        """-> Result[value=bool] True when this work was already dispositioned."""


__all__ = [
    "ORCH_WAVEC_TRANSPLANT_MIN_SIMILARITY",
    "ORCH_WAVEC_PRECEDENT_AUTO_APPROVE",
    "ORCH_WAVEC_MERGE_UNIT",
    "ORCH_WAVEC_RENEWAL_HORIZON_DAYS",
    "Result",
    "ok",
    "err",
    "Disposition",
    "TransplantCandidate",
    "DispositionLedgerEntry",
    "ContractFirstSpec",
    "GoldenPathTemplate",
    "StrategyContext",
    "CodeGenRequest",
    "CodeGenResult",
    "CodeGenerator",
    "DispositionLedger",
    "MatterStage",
    "MatterView",
    "MatterRecord",
    "ExposureRecord",
    "HedgeFlywheelMetric",
    "RenewalScheduleEntry",
    "MatterSpine",
    "ExposureFlywheel",
    "RenewalEngine",
    "InitiativeState",
    "Initiative",
    "InitiativeMergeCard",
    "DispositionMemoryEntry",
    "InitiativeIntegrator",
    "DispositionMemory",
]
