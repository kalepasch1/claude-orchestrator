#!/usr/bin/env python3
"""
test_quarantine.py - self-healing test infrastructure.

When tests flake (pass sometimes, fail sometimes), automatically quarantine them,
measure flake rate, and either fix the flake or mark as flaky so they don't block
merges.

Env vars:
    ORCH_TEST_QUARANTINE      – true/false (default true)
    ORCH_FLAKE_THRESHOLD      – flake-rate above which to quarantine (default 0.2)
    ORCH_QUARANTINE_MIN_RUNS  – minimum runs before quarantine applies (default 10)
"""
import os, sys, threading, time, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db, log

_log = log.get(__name__)

ENABLED = os.environ.get("ORCH_TEST_QUARANTINE", "true").lower() == "true"
FLAKE_THRESHOLD = float(os.environ.get("ORCH_FLAKE_THRESHOLD", "0.2"))
MIN_RUNS = int(os.environ.get("ORCH_QUARANTINE_MIN_RUNS", "10"))
CONSECUTIVE_PASS_TO_PROMOTE = 10
_TABLE = "test_health"

_lock = threading.Lock()
# In-memory store: {(project_id, test_name): {pass_count, fail_count, flake_rate,
#   quarantined, consecutive_passes, updated_at}}
_cache = {}
_merges_unblocked = 0
_dirty = set()  # keys that need DB flush


def _key(project_id, test_name):
    return (project_id, test_name)


def _now():
    return datetime.datetime.utcnow().isoformat() + "Z"


def _compute_flake_rate(passes, fails):
    total = passes + fails
    if total == 0:
        return 0.0
    minority = min(passes, fails)
    return minority / total


def _default_entry():
    return {"pass_count": 0, "fail_count": 0, "flake_rate": 0.0,
            "quarantined": False, "consecutive_passes": 0, "updated_at": _now()}


def _load_from_db(project_id):
    """Bulk-load all entries for a project from DB into cache."""
    try:
        rows = db.select(_TABLE, {"project_id": f"eq.{project_id}"}) or []
        with _lock:
            for r in rows:
                k = _key(r["project_id"], r["test_name"])
                if k not in _cache:
                    _cache[k] = {
                        "pass_count": int(r.get("pass_count", 0)),
                        "fail_count": int(r.get("fail_count", 0)),
                        "flake_rate": float(r.get("flake_rate", 0)),
                        "quarantined": bool(r.get("quarantined", False)),
                        "consecutive_passes": int(r.get("consecutive_passes", 0)),
                        "updated_at": r.get("updated_at", _now()),
                    }
    except Exception as e:
        _log.warning("test_quarantine: DB load failed for %s: %s", project_id, e)


def report_test_result(test_name, passed, project_id, run_context=None):
    """Record a single test outcome (pass or fail)."""
    global _merges_unblocked
    if not ENABLED:
        return
    k = _key(project_id, test_name)
    with _lock:
        if k not in _cache:
            _cache[k] = _default_entry()
        entry = _cache[k]
        if passed:
            entry["pass_count"] += 1
            entry["consecutive_passes"] += 1
        else:
            entry["fail_count"] += 1
            entry["consecutive_passes"] = 0
        entry["flake_rate"] = _compute_flake_rate(entry["pass_count"], entry["fail_count"])
        total = entry["pass_count"] + entry["fail_count"]
        if not entry["quarantined"] and total >= MIN_RUNS and entry["flake_rate"] > FLAKE_THRESHOLD:
            entry["quarantined"] = True
            _log.info("quarantined test %s in %s (flake_rate=%.2f, runs=%d)",
                      test_name, project_id, entry["flake_rate"], total)
        if entry["quarantined"] and entry["consecutive_passes"] >= CONSECUTIVE_PASS_TO_PROMOTE:
            entry["quarantined"] = False
            _log.info("promoted stable test %s in %s (%d consecutive passes)",
                      test_name, project_id, entry["consecutive_passes"])
        entry["updated_at"] = _now()
        _dirty.add(k)


def is_flaky(test_name, project_id):
    """Check whether a test is considered flaky."""
    k = _key(project_id, test_name)
    with _lock:
        entry = _cache.get(k)
    if entry is None:
        _load_from_db(project_id)
        with _lock:
            entry = _cache.get(k)
    if entry is None:
        return {"flaky": False, "flake_rate": 0.0, "total_runs": 0, "quarantined": False}
    total = entry["pass_count"] + entry["fail_count"]
    return {
        "flaky": entry["flake_rate"] > FLAKE_THRESHOLD and total >= MIN_RUNS,
        "flake_rate": round(entry["flake_rate"], 4),
        "total_runs": total,
        "quarantined": entry["quarantined"],
    }


def quarantine_check(failed_tests, project_id):
    """Split failed tests into blocking (real failures) vs quarantined (probably flaky).

    Quarantined tests don't block merges.
    """
    global _merges_unblocked
    if not ENABLED:
        return {"blocking": list(failed_tests), "quarantined": [], "reason": "quarantine disabled"}
    blocking, quarantined = [], []
    for t in failed_tests:
        info = is_flaky(t, project_id)
        if info["quarantined"]:
            quarantined.append(t)
        else:
            blocking.append(t)
    reason = ""
    if quarantined:
        reason = f"{len(quarantined)} test(s) quarantined as flaky, not blocking merge"
        if not blocking:
            with _lock:
                _merges_unblocked += 1
    elif blocking:
        reason = f"{len(blocking)} real failure(s) blocking merge"
    else:
        reason = "no failures"
    return {"blocking": blocking, "quarantined": quarantined, "reason": reason}


def get_quarantine_list(project_id):
    """Return list of quarantined test names with stats for a project."""
    _load_from_db(project_id)
    result = []
    with _lock:
        for (pid, tname), entry in _cache.items():
            if pid == project_id and entry["quarantined"]:
                result.append({
                    "test_name": tname,
                    "flake_rate": round(entry["flake_rate"], 4),
                    "total_runs": entry["pass_count"] + entry["fail_count"],
                    "pass_count": entry["pass_count"],
                    "fail_count": entry["fail_count"],
                    "consecutive_passes": entry["consecutive_passes"],
                })
    return result


def promote_stable(project_id):
    """Un-quarantine tests that have passed CONSECUTIVE_PASS_TO_PROMOTE times in a row."""
    promoted = []
    with _lock:
        for (pid, tname), entry in _cache.items():
            if pid != project_id or not entry["quarantined"]:
                continue
            if entry["consecutive_passes"] >= CONSECUTIVE_PASS_TO_PROMOTE:
                entry["quarantined"] = False
                entry["updated_at"] = _now()
                _dirty.add(_key(pid, tname))
                promoted.append(tname)
    for t in promoted:
        _log.info("promote_stable: un-quarantined %s in %s", t, project_id)
    return promoted


def flush():
    """Persist dirty in-memory entries to DB. Fail-soft on errors."""
    with _lock:
        to_flush = list(_dirty)
        _dirty.clear()
    flushed, failed = 0, 0
    for k in to_flush:
        pid, tname = k
        with _lock:
            entry = _cache.get(k)
        if entry is None:
            continue
        row = {
            "project_id": pid,
            "test_name": tname,
            "pass_count": entry["pass_count"],
            "fail_count": entry["fail_count"],
            "flake_rate": round(entry["flake_rate"], 4),
            "quarantined": entry["quarantined"],
            "consecutive_passes": entry["consecutive_passes"],
            "updated_at": entry["updated_at"],
        }
        try:
            db.upsert(_TABLE, row)
            flushed += 1
        except Exception as e:
            failed += 1
            _log.warning("test_quarantine flush failed for %s/%s: %s", pid, tname, e)
            with _lock:
                _dirty.add(k)
    if flushed or failed:
        _log.info("test_quarantine flush: %d ok, %d failed", flushed, failed)
    return {"flushed": flushed, "failed": failed}


def stats():
    """Return aggregate stats across all tracked tests."""
    with _lock:
        total = len(_cache)
        q_count = sum(1 for e in _cache.values() if e["quarantined"])
        rates = [e["flake_rate"] for e in _cache.values()]
        avg_rate = (sum(rates) / len(rates)) if rates else 0.0
        unblocked = _merges_unblocked
    return {
        "quarantined_count": q_count,
        "total_tracked": total,
        "avg_flake_rate": round(avg_rate, 4),
        "merges_unblocked": unblocked,
    }


def invalidate(project_id=None):
    """Clear in-memory cache (all or per-project). For testing / operator use."""
    with _lock:
        if project_id is None:
            _cache.clear()
            _dirty.clear()
        else:
            to_remove = [k for k in _cache if k[0] == project_id]
            for k in to_remove:
                _cache.pop(k, None)
                _dirty.discard(k)


if __name__ == "__main__":
    # Quick smoke test
    pid = "TEST_PROJECT"
    for i in range(15):
        report_test_result("test_a", i % 3 != 0, pid)  # ~33% fail
    report_test_result("test_b", True, pid)
    print("is_flaky(test_a):", is_flaky("test_a", pid))
    print("is_flaky(test_b):", is_flaky("test_b", pid))
    print("quarantine_check:", quarantine_check(["test_a", "test_b", "test_c"], pid))
    print("quarantine_list:", get_quarantine_list(pid))
    print("stats:", stats())
