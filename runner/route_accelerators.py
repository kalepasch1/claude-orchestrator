#!/usr/bin/env python3
"""route_accelerators.py — speed: triage + routing accelerators (§3, operator 2026-08-02).

Two throughput problems, both measured, both fixed here as pure logic:

1. **Weak routes burn lanes and days.** Legal-class work (need >= 8) was routed to small local
   models and cheap haiku lanes, producing "0/12 merged" cycles. Every one of those attempts
   consumed a lane, RAM, a QA pass, and a merge-train slot — the fleet was busy at full
   capacity producing nothing mergeable. Cost-per-token was optimal and cost-per-MERGE was
   infinite. `enforce_route()` makes that unrepresentable: legal-class never gets a weak coder,
   and any task that has already failed twice is escalated to the strongest route regardless of
   its cost score. The cheap stages (triage, QA) are untouched — only the CODER stage is gated.

2. **Nobody could see where time went.** `stage_cycle_stats()` turns raw task timestamps into
   p50/p90 per stage, per project, per route, and computes the headline metric the operator
   asked for: FIRST-PASS MERGE RATE per route — the share of tasks a route merged without a
   repair attempt. A route with a good p50 and a bad first-pass rate is a route that is fast at
   producing rework.

Pure and dependency-free: no DB, no network, no clock reads outside the callers' inputs, so
every threshold is testable. Fail-soft per CLAUDE.md. Thresholds shared with the rest of the
immune system live in `fleet_immune_contracts`.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fleet_immune_contracts as fic

# need >= this is "legal class": material work where a weak coder is never acceptable.
LEGAL_CLASS_NEED = int(os.environ.get("ORCH_LEGAL_CLASS_NEED", "8"))
# Attempts after which the strongest route is forced regardless of cost score.
ESCALATE_AFTER_ATTEMPTS = int(os.environ.get("ORCH_ESCALATE_AFTER_ATTEMPTS", "2"))

STRONGEST_ROUTE = ("claude", os.environ.get("ORCH_STRONGEST_CODER_MODEL", "claude-opus-4-8"))
STRONG_ROUTE = ("claude", os.environ.get("ORCH_STRONG_CODER_MODEL", "claude-sonnet-4-6"))

# Providers that run small local weights. Cheap and useful for triage and QA panels; never
# adequate as the CODER on material work.
WEAK_PROVIDERS = {"local", "ollama"}
# Model substrings that mark a small/cheap model regardless of provider.
WEAK_MODEL_MARKERS = ("haiku", "3b", "7b", "8b", "mini", "flash", "nano", "small",
                      "llama3.2", "deepseek-coder-v2:16b")

CODER_STAGE = "coder"
STAGES = ("queued_to_claimed", "claimed_to_coder_done", "coder_done_to_qa",
          "qa_to_merged", "merged_to_released")


def is_weak_route(provider, model):
    """True when (provider, model) is too small to be the coder on material work."""
    try:
        prov = str(provider or "").split(":")[0].strip().lower()
        mdl = str(model or "").lower()
        if prov in WEAK_PROVIDERS:
            return True
        return any(marker in mdl for marker in WEAK_MODEL_MARKERS)
    except Exception:
        return False


def enforce_route(provider, model, task_class="build", need=None, attempt=0,
                  stage=CODER_STAGE, reason=""):
    """Apply the §3 routing floors. Returns (provider, model, reason).

    Rules, in order:
      * only the CODER stage is gated — triage and QA may stay cheap;
      * >= ESCALATE_AFTER_ATTEMPTS prior failures -> strongest route, cost score ignored;
      * legal-class (need >= LEGAL_CLASS_NEED) never gets a weak coder.

    Never raises: on any error the caller's original choice is returned unchanged, because a
    routing guard that can throw is a guard that can wedge every claim.
    """
    try:
        need = LEGAL_CLASS_NEED if need is None else int(need)
        attempt = int(attempt or 0)

        if stage != CODER_STAGE:
            return provider, model, reason

        if attempt >= ESCALATE_AFTER_ATTEMPTS:
            prov, mdl = STRONGEST_ROUTE
            return prov, mdl, (
                f"route-escalation: {attempt} prior failed attempts -> forcing strongest coder "
                f"({prov}:{mdl}) regardless of cost score; {reason}".strip("; "))

        if need >= LEGAL_CLASS_NEED and is_weak_route(provider, model):
            prov, mdl = STRONG_ROUTE
            return prov, mdl, (
                f"legal-class floor: need={need} >= {LEGAL_CLASS_NEED}; {provider}:{model} is a "
                f"weak coder route (observed 0/12 merged) -> {prov}:{mdl}; {reason}".strip("; "))

        return provider, model, reason
    except Exception:
        return provider, model, reason


def route_violations(records):
    """Audit records of coder runs; return a Verdict per legal-class run on a weak route.

    `records` are dicts: {task_class, need, provider, model, stage, slug}. This is the query
    proof §PROOFS asks for — "no legal-class coder runs on local small models" becomes an
    assertion rather than an eyeball check. Never raises.
    """
    out = []
    for record in records or ():
        try:
            if not isinstance(record, dict):
                continue
            if record.get("stage", CODER_STAGE) != CODER_STAGE:
                continue
            need = int(record.get("need") or 0)
            provider, model = record.get("provider"), record.get("model")
            if need >= LEGAL_CLASS_NEED and is_weak_route(provider, model):
                out.append(fic.Verdict(
                    fic.DEMOTE,
                    f"legal-class task (need={need}) ran its CODER stage on weak route "
                    f"{provider}:{model}",
                    "demote_route",
                    f"route:{provider}:{model}",
                    {"slug": record.get("slug", ""), "need": need}))
        except Exception:
            continue
    return out


# ── stage cycle metrics ───────────────────────────────────────────────────────────────────

def _percentile(values, pct):
    """Nearest-rank percentile. Returns None for an empty series. Never raises."""
    try:
        series = sorted(float(v) for v in values if v is not None)
        if not series:
            return None
        if len(series) == 1:
            return series[0]
        rank = max(1, min(len(series), int(round(pct / 100.0 * len(series) + 0.5))))
        return series[rank - 1]
    except Exception:
        return None


def _delta(record, start_key, end_key):
    try:
        start, end = record.get(start_key), record.get(end_key)
        if start is None or end is None:
            return None
        value = float(end) - float(start)
        return value if value >= 0 else None
    except Exception:
        return None


def stage_durations(record):
    """Per-stage seconds for one task record. Missing timestamps yield None, never a zero.

    Expected keys (epoch seconds): queued_at, claimed_at, coder_done_at, qa_at, merged_at,
    released_at.
    """
    try:
        return {
            "queued_to_claimed": _delta(record, "queued_at", "claimed_at"),
            "claimed_to_coder_done": _delta(record, "claimed_at", "coder_done_at"),
            "coder_done_to_qa": _delta(record, "coder_done_at", "qa_at"),
            "qa_to_merged": _delta(record, "qa_at", "merged_at"),
            "merged_to_released": _delta(record, "merged_at", "released_at"),
        }
    except Exception:
        return {stage: None for stage in STAGES}


def _summarize(records):
    stats = {"n": 0, "stages": {}, "first_pass_merge_rate": None}
    merged = attempts_free = 0
    buckets = {stage: [] for stage in STAGES}
    for record in records:
        stats["n"] += 1
        for stage, value in stage_durations(record).items():
            if value is not None:
                buckets[stage].append(value)
        try:
            if record.get("merged_at") is not None:
                merged += 1
                if int(record.get("attempt") or 0) == 0:
                    attempts_free += 1
        except Exception:
            continue
    for stage, values in buckets.items():
        stats["stages"][stage] = {
            "n": len(values),
            "p50": _percentile(values, 50),
            "p90": _percentile(values, 90),
        }
    # First-pass merge rate is per TASK SEEN, not per merged task: a route that merges 2 of 12
    # on the first try has a 17% first-pass rate, not 100%.
    if stats["n"]:
        stats["first_pass_merge_rate"] = attempts_free / stats["n"]
        stats["merge_rate"] = merged / stats["n"]
    return stats


def stage_cycle_stats(records, group_by=("project", "route")):
    """p50/p90 per stage plus first-pass merge rate, overall and per group.

    Returns {"overall": {...}, "by": {group_key: {group_value: {...}}}}. Never raises.
    """
    result = {"overall": {}, "by": {}}
    try:
        records = [r for r in (records or ()) if isinstance(r, dict)]
        result["overall"] = _summarize(records)
        for key in group_by or ():
            grouped = {}
            for record in records:
                grouped.setdefault(str(record.get(key) or "unknown"), []).append(record)
            result["by"][key] = {value: _summarize(rows) for value, rows in sorted(grouped.items())}
    except Exception:
        pass
    return result


def slowest_stage(stats):
    """Name the stage with the worst p90 in a summary. "" when unknown. Never raises."""
    try:
        stages = (stats or {}).get("stages", {})
        candidates = [(s, d.get("p90")) for s, d in stages.items() if d.get("p90") is not None]
        return max(candidates, key=lambda pair: pair[1])[0] if candidates else ""
    except Exception:
        return ""


def route_leaderboard(stats, min_samples=None):
    """Routes sorted worst-first by first-pass merge rate, with a demote Verdict attached.

    This is the "first-pass merge rate is the headline metric" view. Never raises.
    """
    min_samples = fic.ROUTE_MIN_SAMPLES if min_samples is None else min_samples
    rows = []
    try:
        for route, summary in ((stats or {}).get("by", {}).get("route", {}) or {}).items():
            n = summary.get("n", 0)
            rate = summary.get("first_pass_merge_rate")
            if rate is None:
                continue
            verdict = fic.classify_route(
                fic.RouteQuality(route=route, task_class="all", samples=n,
                                 merged=int(round(rate * n))),
                min_samples=min_samples)
            rows.append({"route": route, "n": n, "first_pass_merge_rate": rate,
                         "p90_coder": (summary.get("stages", {})
                                       .get("claimed_to_coder_done", {}).get("p90")),
                         "verdict": verdict.state, "action": verdict.action})
        rows.sort(key=lambda r: (r["first_pass_merge_rate"], -r["n"]))
    except Exception:
        return []
    return rows


def render(stats):
    """Operator-readable SLO summary. Never raises."""
    try:
        overall = (stats or {}).get("overall", {})
        lines = ["STAGE CYCLE TIME (p50 / p90 seconds)", "=" * 38,
                 f"  tasks: {overall.get('n', 0)}"]
        for stage in STAGES:
            data = overall.get("stages", {}).get(stage, {})
            p50, p90 = data.get("p50"), data.get("p90")
            if p50 is None:
                continue
            lines.append(f"  {stage:<24} {p50:>9.0f} / {p90:>9.0f}   (n={data.get('n', 0)})")
        rate = overall.get("first_pass_merge_rate")
        if rate is not None:
            lines.append(f"  {'first-pass merge rate':<24} {rate:>9.0%}")
        board = route_leaderboard(stats)
        if board:
            lines.append("")
            lines.append("ROUTE FIRST-PASS MERGE RATE (worst first)")
            for row in board:
                flag = "  <-- demote" if row["action"] == "demote_route" else ""
                lines.append(f"  {row['route']:<38} {row['first_pass_merge_rate']:>6.0%} "
                             f"(n={row['n']}){flag}")
        return "\n".join(lines)
    except Exception:
        return "stage cycle stats unavailable"
