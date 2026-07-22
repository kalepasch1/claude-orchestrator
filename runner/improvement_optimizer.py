#!/usr/bin/env python3
from __future__ import annotations
"""Novelty and downstream-capacity controls for self-improvement drafting."""
import os
import re

REVIEW_CAP = int(os.environ.get("IMPROVE_REVIEW_BACKLOG_CAP", "25"))
BUILD_CAP = int(os.environ.get("IMPROVE_BUILD_BACKLOG_CAP", "12"))
NOVELTY_THRESHOLD = float(os.environ.get("IMPROVE_NOVELTY_THRESHOLD", "0.58"))


def _tokens(value):
    stop = {"the", "and", "for", "with", "that", "from", "into", "using", "improve", "improvement"}
    aliases = {"dollar": "cost", "dollars": "cost", "deployment": "deploy",
               "deployed": "deploy", "deployments": "deploy", "routing": "route",
               "routes": "route", "rank": "select", "optimize": "select"}
    out = set()
    for token in re.findall(r"[a-z0-9]+", str(value or "").lower()):
        token = aliases.get(token, token)
        if token.endswith("ies") and len(token) > 5:
            token = token[:-3] + "y"
        elif token.endswith("s") and not token.endswith("ss") and len(token) > 4:
            token = token[:-1]
        token = aliases.get(token, token)
        if len(token) >= 3 and token not in stop:
            out.add(token)
    return out


def similarity(left, right):
    a, b = _tokens(left), _tokens(right)
    return len(a & b) / len(a | b) if a and b else 0.0


def idea_text(idea):
    return " ".join(str(idea.get(k) or "") for k in ("title", "current_state", "proposal", "rationale"))


def novel(idea, existing, threshold=NOVELTY_THRESHOLD):
    text = idea_text(idea)
    best = (None, 0.0)
    for item in existing or []:
        score = similarity(text, idea_text(item))
        if score > best[1]:
            best = (item.get("id") or item.get("title"), score)
    return {"novel": best[1] < threshold, "nearest": best[0], "similarity": round(best[1], 4)}


def capacity(database):
    try:
        review = database.select("improvement_proposals", {"select": "id", "status": "eq.for_review", "limit": str(REVIEW_CAP + 1)}) or []
    except Exception:
        review = []
    try:
        builds = database.select("tasks", {"select": "id,slug,state", "slug": "like.improve-%", "state": "in.(QUEUED,RUNNING,RETRY,DECOMPOSED)", "limit": str(BUILD_CAP + 1)}) or []
    except Exception:
        builds = []
    review_slots = max(0, REVIEW_CAP - len(review))
    build_slots = max(0, BUILD_CAP - len(builds))
    # The miner creates review proposals only; it does not directly enqueue a
    # build.  A full build lane must therefore not silence new, bounded
    # improvement intake.  The committee remains the gate that promotes a
    # reviewed proposal into build work.
    slots = review_slots
    return {"slots": slots, "review_backlog": len(review), "build_backlog": len(builds),
            "review_cap": REVIEW_CAP, "build_cap": BUILD_CAP,
            "review_slots": review_slots, "build_slots": build_slots,
            "build_limited": build_slots <= 0,
            "limited": slots <= 0}
