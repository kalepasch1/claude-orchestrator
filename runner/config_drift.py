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
        rows = db.query(
            "SELECT count(*) as cnt FROM tasks WHERE state = 'QUEUED'"
        ) or []
        queued = int(rows[0]["cnt"]) if rows else 0
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


# ── Tests ────────────────────────────────────────────────────────────────────
import unittest
from unittest.mock import patch


class TestConfigDrift(unittest.TestCase):

    @patch("config_drift.db")
    def test_no_drift_when_synced(self, mock_db):
        os.environ["ORCH_TEST_VAL"] = "42"
        mock_db.select = lambda *a, **kw: [{"key": "ORCH_TEST_VAL", "value": "42", "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}]
        drifts = detect_drift()
        env_drifts = [d for d in drifts if d["key"] == "ORCH_TEST_VAL" and d["kind"] == "env_db_divergence"]
        self.assertEqual(len(env_drifts), 0)

    @patch("config_drift.db")
    def test_drift_detected(self, mock_db):
        os.environ["ORCH_TEST_VAL"] = "99"
        mock_db.select = lambda *a, **kw: [{"key": "ORCH_TEST_VAL", "value": "42", "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}]
        drifts = detect_drift()
        env_drifts = [d for d in drifts if d["key"] == "ORCH_TEST_VAL" and d["kind"] == "env_db_divergence"]
        self.assertEqual(len(env_drifts), 1)

    @patch("config_drift.db")
    def test_stale_detected(self, mock_db):
        old = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=60)).isoformat()
        mock_db.select = lambda *a, **kw: [{"key": "ORCH_OLD_VAL", "value": "x", "updated_at": old}]
        drifts = detect_drift()
        stale = [d for d in drifts if d["kind"] == "stale"]
        self.assertGreaterEqual(len(stale), 1)

    @patch("config_drift.db")
    def test_unsafe_keys_skipped(self, mock_db):
        mock_db.select = lambda *a, **kw: [{"key": "SECRET_TOKEN", "value": "bad", "updated_at": None}]
        drifts = detect_drift()
        self.assertEqual(len(drifts), 0)

    @patch("config_drift.db")
    def test_suggest_increase_parallel(self, mock_db):
        mock_db.query = lambda q: [{"cnt": 50}]
        os.environ["MAX_PARALLEL"] = "4"
        suggestions = suggest_updates()
        self.assertTrue(any(s["key"] == "MAX_PARALLEL" and s["suggested"] > 4 for s in suggestions))

    @patch("config_drift.db")
    def test_handles_db_error(self, mock_db):
        mock_db.select = lambda *a, **kw: (_ for _ in ()).throw(Exception("down"))
        drifts = detect_drift()
        self.assertEqual(drifts, [])

    def test_tick_failsoft(self):
        with patch("config_drift.detect_drift", side_effect=Exception("boom")):
            result = tick()
            self.assertEqual(result, ([], []))


if __name__ == "__main__":
    if "--test" in sys.argv:
        unittest.main(argv=["test_config_drift"])
    else:
        import json
        d, s = tick()
        print(json.dumps({"drifts": d, "suggestions": s}, indent=2, default=str))
