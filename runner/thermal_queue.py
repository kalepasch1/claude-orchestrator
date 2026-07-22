"""
thermal_queue.py — rank queued tasks by Expected Merged Value Per Minute.

Replaces FIFO ordering with an ROI engine. Each task gets a thermal score:
  score = (merge_probability × value) / (estimated_cost × estimated_minutes)

Factors:
- merge_probability: from project/kind historical merge rates
- value: from task priority, project revenue weight, dependency fan-out
- estimated_cost: from model routing + historical token spend
- estimated_minutes: from historical wall time for this project/kind
- dependency_readiness: bonus for tasks whose deps are all satisfied
- model_confidence: from the learned router's confidence in the assigned model

Periodic job writes a ranked list to controls.thermal_ranking so claim_task()
can consume it without recomputing on every poll.
"""
import os, sys, json, math, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

# Defaults when no historical data exists
DEFAULT_MERGE_RATE = 0.5
DEFAULT_WALL_MINUTES = 8.0
DEFAULT_COST_USD = 0.10
DEFAULT_VALUE = 1.0


def run():
    """Compute thermal ranking and write to controls table."""
    queued = db.select("tasks", {
        "select": "id,slug,project_id,kind,priority,confidence,deps,created_at,prompt",
        "state": "eq.QUEUED",
        "order": "created_at.asc",
        "limit": "2000"
    }) or []

    if not queued:
        return {"ranked": 0}

    # Gather historical data
    merge_rates = _project_kind_merge_rates()
    wall_times = _project_kind_wall_times()
    costs = _project_kind_costs()
    project_weights = _project_revenue_weights()
    done_slugs = _done_slugs()

    # Bottleneck map: how many queued tasks each slug would unblock on completion.
    # Tasks with many dependents are bottlenecks — completing them multiplies throughput.
    dep_fans = {}
    for t in queued:
        for dep_slug in (t.get("deps") or []):
            dep_fans[dep_slug] = dep_fans.get(dep_slug, 0) + 1

    scored = []
    for t in queued:
        score = _thermal_score(t, merge_rates, wall_times, costs, project_weights, done_slugs, dep_fans)
        scored.append((score, t["id"]))

    # Sort descending by score (highest value per minute first)
    scored.sort(key=lambda x: -x[0])
    ranking = [tid for _, tid in scored]

    # Write to controls table
    try:
        db.insert("controls", {
            "key": "thermal_ranking",
            "value": json.dumps(ranking),
            "updated_at": "now()"
        }, upsert=True)
    except Exception as e:
        print(f"[thermal] write failed: {e}")

    if scored:
        top = scored[0]
        bot = scored[-1]
        print(f"[thermal] ranked {len(scored)} tasks. top={top[0]:.4f} bot={bot[0]:.4f}")

    return {"ranked": len(scored)}


def _thermal_score(task, merge_rates, wall_times, costs, project_weights, done_slugs, dep_fans=None):
    """Compute the thermal score for a single task."""
    pid = task.get("project_id", "")
    kind = (task.get("kind") or "build").lower()
    key = f"{pid}:{kind}"

    # Merge probability
    merge_prob = merge_rates.get(key, merge_rates.get(pid, DEFAULT_MERGE_RATE))

    # Task confidence (from preflight or prior attempts)
    task_conf = _safe_float(task.get("confidence"), 0.5)
    effective_merge_prob = merge_prob * 0.7 + task_conf * 0.3

    # Value: priority × project revenue weight × dependency fan-out
    priority_val = max(0.1, 10 - _safe_float(task.get("priority"), 5))
    project_weight = project_weights.get(pid, DEFAULT_VALUE)

    # Dependency readiness bonus
    deps = task.get("deps") or []
    if deps:
        satisfied = sum(1 for d in deps if d in done_slugs)
        dep_readiness = satisfied / len(deps) if deps else 1.0
    else:
        dep_readiness = 1.0

    # Bottleneck multiplier: tasks that unblock many others are critical-path work.
    # log1p scale keeps the boost meaningful but bounded (1 dep → ×1.69, 10 → ×2.40).
    unblock_count = (dep_fans or {}).get(task.get("slug") or "", 0)
    unblock_mult = 1.0 + math.log1p(unblock_count)

    value = priority_val * project_weight * (0.5 + 0.5 * dep_readiness) * unblock_mult

    # Estimated cost and time
    est_cost = max(0.001, costs.get(key, costs.get(pid, DEFAULT_COST_USD)))
    est_minutes = max(0.5, wall_times.get(key, wall_times.get(pid, DEFAULT_WALL_MINUTES)))

    # Age bonus: older tasks get a small boost to prevent starvation
    age_hours = _age_hours(task.get("created_at", ""))
    age_bonus = 1.0 + min(0.5, age_hours / 168)  # up to 50% bonus after a week

    # Final score: expected merged value per minute
    score = (effective_merge_prob * value * age_bonus) / (est_cost * est_minutes)

    return score


def _project_kind_merge_rates():
    """Historical merge rates per project and kind."""
    rates = {}
    try:
        outcomes = db.select("outcomes", {
            "select": "project,kind,tests_passed,integrated",
            "order": "created_at.desc",
            "limit": "2000"
        }) or []

        # Group by project:kind
        groups = {}
        for o in outcomes:
            key = f"{o.get('project', '')}:{(o.get('kind') or 'build').lower()}"
            pid = o.get("project", "")
            if key not in groups:
                groups[key] = {"total": 0, "merged": 0}
            if pid not in groups:
                groups[pid] = {"total": 0, "merged": 0}
            groups[key]["total"] += 1
            groups[pid]["total"] += 1
            if o.get("integrated"):
                groups[key]["merged"] += 1
                groups[pid]["merged"] += 1

        for key, g in groups.items():
            if g["total"] >= 3:
                rates[key] = g["merged"] / g["total"]
    except Exception:
        pass
    return rates


def _project_kind_wall_times():
    """Historical wall times per project and kind."""
    times = {}
    try:
        outcomes = db.select("outcomes", {
            "select": "project,kind,wall_ms",
            "wall_ms": "gt.0",
            "order": "created_at.desc",
            "limit": "1000"
        }) or []

        groups = {}
        for o in outcomes:
            key = f"{o.get('project', '')}:{(o.get('kind') or 'build').lower()}"
            pid = o.get("project", "")
            wall_min = (o.get("wall_ms") or 0) / 60000
            if wall_min > 0:
                for k in (key, pid):
                    if k not in groups:
                        groups[k] = []
                    groups[k].append(wall_min)

        for key, vals in groups.items():
            if vals:
                times[key] = sum(vals) / len(vals)
    except Exception:
        pass
    return times


def _project_kind_costs():
    """Historical costs per project and kind."""
    costs = {}
    try:
        outcomes = db.select("outcomes", {
            "select": "project,kind,usd",
            "usd": "gt.0",
            "order": "created_at.desc",
            "limit": "1000"
        }) or []

        groups = {}
        for o in outcomes:
            key = f"{o.get('project', '')}:{(o.get('kind') or 'build').lower()}"
            pid = o.get("project", "")
            usd = o.get("usd") or 0
            if usd > 0:
                for k in (key, pid):
                    if k not in groups:
                        groups[k] = []
                    groups[k].append(usd)

        for key, vals in groups.items():
            if vals:
                costs[key] = sum(vals) / len(vals)
    except Exception:
        pass
    return costs


def _project_revenue_weights():
    """Revenue-based project weights from the projects table."""
    weights = {}
    try:
        projects = db.select("projects", {"select": "id,concurrency_weight"}) or []
        for p in projects:
            w = p.get("concurrency_weight")
            if w is not None:
                weights[p["id"]] = float(w)
    except Exception:
        pass
    return weights


def _done_slugs():
    """Set of all DONE/MERGED task slugs for dependency checking."""
    try:
        rows = db.select("tasks", {"select": "slug", "state": "in.(DONE,MERGED)", "limit": "5000"})
        return {r["slug"] for r in (rows or [])}
    except Exception:
        return set()


def _age_hours(ts_str):
    try:
        ts = datetime.datetime.fromisoformat(str(ts_str).replace("Z", "+00:00").replace("+00:00", ""))
        return (datetime.datetime.utcnow() - ts).total_seconds() / 3600
    except Exception:
        return 0


def _safe_float(v, default):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


if __name__ == "__main__":
    result = run()
    print(json.dumps(result))
