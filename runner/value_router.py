#!/usr/bin/env python3
"""
value_router.py — MRR-impact-aware merge triage.

Estimates deployed MRR impact for each task using heuristics (task name,
affected files, task kind) and routes tasks into tiers:

  HIGH   (impact > $10k/mo) → expedited: all tests, auto-approve, same-day deploy
  MEDIUM (impact $1k-$10k)  → standard path
  LOW    (impact < $1k/mo)  → skip integration tests, manual approval, weekly batch

Env vars:
    ORCH_VALUE_ROUTER_ENABLED     – "true" (default) / "false"
    ORCH_VALUE_HIGH_THRESHOLD     – MRR threshold for HIGH tier (default 10000)
    ORCH_VALUE_LOW_THRESHOLD      – MRR threshold for LOW tier (default 1000)
"""
import os, sys, re, threading, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log as _log_mod

_log = _log_mod.get("value_router")

ENABLED = os.environ.get("ORCH_VALUE_ROUTER_ENABLED", "true").lower() == "true"
HIGH_THRESHOLD = float(os.environ.get("ORCH_VALUE_HIGH_THRESHOLD", "10000"))
LOW_THRESHOLD = float(os.environ.get("ORCH_VALUE_LOW_THRESHOLD", "1000"))

_lock = threading.Lock()
_stats = {
    "tasks_routed": 0,
    "high": 0,
    "medium": 0,
    "low": 0,
}


# ---------------------------------------------------------------------------
# Impact heuristics
# ---------------------------------------------------------------------------

# Keywords that signal high-impact, user-facing work
_HIGH_IMPACT_SIGNALS = {
    "payment", "billing", "subscription", "checkout", "onboarding",
    "auth", "login", "signup", "dashboard", "api", "pricing",
    "revenue", "conversion", "landing", "deploy", "production",
    "customer", "user-facing", "stripe", "webhook",
}

# Keywords that signal low-impact internal work
_LOW_IMPACT_SIGNALS = {
    "docs", "readme", "comment", "lint", "format", "typo", "rename",
    "cleanup", "refactor", "test", "spec", "chore", "bump", "log",
    "internal", "tooling", "ci", "config",
}

# File paths that indicate user-facing changes
_HIGH_IMPACT_PATHS = {
    "web/", "app/", "pages/", "api/", "components/", "src/",
    "packages/web", "growth-os/",
}

_LOW_IMPACT_PATHS = {
    "docs/", "tests/", "test_", ".github/", "scripts/",
    "memory/", "reports/",
}


def estimate_mrr_impact(task):
    """Estimate MRR impact of a task using heuristics.

    Returns dict: {"impact_usd": float, "signals": list[str], "tier": str}
    """
    slug = (task.get("slug") or "").lower()
    prompt = (task.get("prompt") or "").lower()
    kind = (task.get("kind") or "").lower()
    text = f"{slug} {prompt} {kind}"

    score = 5000.0  # default: medium
    signals = []

    # Check high-impact signals
    for kw in _HIGH_IMPACT_SIGNALS:
        if kw in text:
            score += 3000
            signals.append(f"+high:{kw}")

    # Check low-impact signals
    for kw in _LOW_IMPACT_SIGNALS:
        if kw in text:
            score -= 2000
            signals.append(f"-low:{kw}")

    # Check file paths in prompt
    for p in _HIGH_IMPACT_PATHS:
        if p in text:
            score += 2000
            signals.append(f"+path:{p}")
            break

    for p in _LOW_IMPACT_PATHS:
        if p in text:
            score -= 1500
            signals.append(f"-path:{p}")
            break

    # Kind-based adjustment
    if kind in ("bugfix", "feature"):
        score += 2000
        signals.append(f"+kind:{kind}")
    elif kind in ("docs", "test", "chore", "cleanup"):
        score -= 3000
        signals.append(f"-kind:{kind}")

    score = max(0, score)

    # Determine tier
    if score >= HIGH_THRESHOLD:
        tier = "HIGH"
    elif score <= LOW_THRESHOLD:
        tier = "LOW"
    else:
        tier = "MEDIUM"

    return {"impact_usd": round(score, 2), "signals": signals, "tier": tier}


def route_task(task):
    """Route a task based on its estimated MRR impact.

    Returns dict with routing decision:
        {"tier": str, "impact_usd": float, "skip_integration_tests": bool,
         "auto_approve": bool, "deploy_policy": str, "signals": list}
    """
    if not ENABLED:
        return {"tier": "MEDIUM", "impact_usd": 0, "skip_integration_tests": False,
                "auto_approve": False, "deploy_policy": "standard", "signals": []}

    estimate = estimate_mrr_impact(task)
    tier = estimate["tier"]

    with _lock:
        _stats["tasks_routed"] += 1
        _stats[tier.lower()] += 1

    if tier == "HIGH":
        return {
            "tier": "HIGH",
            "impact_usd": estimate["impact_usd"],
            "skip_integration_tests": False,
            "auto_approve": True,
            "deploy_policy": "same-day",
            "signals": estimate["signals"],
        }
    elif tier == "LOW":
        return {
            "tier": "LOW",
            "impact_usd": estimate["impact_usd"],
            "skip_integration_tests": True,
            "auto_approve": False,
            "deploy_policy": "weekly-batch",
            "signals": estimate["signals"],
        }
    else:
        return {
            "tier": "MEDIUM",
            "impact_usd": estimate["impact_usd"],
            "skip_integration_tests": False,
            "auto_approve": False,
            "deploy_policy": "standard",
            "signals": estimate["signals"],
        }


def route_tasks(tasks):
    """Route a list of tasks. Returns list of (task, routing) tuples."""
    return [(t, route_task(t)) for t in tasks]


def stats():
    """Return copy of router stats."""
    with _lock:
        return dict(_stats)
