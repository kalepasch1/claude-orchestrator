#!/usr/bin/env python3
"""
meta_loop.py - the loop ON the loops. Scores how well each app's learning/remediation loops
are actually working (from outcomes), tunes their cadence (raises remediate frequency for
flaky apps, lowers optimize for stable ones), cross-deploys the best-performing loop configs
from one app to underperforming apps, and auto-tunes the pipeline itself (gates, models, batching)
based on per-stage cycle_time and first_try_yield metrics, and asks each loop's Claude Code agent
"how could this app's loop or the app itself be improved?" — routing those answers through feedback_review.
Schedule daily.
"""
import os, sys, subprocess, json, uuid, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db, feedback

MODEL = os.environ.get("METALOOP_MODEL", "claude-sonnet-4-6")
AUTO_TUNE_ENABLE = os.environ.get("ORCH_AUTO_TUNE_ENABLE", "false").lower() == "true"
AUTO_TUNE_DRYRUN = os.environ.get("ORCH_AUTO_TUNE_DRYRUN", "false").lower() == "true"
AUTO_TUNE_MIN_SAMPLES = int(os.environ.get("ORCH_TUNE_MIN_SAMPLES", "50"))
AUTO_TUNE_MAX_CHANGE_PCT = int(os.environ.get("ORCH_TUNE_MAX_CHANGE_PCT", "15"))

# Cadence bounds (seconds) per loop type
CADENCE_BOUNDS = {
    "remediate": (60, 600),        # flaky apps: tighter; stable: looser
    "optimize":  (21600, 604800),  # stable apps: less frequent
    "learn":     (86400, 604800),
    "review":    (43200, 604800),
}
# How much to adjust cadence each meta_loop run (fraction of current cadence)
TUNE_STEP = 0.25
# Health score gap that triggers a cross-deploy proposal
CROSS_DEPLOY_GAP = 15
# Auto-tune thresholds (per stage metric)
FIRST_TRY_YIELD_THRESHOLD = 0.60  # if < 60%, consider tuning the pipeline
CYCLE_TIME_REGRESSION_PCT = 15  # if cycle_time increases >15%, flag for tuning
PRECEDENT_MATCH_THRESHOLD = 0.85  # if > 85%, consider increasing batch size


def _project_score(project):
    rows = db.select("outcomes", {"select": "tests_passed,integrated,rate_limited",
                                  "project": f"eq.{project}", "limit": "300"}) or []
    if not rows:
        return None
    n = len(rows)
    passed = sum(1 for r in rows if r.get("tests_passed")) / n
    merged = sum(1 for r in rows if r.get("integrated")) / n
    rl = sum(1 for r in rows if r.get("rate_limited")) / n
    releases = db.select("releases", {"select": "deploy_status", "project": f"eq.{project}",
                                      "order": "created_at.desc", "limit": "50"}) or []
    if releases:
        deployed = sum(1 for r in releases if r.get("deploy_status") == "success") / len(releases)
        return round(100 * (0.3 * passed + 0.35 * merged + 0.35 * deployed) - 20 * rl, 1)
    return round(100 * (0.45 * passed + 0.55 * merged) - 20 * rl, 1)


def _tune_cadence(loop, score):
    """
    Adjust a loop's cadence based on the project's health score.
    Flaky (low score) -> tighter remediate cadence, looser optimize.
    Stable (high score) -> looser remediate, tighter optimize.
    Returns new cadence_seconds or None if no change needed.
    """
    typ = loop["type"]
    if typ not in CADENCE_BOUNDS:
        return None
    lo, hi = CADENCE_BOUNDS[typ]
    cur = int(loop.get("cadence_seconds") or (lo + hi) // 2)
    if score is None:
        return None
    if typ == "remediate":
        # low score -> decrease cadence (more frequent)
        direction = -1 if score < 60 else (1 if score > 85 else 0)
    elif typ == "optimize":
        # high score -> decrease cadence (more frequent); low -> less frequent (don't waste on broken)
        direction = -1 if score > 80 else (1 if score < 50 else 0)
    else:
        direction = 0
    if direction == 0:
        return None
    step = max(60, int(cur * TUNE_STEP))
    new_cad = max(lo, min(hi, cur + direction * step))
    return new_cad if new_cad != cur else None


def _read_tuning_state():
    """Load active tuning decisions from resource_events for rollback detection."""
    try:
        events = db.select("resource_events", {
            "select": "detail",
            "kind": "eq.auto_tune_decision",
            "order": "created_at.desc",
            "limit": "100"
        }) or []
        active = {}
        for e in events:
            try:
                detail = json.loads(e.get("detail") or "{}")
                decision_id = detail.get("decision_id")
                if decision_id and detail.get("status") in ("active", None):
                    if decision_id not in active:  # first/most recent
                        active[decision_id] = detail
            except (json.JSONDecodeError, ValueError):
                pass
        return active
    except Exception:
        return {}


def _stage_metrics_summary(project_id=None):
    """Aggregate recent stage_metrics for all projects or a specific project. Returns dict keyed by (project, kind)."""
    try:
        query = {"select": "project_id,kind,window_days,avg_cycle_time_seconds,first_try_yield_pct,sample_count"}
        if project_id:
            query["project_id"] = f"eq.{project_id}"
        query["window_days"] = "eq.30"  # use 30-day window for tuning decisions
        rows = db.select("stage_metrics", query) or []
        summary = {}
        for r in rows:
            k = (r.get("project_id"), r.get("kind"))
            summary[k] = {
                "cycle_time": r.get("avg_cycle_time_seconds", 0),
                "first_try_yield": r.get("first_try_yield_pct", 0) / 100.0,
                "sample_count": r.get("sample_count", 0)
            }
        return summary
    except Exception:
        return {}


def _plan_auto_tune_decisions():
    """Analyze stage_metrics and propose safe tuning decisions. Returns list of dicts."""
    if not (AUTO_TUNE_ENABLE or AUTO_TUNE_DRYRUN):
        return []

    decisions = []
    metrics = _stage_metrics_summary()
    active = _read_tuning_state()

    for (proj_id, kind), data in metrics.items():
        n = data.get("sample_count", 0)
        first_try = data.get("first_try_yield", 1.0)
        cycle_time = data.get("cycle_time", 0)

        # guardrail: only tune if enough samples
        if n < AUTO_TUNE_MIN_SAMPLES:
            continue

        # decision 1: if first_try_yield < 60%, propose low-risk gate bypass (llm-gating-policy)
        if first_try < FIRST_TRY_YIELD_THRESHOLD and kind == "build":
            decision = {
                "decision_id": str(uuid.uuid4()),
                "project_id": proj_id,
                "kind": kind,
                "metric": "first_try_yield",
                "current_value": round(first_try * 100, 1),
                "threshold": FIRST_TRY_YIELD_THRESHOLD * 100,
                "action": "bypass_build_gate_for_low_risk",
                "pct_change": min(AUTO_TUNE_MAX_CHANGE_PCT, 10),  # 10% of low-risk tasks bypass
                "sample_count": n,
                "justification": f"first_try_yield {round(first_try*100, 1)}% < {FIRST_TRY_YIELD_THRESHOLD*100}%: route 10% of low-risk tasks to bypass build gate",
                "status": "active"
            }
            decisions.append(decision)

        # decision 2: detect cycle_time regression (compare 5-day vs 30-day window)
        try:
            metrics_5d = db.select("stage_metrics", {
                "select": "avg_cycle_time_seconds",
                "project_id": f"eq.{proj_id}",
                "kind": f"eq.{kind}",
                "window_days": "eq.5"
            }) or []
            if metrics_5d:
                cycle_5d = metrics_5d[0].get("avg_cycle_time_seconds", 0)
                if cycle_5d and cycle_time and cycle_time > 0:
                    pct_change = ((cycle_5d - cycle_time) / cycle_time) * 100
                    if pct_change > CYCLE_TIME_REGRESSION_PCT:
                        decision = {
                            "decision_id": str(uuid.uuid4()),
                            "project_id": proj_id,
                            "kind": kind,
                            "metric": "cycle_time",
                            "current_value_5d": round(cycle_5d, 1),
                            "baseline_30d": round(cycle_time, 1),
                            "regression_pct": round(pct_change, 1),
                            "action": "rotate_model_mix",
                            "pct_change": min(AUTO_TUNE_MAX_CHANGE_PCT, 10),
                            "justification": f"cycle_time increased {round(pct_change, 1)}%: rotate back to cheaper model in mix",
                            "status": "active"
                        }
                        decisions.append(decision)
        except Exception:
            pass

    return decisions


def _log_tuning_decision(decision):
    """Log a tuning decision to resource_events for audit trail."""
    try:
        db.insert("resource_events", {
            "kind": "auto_tune_decision",
            "detail": json.dumps(decision),
            "created_at": "now()"
        })
    except Exception as e:
        print(f"meta_loop: failed to log tuning decision: {e}")


def _ask_improvement(project, loop_type):
    """
    Ask a capability- and cost-optimized diverse vendor how this loop could be improved.
    Routes the answer through feedback.submit so feedback_review can cluster it.
    """
    prompt = (
        f"You are reviewing the orchestration loop for project '{project}' (loop type: {loop_type}). "
        f"Using deployed-value evidence rather than model self-confidence, suggest ONE concrete improvement "
        f"for either (a) the loop itself (cadence, scope, checks) or (b) the app. "
        f"Reply as a JSON object: "
        f'{{\"category\":\"strategy\",\"severity\":\"med\",\"observation\":\"measured bottleneck...\",'
        f'\"suggestion\":\"reversible mechanism + acceptance metric + rollback...\"}}'
    )
    try:
        import model_policy, model_gateway
        provider, model, _ = model_policy.choose_diverse("plan", need=8)
        resp = model_gateway.complete(provider, model, prompt, timeout=90,
                                      operation="meta_loop_improvement", task_class="plan",
                                      project=project)
        import re, json
        m = re.search(r"\{.*\}", resp.get("text") or "", re.S)
        if m:
            it = json.loads(m.group(0))
            feedback.submit(
                it.get("category", "strategy"), it.get("observation", ""),
                it.get("suggestion", ""), it.get("severity", "med"),
                project=project, slug=f"metaloop-{loop_type}", source="meta_loop",
            )
    except Exception as e:
        print(f"meta_loop: improvement question failed for {project}/{loop_type}: {e}")


def run():
    loops = db.select("loops", {"select": "*"}) or []
    by_project = {}
    for l in loops:
        by_project.setdefault(l["project"], []).append(l)
    scores = {p: _project_score(p) for p in by_project}
    rated = {p: s for p, s in scores.items() if s is not None}

    tuned = 0
    for p, ls in by_project.items():
        score = scores.get(p)
        if score is None:
            db.update("loops", {"project": p}, {"health": 0})
            continue
        for l in ls:
            db.update("loops", {"id": l["id"]}, {"health": score})
            new_cad = _tune_cadence(l, score)
            if new_cad:
                db.update("loops", {"id": l["id"]}, {"cadence_seconds": new_cad})
                tuned += 1
                print(f"meta_loop: tuned {p}/{l['type']} cadence {l['cadence_seconds']}s -> {new_cad}s (score {score})")
        # Ask for loop improvement suggestions (one per project per meta_loop run)
        _ask_improvement(p, "remediate")

    if len(rated) < 2:
        print(f"meta_loop: tuned {tuned} cadences; not enough projects to cross-deploy")
    else:
        best = max(rated, key=rated.get)
        worst = min(rated, key=rated.get)

        # write health back + cross-deploy if gap is large
        if rated[best] - rated[worst] > CROSS_DEPLOY_GAP:
            best_cfg = {l["type"]: {"cadence_seconds": l["cadence_seconds"], "config": l.get("config")}
                        for l in by_project[best]}
            db.insert("approvals", {"project": worst, "kind": "self",
                "title": f"Cross-deploy '{best}' loop config to '{worst}'",
                "why": f"{best} loop-health {rated[best]} vs {worst} {rated[worst]}.",
                "value": "Propagate the better-performing learning/remediation cadence.",
                "risk": "Tune after applying; revertible.",
                "detail": str(best_cfg)})
            print(f"meta_loop: proposed cross-deploy {best}({rated[best]}) -> {worst}({rated[worst]})")
            tuned += 1

        print(f"meta_loop: {tuned} cadence tunes; best {best}={rated[best]}, worst {worst}={rated[worst]}")

    # PIPELINE AUTO-TUNING: measure and tune cycle_time + first_try_yield per stage
    auto_tune_decisions = _plan_auto_tune_decisions()
    if auto_tune_decisions:
        for decision in auto_tune_decisions:
            if AUTO_TUNE_DRYRUN:
                print(f"meta_loop [DRYRUN]: {decision['action']} for {decision['kind']} "
                      f"({decision.get('metric')} = {decision.get('current_value', '?')})")
            else:
                _log_tuning_decision(decision)
                tuned += 1
                print(f"meta_loop: auto-tune decision logged - {decision['action']} "
                      f"({decision.get('justification', '')})")

    return tuned


if __name__ == "__main__":
    run()
