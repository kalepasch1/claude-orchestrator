#!/usr/bin/env python3
"""Queue thermal map: expected merged value per minute.

This module gives claim_task and ev_scheduler one deterministic score that favors
high-value work that is likely to merge quickly, while discounting retry churn.
"""
import math


REVENUE_WORDS = ("revenue", "pricing", "growth", "conversion", "activation", "retention")
SMALL_WORDS = ("copy", "docs", "lint", "test", "small", "targeted", "one file", "fix")
LARGE_WORDS = ("redesign", "migration", "architecture", "monorepo", "rewrite", "refactor all")


def estimate_minutes(task, ctx=None):
    prompt = (task.get("prompt") or "").lower()
    kind = (task.get("kind") or "build").lower()
    base = {"docs": 8, "chore": 10, "mechanical": 10, "test": 14,
            "bugfix": 18, "build": 30, "security": 45, "legal": 45}.get(kind, 30)
    if any(w in prompt for w in SMALL_WORDS):
        base *= 0.65
    if any(w in prompt for w in LARGE_WORDS):
        base *= 1.8
    deps = task.get("deps") or []
    base += len(deps) * 8
    base *= 1 + min(3, int(task.get("remediation_count") or 0)) * 0.35
    return max(3.0, float(base))


def expected_value(task, ctx):
    project = task.get("project") or ""
    revenue = float((ctx.get("revenue_by_project") or {}).get(project, 0) or 0)
    stats = (ctx.get("outcome_stats") or {}).get(project, {}) or {}
    success = float(stats.get("success_rate", 0.7))
    avg_usd = float(stats.get("avg_usd", 0) or 0)
    kind = (task.get("kind") or "").lower()
    prompt = (task.get("prompt") or "").lower()
    slug = str(task.get("slug") or "")

    value = math.log10(1 + max(0.0, revenue)) * success / (avg_usd + 0.5)
    delta = (ctx.get("surface_returns") or {}).get(kind)
    if delta and float(delta) > 0:
        value *= 1 + min(float(delta), 100.0) / 100.0
    if kind == "build" and any(w in prompt for w in REVENUE_WORDS):
        value *= 1.5
    if slug in (ctx.get("approved_slugs") or set()):
        value *= 2.0
    if slug.startswith("recover-missing-branch-"):
        value = max(value, 30.0) * 4.0
    if "integration_sweeper: rebuild missing branch" in str(task.get("note") or ""):
        value = max(value, 30.0) * 4.0
    if project in ("beethoven", "orchestrator", "ORCHESTRATOR"):
        value = max(value, 20.0) * 3.0
    if int(task.get("transient_retries") or 0) >= 2:
        value *= 0.3
    return value


def score(task, ctx):
    return expected_value(task, ctx) / estimate_minutes(task, ctx)


def rank(tasks, ctx):
    return sorted(tasks, key=lambda t: (-score(t, ctx), t.get("created_at") or "", str(t.get("id"))))
