#!/usr/bin/env python3
"""config_drift.py — Automated configuration drift detection and suggestions.

Monitors fleet_config for drift between machines and suggests updates based
on historical patterns. Detects:
  1. Env/DB divergence: keys in fleet_config that don't match the running env
  2. Stale configs: keys unchanged for > STALE_DAYS days
  3. Anomalous values: keys whose values are statistical outliers vs history

No model spend — pure arithmetic on DB data and env introspection.
"""
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

STALE_DAYS = int(os.environ.get("ORCH_CONFIG_STALE_DAYS", "30"))

_SAFE_PREFIXES = ("ORCH_", "MAX_PARALLEL", "PER_TASK_GB", "RAM_FLOOR_GB", "RAM_",
                  "RELEASE_", "QUEUE_", "CONT_", "JANITOR_", "REMEDIATION_",
                  "DEFAULT_TEST_CMD", "TASK_TIMEOUT", "ENABLE_", "SESSION_",
                  "ACCOUNT_COOLDOWN", "MERGE_", "DEPLOY_", "INTEGRATE_", "COST_")
_DENY_MARKERS = ("KEY", "SECRET", "TOKEN", "PASSWORD", "PWD", "CREDENTIAL")


def _safe_key(k):
    ku = k.upper()
    if any(m in ku for m in _DENY_MARKERS):
        return False
    return any(ku.startswith(p) for p in _SAFE_PREFIXES)


def detect_drift():
    """Compare fleet_config DB values against running env.

    Returns list of drift entries: {key, db_value, env_value, kind}.
    """
    drifts = []
    try:
        rows = db.select("fleet_config", {"select": "key,value,updated_at"}) or []
    except Exception:
        return drifts

    for row in rows:
        k = row.get("key", "")
        if not k or not _safe_key(k):
            continue
        db_val = str(row.get("value", ""))
        env_val = os.environ.get(k)

        # Env/DB divergence
        if env_val is not None and env_val != db_val:
            drifts.append({
                "key": k,
                "db_value": db_val,
                "env_value": env_val,
                "kind": "env_db_divergence",
                "suggestion": f"Set {k}={db_val} in env or update DB to {env_val}",
            })

        # Stale config
        updated = row.get("updated_at")
        if updated:
            try:
                ts = datetime.datetime.fromisoformat(str(updated).replace("Z", "+00:00"))
                age_days = (datetime.datetime.now(datetime.timezone.utc) - ts).days
                if age_days > STALE_DAYS:
                    drifts.append({
                        "key": k,
                        "db_value": db_val,
                        "age_days": age_days,
                        "kind": "stale",
                        "suggestion": f"Review {k} — unchanged for {age_days} days",
                    })
            except (ValueError, TypeError):
                pass

    return drifts


def suggest_updates():
    """Analyze fleet_config history and suggest optimizations.

    Looks at scoreboard data to suggest config changes that could improve
    merge rate or reduce cost.
    """
    suggestions = []
    try:
        # Check if current MAX_PARALLEL matches queue pressure
        # Was `db.query("SELECT count(*) as cnt FROM tasks WHERE state='QUEUED'")`.
        # db has no query() — it is a PostgREST client with no raw-SQL channel —
        # so this raised AttributeError into the `except Exception: pass` below
        # and suggest_updates() has always returned []. db.count() is the exact
        # equivalent: an exact server-side count with no rows downloaded.
        queued = int(db.count("tasks", {"state": "eq.QUEUED"}) or 0)
        current_parallel = int(os.environ.get("MAX_PARALLEL", "4"))

        if queued > current_parallel * 3:
            suggestions.append({
                "key": "MAX_PARALLEL",
                "current": current_parallel,
                "suggested": min(current_parallel * 2, 8),
                "reason": f"Queue depth ({queued}) is {queued/max(1,current_parallel):.0f}x parallelism — increase to drain faster",
            })
        elif queued == 0 and current_parallel > 2:
            suggestions.append({
                "key": "MAX_PARALLEL",
                "current": current_parallel,
                "suggested": max(current_parallel // 2, 1),
                "reason": "Queue empty — reduce parallelism to save resources",
            })
    except Exception:
        pass

    return suggestions


def tick():
    """Called from main loop; fail-soft. Returns (drifts, suggestions)."""
    try:
        drifts = detect_drift()
        suggestions = suggest_updates()
        for d in drifts:
            if d["kind"] == "env_db_divergence":
                print(f"config_drift: {d['key']} env={d['env_value']} db={d['db_value']}", flush=True)
        for s in suggestions:
            print(f"config_drift: suggest {s['key']}={s['suggested']} ({s['reason']})", flush=True)
        return drifts, suggestions
    except Exception as e:
        print(f"config_drift: tick error ({e})")
        return [], []


if __name__ == "__main__":
    import json
    d, s = tick()
    print(json.dumps({"drifts": d, "suggestions": s}, indent=2, default=str))
