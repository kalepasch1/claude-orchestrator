#!/usr/bin/env python3
"""
health.py - portfolio health score + the unified action inbox, read from the DB views.
50 projects collapse into one ranked glance. Used by digest.py and the dashboard.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db


def scores():
    """Return all projects sorted by ascending health score (worst first)."""
    return db.select("v_project_health", {"select": "*", "order": "health_score.asc"}) or []


def inbox():
    """Return the unified action inbox — approvals, blockers, and alerts across all projects."""
    return db.select("v_action_inbox", {"select": "*"}) or []


def summary():
    rows = scores()
    worst = rows[:3]
    return {"projects": len(rows),
            "avg_health": round(sum(float(r["health_score"]) for r in rows) / len(rows), 1) if rows else 100,
            "needs_attention": [{"project": r["project"], "score": r["health_score"],
                                 "blocked": r["blocked"], "approvals": r["open_approvals"]} for r in worst],
            "inbox_count": len(inbox())}


if __name__ == "__main__":
    import json
    print(json.dumps(summary(), indent=2))
