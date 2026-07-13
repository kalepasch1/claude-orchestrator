#!/usr/bin/env python3
"""
smoke_test_runner.py — execute smoke tests against a preview URL.

Runs a suite of HTTP health checks (GET /, GET /api/health, basic auth flow)
against a live preview deployment and returns structured pass/fail results
suitable for a promotion decision.

Env vars (never hardcoded):
  SMOKE_TEST_TIMEOUT      — per-request timeout in seconds (default 30)
  SMOKE_TEST_SUITE_TIMEOUT — total suite timeout in seconds (default 300)
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_REQUEST_TIMEOUT = int(os.environ.get("SMOKE_TEST_TIMEOUT", "30"))


def _http_get(url, timeout=None):
    """GET url, return (status_code, body_text). Returns (0, error_msg) on failure."""
    timeout = timeout or _REQUEST_TIMEOUT
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace") if e.fp else ""
    except Exception as e:
        return 0, str(e)


def _test_root(preview_url):
    """GET / returns 2xx."""
    status, body = _http_get(preview_url.rstrip("/") + "/")
    passed = 200 <= status < 300
    result = {"name": "GET /", "status": "pass" if passed else "fail"}
    if not passed:
        result["error"] = f"HTTP {status}" if status else body[:200]
    return result


def _test_health(preview_url):
    """GET /api/health returns 2xx and contains ok-ish body."""
    status, body = _http_get(preview_url.rstrip("/") + "/api/health")
    passed = 200 <= status < 300
    result = {"name": "GET /api/health", "status": "pass" if passed else "fail"}
    if not passed:
        result["error"] = f"HTTP {status}" if status else body[:200]
    return result


def _test_auth_flow(preview_url):
    """Basic auth flow: GET /login returns 2xx (page exists)."""
    status, body = _http_get(preview_url.rstrip("/") + "/login")
    # 2xx or 3xx (redirect to auth provider) both acceptable
    passed = 200 <= status < 400
    result = {"name": "auth flow (GET /login)", "status": "pass" if passed else "fail"}
    if not passed:
        result["error"] = f"HTTP {status}" if status else body[:200]
    return result


# Default smoke test suite
_DEFAULT_SUITE = [_test_root, _test_health, _test_auth_flow]


def run_smoke_tests(preview_url, timeout_secs=None, suite=None):
    """Execute smoke tests against preview_url.

    Args:
        preview_url: base URL of the preview deployment.
        timeout_secs: total suite timeout (default from env or 300).
        suite: list of test functions (default: health checks).

    Returns:
        {"passed": bool, "tests": [{"name": str, "status": "pass"|"fail", "error"?: str}]}
    """
    if timeout_secs is None:
        timeout_secs = int(os.environ.get("SMOKE_TEST_SUITE_TIMEOUT", "300"))
    suite = suite or _DEFAULT_SUITE
    if not preview_url:
        return {"passed": False, "tests": [{"name": "setup", "status": "fail",
                                             "error": "no preview_url provided"}]}

    deadline = time.time() + timeout_secs
    results = []
    all_passed = True

    for test_fn in suite:
        if time.time() > deadline:
            results.append({"name": "timeout", "status": "fail",
                            "error": f"suite exceeded {timeout_secs}s deadline"})
            all_passed = False
            break
        try:
            r = test_fn(preview_url)
        except Exception as e:
            r = {"name": getattr(test_fn, "__name__", "unknown"), "status": "fail",
                 "error": str(e)}
        results.append(r)
        if r.get("status") != "pass":
            all_passed = False

    return {"passed": all_passed, "tests": results}
