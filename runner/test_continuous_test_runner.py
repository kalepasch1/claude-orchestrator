"""Tests for continuous_test_runner module."""
import os
import subprocess
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
import continuous_test_runner as ctr


# ---------------------------------------------------------------------------
# TestResult
# ---------------------------------------------------------------------------
class TestTestResult:
    def test_ok_when_zero_exit_and_no_failures(self):
        r = ctr.TestResult(suite="test", passed=5, exit_code=0)
        assert r.ok is True

    def test_not_ok_with_failures(self):
        r = ctr.TestResult(suite="test", passed=3, failed=2, exit_code=0)
        assert r.ok is False

    def test_not_ok_with_nonzero_exit(self):
        r = ctr.TestResult(suite="test", passed=5, exit_code=1)
        assert r.ok is False

    def test_to_dict(self):
        r = ctr.TestResult(suite="pytest", passed=10, failed=1, skipped=2,
                           duration_s=1.5, exit_code=1, output="out", error="err")
        d = r.to_dict()
        assert d["suite"] == "pytest"
        assert d["passed"] == 10
        assert d["failed"] == 1
        assert d["skipped"] == 2
        assert d["ok"] is False
        assert d["duration_s"] == 1.5

    def test_output_truncation(self):
        r = ctr.TestResult(output="x" * 5000)
        d = r.to_dict()
        assert len(d["output_tail"]) <= 2000


# ---------------------------------------------------------------------------
# _parse_test_counts
# ---------------------------------------------------------------------------
class TestParseTestCounts:
    def test_pytest_output(self):
        output = "===== 5 passed, 2 failed, 1 skipped in 3.21s ====="
        p, f, s = ctr._parse_test_counts(output)
        assert p == 5
        assert f == 2
        assert s == 1

    def test_jest_output(self):
        output = "Tests: 1 failed, 10 passed, 11 total\nTime: 4.5s"
        p, f, s = ctr._parse_test_counts(output)
        assert p == 10
        assert f == 1
        assert s == 0

    def test_no_counts(self):
        p, f, s = ctr._parse_test_counts("no test output here")
        assert p == 0 and f == 0 and s == 0

    def test_passed_only(self):
        p, f, s = ctr._parse_test_counts("12 passed in 1.0s")
        assert p == 12 and f == 0


# ---------------------------------------------------------------------------
# detect_changed_files
# ---------------------------------------------------------------------------
class TestDetectChangedFiles:
    def test_bad_repo(self):
        assert ctr.detect_changed_files("/nonexistent") == []

    def test_none_repo(self):
        assert ctr.detect_changed_files(None) == []

    def test_real_repo(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=str(repo), capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=str(repo), capture_output=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=str(repo), capture_output=True)
        (repo / "f.txt").write_text("init")
        subprocess.run(["git", "add", "."], cwd=str(repo), capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(repo), capture_output=True)
        subprocess.run(["git", "checkout", "-b", "feature"], cwd=str(repo), capture_output=True)
        (repo / "new.py").write_text("print('hi')")
        subprocess.run(["git", "add", "."], cwd=str(repo), capture_output=True)
        subprocess.run(["git", "commit", "-m", "add"], cwd=str(repo), capture_output=True)

        changed = ctr.detect_changed_files(str(repo), "master")
        assert "new.py" in changed


# ---------------------------------------------------------------------------
# run_test_command
# ---------------------------------------------------------------------------
class TestRunTestCommand:
    def test_passing_command(self):
        result = ctr.run_test_command("echo '3 passed in 0.1s'", timeout=10)
        assert result.ok is True
        assert result.exit_code == 0
        assert result.passed == 3

    def test_failing_command(self):
        result = ctr.run_test_command("exit 1", timeout=10)
        assert result.ok is False
        assert result.exit_code == 1

    def test_timeout(self):
        result = ctr.run_test_command("sleep 60", timeout=1)
        assert result.ok is False
        assert "Timed out" in result.error

    def test_with_env_override(self):
        result = ctr.run_test_command("echo $MY_VAR", timeout=10,
                                      env_override={"MY_VAR": "hello"})
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# aggregate_results
# ---------------------------------------------------------------------------
class TestAggregateResults:
    def test_all_passing(self):
        results = [
            {"passed": 5, "failed": 0, "skipped": 0, "duration_s": 1.0, "ok": True},
            {"passed": 3, "failed": 0, "skipped": 1, "duration_s": 0.5, "ok": True},
        ]
        agg = ctr.aggregate_results(results)
        assert agg["ok"] is True
        assert agg["total_passed"] == 8
        assert agg["total_skipped"] == 1
        assert agg["suite_count"] == 2

    def test_one_failing(self):
        results = [
            {"passed": 5, "failed": 0, "skipped": 0, "duration_s": 1.0, "ok": True},
            {"passed": 2, "failed": 1, "skipped": 0, "duration_s": 0.5, "ok": False},
        ]
        agg = ctr.aggregate_results(results)
        assert agg["ok"] is False
        assert agg["total_failed"] == 1

    def test_empty(self):
        agg = ctr.aggregate_results([])
        assert agg["ok"] is True
        assert agg["suite_count"] == 0


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------
class TestStats:
    def test_stats_dict(self):
        s = ctr.stats()
        assert isinstance(s, dict)

    def test_reset(self):
        ctr.reset_stats()
        assert all(v == 0 for v in ctr.stats().values())
