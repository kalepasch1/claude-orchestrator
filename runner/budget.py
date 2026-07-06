#!/usr/bin/env python3
"""
budget.py - per-project spend telemetry/guardrails.

Owner policy: caps should inform routing and spend dashboards, not create manual task
backlogs. The runner therefore does NOT block by default when a project crosses its cap;
subscription/fixed-price coders can keep moving, and paid-API coders enforce their own
small caps at the provider route. Set ORCH_BUDGET_BLOCKS_TASKS=true only for a deliberate
hard stop.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

def _block_on_cap():
    # Evaluate at CALL time (not import) so flipping ORCH_EMERGENCY_BUDGET_STOP via fleet_config +
    # reload takes effect immediately, without waiting for a full runner restart. This is the
    # emergency brake ONLY — in subscription mode real spend is $0, so it must stay OFF or it blocks
    # every over-(phantom)-cap project and starves integrate of inputs (the "ships nothing" bug).
    return os.environ.get("ORCH_EMERGENCY_BUDGET_STOP", "false").lower() in ("true", "1", "yes")


# back-compat module constant (some callers import it); prefer _block_on_cap() for live evaluation
BLOCK_ON_CAP = _block_on_cap()
FILE_BUDGET_CARDS = os.environ.get("ORCH_FILE_BUDGET_CARDS", "false").lower() in ("true", "1", "yes")


def status(project):
    """Return {cap, spent, hard_pause, over} for a project (defaults if unset)."""
    cap, hard = None, True
    try:
        b = db.select("budgets", {"select": "*", "project": f"eq.{project}"}) or []
        if b:
            cap = float(b[0]["monthly_usd_cap"]); hard = bool(b[0]["hard_pause"])
    except Exception:
        pass
    spent = 0.0
    try:
        rows = db.select("v_spend_mtd", {"select": "spent", "project": f"eq.{project}"}) or []
        if rows:
            spent = float(rows[0]["spent"] or 0)
    except Exception:
        pass
    over = cap is not None and spent >= cap
    return {"cap": cap, "spent": round(spent, 2), "hard_pause": hard, "over": over}


def allow(project):
    """True if a new task may run; False only for the explicit emergency stop flag."""
    s = status(project)
    if s["over"] and s["hard_pause"]:
        if FILE_BUDGET_CARDS:
            try:
                db.insert("approvals", {"project": project, "kind": "self",
                    "title": f"Budget cap reached for {project} (${s['spent']}/{s['cap']})",
                    "why": "Month-to-date spend hit the cap; continuing via subscription/failover routes.",
                    "value": "Keeps visibility without blocking queued improvements.",
                    "risk": "Paid API coders remain separately capped by their provider route.",
                    "command": ""})
            except Exception:
                pass
        return not _block_on_cap()
    return True
