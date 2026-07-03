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

BLOCK_ON_CAP = os.environ.get("ORCH_BUDGET_BLOCKS_TASKS", "false").lower() in ("true", "1", "yes")
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
    """True if a new task may run; False only when the owner explicitly enabled hard caps."""
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
        return not BLOCK_ON_CAP
    return True
