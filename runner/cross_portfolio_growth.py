#!/usr/bin/env python3
"""
cross_portfolio_growth.py — Detect compounding growth tactics across portfolios.

When multiple portfolios (projects) queue tasks targeting the same growth
metric or tactic, they compound effort wastefully.  This module scans
QUEUED tasks across all projects for overlapping growth-related work and
flags clusters so the operator can consolidate them into a single,
reusable capability.

Usage:
    from cross_portfolio_growth import detect
    clusters = detect()   # [{tactic, slugs, projects, recommendation}, ...]
"""
import os, sys, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

GROWTH_KEYWORDS = {
    "retention": {"retain", "churn", "engagement", "reactivat"},
    "acquisition": {"signup", "onboard", "registr", "invite", "referral"},
    "conversion": {"convert", "funnel", "checkout", "upsell", "paywall"},
    "activation": {"activat", "first-use", "aha-moment", "tutorial"},
    "revenue": {"revenue", "monetiz", "pricing", "subscription", "billing"},
}

MIN_CLUSTER_SIZE = int(os.environ.get("GROWTH_CLUSTER_MIN", "2"))


def _classify(prompt):
    """Return set of growth tactic names that match the prompt."""
    lower = (prompt or "").lower()
    return {tactic for tactic, kws in GROWTH_KEYWORDS.items()
            if any(kw in lower for kw in kws)}


def detect():
    """Scan QUEUED tasks for compounding growth tactics across projects."""
    tasks = db.select("tasks", {
        "select": "id,slug,prompt,project_id",
        "state": "eq.QUEUED",
        "limit": "2000",
    }) or []

    # bucket by tactic
    buckets = {}
    for t in tasks:
        tactics = _classify(t.get("prompt", ""))
        for tac in tactics:
            buckets.setdefault(tac, []).append(t)

    clusters = []
    for tactic, members in buckets.items():
        projects = {t["project_id"] for t in members}
        if len(projects) < MIN_CLUSTER_SIZE:
            continue
        clusters.append({
            "tactic": tactic,
            "slugs": [t["slug"] for t in members[:20]],
            "projects": list(projects),
            "count": len(members),
            "recommendation": (
                f"Consolidate {len(members)} '{tactic}' tasks across "
                f"{len(projects)} projects into a shared capability."
            ),
        })

    return clusters


def flag_clusters():
    """Detect and persist cross-portfolio growth clusters as advisories."""
    clusters = detect()
    flagged = 0
    for c in clusters:
        try:
            db.insert("approvals", {
                "project": "PORTFOLIO",
                "kind": "self",
                "status": "approved",
                "decided_by": "auto-policy:cross-portfolio-growth",
                "decision_type": "approve",
                "decision_text": "Auto-approved advisory; no merge action taken.",
                "title": f"Cross-portfolio compounding: {c['tactic']} ({c['count']} tasks)",
                "why": c["recommendation"],
                "value": f"Avoid {c['count']} agents solving similar {c['tactic']} work independently.",
                "risk": "Low — advisory only.",
                "command": "",
            })
            flagged += 1
        except Exception:
            pass
    return {"clusters": len(clusters), "flagged": flagged}


if __name__ == "__main__":
    import json
    print(json.dumps(detect(), indent=2)[:3000])
