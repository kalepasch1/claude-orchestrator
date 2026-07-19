#!/usr/bin/env python3
"""Closed-loop control compiler: proposal -> simulation -> canary -> DiD -> receipt."""
import hashlib
import os
import time

import adversarial_fleet
import db
import evidence_bus


def _change_id(key, value):
    return hashlib.sha256(f"{key}={value}".encode()).hexdigest()[:32]


def propose_config(key, value, actor="auto"):
    change_id = _change_id(key, value)
    proposal = evidence_bus.append("ORCHESTRATOR", "config.proposed", key,
                                   {"value": str(value), "actor": actor}, key=change_id)
    return change_id, proposal


def authorize_config(key, value, actor="auto", simulation=None):
    """Create the sole authorization record consumed by fleet_config replication."""
    change_id, proposal = propose_config(key, value, actor)
    simulation = simulation or adversarial_fleet.calibrated_simulation(key, value)
    status = "authorized" if simulation.get("passed") else "rejected"
    record = {"id": change_id, "config_key": key, "candidate_value": str(value),
              "actor": actor, "status": status, "simulation": simulation,
              "evidence_key": proposal["idempotency_key"]}
    try:
        db.insert("policy_config_changes", record, upsert=True)
    except Exception as exc:
        return {**record, "status": "rejected", "reason": f"persistence:{exc}"}
    evidence_bus.append("ORCHESTRATOR", f"config.{status}", key, record,
                        parent_key=proposal["idempotency_key"], key=f"{change_id}:{status}")
    return record


def complete_config(change_id, outcome, metrics=None):
    status = "graduated" if outcome == "applied" else "rolled_back"
    try:
        db.update("policy_config_changes", {"id": change_id},
                  {"status": status, "outcome": outcome, "metrics": metrics or {}, "decided_at": "now()"})
    except Exception:
        pass
    return evidence_bus.append("ORCHESTRATOR", f"config.{status}", change_id,
                               {"outcome": outcome, "metrics": metrics or {}})


def authorized(change_id):
    try:
        rows = db.select("policy_config_changes", {"select": "status", "id": f"eq.{change_id}", "limit": "1"}) or []
        return bool(rows and rows[0].get("status") in ("authorized", "graduated"))
    except Exception:
        return False


def route_experiment(experiment, subject, cohort, metric_start):
    """Persist deterministic treatment/control assignment and its baseline."""
    payload = {"experiment_id": experiment, "cohort": cohort, "metric_start": metric_start}
    return evidence_bus.append("ORCHESTRATOR", "experiment.assignment", subject, payload,
                               key=evidence_bus.idempotency_key("ORCHESTRATOR", "experiment.assignment", subject, payload))
