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

Env vars (all ORCH_COUNTERFACTUAL_* for fleet-wide consistency):
    ORCH_COUNTERFACTUAL_ENABLED         "true" to enable (default "true")
    ORCH_COUNTERFACTUAL_LOOKBACK_DAYS   how far back to scan (default 7)
    ORCH_COUNTERFACTUAL_BATCH_SIZE      max tasks per run (default 100)
    ORCH_COUNTERFACTUAL_INTERVAL_MIN    periodic replay interval in minutes (default 60)
    ORCH_COUNTERFACTUAL_QUALITY_THRESHOLD  min quality delta to flag change (default 0.5)
"""
import os
import sys
import time
import threading
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log as _log_mod

_log = _log_mod.get("counterfactual_replay")

ENABLED = os.environ.get("ORCH_COUNTERFACTUAL_ENABLED", "true").lower() in ("1", "true", "yes")
LOOKBACK_DAYS = int(os.environ.get("ORCH_COUNTERFACTUAL_LOOKBACK_DAYS", "7"))
BATCH_SIZE = int(os.environ.get("ORCH_COUNTERFACTUAL_BATCH_SIZE", "100"))
INTERVAL_MINUTES = int(os.environ.get("ORCH_COUNTERFACTUAL_INTERVAL_MIN", "60"))
QUALITY_THRESHOLD = float(os.environ.get("ORCH_COUNTERFACTUAL_QUALITY_THRESHOLD", "0.5"))

_periodic_runner = None
_runner_lock = threading.Lock()


class TaskResult:
    """Result of a task replay: original vs. counterfactual outcome."""
    def __init__(self, task_id, changed, original_coder, recommended, quality_delta):
        self.task_id = task_id
        self.changed = changed
        self.original_coder = original_coder
        self.recommended = recommended
        self.quality_delta = quality_delta


class Divergence:
    """A detected divergence between historical and counterfactual decision."""
    def __init__(self, task_id, task_kind, task_slug, quality_delta, original, recommended):
        self.task_id = task_id
        self.task_kind = task_kind
        self.task_slug = task_slug
        self.quality_delta = quality_delta
        self.original = original
        self.recommended = recommended


def _fetch_recent_decisions(lookback_days=None, limit=None):
    """Fetch completed tasks with routing metadata from the last N days."""
    import db
    try:
        lookback = lookback_days or LOOKBACK_DAYS
        limit = limit or BATCH_SIZE
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
    except Exception as exc:
        _log.warning("failed to fetch recent decisions: %s", exc)
        return []


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
            try:
                key = (r.get("model", ""), r.get("task_kind", ""))
                q_val = r.get("quality")
                c_val = r.get("cost_usd")
                roster[key] = {
                    "quality": float(q_val) if q_val not in (None, "") else 0.0,
                    "cost": float(c_val) if c_val not in (None, "") else 0.0,
                }
            except (ValueError, TypeError):
                continue
        return roster
    except Exception as exc:
        _log.warning("failed to load model roster: %s", exc)
        return {}


def replay_decision(task, roster):
    """Re-evaluate a single task's routing decision against current model scores.

    Returns a TaskResult with original vs. recommended model.
    """
    try:
        task_id = task.get("id", "")
        original = task.get("force_coder") or "unknown"
        kind = task.get("kind", "build")
        slug = task.get("slug", "")

        best_model, best_quality = original, 0.0
        for (model, task_kind), scores in roster.items():
            if task_kind == kind and scores["quality"] > best_quality:
                best_quality = scores["quality"]
                best_model = model

        original_quality = roster.get((original, kind), {}).get("quality", 0.0)
        quality_delta = best_quality - original_quality

        changed = best_model != original and quality_delta > QUALITY_THRESHOLD
        return TaskResult(task_id, changed, original, best_model, round(quality_delta, 2))
    except Exception as exc:
        _log.warning("failed to replay decision for task %s: %s", task.get("id"), exc)
        return TaskResult(task.get("id", ""), False, "", "", 0.0)


def detect_divergences(historical, counterfactual):
    """Compare historical decisions with counterfactual results.

    Args:
        historical: dict mapping task_id -> TaskResult from original run (optional)
        counterfactual: dict mapping task_id -> TaskResult from replay

    Returns:
        List of Divergence objects for tasks where decision changed.
    """
    divergences = []
    try:
        for task_id, cf_result in counterfactual.items():
            if historical and task_id not in historical:
                continue
            if cf_result.changed and cf_result.original_coder != cf_result.recommended:
                div = Divergence(
                    task_id,
                    "unknown",
                    "",
                    cf_result.quality_delta,
                    cf_result.original_coder,
                    cf_result.recommended,
                )
                divergences.append(div)
    except Exception as exc:
        _log.warning("failed to detect divergences: %s", exc)
    return divergences


def replay_task_batch(task_ids, model_version=None):
    """Re-execute a batch of tasks with a specific model version.

    Args:
        task_ids: list of task IDs to replay
        model_version: optional model version override

    Returns:
        dict mapping task_id -> TaskResult
    """
    import db
    results = {}
    try:
        tasks = db.select("tasks", {
            "select": "id,slug,kind,project_id,state,note,force_coder,attempt,updated_at",
            "id": f"in.({','.join(task_ids)})",
        }) or []
        roster = _current_model_roster()
        for task in tasks:
            result = replay_decision(task, roster)
            results[task.get("id", "")] = result
    except Exception as exc:
        _log.warning("failed to replay task batch: %s", exc)
    return results


def update_policies_from_divergences(divergences):
    """Persist policy updates to fleet_config for diverged decisions.

    Args:
        divergences: list of Divergence objects

    Returns:
        count of successfully updated policies
    """
    import db
    try:
        updated = 0
        for div in divergences:
            try:
                policy_key = f"ORCH_COUNTERFACTUAL_ROUTE_{div.task_kind.upper()}"
                db.upsert("fleet_config", {
                    "key": policy_key,
                    "value": json.dumps({
                        "preferred_model": div.recommended,
                        "quality_delta": div.quality_delta,
                        "updated_by": "counterfactual_replay",
                        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    }),
                })
                updated += 1
                _log.info("updated policy for %s: %s -> %s (delta: %.2f)",
                         div.task_kind, div.original, div.recommended, div.quality_delta)
            except Exception as exc:
                _log.warning("failed to update policy for task %s: %s", div.task_id, exc)
        return updated
    except Exception as exc:
        _log.warning("failed to update policies: %s", exc)
        return 0


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

    try:
        tasks = _fetch_recent_decisions(lookback_days, limit)
        if not tasks:
            _log.debug("no tasks to replay")
            return {"tasks_scanned": 0, "decisions_diverged": 0, "divergence_rate": 0}

        roster = _current_model_roster()
        if not roster:
            _log.warning("no model roster available — skipping replay")
            return {"error": "no_roster", "tasks_scanned": len(tasks)}

        results = {}
        changed_count = 0
        for t in tasks:
            r = replay_decision(t, roster)
            results[t.get("id", "")] = r
            if r.changed:
                changed_count += 1

        divergences = detect_divergences({}, results)

        if apply and divergences:
            applied = update_policies_from_divergences(divergences)
            _log.info("applied %d policy updates", applied)

        summary = {
            "tasks_scanned": len(tasks),
            "decisions_diverged": changed_count,
            "divergence_rate": round(changed_count / max(len(tasks), 1), 3),
            "policies_applied": apply and len(divergences) > 0,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        _log.info("replay complete: %d/%d diverged (%.1f%%)",
                  changed_count, len(tasks), summary["divergence_rate"] * 100)
        return summary
    except Exception as exc:
        _log.error("replay failed: %s", exc)
        return {"error": str(exc)}


def run_periodic_replay(interval_minutes=None):
    """Background runner: periodically execute counterfactual replay.

    Args:
        interval_minutes: repeat interval in minutes (default from env)

    Runs in a background thread; errors are logged but never raised.
    """
    interval = interval_minutes or INTERVAL_MINUTES
    sleep_seconds = max(interval * 60, 60)

    def _loop():
        while True:
            try:
                _log.debug("periodic replay starting")
                run_replay(apply=True)
            except Exception as exc:
                _log.error("periodic replay failed: %s", exc)
            try:
                time.sleep(sleep_seconds)
            except Exception:
                pass

    thread = threading.Thread(target=_loop, daemon=True, name="counterfactual-replay")
    thread.start()
    return thread


def start_periodic_replay():
    """Singleton: start the background replay runner if not already running."""
    global _periodic_runner
    with _runner_lock:
        if _periodic_runner is None or not _periodic_runner.is_alive():
            _periodic_runner = run_periodic_replay()
            _log.info("started periodic counterfactual replay (interval: %d min)", INTERVAL_MINUTES)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Counterfactual replay for routing decisions")
    parser.add_argument("--apply", action="store_true", help="Apply policy updates")
    parser.add_argument("--limit", type=int, default=None, help="Max tasks to replay")
    parser.add_argument("--lookback", type=int, default=None, help="Days to look back")
    args = parser.parse_args()

    result = run_replay(lookback_days=args.lookback, limit=args.limit, apply=args.apply)
    print(json.dumps(result, indent=2, default=str))
