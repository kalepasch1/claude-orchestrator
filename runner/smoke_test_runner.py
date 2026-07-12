

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
        timeout_secs = int(os.environ.get("SMOKE_TEST_SUITE_TIMEOUT", "300"))
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
