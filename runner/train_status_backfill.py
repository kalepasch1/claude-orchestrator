"""
train_status_backfill.py — attribute train and deploy outcomes back to the originating
coder outcome so router_stats can optimize by stage-specific deployed value per minute.

Called after the train runs. For each task that passed/failed the train, update its
outcome row with the train result so router_stats sees the full pipeline signal.
"""
import os, sys, logging, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

log = logging.getLogger(__name__)

# Valid train statuses that indicate the task completed the train stage
_TRAIN_PASS_STATES = frozenset({"MERGED", "DONE"})
_TRAIN_FAIL_MARKERS = frozenset({"TESTFAIL", "BUILDFAIL", "BLOCKED"})


def backfill_train_status(window_hours=24):
    """Stamp train_status on outcome rows for recently-trained tasks.

    Reads tasks that changed state in the last `window_hours`, finds their
    outcome rows, and sets outcome.deploy_status to reflect the train result.
    This lets router_stats attribute the full pipeline conversion rate back
    to the coder/model that produced the diff.

    Returns (updated_count, skipped_count).
    """
    import datetime
    cutoff = (datetime.datetime.utcnow() - datetime.timedelta(hours=window_hours)).isoformat()

    # Get recently-changed tasks with a terminal train state
    tasks = db.select("tasks", {
        "select": "id,slug,state,project_id,account,artifact_branch,note",
        "updated_at": f"gte.{cutoff}",
        "state": f"in.({','.join(_TRAIN_PASS_STATES | _TRAIN_FAIL_MARKERS)})",
        "order": "updated_at.desc",
        "limit": "500",
    }) or []

    if not tasks:
        return 0, 0

    updated = 0
    skipped = 0

    for t in tasks:
        task_id = t.get("id")
        state = t.get("state", "")
        if not task_id:
            skipped += 1
            continue

        # Determine train status
        if state in _TRAIN_PASS_STATES:
            train_status = "merged" if state == "MERGED" else "passed"
        elif state in _TRAIN_FAIL_MARKERS:
            train_status = f"train-{state.lower()}"
        else:
            skipped += 1
            continue

        # Find the outcome row for this task
        outcomes = db.select("outcomes", {
            "select": "id,deploy_status",
            "task_id": f"eq.{task_id}",
            "limit": "1",
        }) or []

        if not outcomes:
            skipped += 1
            continue

        outcome = outcomes[0]
        existing_status = str(outcome.get("deploy_status") or "").lower()

        # Don't overwrite a more authoritative status (actual deploy evidence)
        if existing_status in ("deployed", "success", "green", "ready"):
            skipped += 1
            continue

        try:
            db.update("outcomes", {"deploy_status": train_status}, id=outcome["id"])
            updated += 1
        except Exception as e:
            log.warning("train_status_backfill: failed to update outcome %s: %s", outcome["id"], e)
            skipped += 1

    return updated, skipped


def deployed_value_per_minute(outcomes_by_coder):
    """Compute stage-specific deployed value per wall-clock minute.

    Args:
        outcomes_by_coder: dict of coder -> list of outcome dicts

    Returns:
        dict of coder -> {stage: float} where float is deployed outcomes / total wall minutes
    """
    import collections
    result = {}
    for coder, outcomes in outcomes_by_coder.items():
        by_stage = collections.defaultdict(lambda: {"deployed": 0, "wall_min": 0.0, "n": 0})
        for o in outcomes:
            stage = _stage_of_outcome(o)
            s = by_stage[stage]
            s["n"] += 1
            s["wall_min"] += float(o.get("wall_ms") or 0) / 60_000.0
            if _is_deployed(o):
                s["deployed"] += 1
        coder_result = {}
        for stage, s in by_stage.items():
            if s["wall_min"] > 0 and s["n"] >= 5:
                coder_result[stage] = round(s["deployed"] / s["wall_min"], 4)
        result[coder] = coder_result
    return result


def _stage_of_outcome(o):
    kind = str(o.get("kind") or "build").lower()
    slug = str(o.get("slug") or "").lower()
    if slug.startswith("recover-"):
        return "recovery"
    if "buildfail" in slug or kind == "bugfix":
        return "build-fix"
    return kind or "build"


def _is_deployed(o):
    return bool(o.get("deployed") or str(o.get("deploy_status") or "").lower()
                in ("ready", "success", "deployed", "green", "merged", "passed"))


if __name__ == "__main__":
    updated, skipped = backfill_train_status()
    print(f"train_status_backfill: {updated} updated, {skipped} skipped")
