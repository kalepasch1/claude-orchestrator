#!/usr/bin/env python3
"""Coordination rules for task execution."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db


def check_active_loop_work():
    """Check for active loop-generated work."""
    try:
        rows = db.select("active_work", {})
        if rows:
            return {
                "active_work": [r.get("branch") for r in rows],
                "conflicts": []
            }
    except Exception:
        pass
    return {"active_work": [], "conflicts": []}


def check_queued_improvements():
    """Check queued improvements not yet shipped."""
    try:
        rows = db.select("queued_improvements", {})
        if rows:
            return {
                "queued_improvements": [r.get("branch") for r in rows],
                "preserved": True
            }
    except Exception:
        pass
    return {"queued_improvements": [], "preserved": True}


def check_recovered_work():
    """Check recovered work status."""
    try:
        rows = db.select("recovered_work", {})
        if rows:
            return {
                "recovered_work": [r.get("task_id") for r in rows],
                "status": "queued",
                "shipped": False
            }
    except Exception:
        pass
    return {"recovered_work": [], "status": "queued", "shipped": False}


def reuse_prior_solutions_first():
    """Return True if prior solutions should be reused."""
    return True


def preserve_queued_improvements():
    """Return True if queued improvements must be preserved."""
    return True
