#!/usr/bin/env python3
"""
opportunity_scorer.py - Score proposals against historical surface returns
and summarize opportunity pipeline status.

Fail-soft: returns sensible defaults on any error.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db


def score_proposal(proposal_text, project_id, surface_returns=None):
    """Score a proposal based on historical ROI data.

    Returns dict with 'score', 'reasoning', and 'components'.
    Components map surface names to individual contribution scores.
    """
    if surface_returns is None:
        surface_returns = {}

    components = {}
    total = 0.0

    # Fetch historical ROI data for this project
    try:
        history = db.select(
            "opportunity_history",
            {"select": "surface,roi", "eq": {"project_id": project_id}},
        ) or []
    except Exception:
        history = []

    hist_map = {}
    for row in history:
        s = row.get("surface", "")
        if s:
            hist_map[s] = float(row.get("roi", 0.0))

    for surface, value in surface_returns.items():
        hist_roi = hist_map.get(surface, 0.0)
        contribution = (float(value) * hist_roi) / 1_000_000 if hist_roi else 0.0
        components[surface] = round(contribution, 4)
        total += contribution

    reasoning = (
        f"Scored {len(surface_returns)} surfaces against "
        f"{len(hist_map)} historical records"
    )

    return {
        "score": round(total, 4),
        "reasoning": reasoning,
        "components": components,
    }


def summarize_opportunities(project_id):
    """Return status counts for a project's opportunity pipeline."""
    try:
        rows = db.select(
            "opportunities",
            {"select": "status", "eq": {"project_id": project_id}},
        ) or []
    except Exception:
        rows = []

    counts = {}
    for row in rows:
        status = row.get("status", "unknown")
        counts[status] = counts.get(status, 0) + 1

    return counts
