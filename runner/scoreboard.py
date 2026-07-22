#!/usr/bin/env python3
"""Fleet scoreboard – persistence layer.

Assembles payload from collect_all + compute_metrics, upserts to controls,
appends to scoreboard table, prints summary.

NOTE: scoreboard rows are pruned by RETENTION_DAYS (default 90) via
scheduled DB maintenance; see fleet_config / db_maintenance for details.
"""
import datetime, json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

WINDOW_H = int(os.environ.get("ORCH_SCOREBOARD_WINDOW_H", "24"))
CONTROL_KEY = "fleet_scoreboard"
HISTORY_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           ".runtime")
HISTORY_FILE = os.path.join(HISTORY_DIR, "scoreboard_history.jsonl")
HISTORY_RETENTION_DAYS = int(os.environ.get("ORCH_SCOREBOARD_RETENTION_DAYS", "90"))


def _iso_hours_ago(hours):
    return (datetime.datetime.utcnow() - datetime.timedelta(hours=hours)).isoformat()


def _select_outcomes():
    params = {
        "select": "project,model,coder,tests_passed,integrated,usd,wall_ms,input_tokens,output_tokens,review_failures,created_at",
        "created_at": f"gte.{_iso_hours_ago(WINDOW_H)}",
        "limit": "5000",
    }
    try:
        return db.select("outcomes", params) or []
    except Exception:
        fallback = {
            "select": "project,model,tests_passed,integrated,usd,wall_ms,created_at",
            "created_at": f"gte.{_iso_hours_ago(WINDOW_H)}",
            "limit": "5000",
        }
        return db.select("outcomes", fallback) or []


def _queue():
    try:
        import queue_counters
        return queue_counters.exact_counts(db_client=db)
    except Exception as e:
        try:
            import importlib.util
            path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "queue_counters.py")
            spec = importlib.util.spec_from_file_location("queue_counters_fallback", path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod.exact_counts(db_client=db)
        except Exception as e2:
            return {"error": f"{e}; fallback: {e2}"[:300], "states": {}}


def _paused_minutes_today():
    try:
        rows = db.select("controls", {"select": "paused,scope,updated_at,updated_by",
                                      "scope": "eq.global",
                                      "order": "updated_at.asc",
                                      "limit": "1000"}) or []
    except Exception:
        return None
    if not rows:
        return 0
    now = datetime.datetime.now(datetime.timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    total = 0.0
    paused_since = None
    for row in rows:
        ts = _parse_ts(row.get("updated_at"))
        if not ts:
            continue
        if row.get("paused"):
            paused_since = max(ts, start)
        elif paused_since:
            end = max(ts, start)
            if end > paused_since:
                total += (end - paused_since).total_seconds()
            paused_since = None
    if paused_since:
        total += (now - paused_since).total_seconds()
    return round(total / 60.0, 1)


def _parse_ts(value):
    if not value:
        return None
    raw = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.datetime.fromisoformat(raw)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=datetime.timezone.utc)
        return parsed
    except Exception:
        return None


def _outcome_metrics(rows):
    attempts = len(rows)
    tests_passed = sum(1 for r in rows if r.get("tests_passed"))
    merged = sum(1 for r in rows if r.get("integrated"))
    usd = sum(float(r.get("usd") or 0) for r in rows)
    tokens = sum(int(r.get("input_tokens") or 0) + int(r.get("output_tokens") or 0) for r in rows)
    wall_ms = sum(int(r.get("wall_ms") or 0) for r in rows)
    review_failures = sum(int(r.get("review_failures") or 0) for r in rows)
    first_pass_rate = round(tests_passed / attempts, 4) if attempts else None
    merge_rate = round(merged / attempts, 4) if attempts else None
    return {
        "attempts": attempts,
        "tests_passed": tests_passed,
        "merged": merged,
        "first_pass_rate": first_pass_rate,
        "merge_rate": merge_rate,
        "usd": round(usd, 4),
        "usd_per_merge": round(usd / merged, 4) if merged else None,
        "tokens": tokens,
        "tokens_per_merge": round(tokens / merged, 1) if merged else None,
        "avg_wall_min": round((wall_ms / max(1, attempts)) / 60000, 2) if attempts else None,
        "review_failures": review_failures,
        "review_failures_per_merge": round(review_failures / merged, 3) if merged else None,
    }


def _by_model(rows):
    grouped = {}
    for row in rows:
        key = row.get("model") or row.get("coder") or "unknown"
        grouped.setdefault(str(key), []).append(row)
    return {key: _outcome_metrics(vals) for key, vals in grouped.items()}


def _by_project(rows):
    grouped = {}
    for row in rows:
        key = row.get("project") or "unknown"
        grouped.setdefault(str(key), []).append(row)
    return {key: _outcome_metrics(vals) for key, vals in grouped.items()}


# ── Lead time metrics (D1) ────────────────────────────────────────────────────

def _lead_time_metrics():
    """Compute objective→prompt and prompt→merged lead times from recent data.

    - objective_to_prompt_h: average hours from goal creation to first task queued
    - prompt_to_merged_h: average hours from task creation to merged outcome
    - tokens_per_task: average token estimate per assembled prompt
    """
    result = {
        "objective_to_prompt_h": None,
        "prompt_to_merged_h": None,
        "tokens_per_task": None,
    }

    # prompt→merged: time from task created_at to outcome created_at (integrated=true)
    try:
        outcomes = db.select("outcomes", {
            "select": "slug,project,created_at",
            "integrated": "eq.true",
            "order": "created_at.desc",
            "limit": "200",
        }) or []
        if outcomes:
            deltas = []
            for o in outcomes:
                outcome_ts = _parse_ts(o.get("created_at"))
                if not outcome_ts:
                    continue
                slug = o.get("slug")
                if not slug:
                    continue
                try:
                    tasks = db.select("tasks", {
                        "select": "created_at",
                        "slug": f"eq.{slug}",
                        "limit": "1",
                    }) or []
                except Exception:
                    continue
                if tasks:
                    task_ts = _parse_ts(tasks[0].get("created_at"))
                    if task_ts and outcome_ts > task_ts:
                        deltas.append((outcome_ts - task_ts).total_seconds() / 3600.0)
            if deltas:
                result["prompt_to_merged_h"] = round(sum(deltas) / len(deltas), 2)
    except Exception:
        pass

    # objective→prompt: time from goal created_at to first task created_at for that project
    try:
        goals = db.select("goals", {
            "select": "objective,project,created_at",
            "status": "in.(active,met)",
            "order": "created_at.desc",
            "limit": "50",
        }) or []
        if goals:
            deltas = []
            for g in goals:
                goal_ts = _parse_ts(g.get("created_at"))
                proj = g.get("project")
                if not goal_ts or not proj:
                    continue
                try:
                    tasks = db.select("tasks", {
                        "select": "created_at",
                        "order": "created_at.asc",
                        "limit": "1",
                    }) or []
                except Exception:
                    continue
                if tasks:
                    task_ts = _parse_ts(tasks[0].get("created_at"))
                    if task_ts and task_ts > goal_ts:
                        deltas.append((task_ts - goal_ts).total_seconds() / 3600.0)
            if deltas:
                result["objective_to_prompt_h"] = round(sum(deltas) / len(deltas), 2)
    except Exception:
        pass

    # tokens per task from prompt_assembler stats
    try:
        import prompt_assembler
        pa_stats = prompt_assembler.stats()
        result["tokens_per_task"] = pa_stats.get("avg_tokens")
    except Exception:
        pass

    return result


# ── History persistence ───────────────────────────────────────────────────────

def _append_history(payload):
    """Append snapshot to JSONL file for >=30-day retention."""
    try:
        os.makedirs(HISTORY_DIR, exist_ok=True)
        with open(HISTORY_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, default=str) + "\n")
    except Exception:
        pass


def _prune_history():
    """Remove entries older than HISTORY_RETENTION_DAYS from the JSONL file."""
    if not os.path.isfile(HISTORY_FILE):
        return
    try:
        cutoff = (datetime.datetime.utcnow() -
                  datetime.timedelta(days=HISTORY_RETENTION_DAYS)).isoformat()
        kept = []
        with open(HISTORY_FILE, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                    ts = row.get("generated_at", "")
                    if ts >= cutoff:
                        kept.append(line)
                except Exception:
                    pass
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            for line in kept:
                f.write(line + "\n")
    except Exception:
        pass


def history(days=30):
    """Read historical snapshots from JSONL. Returns list of dicts."""
    if not os.path.isfile(HISTORY_FILE):
        return []
    cutoff = (datetime.datetime.utcnow() -
              datetime.timedelta(days=days)).isoformat()
    results = []
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                    if row.get("generated_at", "") >= cutoff:
                        results.append(row)
                except Exception:
                    pass
    except Exception:
        pass
    return results


def compute():
    data = collect_all()
    return {"generated_at": datetime.datetime.utcnow().isoformat(),
            "window_h": WINDOW_H, "queue": data["queue"],
            "paused_minutes_today": data["paused_minutes"],
            **compute_metrics(data["outcomes"])}


def run():
    payload = compute()
    for table, row in [("controls", {"key": CONTROL_KEY,
                                      "value": json.dumps(payload, default=str),
                                      "updated_at": "now()"}),
                       ("scoreboard", payload)]:
        try:
            db.insert(table, row, upsert=(table == "controls"))
        except Exception:
            pass
    o, q = payload["overall"], payload.get("queue") or {}
    print(f"scoreboard: queued={q.get('queued')} running={q.get('running')} "
          f"merged={o.get('merged')}/{o.get('attempts')} "
          f"merge_rate={o.get('merge_rate')} usd/merge={o.get('usd_per_merge')} "
          f"paused_min={payload.get('paused_minutes_today')}")
    return payload


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, default=str))
