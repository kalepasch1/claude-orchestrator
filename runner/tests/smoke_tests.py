#!/usr/bin/env python3
"""
smoke_tests.py — post-deploy smoke tests for preview environments.

Runs after preview deploy to verify:
1. API health check (GET / returns 200)
2. Database connectivity check (query succeeds)
3. Critical workflow smoke test (create entity, query it back)

Uses preview_env URLs from preview_env_manager.
"""
import json
import os
import sys
import time
import urllib.request
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

HOME = os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator"))
SMOKE_LOG = os.path.join(HOME, "smoke-results.json")


class SmokeResult:
    """Container for smoke test results."""
    def __init__(self, name, passed, detail=""):
        self.name = name
        self.passed = passed
        self.detail = detail

    def to_dict(self):
        return {"name": self.name, "passed": self.passed, "detail": self.detail}


def health_check(base_url):
    """API health check — GET / returns 200."""
    try:
        req = urllib.request.Request(base_url, method="GET")
        with urllib.request.urlopen(req, timeout=10) as r:
            return SmokeResult("health_check", r.status == 200,
                               f"status={r.status}")
    except urllib.error.HTTPError as e:
        return SmokeResult("health_check", False, f"HTTP {e.code}")
    except Exception as e:
        return SmokeResult("health_check", False, str(e))


def db_connectivity_check(env_vars):
    """Database connectivity — verify a query succeeds against preview DB."""
    db_url = env_vars.get("PREVIEW_DB_URL", "")
    db_ref = env_vars.get("PREVIEW_DB_REF", "")

    if not db_url and not db_ref:
        return SmokeResult("db_connectivity", False, "no DB configured")

    try:
        import db as runner_db
    except Exception as e:
        return SmokeResult("db_connectivity", False, f"db module unimportable: {e}")

    client = getattr(runner_db, "supabase", None)
    if not client:
        # Previously this returned passed=True with the detail "(logical)".
        # db_connectivity is one of the two CRITICAL checks — the ones whose
        # failure aborts a promote — so "no client at all" reporting as healthy
        # meant the abort could not fire for the case it exists to catch. A
        # check that cannot fail is not a check.
        return SmokeResult("db_connectivity", False,
                           f"db_ref={db_ref} no client configured")

    # Importing the module proves nothing about reachability; issue the
    # cheapest real round-trip the db module offers and let it raise.
    try:
        probe = getattr(runner_db, "select", None)
        if callable(probe):
            probe("tasks", {"select": "id", "limit": "1"})
            return SmokeResult("db_connectivity", True, f"db_ref={db_ref} query ok")
        return SmokeResult("db_connectivity", True, f"db_ref={db_ref} client present")
    except Exception as e:
        return SmokeResult("db_connectivity", False, f"db_ref={db_ref} query failed: {e}")


def workflow_smoke_test(base_url, env_vars):
    """Critical workflow — create an entity and query it back.

    The round-trip is deliberately local (a marker file under CLAUDE_ORCH_HOME):
    the preview environments this runs against expose no write endpoint, so
    there is nothing to POST to. What it therefore proves is narrow — the
    runner's data directory is writable and readable — and the detail string now
    says so instead of claiming a workflow was exercised end to end.

    It does still require `base_url`. Previously the parameter was accepted and
    never read, so this check passed for an environment with no deploy behind it
    at all, which is precisely the situation a post-deploy smoke test exists to
    notice.
    """
    task_id = env_vars.get("PREVIEW_TASK_ID", "smoke-test")

    if not base_url:
        return SmokeResult("workflow_smoke", False, "no preview URL to exercise")

    try:
        # Write a test marker to the preview env's data dir
        marker_dir = os.path.join(HOME, "smoke-markers")
        os.makedirs(marker_dir, exist_ok=True)
        marker_file = os.path.join(marker_dir, f"smoke-{task_id}.json")

        test_entity = {
            "id": f"smoke-{task_id}",
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "type": "smoke_test",
        }
        with open(marker_file, "w") as f:
            json.dump(test_entity, f)

        # Read it back
        with open(marker_file) as f:
            read_back = json.load(f)

        # Removed on BOTH paths. The mismatch branch used to leak its marker,
        # so a failing run left a stale smoke-<task_id>.json that the next run
        # for the same task would read back as its own and pass on.
        try:
            os.remove(marker_file)
        except OSError:
            pass

        if read_back.get("id") == test_entity["id"]:
            return SmokeResult("workflow_smoke", True,
                               "entity round-trip ok (runner data dir)")
        return SmokeResult("workflow_smoke", False, "entity mismatch on read-back")
    except Exception as e:
        return SmokeResult("workflow_smoke", False, str(e))


def run_smoke_suite(task_id):
    """Run full smoke suite for a preview environment.

    Returns dict with overall status and individual results.
    """
    import preview_env_manager

    env = preview_env_manager.get_preview_env(task_id)
    if not env:
        return {
            "task_id": str(task_id),
            "status": "abort",
            "detail": "no active preview env found",
            "results": [],
        }

    base_url = env.get("url", "")
    env_vars = env.get("env_vars", {})

    results = [
        health_check(base_url),
        db_connectivity_check(env_vars),
        workflow_smoke_test(base_url, env_vars),
    ]

    all_passed = all(r.passed for r in results)
    critical_failed = any(not r.passed for r in results
                          if r.name in ("health_check", "db_connectivity"))

    if critical_failed:
        status = "abort"
    elif all_passed:
        status = "pass"
    else:
        status = "fail"

    report = {
        "task_id": str(task_id),
        "status": status,
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "results": [r.to_dict() for r in results],
    }

    # Log result
    try:
        log = []
        if os.path.isfile(SMOKE_LOG):
            with open(SMOKE_LOG) as f:
                log = json.load(f)
        log.append(report)
        with open(SMOKE_LOG, "w") as f:
            json.dump(log, f, indent=2)
    except Exception:
        pass

    return report
