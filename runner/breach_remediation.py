#!/usr/bin/env python3
"""
breach_remediation.py - Breach detection, self-healing and remediation pipeline.

Contract exercised by runner/tests/test_breach_remediation.py: breach
detection activates a self-healing ring, replacement parties are discovered
and scored, honest parties are resumed, a pre-agreed shared-cost remediation
matter is opened via the smarter warRoom bridge, credit penalties are applied
on reveal, and the contract is resumed.

Conventions (per CLAUDE.md):
- Module-level singleton pattern: functions delegate to a thread-safe
  RemediationOrchestrator singleton (created lazily, cleared by invalidate()).
- Fail-soft error handling: public functions never raise on bad input.
- Environment variable configuration with sensible defaults.
- Thread-safe with explicit locks; minimal critical sections.
"""
import json
import os
import threading
import uuid
from datetime import datetime

DEFAULT_PENALTY_CREDITS = int(os.environ.get("BREACH_PENALTY_CREDITS", "100"))
DEFAULT_COST_SHARE_AGREEMENT = os.environ.get(
    "BREACH_COST_SHARE_AGREEMENT", "pre_agreed_v1"
)

_lock = threading.Lock()
_orchestrator = None


# --- Fail-soft collaborator seams (patchable in tests) -----------------------


class _Ring:
    """Self-healing ring seam."""

    def activate(self, **kwargs):
        return {"activated": True, **kwargs}


class _Store:
    """In-memory remediation state store (fail-soft)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._records = []

    def save(self, record):
        with self._lock:
            self._records.append(record)
        return True

    def cleanup(self):
        with self._lock:
            self._records = []
        return True


class _Discovery:
    """Replacement party/parcel discovery seam."""

    def find_candidates(self, affected_party=None, parcel_type=None):
        return []


class _Notifier:
    """Resume-signal notifier seam."""

    def send_resume_signal(self, party, replacement_party=None):
        return True


class _Smarter:
    """smarter warRoomSync bridge seam."""

    def activate_warroom(self, payload=None):
        return {"warroom_id": "wr_" + uuid.uuid4().hex[:8], "status": "active"}


class _CostCalculator:
    """Remediation cost-split calculator (equal split default)."""

    def calculate_split(self, parties=None, agreement=None):
        parties = list(parties or [])
        if not parties:
            return {}
        share = round(100.0 / len(parties), 2)
        return {p: share for p in parties}


class _Payload:
    """Remediation payload serializer (fail-soft)."""

    def serialize(self, payload):
        try:
            return json.dumps(payload, default=str)
        except Exception:
            return "{}"


class _Ledger:
    """Credit ledger seam."""

    def deduct(self, party, amount):
        return {"new_balance": 0, "transaction_id": "tx_" + uuid.uuid4().hex[:8]}


class _AuditLog:
    """Append-only audit trail (fail-soft)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._entries = []

    def record(self, entry):
        with self._lock:
            self._entries.append(entry)
        return True


class _ContractEngine:
    """Contract lifecycle seam."""

    def reactivate(self, contract_id):
        return {"status": "active", "resumed_at": datetime.now().isoformat()}

    def integrate_party(self, contract_id, party):
        return True


ring = _Ring()
store = _Store()
discovery = _Discovery()
notifier = _Notifier()
smarter = _Smarter()
cost_calculator = _CostCalculator()
payload = _Payload()
ledger = _Ledger()
audit_log = _AuditLog()
contract_engine = _ContractEngine()


# --- Singleton ---------------------------------------------------------------


class RemediationOrchestrator:
    """Holds per-process remediation state; access is lock-guarded."""

    def __init__(self):
        self.lock = threading.Lock()
        self.remediations = {}

    def track(self, breach_id, data):
        with self.lock:
            self.remediations[breach_id] = data


def _get_orchestrator():
    global _orchestrator
    if _orchestrator is None:
        with _lock:
            if _orchestrator is None:
                _orchestrator = RemediationOrchestrator()
    return _orchestrator


def invalidate():
    """Clear the singleton (tests / lifecycle)."""
    global _orchestrator
    with _lock:
        _orchestrator = None
    return None


def _now():
    return datetime.now().isoformat()


# --- Public API --------------------------------------------------------------


def detect_breach(breach_id, contract_id, affected_parties):
    """Detect a breach: persist metadata and activate the self-healing ring."""
    orchestrator = _get_orchestrator()
    parties = list(dict.fromkeys(affected_parties or []))
    result = {"breach_id": breach_id, "timestamp": _now(), "ring_activated": False}
    if not parties:
        result["warning"] = "empty affected_parties list"
    record = {
        "breach_id": breach_id,
        "contract_id": contract_id,
        "affected_parties": parties,
        "detected_at": result["timestamp"],
    }
    try:
        store.save(record)
    except Exception as exc:  # fail-soft
        result["store_error"] = str(exc)
    try:
        ring.activate(breach_id=breach_id, contract_id=contract_id, parties=parties)
        result["ring_activated"] = True
    except Exception as exc:  # fail-soft
        result["ring_error"] = str(exc)
    orchestrator.track(breach_id, record)
    return result


def discover_pairings(affected_party, parcel_type):
    """Locate and score replacement party/parcel candidates."""
    _get_orchestrator()
    normalized = str(parcel_type or "").strip().lower()
    try:
        candidates = discovery.find_candidates(
            affected_party=affected_party, parcel_type=normalized
        )
    except Exception as exc:  # fail-soft
        candidates = []
    candidates = list(candidates or [])
    if not candidates:
        return {
            "candidates": [],
            "fallback_mode": True,
            "escalation_required": True,
            "affected_party": affected_party,
        }
    result = {"candidates": candidates, "fallback_mode": False}
    scored = [c for c in candidates if isinstance(c, dict)]
    if scored:
        result["selected_candidate"] = max(
            scored, key=lambda c: c.get("reliability_score") or 0.0
        )
    else:
        result["selected_candidate"] = {"id": candidates[0]}
    return result


def resume_honest_parties(affected_parties, replacement_party=None):
    """Signal honest parties to resume operations with the replacement party."""
    _get_orchestrator()
    parties = list(affected_parties or [])
    errors = []
    for party in parties:
        try:
            notifier.send_resume_signal(party, replacement_party)
        except Exception as exc:  # fail-soft, keep notifying the rest
            errors.append({"party": party, "error": str(exc)})
    result = {
        "resumed": len(errors) < len(parties) or not parties,
        "recovery_timestamp": _now(),
        "notification_errors": errors,
        "replacement_party": replacement_party,
    }
    try:
        store.save({"event": "resume_honest_parties", **result})
    except Exception:
        pass
    return result


def open_remediation_matter(breach_id, affected_parties, cost_share_agreement):
    """Open a pre-agreed shared-cost remediation matter via the smarter bridge."""
    _get_orchestrator()
    parties = list(affected_parties or [])
    matter_payload = {
        "breach_details": {"breach_id": breach_id, "affected_parties": parties},
        "remediation_scope": {"cost_share_agreement": cost_share_agreement},
    }
    result = {"breach_id": breach_id}
    try:
        result["serialized_payload"] = payload.serialize(matter_payload)
    except Exception as exc:  # fail-soft
        result["serialization_error"] = str(exc)
    try:
        result["cost_split"] = cost_calculator.calculate_split(
            parties=parties, agreement=cost_share_agreement
        )
    except Exception as exc:  # fail-soft
        result["cost_split"] = {}
        result["cost_split_error"] = str(exc)
    try:
        warroom = smarter.activate_warroom(matter_payload)
        if isinstance(warroom, dict):
            result.update(warroom)
        result.setdefault("escalation_triggered", False)
    except Exception as exc:
        result["escalation_triggered"] = True
        result["error"] = str(exc)
    return result


def apply_credit_penalty(party, penalty_amount, reason):
    """Deduct credits from the breaching party and record an audit entry."""
    _get_orchestrator()
    if penalty_amount is None or penalty_amount < 0:
        return {"error": "negative penalty_amount rejected", "party": party}
    result = {"party": party, "penalty_amount": penalty_amount, "reason": reason}
    if penalty_amount == 0:
        result["amount_validation"] = "zero_amount_noop"
        return result
    try:
        deducted = ledger.deduct(party, penalty_amount)
        if isinstance(deducted, dict):
            result.update(deducted)
        result["applied"] = True
    except Exception as exc:
        result["error"] = str(exc)
        result["applied"] = False
        return result
    try:
        audit_log.record(
            {"party": party, "penalty_amount": penalty_amount, "reason": reason,
             "timestamp": _now()}
        )
    except Exception:  # fail-soft: audit failure never blocks the penalty
        pass
    return result


def resume_contract(contract_id, remediation_id, replacement_party=None):
    """Reactivate the contract after remediation; integrate replacement party."""
    _get_orchestrator()
    result = {"contract_id": contract_id, "remediation_id": remediation_id}
    try:
        reactivated = contract_engine.reactivate(contract_id)
        if isinstance(reactivated, dict):
            result.update(reactivated)
        result.setdefault("status", "active")
    except Exception as exc:  # fail-soft
        result["status"] = "error"
        result["error"] = str(exc)
        return result
    if replacement_party:
        try:
            contract_engine.integrate_party(contract_id, replacement_party)
            result["replacement_party"] = replacement_party
        except Exception as exc:  # fail-soft
            result["integration_error"] = str(exc)
    return result


def orchestrate_breach_remediation(breach_id, contract_id, affected_parties,
                                   parcel_type,
                                   cost_share_agreement=DEFAULT_COST_SHARE_AGREEMENT,
                                   penalty_amount=DEFAULT_PENALTY_CREDITS,
                                   breaching_party=None):
    """Run the complete remediation pipeline. Critical failure -> rollback."""
    _get_orchestrator()
    parties = list(affected_parties or [])
    result = {"breach_id": breach_id, "success": False, "partial_failure": False}
    try:
        detection = detect_breach(breach_id, contract_id, parties)
        result["detection"] = detection
    except Exception as exc:  # critical: roll back
        try:
            store.cleanup()
        except Exception:
            pass
        result["error"] = str(exc)
        return result
    try:
        pairing = discover_pairings(parties[0] if parties else "", parcel_type)
        selected = pairing.get("selected_candidate") or {}
        replacement = selected.get("id") if isinstance(selected, dict) else None
    except Exception as exc:
        result["partial_failure"] = True
        result["pairing_error"] = str(exc)
        replacement = None
    result["replacement_party"] = replacement

    try:
        resumed = resume_honest_parties(parties, replacement)
        result["honest_parties_resumed"] = resumed
    except Exception as exc:  # non-critical: continue the pipeline
        result["partial_failure"] = True
        result["resume_error"] = str(exc)
    try:
        matter = open_remediation_matter(breach_id, parties, cost_share_agreement)
        if isinstance(matter, dict) and "warroom_id" in matter:
            result["warroom_id"] = matter["warroom_id"]
        result["remediation_matter"] = matter
    except Exception as exc:
        result["partial_failure"] = True
        result["matter_error"] = str(exc)
        matter = {}
    try:
        penalty = apply_credit_penalty(
            breaching_party or (parties[0] if parties else "unknown"),
            penalty_amount,
            "contract_breach_reveal",
        )
        result["credit_penalty_applied"] = penalty
    except Exception as exc:
        result["partial_failure"] = True
        result["penalty_error"] = str(exc)

    try:
        contract = resume_contract(contract_id, "rem_" + str(breach_id), replacement)
        if isinstance(contract, dict):
            result["contract_status"] = contract.get("status")
    except Exception as exc:
        result["partial_failure"] = True
        result["contract_error"] = str(exc)
    result["remediation_payload"] = {
        "breach_id": breach_id,
        "contract_id": contract_id,
        "affected_parties": parties,
        "parcel_type": parcel_type,
        "replacement_party": replacement,
        "completed_at": _now(),
    }
    result["success"] = True
    try:
        store.save({"event": "remediation_complete", **result["remediation_payload"]})
    except Exception:  # fail-soft
        pass
    return result
