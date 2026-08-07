#!/usr/bin/env python3
"""
breach_remediation.py - Contract breach detection, self-healing ring coordination,
replacement sourcing, remediation matter creation, and credit penalty application.

Provides a module-level singleton API for orchestrating breach remediation workflows
following the fail-soft pattern: all public functions handle errors gracefully and
return status dicts rather than raising exceptions.
"""
import threading
import time
from datetime import datetime
from typing import Dict, List, Any, Optional, Callable

# Mock-able sub-components that tests patch
class _Ring:
    def activate(self, breach_id: str, parties: List[str]) -> bool:
        return True

class _Store:
    def save(self, data: Dict[str, Any]) -> bool:
        return True
    def cleanup(self) -> None:
        pass

class _Discovery:
    def find_candidates(self, party: str, parcel_type: str) -> List[Any]:
        return []

class _Notifier:
    def send_resume_signal(self, party: str, replacement: str) -> bool:
        return True

class _Smarter:
    def activate_warroom(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return {"warroom_id": "wr_default", "status": "pending"}

class _CostCalculator:
    def calculate_split(self, parties: List[str], agreement: str) -> Dict[str, float]:
        return {p: 100 / len(parties) for p in parties}

class _Payload:
    def serialize(self, data: Dict[str, Any]) -> str:
        return str(data)

class _Ledger:
    def deduct(self, party: str, amount: float) -> Dict[str, Any]:
        return {"new_balance": 1000 - amount, "transaction_id": f"tx_{party}_{amount}"}

class _AuditLog:
    def record(self, entry: Dict[str, Any]) -> bool:
        return True

class _ContractEngine:
    def reactivate(self, contract_id: str) -> Dict[str, Any]:
        return {"status": "active", "resumed_at": datetime.now().isoformat()}
    def integrate_party(self, contract_id: str, party: str) -> bool:
        return True

# Singleton instances (replaceable for testing)
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

# Module-level singleton orchestrator
_orchestrator: Optional['RemediationOrchestrator'] = None
_lock = threading.Lock()

class RemediationOrchestrator:
    """Stateful breach remediation orchestrator with fail-soft error handling."""

    def __init__(self):
        self.state: Dict[str, Any] = {}
        self.lock = threading.Lock()

def _get_orchestrator() -> RemediationOrchestrator:
    """Get or create the singleton orchestrator."""
    global _orchestrator
    if _orchestrator is None:
        with _lock:
            if _orchestrator is None:
                _orchestrator = RemediationOrchestrator()
    return _orchestrator

def detect_breach(breach_id: str, contract_id: str,
                  affected_parties: List[str]) -> Dict[str, Any]:
    """
    Detect contract breach and activate self-healing ring.

    Returns dict with ring_activated, timestamp, and breach_id.
    """
    try:
        orch = _get_orchestrator()

        # Deduplicate parties
        unique_parties = list(set(affected_parties))

        # Prepare breach data
        breach_data = {
            "breach_id": breach_id,
            "contract_id": contract_id,
            "affected_parties": unique_parties,
            "detected_at": datetime.now().isoformat(),
        }

        # Store and activate ring
        store.save(breach_data)
        ring.activate(breach_id, unique_parties)

        result = {
            "ring_activated": True,
            "timestamp": datetime.now().isoformat(),
            "breach_id": breach_id,
        }

        if not unique_parties:
            result["warning"] = "Empty affected parties list"

        return result
    except Exception as e:
        return {"error": str(e), "ring_activated": False}

def discover_pairings(affected_party: str, parcel_type: str) -> Dict[str, Any]:
    """
    Discover replacement parties for affected party/parcel.

    Returns dict with candidates and selected_candidate, or fallback mode if empty.
    """
    try:
        # Normalize parcel type
        normalized_type = parcel_type.lower()

        # Find candidates
        candidates = discovery.find_candidates(
            party=affected_party,
            parcel_type=normalized_type
        )

        if not candidates:
            return {
                "fallback_mode": True,
                "escalation_required": True,
                "candidates": [],
            }

        # Score and select best candidate
        def score_candidate(c):
            if isinstance(c, dict):
                return c.get("reliability_score", 0)
            return 0

        selected = max(candidates, key=score_candidate)

        return {
            "candidates": candidates,
            "selected_candidate": selected,
            "fallback_mode": False,
            "escalation_required": False,
        }
    except Exception as e:
        return {
            "error": str(e),
            "fallback_mode": True,
            "escalation_required": True,
        }

def resume_honest_parties(affected_parties: List[str],
                         replacement_party: str) -> Dict[str, Any]:
    """
    Resume honest parties after breach detection and replacement sourcing.

    Returns dict with resumed status and recovery_timestamp.
    """
    try:
        notification_errors = []

        for party in affected_parties:
            try:
                notifier.send_resume_signal(party, replacement_party)
            except Exception as e:
                notification_errors.append(str(e))

        result = {
            "resumed": True,
            "recovery_timestamp": datetime.now().isoformat(),
            "parties_notified": len(affected_parties),
        }

        if notification_errors:
            result["notification_errors"] = notification_errors

        # Persist state
        store.save({
            "affected_parties": affected_parties,
            "replacement_party": replacement_party,
            "resumed_at": result["recovery_timestamp"],
        })

        return result
    except Exception as e:
        return {"error": str(e), "resumed": False}

def open_remediation_matter(breach_id: str, affected_parties: List[str],
                           cost_share_agreement: str) -> Dict[str, Any]:
    """
    Open remediation matter and activate warRoom for cost-sharing.

    Returns dict with warroom_id, status, and cost_split.
    """
    try:
        # Calculate cost split
        cost_split = cost_calculator.calculate_split(affected_parties, cost_share_agreement)

        # Prepare payload
        remediation_payload = {
            "breach_details": {"breach_id": breach_id},
            "remediation_scope": {"parties": affected_parties},
            "cost_split": cost_split,
            "timestamp": datetime.now().isoformat(),
        }

        # Serialize payload
        payload.serialize(remediation_payload)

        # Activate warroom
        warroom_result = smarter.activate_warroom(remediation_payload)

        result = {
            "warroom_id": warroom_result.get("warroom_id"),
            "status": warroom_result.get("status", "pending"),
            "cost_split": cost_split,
        }

        return result
    except Exception as e:
        return {
            "error": str(e),
            "escalation_triggered": True,
        }

def apply_credit_penalty(party: str, penalty_amount: float,
                         reason: str) -> Dict[str, Any]:
    """
    Apply credit penalty to breaching party.

    Returns dict with new_balance and transaction details.
    """
    try:
        # Validate amount
        if penalty_amount < 0:
            return {"error": "negative penalty amount not allowed"}

        if penalty_amount == 0:
            return {"amount_validation": "zero amount", "skipped": True}

        # Deduct from ledger
        ledger_result = ledger.deduct(party, penalty_amount)

        # Record audit entry
        audit_entry = {
            "party": party,
            "penalty_amount": penalty_amount,
            "reason": reason,
            "timestamp": datetime.now().isoformat(),
            "transaction_id": ledger_result.get("transaction_id"),
        }
        audit_log.record(audit_entry)

        result = {
            "new_balance": ledger_result.get("new_balance"),
            "transaction_id": ledger_result.get("transaction_id"),
            "partial": ledger_result.get("partial", False),
        }

        if "available" in ledger_result:
            result["available"] = ledger_result["available"]

        return result
    except Exception as e:
        return {"error": str(e)}

def resume_contract(contract_id: str, remediation_id: str,
                   replacement_party: Optional[str] = None) -> Dict[str, Any]:
    """
    Resume contract after remediation is complete.

    Returns dict with reactivated contract status.
    """
    try:
        # Reactivate contract
        contract_result = contract_engine.reactivate(contract_id)

        # Integrate replacement party if provided
        if replacement_party:
            contract_engine.integrate_party(contract_id, replacement_party)

        return {
            "status": contract_result.get("status"),
            "resumed_at": contract_result.get("resumed_at"),
            "contract_id": contract_id,
            "remediation_id": remediation_id,
        }
    except Exception as e:
        return {"error": str(e), "status": "failed"}

def orchestrate_breach_remediation(breach_id: str, contract_id: str,
                                  affected_parties: List[str],
                                  parcel_type: str,
                                  cost_share_agreement: str = "pre_agreed_v1") -> Dict[str, Any]:
    """
    Execute complete breach remediation pipeline end-to-end.

    Orchestrates: detect -> discover -> resume -> matter -> penalty -> contract.
    Continues on non-critical failures with partial_failure flag.
    Rolls back on critical failures.
    """
    try:
        orch = _get_orchestrator()

        # Step 1: Detect breach
        try:
            detect_result = detect_breach(breach_id, contract_id, affected_parties)
            if not detect_result.get("ring_activated"):
                raise Exception("Ring activation failed")
        except Exception as e:
            # Critical failure - rollback
            store.cleanup()
            return {
                "success": False,
                "error": str(e),
                "breach_id": breach_id,
            }

        # Step 2: Discover replacement pairings
        try:
            discover_result = discover_pairings(affected_parties[0] if affected_parties else "unknown", parcel_type)
            replacement_party = discover_result.get("selected_candidate", {}).get("id")
        except Exception as e:
            discover_result = {"error": str(e)}
            replacement_party = None

        # Step 3: Resume honest parties
        partial_failure = False
        try:
            resume_result = resume_honest_parties(affected_parties, replacement_party or "default")
        except Exception as e:
            resume_result = {"error": str(e)}
            partial_failure = True

        # Step 4: Open remediation matter
        try:
            matter_result = open_remediation_matter(breach_id, affected_parties, cost_share_agreement)
            warroom_id = matter_result.get("warroom_id")
        except Exception as e:
            matter_result = {"error": str(e)}
            warroom_id = None

        # Step 5: Apply credit penalty
        try:
            penalty_result = apply_credit_penalty(
                affected_parties[0] if affected_parties else "unknown",
                100,
                "contract_breach_remediation"
            )
            new_balance = penalty_result.get("new_balance")
        except Exception as e:
            penalty_result = {"error": str(e)}
            new_balance = None

        # Step 6: Resume contract
        try:
            contract_result = resume_contract(contract_id, breach_id, replacement_party)
            contract_status = contract_result.get("status")
        except Exception as e:
            contract_result = {"error": str(e)}
            contract_status = None

        result = {
            "success": not partial_failure,
            "breach_id": breach_id,
            "contract_id": contract_id,
            "replacement_party": replacement_party,
            "warroom_id": warroom_id,
            "contract_status": contract_status,
            "credit_penalty_applied": new_balance is not None,
            "remediation_payload": {
                "breach_details": {"breach_id": breach_id},
                "remediation_scope": {"parties": affected_parties},
            },
        }

        if partial_failure:
            result["partial_failure"] = True

        # Persist final orchestration state
        store.save(result)

        return result
    except Exception as e:
        store.cleanup()
        return {
            "success": False,
            "error": str(e),
            "breach_id": breach_id,
        }

def invalidate() -> None:
    """Clear the module-level singleton for testing."""
    global _orchestrator
    with _lock:
        _orchestrator = None
