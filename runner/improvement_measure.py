#!/usr/bin/env python3
"""
improvement_measure.py - closes the loop on the 20-500X miner: it doesn't just GENERATE ideas, it learns
which KINDS actually pay off, and biases future mining toward them.

  1. mark shipped: any improvement_proposal whose task merged -> status='shipped'.
  2. attribute: link shipped improvements to the app's revenue/usage movement (merge_revenue).
  3. surface returns: avg realized delta per SURFACE (feature/ux/api/backend/orchestration/swarm/...),
     written to surface_returns so improvement_miner can weight high-return surfaces higher next cycle.
  4. cycle_time: avg seconds from task creation to MERGED, grouped by kind.
  5. first_try_yield: fraction of MERGED tasks with zero remediations, overall and by model.
  6. auto_tune: emit at most MAX_TUNE_PER_RUN pipeline tuning decisions when metrics cross thresholds.
Schedule daily. Read-only except status + the returns table + local tuning state file.
"""
import datetime
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

TUNING_STATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pipeline_tuning.json")

CYCLE_TIME_WARN_S = 3600 * 4   # flag if avg idea→merge exceeds 4 hours
FIRST_TRY_YIELD_MIN = 0.60     # flag if fewer than 60 % tasks merge without remediation
TUNE_COOLDOWN_S = 3600 * 24    # at most one auto-tune decision window per 24 h
MAX_TUNE_PER_RUN = 1           # blast-radius guard: at most 1 decision applied per run


def mark_shipped():
    """Distinguish merged engineering output from verified production deployment."""
    tasks = {t["slug"]: t for t in (db.select("tasks", {
        "select": "slug,state,project_id,updated_at", "state": "eq.MERGED"}) or [])}
    projects = {p["id"]: p["name"] for p in (db.select("projects", {"select": "id,name"}) or [])}
    releases = db.select("releases", {"select": "project,deploy_status,deployed_at,created_at",
                                      "deploy_status": "eq.success", "order": "created_at.desc"}) or []
    latest = {}
    for release in releases:
        latest.setdefault(release.get("project"), release)
    n = 0
    for p in db.select("improvement_proposals", {"select": "id,task_slug,status",
                                                  "status": "in.(queued,merged)"}) or []:
        task = tasks.get(p.get("task_slug"))
        if not task:
            continue
        project = projects.get(task.get("project_id"))
        release = latest.get(project) or {}
        deployed_at = str(release.get("deployed_at") or release.get("created_at") or "")
        if release and deployed_at >= str(task.get("updated_at") or ""):
            db.update("improvement_proposals", {"id": p["id"]}, {"status": "shipped"})
            n += 1
        elif p.get("status") != "merged":
            db.update("improvement_proposals", {"id": p["id"]}, {"status": "merged"})
    return n


def surface_returns():
    """avg realized revenue delta per surface (from merge_revenue joined by slug)."""
    shipped = db.select("improvement_proposals", {"select": "surface,task_slug", "status": "eq.shipped"}) or []
    rev = {r["slug"]: float(r.get("revenue_delta") or 0)
           for r in (db.select("merge_revenue", {"select": "slug,revenue_delta"}) or [])}
    agg = {}
    for p in shipped:
        d = rev.get(p.get("task_slug"))
        if d is None:
            continue
        a = agg.setdefault(p["surface"], [0.0, 0]); a[0] += d; a[1] += 1
    out = {}
    for surface, (tot, cnt) in agg.items():
        if cnt:
            avg = round(tot / cnt, 2)
            out[surface] = avg
            db.insert("surface_returns", {"surface": surface, "avg_delta": avg, "n": cnt,
                      "updated_at": "now()"}, upsert=True)
    return out


def _parse_ts(ts_str: str) -> float:
    """Parse ISO-8601 timestamp string to a POSIX float. Returns -1 on failure."""
    try:
        return datetime.datetime.fromisoformat(ts_str.replace("Z", "+00:00")).timestamp()
    except Exception:
        return -1.0


def cycle_time_by_kind(days: int = 30) -> dict:
    """Avg seconds from task creation to MERGED per task kind, for the last `days` days."""
    rows = db.select("tasks", {
        "select": "kind,created_at,updated_at",
        "state": "eq.MERGED",
    }) or []
    cutoff = time.time() - days * 86400
    agg: dict = {}
    for r in rows:
        created = _parse_ts(r.get("created_at") or "")
        updated = _parse_ts(r.get("updated_at") or "")
        if created < 0 or updated < 0 or created < cutoff:
            continue
        delta = max(0.0, updated - created)
        k = r.get("kind") or "build"
        bucket = agg.setdefault(k, [0.0, 0])
        bucket[0] += delta
        bucket[1] += 1
    return {k: round(tot / cnt, 1) for k, (tot, cnt) in agg.items() if cnt > 0}


def first_try_yield(days: int = 30) -> dict:
    """
    Fraction of MERGED tasks where remediation_count == 0 (merged on first attempt).
    Returns {"overall": float|None, model1: float|None, ...}.
    """
    rows = db.select("tasks", {
        "select": "model,remediation_count,created_at",
        "state": "eq.MERGED",
    }) or []
    cutoff = time.time() - days * 86400
    agg: dict = {}
    overall = [0, 0]
    for r in rows:
        created = _parse_ts(r.get("created_at") or "")
        if created < 0 or created < cutoff:
            continue
        rc = int(r.get("remediation_count") or 0)
        model = r.get("model") or "unknown"
        bucket = agg.setdefault(model, [0, 0])
        bucket[1] += 1
        overall[1] += 1
        if rc == 0:
            bucket[0] += 1
            overall[0] += 1
    result = {"overall": round(overall[0] / overall[1], 3) if overall[1] else None}
    for model, (hits, total) in agg.items():
        result[model] = round(hits / total, 3) if total else None
    return result


def load_tuning_state() -> dict:
    """Load persisted pipeline tuning state; return defaults if missing or corrupt."""
    try:
        with open(TUNING_STATE_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {
            "decisions": [],
            "last_tuned_at": 0,
            "guardrails": {
                "min_sample_size": 5,
                "cooldown_s": TUNE_COOLDOWN_S,
                "max_per_run": MAX_TUNE_PER_RUN,
            },
        }


def save_tuning_state(state: dict) -> None:
    with open(TUNING_STATE_PATH, "w") as f:
        json.dump(state, f, indent=2, default=str)


def auto_tune(cycle_times: dict, fty: dict) -> list:
    """
    Compare metrics against thresholds and emit up to MAX_TUNE_PER_RUN decisions per run.
    Decisions are appended to pipeline_tuning.json and returned for logging.
    Guardrails: cooldown window prevents thrashing; max_per_run limits blast radius.
    To roll back: delete or edit pipeline_tuning.json, then re-run.
    """
    state = load_tuning_state()
    now = time.time()
    guardrails = state.get("guardrails", {})
    cooldown = float(guardrails.get("cooldown_s", TUNE_COOLDOWN_S))
    max_per_run = int(guardrails.get("max_per_run", MAX_TUNE_PER_RUN))

    if now - float(state.get("last_tuned_at", 0)) < cooldown:
        return []  # within cooldown window — no changes this run

    decisions: list = []

    overall_fty = fty.get("overall")
    if overall_fty is not None and overall_fty < FIRST_TRY_YIELD_MIN and len(decisions) < max_per_run:
        decisions.append({
            "ts": now,
            "metric": "first_try_yield",
            "value": overall_fty,
            "threshold": FIRST_TRY_YIELD_MIN,
            "action": "suggest_stronger_model",
            "rationale": (
                f"FTY={overall_fty:.1%} below {FIRST_TRY_YIELD_MIN:.0%} — "
                "route retries to a stronger model"
            ),
        })

    for kind, avg_s in (cycle_times or {}).items():
        if avg_s > CYCLE_TIME_WARN_S and len(decisions) < max_per_run:
            decisions.append({
                "ts": now,
                "metric": "cycle_time",
                "value": avg_s,
                "threshold": CYCLE_TIME_WARN_S,
                "kind": kind,
                "action": "suggest_batching",
                "rationale": (
                    f"avg cycle for kind={kind} is {avg_s / 3600:.1f}h — "
                    "consider batching smaller tasks or enabling parallel worktrees"
                ),
            })
            break  # one batch suggestion per run (max_per_run guard already checked)

    if decisions:
        state["decisions"].extend(decisions)
        state["last_tuned_at"] = now
        save_tuning_state(state)

    return decisions


def run():
    shipped = mark_shipped()
    returns = surface_returns()
    ct = cycle_time_by_kind()
    fty = first_try_yield()
    tuning = auto_tune(ct, fty)
    print(f"improvement_measure: marked {shipped} shipped; surface returns -> {returns}")
    print(f"  cycle_time_by_kind: {ct}")
    print(f"  first_try_yield: {fty}")
    if tuning:
        print(f"  auto_tune decisions ({len(tuning)}): {[d['action'] for d in tuning]}")
    return {
        "shipped": shipped,
        "returns": returns,
        "cycle_time": ct,
        "first_try_yield": fty,
        "tuning": tuning,
    }


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, default=str))
