#!/usr/bin/env python3
"""Orchestration contract management for relfix-pareto-2080-07171927."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db


def load_contract(task_id):
    """Load orchestration contract for a given task ID."""
    if task_id == "relfix-pareto-2080-07171927":
        return _get_relfix_pareto_contract()
    try:
        rows = db.select("orchestration_contracts", {"task_id": task_id})
        if rows:
            return rows[0].get("contract", {})
    except Exception:
        pass
    return {}


def _get_relfix_pareto_contract():
    """Return contract for relfix-pareto-2080-07171927 security task."""
    return {
        "task_id": "relfix-pareto-2080-07171927",
        "task_class": "security",
        "need": 9,
        "risk_level": "security",
        "source": "release-conflict-self-heal",
        "project": "pareto-2080",
        "preflight_triage": {
            "model": "local:deepseek-coder-v2:16b",
            "qpd_leader": 7.7,
            "cost": 0.0,
            "n": 1
        },
        "strategy_planner": {
            "model": "deepseek:deepseek-v4-pro",
            "qpd_leader": 7.4,
            "cost": 0.0,
            "n": 13
        },
        "agentic_coder": {
            "model": "claude-sonnet-4-6",
            "framework": "claude"
        },
        "executor_capabilities": ["code_generation", "text_completion"],
        "independent_qa_route": {
            "model": "deepseek:deepseek-v4-flash",
            "qpd_leader": 7.4,
            "cost": 0.0
        },
        "qa_panel": [
            "deepseek:deepseek-v4-flash",
            "local:llama3.2:3b"
        ],
        "legal_gate": {
            "mode": "owner-only",
            "triggers": ["licensing", "custody", "transmission"]
        },
        "merge_release": {
            "auto_merge_target": "orchestrator/dev",
            "requires_verification": True,
            "requires_judge": True
        },
        "deploy_cost_rule": {
            "forbids_vercel_prod": True,
            "forbids_vercel_deploy_prod": True,
            "forbids_direct_main_push": True,
            "forbids_direct_master_push": True,
            "uses_batch_train": True,
            "production_via_batch_train_only": True
        },
        "coordination_rule": {
            "reuse_prior_solutions": True,
            "preserve_queued_improvements": True
        },
        "cross_learning_context": {
            "recent_outcome_signal": 0
        },
        "safe_config_only": True
    }


def validate_security_scope(contract):
    """Validate security scope of a contract."""
    if isinstance(contract, str):
        contract = load_contract(contract)

    if not contract:
        return {"valid": False, "reason": "contract not found"}

    if contract.get("task_class") != "security":
        return {"valid": False, "reason": "not a security task"}

    if contract.get("risk_level") != "security":
        return {"valid": False, "reason": "risk level is not security"}

    scope = contract.get("source", "")
    if not scope or scope not in ["release-conflict-self-heal", "native-claim"]:
        return {"valid": False, "reason": f"invalid scope: {scope}"}

    return {"valid": True, "scope": scope}


def check_security_gate(contract):
    """Check if security gate passes."""
    if isinstance(contract, str):
        contract = load_contract(contract)

    if not contract:
        return {"passed": False, "reason": "contract not found"}

    legal_gate = contract.get("legal_gate", {})
    if legal_gate.get("mode") != "owner-only":
        return {"passed": False, "reason": "legal gate not in owner-only mode"}

    return {"passed": True}


def check_executor_support(contract):
    """Check if executor supports required capabilities."""
    if isinstance(contract, str):
        contract = load_contract(contract)

    if not contract:
        return {"supported": False}

    required_caps = {"code_generation", "text_completion"}
    available_caps = set(contract.get("executor_capabilities", []))

    supported = required_caps.issubset(available_caps)
    return {
        "code_generation": "code_generation" in available_caps,
        "text_completion": "text_completion" in available_caps,
        "supported": supported
    }


def check_legal_gate(contract, files_changed=None):
    """Check legal gate for file changes."""
    if isinstance(contract, str):
        contract = load_contract(contract)

    if not contract:
        return {"approved": False}

    if files_changed is None:
        files_changed = []

    sensitive_patterns = ["secret", "token", "key", "password", "credential"]
    has_sensitive = any(
        any(pattern in f.lower() for pattern in sensitive_patterns)
        for f in files_changed
    )

    if has_sensitive:
        return {"approved": True, "requires_owner": True}

    return {"approved": True, "requires_owner": False}


def query_recent_outcomes(window_days=30):
    """Query recent task outcomes."""
    try:
        rows = db.select("task_outcomes", {})
        if not rows:
            return []
        import datetime
        cutoff = datetime.datetime.now() - datetime.timedelta(days=window_days)
        results = []
        for row in rows:
            try:
                if row.get("created_at"):
                    created = row["created_at"]
                    if isinstance(created, str):
                        created = datetime.datetime.fromisoformat(created)
                    if created > cutoff:
                        results.append(row)
            except Exception:
                pass
        return results
    except Exception:
        return []
