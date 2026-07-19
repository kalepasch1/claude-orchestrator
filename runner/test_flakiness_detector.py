#!/usr/bin/env python3
"""
test_flakiness_detector.py – Detect and track flaky tests in the runner suite.

Runs each test multiple times, identifies non-deterministic failures, and
maintains a flakiness database for the merge train to skip or quarantine
unreliable tests.

Conventions: module-level singleton, fail-soft, ORCH_ env vars, thread-safe.
"""
import os, sys, json, datetime, threading, subprocess, hashlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

RUNNER_DIR = os.path.dirname(os.path.abspath(__file__))
FLAKE_RUNS = int(os.environ.get("ORCH_FLAKE_RUNS", "3"))
FLAKE_DB = os.path.expanduser("~/.claude-orchestrator/flaky-tests.json")
FLAKE_THRESHOLD = float(os.environ.get("ORCH_FLAKE_THRESHOLD", "0.5"))

_lock = threading.Lock()
_STATE = {
    "last_scan": None,
    "flaky_tests": [],
    "total_scans": 0,
}


def _load_flake_db():
    try:
        with open(FLAKE_DB) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _save_flake_db(db):
    try:
        os.makedirs(os.path.dirname(FLAKE_DB), exist_ok=True)
        with open(FLAKE_DB, "w") as f:
            json.dump(db, f, indent=2)
    except OSError:
        pass


def _run_test(test_path, repo_root):
    try:
        result = subprocess.run(
            ["python3", "-m", "pytest", test_path, "-x", "-q", "--tb=line"],
            capture_output=True, text=True, cwd=repo_root, timeout=30,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def check_flakiness(test_path, runs=None):
    """Run a test multiple times and return flakiness ratio."""
    if runs is None:
        runs = FLAKE_RUNS
    repo_root = os.path.dirname(RUNNER_DIR)
    results = [_run_test(test_path, repo_root) for _ in range(runs)]
    passes = sum(results)
    failures = runs - passes

    if passes == runs:
        status = "stable_pass"
    elif failures == runs:
        status = "stable_fail"
    else:
        status = "flaky"

    return {
        "test": test_path,
        "runs": runs,
        "passes": passes,
        "failures": failures,
        "flakiness_ratio": round(failures / runs, 3),
        "status": status,
    }


def scan_all(runs=None):
    """Scan all runner tests for flakiness."""
    tests = []
    try:
        for f in sorted(os.listdir(RUNNER_DIR)):
            if f.startswith("test_") and f.endswith(".py"):
                tests.append(os.path.join("runner", f))
    except OSError:
        return {"error": "cannot list runner directory"}

    results = []
    flaky = []
    for t in tests:
        result = check_flakiness(t, runs)
        results.append(result)
        if result["status"] == "flaky":
            flaky.append(result)

    # Update flake DB
    db = _load_flake_db()
    now = datetime.datetime.utcnow().isoformat() + "Z"
    for r in results:
        key = r["test"]
        if key not in db:
            db[key] = {"history": [], "first_seen": now}
        db[key]["history"].append({
            "at": now,
            "ratio": r["flakiness_ratio"],
            "status": r["status"],
        })
        db[key]["history"] = db[key]["history"][-10:]  # keep last 10
        db[key]["latest_status"] = r["status"]
    _save_flake_db(db)

    summary = {
        "total_tests": len(results),
        "flaky_count": len(flaky),
        "stable_pass": sum(1 for r in results if r["status"] == "stable_pass"),
        "stable_fail": sum(1 for r in results if r["status"] == "stable_fail"),
        "flaky_tests": flaky,
        "scanned_at": now,
    }

    with _lock:
        _STATE["last_scan"] = now
        _STATE["flaky_tests"] = [f["test"] for f in flaky]
        _STATE["total_scans"] += 1

    return summary


def get_known_flaky():
    """Return list of known flaky tests from the DB."""
    db = _load_flake_db()
    return [
        {"test": k, "latest": v.get("latest_status"), "first_seen": v.get("first_seen")}
        for k, v in db.items()
        if v.get("latest_status") == "flaky"
    ]


def should_skip(test_path):
    """Check if a test should be skipped due to known flakiness."""
    db = _load_flake_db()
    entry = db.get(test_path)
    if not entry:
        return False
    recent = entry.get("history", [])[-3:]
    if not recent:
        return False
    avg_flake = sum(h.get("ratio", 0) for h in recent) / len(recent)
    return avg_flake >= FLAKE_THRESHOLD


def stats():
    with _lock:
        return dict(_STATE)


def run():
    """Entry point — scan all tests with minimal runs for speed."""
    return scan_all(runs=2)


if __name__ == "__main__":
    result = scan_all()
    print(f"Flaky: {result['flaky_count']}/{result['total_tests']} tests")
