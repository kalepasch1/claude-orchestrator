#!/usr/bin/env python3
"""Queue thermal map: expected merged value per minute.

This module gives claim_task and ev_scheduler one deterministic score that favors
high-value work that is likely to merge quickly, while discounting retry churn.
"""
import math
import os


#: THE SINGLE DEFINITION OF BOTH FLOORS. ev_scheduler imports these rather than keeping
#: its own copies — it already imports this module, and two independent copies of the
#: same constant in two near-identical scoring functions is how the first fix came to be
#: applied to the twin that nothing calls.
#:
#: NO_REVENUE_BASE stands in for log10(1 + MRR) when NO project anywhere reports revenue.
#: 1.0 is log10(1 + $9) — deliberately modest, not a thumb on the scale. Set to 0 to
#: restore the old arithmetic exactly.
NO_REVENUE_BASE = float(os.environ.get("ORCH_EV_NO_REVENUE_BASE", "1.0") or 1.0)
#: Floor under a project's recent success rate, for the same reason ev_scheduler's
#: outcome_weight() floors its result at 0.1: a multiplier of exactly zero does not rank
#: a project low, it erases it.
SUCCESS_RATE_FLOOR = float(os.environ.get("ORCH_EV_SUCCESS_RATE_FLOOR", "0.05") or 0.05)

REVENUE_WORDS = ("revenue", "pricing", "growth", "conversion", "activation", "retention")
SMALL_WORDS = ("copy", "docs", "lint", "test", "small", "targeted", "one file", "fix")
LARGE_WORDS = ("redesign", "migration", "architecture", "monorepo", "rewrite", "refactor all")


def estimate_minutes(task, ctx=None):
    """Estimate how many wall-clock minutes ``task`` will take to merge.

    Args:
        task: Task row mapping. Reads ``prompt``, ``kind``, ``deps`` and
            ``remediation_count``. Missing keys fall back to safe defaults.
        ctx: Unused; accepted so callers can pass the same scoring context
            they pass to :func:`expected_value` and :func:`score`.

    Returns:
        float: Estimated minutes, floored at 3.0 so the value is always a
        usable divisor in :func:`score`.
    """
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
    """Score the expected merged value of ``task``, before time is factored in.

    Starts from the project's revenue (log-damped), scaled by that project's
    historical success rate and discounted by its average cost per task, then
    applies multipliers for revenue-bearing builds, operator-approved slugs,
    missing-branch recovery, orchestrator self-repair, and a penalty for tasks
    that have already burned transient retries.

    Args:
        task: Task row mapping. Reads ``project``, ``kind``, ``prompt``,
            ``slug``, ``note`` and ``transient_retries``.
        ctx: Scoring context. Reads ``revenue_by_project``, ``outcome_stats``,
            ``surface_returns`` and ``approved_slugs``. Missing keys are
            treated as empty.

    Returns:
        float: Unitless expected value; higher means more worth claiming.
    """
    project = task.get("project") or ""
    revenue_by_project = ctx.get("revenue_by_project") or {}
    revenue = float(revenue_by_project.get(project, 0) or 0)
    stats = (ctx.get("outcome_stats") or {}).get(project, {}) or {}
    success = max(float(stats.get("success_rate", 0.7)), SUCCESS_RATE_FLOOR)
    avg_usd = float(stats.get("avg_usd", 0) or 0)
    kind = (task.get("kind") or "").lower()
    prompt = (task.get("prompt") or "").lower()
    slug = str(task.get("slug") or "")

    # TWO MULTIPLY-BY-ZEROS, AND THIS IS THE FUNCTION THAT ACTUALLY DECIDES THE QUEUE.
    #
    # ev_scheduler.score() is a near-identical twin of this function and had the same
    # pair of bugs. Fixing that one on 2026-09-01 changed nothing that matters, because
    # _scored_queue() — which feeds BOTH park_zero_ev and claim_task's ordering — calls
    # thermal_score(), which calls this. Measured on the live queue afterwards:
    #
    #     ev_scheduler.score()   0 of 296 tasks below ZERO_EV
    #     thermal_map.score()  185 of 296 below, minimum exactly 0.0000
    #
    # and 18 tasks were still being stamped "near-zero expected value" per run,
    # including several the fixed twin scored at 0.42 and 1.4.
    #
    # base: app_revenue is an EMPTY TABLE on this fleet, so log10(1+0) = 0 and every
    # multiplier below — kind ROI, the revenue-word boost, the approved-slug doubling,
    # the recovery and self-repair boosts, the flaky discount — multiplied zero.
    # The fallback applies ONLY when no project anywhere reports revenue; the moment one
    # does, revenue weighting is exactly what it was.
    #
    # success: reads 0.000 for apparently-law and tomorrow in the recent outcomes window,
    # which is absorbing in the same way and self-fulfilling — a project that lands
    # nothing sorts last, so it is claimed last, so it lands nothing.
    base = math.log10(1 + max(0.0, revenue))
    if base <= 0 and not any(float(v or 0) > 0 for v in revenue_by_project.values()):
        base = NO_REVENUE_BASE

    value = base * success / (avg_usd + 0.5)
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
    """Return the thermal-map score: expected merged value per minute.

    This is the single number ``claim_task`` and ``ev_scheduler`` sort on, so
    a cheap, quick, high-value task outranks an equally valuable one that will
    take an hour.

    Args:
        task: Task row mapping (see :func:`expected_value`).
        ctx: Scoring context (see :func:`expected_value`).

    Returns:
        float: Expected value divided by estimated minutes. The divisor is
        floored at 3.0 by :func:`estimate_minutes`, so this never divides by
        zero.
    """
    return expected_value(task, ctx) / estimate_minutes(task, ctx)


def rank(tasks, ctx):
    """Order ``tasks`` best-first by :func:`score`.

    Ties break on ``created_at`` then ``id`` so the ordering is deterministic
    across runs and across the parallel claimers that share this ranking.

    Args:
        tasks: Iterable of task row mappings.
        ctx: Scoring context (see :func:`expected_value`).

    Returns:
        list: New list of the same tasks, highest score first.
    """
    return sorted(tasks, key=lambda t: (-score(t, ctx), t.get("created_at") or "", str(t.get("id"))))
