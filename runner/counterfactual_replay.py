#!/usr/bin/env python3
"""
counterfactual_replay.py — periodically re-run past routing/planning decisions
with newer models or data to detect where the system would now choose differently.

This lets the orchestrator self-correct: if a routing decision made last week would
produce a different (better) outcome with today's model roster or quality data, the
module flags it and optionally updates the routing policy.

Usage:
    python3 counterfactual_replay.py              # dry-run report
    python3 counterfactual_replay.py --apply       # apply policy updates
    python3 counterfactual_replay.py --limit 50    # cap tasks to replay

Env vars:
    ORCH_REPLAY_ENABLED        "true" to enable (default "true")
    ORCH_REPLAY_LOOKBACK_DAYS  how far back to scan (default 7)
    ORCH_REPLAY_SAMPLE_SIZE    max tasks to replay per run (default 100)
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log as _log_mod

_log = _log_mod.get("counterfactual_replay")

ENABLED = os.environ.get("ORCH_REPLAY_ENABLED", "true").lower() in ("1", "true", "yes")
LOOKBACK_DAYS = int(os.environ.get("ORCH_REPLAY_LOOKBACK_DAYS", "7"))
SAMPLE_SIZE = int(os.environ.get("ORCH_REPLAY_SAMPLE_SIZE", "100"))


def _fetch_recent_decisions(lookback_days=None, limit=None):
    """Fetch completed tasks with routing metadata from the last N days."""
    import db
    lookback = lookback_days or LOOKBACK_DAYS
    limit = limit or SAMPLE_SIZE
    cutoff = time.strftime(
        "%Y-%m-%dT%H:%M:%SZ",
        time.gmtime(time.time() - lookback * 86400),
    )
    tasks = db.select("tasks", {
        "select": "id,slug,kind,project_id,state,note,force_coder,attempt,updated_at",
        "state": "in.(DONE,MERGED)",
        "updated_at": f"gte.{cutoff}",
        "order": "updated_at.desc",
        "limit": str(limit),
    }) or []
    return tasks


def _current_model_roster():
    """Load the current model quality scores for comparison."""
    import db
    try:
        rows = db.select("model_scores", {
            "select": "model,task_kind,quality,cost_usd",
            "order": "quality.desc",
            "limit": "200",
        }) or []
        roster = {}
        for r in rows:
            key = (r.get("model", ""), r.get("task_kind", ""))
            roster[key] = {
                "quality": float(r.get("quality") or 0),
                "cost": float(r.get("cost_usd") or 0),
            }
        return roster
    except Exception:
        return {}


def replay_decision(task, roster):
    """Re-evaluate a single task's routing decision against current model scores.

    Returns a dict:
        changed (bool)   — would the decision differ today?
        original_coder   — model used originally
        recommended       — model that would be chosen now
        quality_delta     — quality improvement if switched
        task_slug         — for logging
    """
    original = task.get("force_coder") or "unknown"
    kind = task.get("kind", "build")
    slug = task.get("slug", "")

    # Find the best current model for this task kind
    best_model, best_quality = original, 0.0
    for (model, task_kind), scores in roster.items():
        if task_kind == kind and scores["quality"] > best_quality:
            best_quality = scores["quality"]
            best_model = model

    # What quality did the original model have?
    original_quality = roster.get((original, kind), {}).get("quality", 0.0)
    quality_delta = best_quality - original_quality

    return {
        "changed": best_model != original and quality_delta > 0.5,
        "original_coder": original,
        "recommended": best_model,
        "quality_delta": round(quality_delta, 2),
        "original_quality": round(original_quality, 2),
        "best_quality": round(best_quality, 2),
        "task_slug": slug,
        "task_kind": kind,
    }


def run_replay(lookback_days=None, limit=None, apply=False):
    """Main entry: replay recent decisions and report divergences.

    Args:
        lookback_days: how far back to scan
        limit: max tasks to evaluate
        apply: if True, persist updated routing preferences

    Returns dict with replay summary.
    """
    if not ENABLED:
        _log.info("counterfactual replay disabled")
        return {"enabled": False}

    tasks = _fetch_recent_decisions(lookback_days, limit)
    roster = _current_model_roster()
    if not roster:
        _log.warning("no model roster available — skipping replay")
        return {"error": "no_roster", "tasks_scanned": len(tasks)}

    results = []
    changed_count = 0
    for t in tasks:
        r = replay_decision(t, roster)
        results.append(r)
        if r["changed"]:
            changed_count += 1

    if apply and changed_count > 0:
        _apply_policy_updates(results)

    summary = {
        "tasks_scanned": len(tasks),
        "decisions_diverged": changed_count,
        "divergence_rate": round(changed_count / max(len(tasks), 1), 3),
        "applied": apply and changed_count > 0,
        "top_changes": sorted(
            [r for r in results if r["changed"]],
            key=lambda x: x["quality_delta"],
            reverse=True,
        )[:10],
    }
    _log.info("replay complete: %d/%d diverged (%.1f%%)",
              changed_count, len(tasks),
              summary["divergence_rate"] * 100)
    return summary


def _apply_policy_updates(results):
    """Persist routing policy updates for diverged decisions."""
    import db
    updates = [r for r in results if r["changed"]]
    for u in updates:
        try:
            db.upsert({
                "key": f"route_override:{u['task_kind']}",
                "value": {
                    "preferred_model": u["recommended"],
                    "quality": u["best_quality"],
                    "updated_by": "counterfactual_replay",
                    "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                },
            })
        except Exception as exc:
            _log.warning("failed to apply route update for %s: %s", u["task_kind"], exc)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Counterfactual replay for routing decisions")
    parser.add_argument("--apply", action="store_true", help="Apply policy updates")
    parser.add_argument("--limit", type=int, default=None, help="Max tasks to replay")
    parser.add_argument("--lookback", type=int, default=None, help="Days to look back")
    args = parser.parse_args()

    import json
    result = run_replay(lookback_days=args.lookback, limit=args.limit, apply=args.apply)
    print(json.dumps(result, indent=2, default=str))
