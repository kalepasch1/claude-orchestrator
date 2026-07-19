"""Self-healing test infrastructure — quarantine flaky tests, auto-fix or mark."""
import sys, os, re, json, time, threading, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log as _log_mod
_log = _log_mod.get("flaky_test_healer")
try:
    import db
except Exception:
    db = None

ENABLED = os.environ.get("ORCH_FLAKY_TEST_HEALER_ENABLED", "true").lower() in ("true", "1", "yes")
FLAKE_THRESHOLD = float(os.environ.get("ORCH_FLAKE_THRESHOLD", "0.3"))
RERUN_COUNT = int(os.environ.get("ORCH_FLAKE_RERUN_COUNT", "5"))

_TEST_NAME_PAT = re.compile(r"(?:FAIL|FAILED|ERROR)\s+(\S+)")


class _FlakyTestHealer:
    def __init__(self):
        self._lock = threading.Lock()
        self._test_history = {}  # test_name -> {"pass": int, "fail": int, "last_fail_output": str}
        self._quarantined = set()
        self._stats = {"tests_tracked": 0, "quarantined": 0, "healed": 0,
                        "flake_rate_assessments": 0}

    def record_test_result(self, test_name, passed, output=""):
        """Record a test pass/fail for flake tracking."""
        if not ENABLED:
            return
        with self._lock:
            entry = self._test_history.setdefault(test_name, {"pass": 0, "fail": 0, "last_fail_output": ""})
            if passed:
                entry["pass"] += 1
            else:
                entry["fail"] += 1
                if output:
                    entry["last_fail_output"] = output[-500:]

    def extract_test_names(self, test_output):
        """Extract individual test names from test runner output."""
        names = set()
        for line in (test_output or "").splitlines():
            m = _TEST_NAME_PAT.search(line)
            if m:
                names.add(m.group(1))
        return list(names)

    def record_suite_result(self, test_output, all_passed):
        """Record results from a full test suite run."""
        if not ENABLED:
            return
        failed_tests = self.extract_test_names(test_output)
        for t in failed_tests:
            self.record_test_result(t, False, test_output)

    def flake_rate(self, test_name):
        """Compute flake rate for a test (0=always passes, 1=always fails)."""
        with self._lock:
            entry = self._test_history.get(test_name)
            if not entry:
                return 0.0
            total = entry["pass"] + entry["fail"]
            if total == 0:
                return 0.0
            fail_rate = entry["fail"] / total
            # A flaky test fails sometimes but not always
            if fail_rate > 0 and fail_rate < 1:
                return fail_rate
            return 0.0  # Always-fail or always-pass isn't flaky

    def assess_flakiness(self, repo_path, test_name, test_cmd):
        """Run a specific test multiple times to assess flake rate."""
        if not ENABLED:
            return {"flaky": False, "rate": 0, "runs": 0}
        passes, fails = 0, 0
        try:
            for _ in range(RERUN_COUNT):
                # Try to run just this test
                if "pytest" in test_cmd:
                    cmd = f"pytest {test_name} -x --tb=short 2>&1"
                elif "jest" in test_cmd:
                    cmd = f"jest --testNamePattern={test_name} 2>&1"
                else:
                    cmd = test_cmd
                r = subprocess.run(cmd, shell=True, cwd=repo_path,
                                   capture_output=True, text=True, timeout=60)
                if r.returncode == 0:
                    passes += 1
                else:
                    fails += 1
        except Exception:
            pass
        total = passes + fails
        rate = fails / total if total > 0 else 0
        flaky = 0 < rate < 1
        with self._lock:
            self._stats["flake_rate_assessments"] += 1
        return {"flaky": flaky, "rate": round(rate, 3), "runs": total,
                "passes": passes, "fails": fails}

    def quarantine(self, test_name, reason=""):
        """Mark a test as quarantined (should not block merges)."""
        with self._lock:
            self._quarantined.add(test_name)
            self._stats["quarantined"] += 1
        _log.info("quarantined flaky test: %s (%s)", test_name, reason)

    def is_quarantined(self, test_name):
        with self._lock:
            return test_name in self._quarantined

    def filter_flaky_failures(self, failed_tests):
        """Remove quarantined tests from a failure list. Returns (real_failures, flaky_failures)."""
        real = []
        flaky = []
        for t in (failed_tests or []):
            if self.is_quarantined(t):
                flaky.append(t)
            else:
                real.append(t)
        return real, flaky

    def should_block_merge(self, test_output):
        """Determine if test failures should block a merge (filters out known flaky tests)."""
        if not ENABLED:
            return True  # Default: all failures block
        failed = self.extract_test_names(test_output)
        if not failed:
            return False
        real, flaky = self.filter_flaky_failures(failed)
        return len(real) > 0  # Only block on real failures

    def heal(self, test_name):
        """Mark a test as healed (no longer flaky)."""
        with self._lock:
            self._quarantined.discard(test_name)
            self._stats["healed"] += 1

    def get_flaky_report(self):
        """Report on all tracked tests and their flake rates."""
        report = []
        with self._lock:
            for name, entry in self._test_history.items():
                total = entry["pass"] + entry["fail"]
                if total < 3:
                    continue
                rate = entry["fail"] / total
                if 0 < rate < 1:
                    report.append({
                        "test": name, "flake_rate": round(rate, 3),
                        "total_runs": total, "quarantined": name in self._quarantined
                    })
        report.sort(key=lambda x: x["flake_rate"], reverse=True)
        return report

    def stats(self):
        with self._lock:
            return dict(self._stats, enabled=ENABLED,
                        tests_tracked=len(self._test_history),
                        currently_quarantined=len(self._quarantined))


_healer = _FlakyTestHealer()

def record_test_result(test_name, passed, output=""):
    try: _healer.record_test_result(test_name, passed, output)
    except Exception: pass

def record_suite_result(test_output, all_passed=True):
    try: _healer.record_suite_result(test_output, all_passed)
    except Exception: pass

def extract_test_names(test_output):
    try: return _healer.extract_test_names(test_output)
    except Exception: return []

def flake_rate(test_name):
    try: return _healer.flake_rate(test_name)
    except Exception: return 0.0

def assess_flakiness(repo_path, test_name, test_cmd):
    try: return _healer.assess_flakiness(repo_path, test_name, test_cmd)
    except Exception: return {"flaky": False, "rate": 0, "runs": 0}

def quarantine(test_name, reason=""):
    try: _healer.quarantine(test_name, reason)
    except Exception: pass

def is_quarantined(test_name):
    try: return _healer.is_quarantined(test_name)
    except Exception: return False

def filter_flaky_failures(failed_tests):
    try: return _healer.filter_flaky_failures(failed_tests)
    except Exception: return (failed_tests or []), []

def should_block_merge(test_output):
    try: return _healer.should_block_merge(test_output)
    except Exception: return True

def heal(test_name):
    try: _healer.heal(test_name)
    except Exception: pass

def get_flaky_report():
    try: return _healer.get_flaky_report()
    except Exception: return []

def stats():
    try: return _healer.stats()
    except Exception: return {"enabled": False}
