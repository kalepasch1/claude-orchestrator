"""Tests for test_automation module."""
import os
import sys
import types

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Provide a stub db module before importing
if "db" not in sys.modules:
    _db = types.ModuleType("db")
    _db.client = None
    sys.modules["db"] = _db

import test_automation as ta


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_counters():
    """Reset module-level counters between tests."""
    ta._invocations = 0
    ta._errors = 0
    ta._suites_run = 0
    yield


@pytest.fixture
def tmp_test_dir(tmp_path):
    """Create a temporary directory with fake test files."""
    for name in ["test_alpha.py", "test_beta.py", "helper.py"]:
        (tmp_path / name).write_text(f"# {name}\n")
    return str(tmp_path)


# ---------------------------------------------------------------------------
# Test discovery
# ---------------------------------------------------------------------------

class TestDiscoverTests:
    def test_discovers_test_files(self, tmp_test_dir):
        found = ta.discover_tests(tmp_test_dir)
        basenames = [os.path.basename(f) for f in found]
        assert "test_alpha.py" in basenames
        assert "test_beta.py" in basenames
        assert "helper.py" not in basenames

    def test_returns_sorted(self, tmp_test_dir):
        found = ta.discover_tests(tmp_test_dir)
        assert found == sorted(found)

    def test_empty_dir(self, tmp_path):
        found = ta.discover_tests(str(tmp_path))
        assert found == []

    def test_nonexistent_dir(self):
        found = ta.discover_tests("/nonexistent/path/xyz")
        assert found == []


# ---------------------------------------------------------------------------
# Suite execution (mock subprocess)
# ---------------------------------------------------------------------------

class TestRunTestSuite:
    def test_run_suite_with_mock(self, tmp_test_dir, monkeypatch):
        """Mock subprocess.run to simulate a passing pytest run."""
        import subprocess as sp
        fake_stdout = "2 passed in 0.05s\n"
        fake = type("R", (), {
            "returncode": 0, "stdout": fake_stdout, "stderr": "",
        })()
        monkeypatch.setattr(sp, "run", lambda *a, **kw: fake)
        result = ta.run_test_suite(tmp_test_dir)
        assert result["passed"] == 2
        assert result["failed"] == 0
        assert result["total"] == 2
        assert result["exit_code"] == 0
        assert len(result["files"]) == 2

    def test_run_suite_with_pattern(self, tmp_test_dir, monkeypatch):
        import subprocess as sp
        fake = type("R", (), {
            "returncode": 0, "stdout": "1 passed\n", "stderr": "",
        })()
        monkeypatch.setattr(sp, "run", lambda *a, **kw: fake)
        result = ta.run_test_suite(tmp_test_dir, pattern="alpha")
        assert len(result["files"]) == 1
        assert "alpha" in result["files"][0]

    def test_run_suite_no_matches(self, tmp_path):
        result = ta.run_test_suite(str(tmp_path), pattern="zzz_nonexistent")
        assert result["total"] == 0
        assert result["files"] == []

    def test_run_suite_timeout(self, tmp_test_dir, monkeypatch):
        import subprocess as sp
        def timeout_run(*a, **kw):
            raise sp.TimeoutExpired(cmd="pytest", timeout=5)
        monkeypatch.setattr(sp, "run", timeout_run)
        result = ta.run_test_suite(tmp_test_dir)
        assert result["exit_code"] == -1
        assert "timed out" in result["error"]


# ---------------------------------------------------------------------------
# Affected test detection
# ---------------------------------------------------------------------------

class TestAffectedTests:
    def test_source_to_test_mapping(self):
        changed = ["runner/foo.py", "runner/bar.py"]
        affected = ta._affected_tests(changed)
        assert "runner/tests/test_foo.py" in affected
        assert "runner/tests/test_bar.py" in affected

    def test_test_file_included_directly(self):
        changed = ["runner/tests/test_widget.py"]
        affected = ta._affected_tests(changed)
        assert "runner/tests/test_widget.py" in affected

    def test_non_python_ignored(self):
        changed = ["runner/README.md", "runner/config.json"]
        affected = ta._affected_tests(changed)
        assert affected == []

    def test_run_on_merge_request_no_files(self, monkeypatch):
        result = ta.run_on_merge_request([])
        assert result["total"] == 0


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

class TestGenerateReport:
    def test_passing_report(self):
        results = {"passed": 5, "failed": 0, "skipped": 1, "total": 6,
                    "duration_s": 1.23, "error": ""}
        report = ta.generate_report(results)
        assert "PASS" in report
        assert "5" in report
        assert "1.23" in report

    def test_failing_report(self):
        results = {"passed": 3, "failed": 2, "skipped": 0, "total": 5,
                    "duration_s": 2.50, "error": ""}
        report = ta.generate_report(results)
        assert "FAIL" in report
        assert "2" in report

    def test_empty_report(self):
        results = {"passed": 0, "failed": 0, "skipped": 0, "total": 0,
                    "duration_s": 0.0, "error": ""}
        report = ta.generate_report(results)
        assert "NO TESTS" in report

    def test_invalid_input(self):
        report = ta.generate_report("not a dict")
        assert "Invalid" in report

    def test_report_includes_error(self):
        results = {"passed": 0, "failed": 1, "skipped": 0, "total": 1,
                    "duration_s": 0.5, "error": "ImportError: no module"}
        report = ta.generate_report(results)
        assert "ImportError" in report


# ---------------------------------------------------------------------------
# Feature flag behavior
# ---------------------------------------------------------------------------

class TestFeatureFlag:
    def test_disabled_discover(self, monkeypatch):
        monkeypatch.setattr(ta, "ENABLED", False)
        result = ta.discover_tests()
        assert result == []

    def test_disabled_run_suite(self, monkeypatch):
        monkeypatch.setattr(ta, "ENABLED", False)
        result = ta.run_test_suite()
        assert result["total"] == 0

    def test_disabled_merge_request(self, monkeypatch):
        monkeypatch.setattr(ta, "ENABLED", False)
        result = ta.run_on_merge_request(["runner/foo.py"])
        assert result["total"] == 0


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

class TestStats:
    def test_stats_shape(self):
        s = ta.stats()
        assert "enabled" in s
        assert "invocations" in s
        assert "errors" in s
        assert "suites_run" in s

    def test_stats_tracks_invocations(self, tmp_test_dir):
        ta.discover_tests(tmp_test_dir)
        s = ta.stats()
        assert s["invocations"] >= 1


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:
    def test_subprocess_exception(self, tmp_test_dir, monkeypatch):
        import subprocess as sp
        def explode(*a, **kw):
            raise RuntimeError("boom")
        monkeypatch.setattr(sp, "run", explode)
        result = ta.run_test_suite(tmp_test_dir)
        assert "boom" in result["error"]
        assert ta._errors >= 1
