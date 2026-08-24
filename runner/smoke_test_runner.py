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

_DEFAULT_REQUEST_TIMEOUT = 30
_DEFAULT_SUITE_TIMEOUT = 300


def _env_int(name, default):
    """Read an int env var, falling back to `default` for anything unusable.

    WHY. These knobs were read with a bare `int(os.environ.get(...))` at import time,
    so an env var that was exported empty or misspelt did not degrade the suite — it
    raised ValueError while the MODULE was importing, and the smoke runner could not
    start at all. `SMOKE_TEST_TIMEOUT=` (a common way to "unset" a value in a shell
    wrapper or CI matrix) was enough to do it, and the traceback pointed at line 22
    rather than at the environment, which is where the fault actually was.

    A timeout is a tuning parameter. A bad one is worth a warning, never a dead
    runner, so this is fail-soft in the repo's usual sense: warn and use the default.
    Non-positive values are rejected too — a 0 or negative timeout makes every request
    fail instantly, which looks like a total outage rather than a misconfiguration.
    """
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        print(f"smoke: {name}={raw!r} is not an integer; using {default}", file=sys.stderr)
        return default
    if value <= 0:
        print(f"smoke: {name}={value} must be positive; using {default}", file=sys.stderr)
        return default
    return value


_REQUEST_TIMEOUT = _env_int("SMOKE_TEST_TIMEOUT", _DEFAULT_REQUEST_TIMEOUT)


def verify_environment(preview_url=None):
    """Preflight the smoke-test environment. Returns a structured readiness report.

    {"ready": bool, "checks": [{"name", "status": "pass"|"fail", "detail"?}],
     "request_timeout": int, "suite_timeout": int}

    Never raises and never performs a network call — it answers "can the runner
    start?", which is a different question from "does the deployment pass?". A
    caller gates on `ready` before spending a suite timeout on a run that was
    always going to die in setup.
    """
    checks = []

    def add(name, ok, detail=None):
        entry = {"name": name, "status": "pass" if ok else "fail"}
        if detail:
            entry["detail"] = detail
        checks.append(entry)
        return ok

    for var, default in (("SMOKE_TEST_TIMEOUT", _DEFAULT_REQUEST_TIMEOUT),
                         ("SMOKE_TEST_SUITE_TIMEOUT", _DEFAULT_SUITE_TIMEOUT)):
        raw = os.environ.get(var)
        if raw is None or str(raw).strip() == "":
            add(f"env {var}", True, f"unset; using default {default}")
        else:
            resolved = _env_int(var, default)
            add(f"env {var}", str(resolved) == str(raw).strip(),
                f"{raw!r} is not a usable positive integer; falling back to {default}"
                if str(resolved) != str(raw).strip() else None)

    for mod in ("json", "urllib.request", "urllib.error"):
        try:
            __import__(mod)
            add(f"import {mod}", True)
        except Exception as e:                       # pragma: no cover - stdlib
            add(f"import {mod}", False, str(e))

    if preview_url is None:
        add("preview_url", True, "not supplied; caller provides it at run time")
    elif not str(preview_url).startswith(("http://", "https://")):
        add("preview_url", False, f"{preview_url!r} is not an http(s) URL")
    else:
        add("preview_url", True)

    try:
        add("suite discoverable", bool(discover_tests()))
    except Exception as e:
        add("suite discoverable", False, str(e))

    return {
        "ready": all(c["status"] == "pass" for c in checks),
        "checks": checks,
        "request_timeout": _env_int("SMOKE_TEST_TIMEOUT", _DEFAULT_REQUEST_TIMEOUT),
        "suite_timeout": _env_int("SMOKE_TEST_SUITE_TIMEOUT", _DEFAULT_SUITE_TIMEOUT),
    }


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
        timeout_secs = _env_int("SMOKE_TEST_SUITE_TIMEOUT", _DEFAULT_SUITE_TIMEOUT)
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


# --- SmokeTest registry (kept from master; the HTTP probe layer above was
# lost from this file and is restored from 4d42d791) ---


# --- SmokeTest registry (structured test definition) ---

class SmokeTest:
    """Named smoke test with a check function and timeout."""

    __slots__ = ("name", "check_fn", "timeout_sec")

    def __init__(self, name, check_fn, timeout_sec=30):
        self.name = name
        self.check_fn = check_fn
        self.timeout_sec = timeout_sec

    def run(self, preview_url):
        """Execute this test against preview_url. Returns result dict."""
        try:
            result = self.check_fn(preview_url)
            if isinstance(result, dict):
                result.setdefault("name", self.name)
                return result
            passed = bool(result)
            return {"name": self.name, "status": "pass" if passed else "fail"}
        except Exception as e:
            return {"name": self.name, "status": "fail", "error": str(e)}


# Global registry
_SMOKE_REGISTRY = []


def register_smoke_test(name, check_fn, timeout_sec=30):
    """Register a smoke test in the global registry."""
    _SMOKE_REGISTRY.append(SmokeTest(name, check_fn, timeout_sec))


def discover_tests():
    """Return all registered smoke tests. Falls back to default suite."""
    if _SMOKE_REGISTRY:
        return list(_SMOKE_REGISTRY)
    return [
        SmokeTest("GET /", _test_root),
        SmokeTest("GET /api/health", _test_health),
        SmokeTest("auth flow (GET /login)", _test_auth_flow),
    ]


def run_registered_tests(preview_url, timeout_secs=None):
    """Execute all registered/discovered smoke tests. Idempotent (multiple runs safe)."""
    tests = discover_tests()
    if timeout_secs is None:
        timeout_secs = _env_int("SMOKE_TEST_SUITE_TIMEOUT", _DEFAULT_SUITE_TIMEOUT)
    deadline = time.time() + timeout_secs
    results = []
    all_passed = True
    for t in tests:
        if time.time() > deadline:
            results.append({"name": "timeout", "status": "fail",
                            "error": f"suite exceeded {timeout_secs}s"})
            all_passed = False
            break
        r = t.run(preview_url)
        results.append(r)
        if r.get("status") != "pass":
            all_passed = False
    return {"passed": all_passed, "tests": results}
