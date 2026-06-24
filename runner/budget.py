#!/usr/bin/env python3
"""
budget.py - per-project spend guardrails. Before running a task the runner checks
month-to-date spend (outcomes) against the project's cap (budgets table). If over and
hard_pause is set, the task is held (state BLOCKED, note 'budget cap') and an approval
card is filed so you can raise the cap or wait for the reset. No spend surprises.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db


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
    """True if a new task may run; False if hard budget cap reached."""
    s = status(project)
    if s["over"] and s["hard_pause"]:
        try:
            db.insert("approvals", {"project": project, "kind": "self",
                "title": f"Budget cap reached for {project} (${s['spent']}/{s['cap']})",
                "why": "Month-to-date spend hit the cap; swarm paused for this project.",
                "value": "Prevents runaway spend.",
                "risk": "Work is paused until you raise the cap or the month resets.",
                "command": ""})
        except Exception:
            pass
        return False
    return True
