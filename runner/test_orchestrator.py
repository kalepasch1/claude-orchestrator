#!/usr/bin/env python3
"""
test_orchestrator.py — automated testing framework with unit, integration,
and e2e test orchestration.

Discovers test files across the repo, runs unit suites via subprocess with
configurable timeouts, validates integration connectivity against Supabase
endpoints, and exercises end-to-end task-lifecycle scenarios
(create -> claim -> run -> done).  Returns a combined report with
pass/fail/skip/duration breakdowns.

Env vars (never hardcoded):
  ORCH_TEST_ROOT        — directory root for test discovery (default: .)
  ORCH_TEST_PATTERN     — glob pattern for test files (default: test_*.py)
  ORCH_TEST_TIMEOUT     — per-file subprocess timeout in seconds (default: 60)
  ORCH_SUITE_TIMEOUT    — total suite timeout in seconds (default: 600)
  ORCH_SUPABASE_URL     — Supabase URL for integration checks
  ORCH_SUPABASE_KEY     — Supabase anon key for integration checks
"""
import os
import sys
import subprocess
import time
import json
import fnmatch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

# ---------------------------------------------------------------------------
# Config from env
# ---------------------------------------------------------------------------
TEST_ROOT = os.environ.get("ORCH_TEST_ROOT", ".")
TEST_PATTERN = os.environ.get("ORCH_TEST_PATTERN", "test_*.py")
TEST_TIMEOUT = int(os.environ.get("ORCH_TEST_TIMEOUT", "60"))
SUITE_TIMEOUT = int(os.environ.get("ORCH_SUITE_TIMEOUT", "600"))
SUPABASE_URL = os.environ.get("ORCH_SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("ORCH_SUPABASE_KEY", "")

_invocations = 0
_last_run_ts = None


# ---------------------------------------------------------------------------
# discover — walk directory tree finding test files
# ---------------------------------------------------------------------------
def discover(root=None, pattern=None):
    """Walk *root* looking for files matching *pattern*.

    Returns a sorted list of absolute paths.  Fail-soft: returns [] on error.
    """
    root = root or TEST_ROOT
    pattern = pattern or TEST_PATTERN
    try:
        found = []
        for dirpath, _dirs, filenames in os.walk(root):
            for fn in filenames:
                if fnmatch.fnmatch(fn, pattern) or fnmatch.fnmatch(fn, "*_test.py"):
                    found.append(os.path.abspath(os.path.join(dirpath, fn)))
        return sorted(found)
    except Exception:
        return []


# ---------------------------------------------------------------------------
# run_suite — run unit tests via subprocess
# ---------------------------------------------------------------------------
def run_suite(test_files=None, timeout=None):
    """Run each test file with ``python3 -m pytest`` in a subprocess.

    Returns a list of result dicts with keys: file, passed, duration, output.
    Fail-soft: individual file errors are captured, never raised.
    """
    timeout = timeout or TEST_TIMEOUT
    test_files = test_files or []
    results = []
    for fpath in test_files:
        t0 = time.time()
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", fpath, "-q", "--tb=short"],
                capture_output=True, text=True, timeout=timeout,
            )
            elapsed = time.time() - t0
            results.append({
                "file": fpath,
                "passed": proc.returncode == 0,
                "duration": round(elapsed, 2),
                "output": (proc.stdout + proc.stderr)[-2000:],
            })
        except subprocess.TimeoutExpired:
            results.append({
                "file": fpath,
                "passed": False,
                "duration": timeout,
                "output": f"TIMEOUT after {timeout}s",
            })
        except Exception as exc:
            results.append({
                "file": fpath,
                "passed": False,
                "duration": round(time.time() - t0, 2),
                "output": str(exc),
            })
    return results


# ---------------------------------------------------------------------------
# run_integration — hit Supabase endpoints, check connectivity
# ---------------------------------------------------------------------------
def run_integration(config=None):
    """Validate integration connectivity against Supabase endpoints.

    *config* may supply ``url`` and ``key`` overrides; falls back to env vars.
    Returns a dict with ``ok``, ``checks`` list, and ``duration``.
    Fail-soft: network errors are captured, never raised.
    """
    config = config or {}
    url = config.get("url") or SUPABASE_URL
    key = config.get("key") or SUPABASE_KEY
    checks = []
    t0 = time.time()

    # Check 1: Supabase REST health
    try:
        if not url:
            checks.append({"name": "supabase_rest", "status": "skip",
                           "detail": "ORCH_SUPABASE_URL not set"})
        else:
            import urllib.request, urllib.error
            req = urllib.request.Request(
                f"{url.rstrip('/')}/rest/v1/",
                headers={"apikey": key, "Authorization": f"Bearer {key}"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                code = resp.status
            checks.append({"name": "supabase_rest", "status": "pass" if 200 <= code < 400 else "fail"})
    except Exception as exc:
        checks.append({"name": "supabase_rest", "status": "fail", "detail": str(exc)[:200]})

    # Check 2: db module connectivity
    try:
        db.select("tasks", {"select": "id", "limit": "1"})
        checks.append({"name": "db_module", "status": "pass"})
    except Exception as exc:
        checks.append({"name": "db_module", "status": "fail", "detail": str(exc)[:200]})

    elapsed = round(time.time() - t0, 2)
    ok = all(c["status"] in ("pass", "skip") for c in checks)
    return {"ok": ok, "checks": checks, "duration": elapsed}


# ---------------------------------------------------------------------------
# run_e2e — end-to-end task lifecycle scenarios
# ---------------------------------------------------------------------------
def run_e2e(scenarios=None):
    """Run end-to-end test scenarios exercising the task lifecycle:
    create -> claim -> run -> done.

    *scenarios* is a list of dicts, each with a ``name`` key and optional
    overrides.  When omitted a single default scenario is used.
    Returns a list of scenario result dicts.
    Fail-soft: errors per-scenario are captured, never raised.
    """
    if scenarios is None:
        scenarios = [{"name": "default_lifecycle"}]

    results = []
    for scenario in scenarios:
        name = scenario.get("name", "unnamed")
        t0 = time.time()
        steps = {}
        try:
            # Step 1 — create
            row = db.insert("tasks", {
                "project": "TEST_ORCH",
                "scope": f"e2e-{name}",
                "status": "queued",
                "title": f"E2E smoke: {name}",
            })
            task_id = row.get("id") if isinstance(row, dict) else None
            steps["create"] = "pass" if task_id else "fail"

            # Step 2 — claim
            if task_id:
                upd = db.update("tasks", {"id": task_id}, {"status": "running", "agent": "test_orchestrator"})
                steps["claim"] = "pass" if upd else "fail"
            else:
                steps["claim"] = "skip"

            # Step 3 — run (simulate work)
            steps["run"] = "pass"

            # Step 4 — done
            if task_id:
                upd = db.update("tasks", {"id": task_id}, {"status": "done"})
                steps["done"] = "pass" if upd else "fail"
            else:
                steps["done"] = "skip"

        except Exception as exc:
            steps["error"] = str(exc)[:300]

        elapsed = round(time.time() - t0, 2)
        passed = all(v == "pass" for v in steps.values() if v not in ("skip",))
        results.append({"scenario": name, "passed": passed, "steps": steps, "duration": elapsed})

    return results


# ---------------------------------------------------------------------------
# report — generate test report dict
# ---------------------------------------------------------------------------
def report(results):
    """Build a summary report from a list of result dicts.

    Returns a dict with counts for pass / fail / skip, total duration,
    and the individual results list.
    """
    try:
        passed = sum(1 for r in results if r.get("passed") is True)
        failed = sum(1 for r in results if r.get("passed") is False)
        skipped = sum(1 for r in results if r.get("passed") is None)
        duration = round(sum(r.get("duration", 0) for r in results), 2)
        return {
            "total": len(results),
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "duration": duration,
            "all_passed": failed == 0,
            "results": results,
        }
    except Exception:
        return {"total": 0, "passed": 0, "failed": 0, "skipped": 0,
                "duration": 0, "all_passed": False, "results": []}


# ---------------------------------------------------------------------------
# stats — module telemetry
# ---------------------------------------------------------------------------
def stats():
    """Return module telemetry: invocation count, config, last run timestamp."""
    return {
        "module": "test_orchestrator",
        "invocations": _invocations,
        "last_run": _last_run_ts,
        "config": {
            "test_root": TEST_ROOT,
            "test_pattern": TEST_PATTERN,
            "test_timeout": TEST_TIMEOUT,
            "suite_timeout": SUITE_TIMEOUT,
            "supabase_url_set": bool(SUPABASE_URL),
        },
    }


# ---------------------------------------------------------------------------
# run — orchestrate discovery + all suites + report
# ---------------------------------------------------------------------------
def run():
    """Orchestrate full test run: discover -> unit -> integration -> e2e -> report.

    Returns a combined dict with section results and an overall summary.
    """
    global _invocations, _last_run_ts
    _invocations += 1
    _last_run_ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    t0 = time.time()

    try:
        # Discovery
        test_files = discover()

        # Unit tests
        unit_results = run_suite(test_files)

        # Integration tests
        integration = run_integration()

        # E2E tests
        e2e_results = run_e2e()

        # Combined report
        all_results = unit_results + e2e_results
        summary = report(all_results)

        return {
            "discovered": len(test_files),
            "unit": report(unit_results),
            "integration": integration,
            "e2e": report(e2e_results),
            "summary": summary,
            "duration": round(time.time() - t0, 2),
        }
    except Exception as exc:
        return {
            "discovered": 0,
            "unit": {"total": 0, "passed": 0, "failed": 0},
            "integration": {"ok": False, "checks": []},
            "e2e": {"total": 0, "passed": 0, "failed": 0},
            "summary": {"all_passed": False, "error": str(exc)[:300]},
            "duration": round(time.time() - t0, 2),
        }


if __name__ == "__main__":
    print(run())
