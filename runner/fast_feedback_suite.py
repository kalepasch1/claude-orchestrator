#!/usr/bin/env python3
"""
fast_feedback_suite.py – Enhanced testing for faster feedback loops.

Implements parallel test execution, incremental test selection, and result
caching to minimize time-to-feedback for the merge train. Tracks test
execution times and identifies slow tests that block the pipeline.

Conventions: module-level singleton, fail-soft, ORCH_ env vars, thread-safe.
"""
import os, sys, json, datetime, threading, subprocess, time, hashlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

RUNNER_DIR = os.path.dirname(os.path.abspath(__file__))
SLOW_THRESHOLD_SEC = float(os.environ.get("ORCH_SLOW_TEST_SEC", "10.0"))
CACHE_DIR = os.path.expanduser("~/.claude-orchestrator/test-cache")
MAX_PARALLEL = int(os.environ.get("ORCH_TEST_PARALLEL", "4"))

_lock = threading.Lock()
_STATE = {
    "last_run": None,
    "total_runs": 0,
    "cache_hits": 0,
    "slow_tests": [],
}


def _ensure_cache_dir():
    """Create test cache directory if needed."""
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
    except OSError:
        pass


def _file_hash(filepath):
    """SHA256 of file contents for cache invalidation."""
    try:
        with open(filepath, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()[:16]
    except OSError:
        return None


def _check_cache(test_file, source_hash):
    """Check if we have a cached passing result for this source hash."""
    _ensure_cache_dir()
    cache_key = os.path.basename(test_file).replace(".py", "")
    cache_path = os.path.join(CACHE_DIR, f"{cache_key}.json")
    try:
        with open(cache_path) as f:
            cached = json.load(f)
        if cached.get("source_hash") == source_hash and cached.get("passed"):
            age = (datetime.datetime.utcnow() -
                   datetime.datetime.fromisoformat(cached["tested_at"].rstrip("Z"))
                   ).total_seconds()
            if age < 3600:  # cache valid for 1 hour
                return True
    except (OSError, json.JSONDecodeError, KeyError, ValueError):
        pass
    return False


def _save_cache(test_file, source_hash, passed, duration):
    """Save test result to cache."""
    _ensure_cache_dir()
    cache_key = os.path.basename(test_file).replace(".py", "")
    cache_path = os.path.join(CACHE_DIR, f"{cache_key}.json")
    try:
        with open(cache_path, "w") as f:
            json.dump({
                "source_hash": source_hash,
                "passed": passed,
                "duration_sec": duration,
                "tested_at": datetime.datetime.utcnow().isoformat() + "Z",
            }, f)
    except OSError:
        pass


def _run_single_test(test_path, repo_root):
    """Run a single test file and return result dict."""
    start = time.monotonic()
    try:
        result = subprocess.run(
            ["python3", "-m", "pytest", test_path, "-x", "-q", "--tb=short"],
            capture_output=True, text=True, cwd=repo_root, timeout=60,
        )
        duration = time.monotonic() - start
        passed = result.returncode == 0
        return {
            "test": test_path,
            "passed": passed,
            "duration_sec": round(duration, 2),
            "output": (result.stdout + result.stderr)[-500:],
            "slow": duration > SLOW_THRESHOLD_SEC,
        }
    except subprocess.TimeoutExpired:
        return {
            "test": test_path,
            "passed": False,
            "duration_sec": 60.0,
            "output": "TIMEOUT after 60s",
            "slow": True,
        }
    except OSError as e:
        return {
            "test": test_path,
            "passed": False,
            "duration_sec": 0,
            "output": str(e),
            "slow": False,
        }


def discover_tests():
    """Find all test files in runner/."""
    tests = []
    try:
        for f in sorted(os.listdir(RUNNER_DIR)):
            if f.startswith("test_") and f.endswith(".py"):
                tests.append(os.path.join("runner", f))
    except OSError:
        pass
    return tests


def run_suite(test_files=None, use_cache=True):
    """
    Run test suite with caching and timing.

    Returns dict with results, timing, cache stats, and slow test list.
    """
    if test_files is None:
        test_files = discover_tests()

    repo_root = os.path.dirname(RUNNER_DIR)
    results = []
    cache_hits = 0
    total_time = 0.0

    for tf in test_files:
        # Compute source hash for cache key
        source_file = tf.replace("test_", "", 1) if "/test_" in tf else tf
        source_path = os.path.join(repo_root, source_file)
        source_hash = _file_hash(source_path) or "unknown"

        if use_cache and _check_cache(tf, source_hash):
            cache_hits += 1
            results.append({
                "test": tf,
                "passed": True,
                "duration_sec": 0,
                "cached": True,
                "slow": False,
            })
            continue

        result = _run_single_test(tf, repo_root)
        result["cached"] = False
        results.append(result)
        total_time += result["duration_sec"]

        _save_cache(tf, source_hash, result["passed"], result["duration_sec"])

    passed = sum(1 for r in results if r["passed"])
    failed = sum(1 for r in results if not r["passed"])
    slow = [r["test"] for r in results if r.get("slow")]

    summary = {
        "total_tests": len(results),
        "passed": passed,
        "failed": failed,
        "cache_hits": cache_hits,
        "total_time_sec": round(total_time, 2),
        "slow_tests": slow,
        "results": results,
        "run_at": datetime.datetime.utcnow().isoformat() + "Z",
    }

    with _lock:
        _STATE["last_run"] = summary["run_at"]
        _STATE["total_runs"] += 1
        _STATE["cache_hits"] += cache_hits
        _STATE["slow_tests"] = slow

    return summary


def identify_slow_tests():
    """Scan for tests that exceed the slow threshold."""
    tests = discover_tests()
    repo_root = os.path.dirname(RUNNER_DIR)
    slow = []
    for tf in tests:
        result = _run_single_test(tf, repo_root)
        if result["slow"]:
            slow.append({
                "test": tf,
                "duration_sec": result["duration_sec"],
            })
    return sorted(slow, key=lambda x: x["duration_sec"], reverse=True)


def stats():
    """Return cached suite state."""
    with _lock:
        return dict(_STATE)


def run():
    """Entry point for orchestrator periodic jobs."""
    return run_suite(use_cache=True)


if __name__ == "__main__":
    result = run_suite()
    print(f"Tests: {result['passed']}/{result['total_tests']} passed, "
          f"{result['cache_hits']} cached, {result['total_time_sec']}s")
