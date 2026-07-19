#!/usr/bin/env python3
"""Evidence-first autonomous-control extensions (#26--#33).

All actuators are deliberately bounded: simulations only gate configuration changes,
experiments only auto-graduate reversible changes, and constitutional changes are
always proposals for an explicit human approval.
"""
import hashlib
import math
import os
import random
import time
from collections import defaultdict

import db


def calibrated_simulation(key, value, runs=500):
    """Bootstrap historical fleet evidence and model the specific config perturbation."""
    try:
        import evidence_bus
        rows = evidence_bus.events("fleet.snapshot", limit=2000)
        rollbacks = evidence_bus.events("incident.rollback", limit=2000)
    except Exception:
        rows = []; rollbacks = []
    samples = [r.get("payload") or {} for r in rows]
    try:
        current, candidate = float(os.environ.get(key, "4")), float(value)
    except (TypeError, ValueError):
        current = candidate = 1.0
    ratio = max(.1, min(10.0, candidate / max(current, .1)))
    queue = [float(x.get("queue_growth", 0)) for x in samples]
    latency = [float(x.get("latency_drift", 0)) for x in samples]
    burn = [float(x.get("budget_burn", 0)) for x in samples]
    pressure = ratio if key in ("MAX_PARALLEL", "ORCH_FLEET_CAPACITY") else 1.0
    cfg = {"budget": 1 / max((sum(burn) / len(burn)) if burn else .35, .05),
           "capacity": max(1.0, 4 / pressure),
           "max_failure_rate": float(os.environ.get("ORCH_SIMULATION_MAX_FAILURE_RATE", ".08")),
           "outage_rate": min(.25, .02 + max(latency or [0]) * .05 + len(rollbacks) / max(len(samples), 1) * .10),
           "correlation_rate": min(.30, .05 + max(queue or [0]) * .10)}
    result = simulate(cfg, runs=runs, seed=int(hashlib.sha256(f"{key}={value}".encode()).hexdigest()[:8], 16))
    result.update({"calibrated_samples": len(samples), "rollback_samples": len(rollbacks), "config_key": key, "candidate": str(value)})
    return result


def _pct(values):
    return sum(values) / max(len(values), 1)


# #26: reproducible adversarial Monte Carlo gate ---------------------------------
def simulate(config, runs=500, seed=0):
    """Stress a configuration against cascades, correlated regression, and budget drain."""
    rng = random.Random(seed)
    budget = max(float(config.get("budget", 1)), 1.0)
    capacity = max(float(config.get("capacity", 1)), 1.0)
    failures = []
    for _ in range(max(1, runs)):
        correlated = rng.random() < float(config.get("correlation_rate", .08))
        outage = rng.random() < float(config.get("outage_rate", .03))
        load = rng.lognormvariate(0, .45) * (2.2 if correlated else 1.0)
        spend = rng.lognormvariate(math.log(max(budget * .35, .01)), .55) * (1.8 if outage else 1.0)
        failed = outage or load > capacity or spend > budget
        failures.append(failed)
    return {"runs": len(failures), "failure_rate": round(_pct(failures), 4),
            "passed": _pct(failures) <= float(config.get("max_failure_rate", .05)), "seed": seed}


# #27: DiD experiment decision -----------------------------------------------------
def difference_in_differences(control_before, control_after, treatment_before, treatment_after):
    """Return an effect only when all four cohort summaries are present."""
    return round((float(treatment_after) - float(treatment_before)) -
                 (float(control_after) - float(control_before)), 6)


def experiment_verdict(effect, minimum_effect=0.0, reversible=True):
    if effect >= minimum_effect and reversible:
        return "graduate"
    return "rollback" if effect < 0 else "hold_for_human"


# #28: privacy-preserving MAML-style initialization --------------------------------
def meta_initialize(global_weights, tenant_gradients, step_size=.1):
    """One first-order meta step; callers provide only clipped/noised tenant gradients."""
    if not tenant_gradients:
        return list(global_weights)
    width = len(global_weights)
    mean = [sum(float(g[i]) for g in tenant_gradients if len(g) > i) / len(tenant_gradients)
            for i in range(width)]
    return [round(float(w) - step_size * mean[i], 8) for i, w in enumerate(global_weights)]


# #29: Vickrey allocation -----------------------------------------------------------
def vickrey_allocate(bids, slots):
    """Allocate scarce compute by bid; winners pay the highest losing bid, never exceed bid."""
    ranked = sorted((b for b in bids if float(b.get("roi", 0)) > 0),
                    key=lambda b: (-float(b["roi"]), str(b.get("agent", ""))))
    winners, clearing = ranked[:max(0, int(slots))], (ranked[int(slots):int(slots)+1] or [{"roi": 0}])[0]
    price = float(clearing.get("roi", 0))
    return [{"agent": b["agent"], "allocation": 1, "clearing_price": min(float(b["roi"]), price)} for b in winners]


# #30: pre-incident detector --------------------------------------------------------
def predictive_incident(snapshot):
    """Require multiple leading indicators, avoiding alert noise from a single spike."""
    signals = [float(snapshot.get("queue_growth", 0)) >= .25,
               float(snapshot.get("latency_drift", 0)) >= .20,
               float(snapshot.get("budget_burn", 0)) >= .80]
    if sum(signals) < 2:
        return None
    action = "throttle" if signals[2] else "scale"
    return {"signal": "pre_incident", "severity": "warn", "action": action,
            "detail": "leading indicators: queue/latency/budget=" + "/".join(map(str, signals))}


# #31: constitution amendments remain human-gated ----------------------------------
def amendment_proposal(rule, blocked, later_safe, threshold=.20, min_samples=20):
    rate = float(later_safe) / max(int(blocked), 1)
    if int(blocked) < min_samples or rate <= threshold:
        return None
    return {"rule": rule, "false_positive_rate": round(rate, 4), "status": "proposed",
            "requires_human_approval": True}


# #32: structured high-stakes debate ------------------------------------------------
def debate_required(blast_radius, threshold=50):
    return float(blast_radius or 0) >= threshold


# #33: continuous compliance coverage ------------------------------------------------
def compliance_coverage(receipts, required_controls):
    observed = {r.get("control") for r in receipts if r.get("valid", True)}
    required = set(required_controls)
    missing = sorted(required - observed)
    return {"coverage": round((len(required) - len(missing)) / max(len(required), 1), 4), "missing": missing}


def advance_advisory_controls():
    """Consume signed bus inputs for #28/#29/#31; never actuate tenants or budgets directly."""
    try:
        import evidence_bus
        events = evidence_bus.events(limit=2000)
    except Exception:
        return {"meta": 0, "auctions": 0, "amendments": 0}
    gradients, bids, outcomes = defaultdict(list), defaultdict(list), defaultdict(list)
    for event in events:
        payload = event.get("payload") or {}
        if event.get("kind") == "federated.gradient" and payload.get("dp_epsilon") and payload.get("gradient"):
            gradients[payload.get("tenant_id")].append(payload)
        elif event.get("kind") == "budget.bid" and payload.get("signature") and payload.get("roi") is not None:
            bids[payload.get("auction_id", "default")].append(payload)
        elif event.get("kind") == "constitution.outcome" and payload.get("rule"):
            outcomes[payload["rule"]].append(payload)
    meta = auctions = amendments = 0
    for tenant, rows in gradients.items():
        if not tenant or len(rows) >= 10:  # bootstrap only the intended cold-start window
            continue
        initial = meta_initialize(rows[0].get("global_weights", []), [r["gradient"] for r in rows])
        record = {"tenant_id": tenant, "observation_count": len(rows), "dp_epsilon": rows[0]["dp_epsilon"],
                  "global_model_version": rows[0].get("global_model_version"), "initialization": initial, "status": "advisory"}
        try: db.insert("tenant_meta_initializations", record); evidence_bus.append("ORCHESTRATOR", "federated.initialized", tenant, record); meta += 1
        except Exception: pass
    for auction_id, rows in bids.items():
        allocation = vickrey_allocate(rows, min(len(rows), int(os.environ.get("ORCH_AUCTION_SLOTS", "1"))))
        record = {"id": str(auction_id), "bids": rows, "allocation": allocation, "reserve_price": 0, "status": "advisory"}
        try: db.insert("compute_auction_rounds", record, upsert=True); evidence_bus.append("ORCHESTRATOR", "budget.auction_advisory", auction_id, record); auctions += 1
        except Exception: pass
    for rule, rows in outcomes.items():
        proposal = amendment_proposal(rule, len(rows), sum(bool(r.get("later_safe")) for r in rows))
        if proposal:
            try: db.insert("constitutional_amendment_proposals", {"rule": rule, "evidence": {"samples": rows}, "status": "proposed"}); evidence_bus.append("ORCHESTRATOR", "constitution.amendment_proposed", rule, proposal); amendments += 1
            except Exception: pass
    return {"meta": meta, "auctions": auctions, "amendments": amendments}


def run():
    """Read-only/append-only coordination pass; external actions stay in existing gated loops."""
    now = int(time.time())
    def select(table, query):
        try:
            return db.select(table, query) or []
        except Exception as e:
            print(f"adversarial_fleet: {table} unavailable ({e})")
            return []

    snapshots = select("fleet_signal_snapshots", {"select": "*", "limit": "100"})
    predicted = 0
    for snap in snapshots:
        try:
            import evidence_bus
            evidence_bus.append(snap.get("app", "ORCHESTRATOR"), "fleet.snapshot", str(snap.get("id", "")), snap)
        except Exception:
            pass
        finding = predictive_incident(snap)
        if finding:
            db.insert("incidents", {"app": snap.get("app", "ORCHESTRATOR"), **finding})
            try:
                evidence_bus.append(snap.get("app", "ORCHESTRATOR"), "incident.predicted", str(snap.get("id", "")), finding)
            except Exception:
                pass
            predicted += 1
    receipts = select("compliance_receipts", {"select": "*", "limit": "1000"})
    rules = select("compliance_control_requirements", {"select": "app,control,sla_coverage"})
    by_app, controls = defaultdict(list), defaultdict(list)
    for row in receipts: by_app[row.get("app", "ORCHESTRATOR")].append(row)
    for row in rules: controls[row.get("app", "ORCHESTRATOR")].append(row.get("control"))
    remediation = 0
    for app, required in controls.items():
        status = compliance_coverage(by_app[app], required)
        sla = min([float(r.get("sla_coverage") or 1) for r in rules if r.get("app", "ORCHESTRATOR") == app] or [1])
        db.insert("continuous_compliance_status", {"app": app, **status, "checked_at": now})
        try:
            evidence_bus.append(app, "compliance.coverage", app, status)
        except Exception:
            pass
        if status["coverage"] < sla:
            db.insert("compliance_remediations", {"app": app, "missing_controls": status["missing"], "status": "open"})
            remediation += 1
    advisory = advance_advisory_controls()
    print(f"adversarial_fleet: predicted={predicted} compliance_remediations={remediation} advisory={advisory}")
    return {"predicted": predicted, "remediations": remediation, **advisory}


if __name__ == "__main__":
    run()
