#!/usr/bin/env python3
"""
realtime_test_monitor.py - live monitoring of test outcomes via Supabase.

Queries the `outcomes` table to surface:
- snapshot of recent pass/fail rates and average duration
- per-project test health scores
- slow tests exceeding a configurable threshold
- flaky test candidates (inconsistent pass/fail patterns)

All functions are fail-soft: errors return safe defaults so the
orchestrator never crashes on telemetry failures.

Env vars (all optional):
- ORCH_MONITOR_LIMIT: max rows to fetch (default 500)
- ORCH_SLOW_THRESHOLD_S: duration in seconds to flag as slow (default 120)
- ORCH_FLAKY_MIN_RUNS: minimum runs before flagging flakiness (default 4)
- ORCH_FLAKY_BAND: pass-rate band [lo, hi] considered flaky (default 0.25-0.75)
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

LIMIT = int(os.environ.get("ORCH_MONITOR_LIMIT", "500"))
SLOW_THRESHOLD = float(os.environ.get("ORCH_SLOW_THRESHOLD_S", "120"))
FLAKY_MIN_RUNS = int(os.environ.get("ORCH_FLAKY_MIN_RUNS", "4"))
FLAKY_LO = float(os.environ.get("ORCH_FLAKY_BAND_LO", "0.25"))
FLAKY_HI = float(os.environ.get("ORCH_FLAKY_BAND_HI", "0.75"))


def _fetch_outcomes():
    """Fetch recent outcomes from Supabase, fail-soft."""
    try:
        return db.select("outcomes", {
            "select": "*",
            "order": "created_at.desc",
            "limit": str(LIMIT),
        }) or []
    except Exception:
        return []


def snapshot():
    """Aggregate pass/fail rates and average duration over recent outcomes."""
    try:
        rows = _fetch_outcomes()
        if not rows:
            return {"total": 0, "pass_rate": 0.0, "fail_rate": 0.0, "avg_duration_s": 0.0}
        total = len(rows)
        passed = sum(1 for r in rows if r.get("tests_passed"))
        durations = [float(r.get("duration_s") or 0) for r in rows]
        avg_dur = sum(durations) / max(1, len(durations))
        return {
            "total": total,
            "pass_rate": round(passed / total, 4),
            "fail_rate": round((total - passed) / total, 4),
            "avg_duration_s": round(avg_dur, 2),
        }
    except Exception as e:
        return {"total": 0, "pass_rate": 0.0, "fail_rate": 0.0, "avg_duration_s": 0.0,
                "error": str(e)}


def test_health():
    """Return per-project test health scores based on recent pass rates."""
    try:
        rows = _fetch_outcomes()
        if not rows:
            return {}
        projects = {}
        for r in rows:
            proj = r.get("project") or "unknown"
            if proj not in projects:
                projects[proj] = {"passed": 0, "total": 0}
            projects[proj]["total"] += 1
            if r.get("tests_passed"):
                projects[proj]["passed"] += 1
        return {
            proj: round(v["passed"] / max(1, v["total"]), 4)
            for proj, v in projects.items()
        }
    except Exception:
        return {}


def slow_tests():
    """Identify tests exceeding the configured duration threshold."""
    try:
        rows = _fetch_outcomes()
        slow = []
        for r in rows:
            dur = float(r.get("duration_s") or 0)
            if dur > SLOW_THRESHOLD:
                slow.append({
                    "project": r.get("project", "unknown"),
                    "task": r.get("task_id") or r.get("id", ""),
                    "duration_s": round(dur, 2),
                })
        slow.sort(key=lambda x: x["duration_s"], reverse=True)
        return slow
    except Exception:
        return []


def flaky_candidates():
    """Detect tests with inconsistent results (mix of pass and fail)."""
    try:
        rows = _fetch_outcomes()
        if not rows:
            return []
        buckets = {}
        for r in rows:
            key = r.get("task_id") or r.get("branch") or r.get("id", "")
            if not key:
                continue
            if key not in buckets:
                buckets[key] = {"passed": 0, "total": 0, "project": r.get("project", "unknown")}
            buckets[key]["total"] += 1
            if r.get("tests_passed"):
                buckets[key]["passed"] += 1
        flaky = []
        for key, v in buckets.items():
            if v["total"] < FLAKY_MIN_RUNS:
                continue
            rate = v["passed"] / v["total"]
            if FLAKY_LO <= rate <= FLAKY_HI:
                flaky.append({
                    "key": key,
                    "project": v["project"],
                    "runs": v["total"],
                    "pass_rate": round(rate, 4),
                })
        flaky.sort(key=lambda x: x["runs"], reverse=True)
        return flaky
    except Exception:
        return []


def stats():
    """Return module telemetry / config for health checks."""
    return {
        "module": "realtime_test_monitor",
        "limit": LIMIT,
        "slow_threshold_s": SLOW_THRESHOLD,
        "flaky_min_runs": FLAKY_MIN_RUNS,
        "flaky_band": [FLAKY_LO, FLAKY_HI],
    }


def run():
    """Orchestrate all monitors and return a combined report."""
    try:
        return {
            "snapshot": snapshot(),
            "test_health": test_health(),
            "slow_tests": slow_tests(),
            "flaky_candidates": flaky_candidates(),
            "stats": stats(),
        }
    except Exception as e:
        return {"error": str(e), "stats": stats()}


if __name__ == "__main__":
    print(run())
