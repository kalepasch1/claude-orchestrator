#!/usr/bin/env python3
"""The continuous-testing pipeline must be able to report failure.

THE DEFECT
----------
`_detect_test_cmd` returned commands ending in `2>&1 || true`:

    "python -m pytest --tb=short -q 2>&1 || true"
    f"python -m pytest {test_dir} --tb=short -q 2>&1 || true"
    "python -m pytest tests/browser --tb=short -q 2>&1 || true"

`_run_cmd` derives `passed` from `returncode == 0`, so `|| true` made
`run_unit_tests()` and `run_browser_tests()` report ok=True for every Python project
regardless of how many tests failed. Continuous testing reported success
unconditionally — worse than not running, because it looks like coverage.

`2>&1` compounded it: folding stderr into stdout left the `note` field, which is built
from stderr, empty on failure. So there was nothing to diagnose from either.

This is the same class of bug as package.json's `"test": "... || true"`, fixed
separately; these three were hardcoded in Python and would have survived that fix.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import continuous_test as ct  # noqa: E402


# ── no detected command may swallow its exit code ───────────────────────────

@pytest.fixture()
def python_project(tmp_path, monkeypatch):
    monkeypatch.setattr(ct, "UNIT_TEST_CMD", "", raising=False)
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    return tmp_path


@pytest.fixture()
def runner_tests_project(tmp_path, monkeypatch):
    monkeypatch.setattr(ct, "UNIT_TEST_CMD", "", raising=False)
    (tmp_path / "runner" / "tests").mkdir(parents=True)
    return tmp_path


@pytest.mark.parametrize("swallow", ["|| true", "|| :", "; true", "exit 0"])
def test_a_pyproject_command_does_not_swallow_failure(python_project, swallow):
    assert swallow not in ct._detect_test_cmd(str(python_project))


@pytest.mark.parametrize("swallow", ["|| true", "|| :", "; true", "exit 0"])
def test_a_runner_tests_command_does_not_swallow_failure(runner_tests_project, swallow):
    assert swallow not in ct._detect_test_cmd(str(runner_tests_project))


def test_stderr_is_not_folded_into_stdout(python_project):
    """`2>&1` emptied the stderr-derived `note`, leaving failures undiagnosable."""
    assert "2>&1" not in ct._detect_test_cmd(str(python_project))


def test_a_pytest_command_is_still_detected(python_project):
    cmd = ct._detect_test_cmd(str(python_project))
    assert "pytest" in cmd


def test_an_explicit_override_still_wins(tmp_path, monkeypatch):
    monkeypatch.setattr(ct, "UNIT_TEST_CMD", "make test", raising=False)
    assert ct._detect_test_cmd(str(tmp_path)) == "make test"


def test_a_project_with_no_tests_yields_no_command(tmp_path, monkeypatch):
    monkeypatch.setattr(ct, "UNIT_TEST_CMD", "", raising=False)
    assert ct._detect_test_cmd(str(tmp_path)) == ""


# ── failure actually propagates ─────────────────────────────────────────────

def test_a_failing_unit_run_reports_not_ok(python_project, monkeypatch):
    """The whole point: a non-zero exit must surface as ok=False."""
    monkeypatch.setattr(ct, "_run_cmd", lambda *a, **k: {
        "returncode": 1, "stdout": "2 failed", "stderr": "boom", "passed": False})
    result = ct.run_unit_tests(str(python_project))
    assert result["ok"] is False
    assert result["failed"] == 1


def test_a_failing_unit_run_carries_a_diagnostic_note(python_project, monkeypatch):
    monkeypatch.setattr(ct, "_run_cmd", lambda *a, **k: {
        "returncode": 1, "stdout": "", "stderr": "ImportError: no module", "passed": False})
    assert "ImportError" in ct.run_unit_tests(str(python_project))["note"]


def test_a_passing_unit_run_reports_ok(python_project, monkeypatch):
    monkeypatch.setattr(ct, "_run_cmd", lambda *a, **k: {
        "returncode": 0, "stdout": "10 passed", "stderr": "", "passed": True})
    result = ct.run_unit_tests(str(python_project))
    assert result["ok"] is True and result["failed"] == 0


def test_a_project_with_no_test_command_is_not_reported_as_failing(tmp_path, monkeypatch):
    """Absence of tests is not a failure — it is a different thing, and says so."""
    monkeypatch.setattr(ct, "UNIT_TEST_CMD", "", raising=False)
    result = ct.run_unit_tests(str(tmp_path))
    assert result["ok"] is True
    assert "no test command" in result["note"]


# ── browser tests ───────────────────────────────────────────────────────────

def test_the_browser_command_does_not_swallow_failure(tmp_path, monkeypatch):
    captured = {}
    monkeypatch.setattr(ct, "BROWSER_TESTS_ENABLED", True, raising=False)
    monkeypatch.setattr(ct, "BROWSER_TEST_CMD", "", raising=False)

    def fake(cmd, cwd, timeout=None):
        captured["cmd"] = cmd
        return {"returncode": 0, "stdout": "", "stderr": "", "passed": True}

    monkeypatch.setattr(ct, "_run_cmd", fake)
    ct.run_browser_tests(str(tmp_path))
    assert "|| true" not in captured["cmd"]
    assert "2>&1" not in captured["cmd"]


def test_a_failing_browser_run_reports_not_ok(tmp_path, monkeypatch):
    monkeypatch.setattr(ct, "BROWSER_TESTS_ENABLED", True, raising=False)
    monkeypatch.setattr(ct, "BROWSER_TEST_CMD", "", raising=False)
    monkeypatch.setattr(ct, "_run_cmd", lambda *a, **k: {
        "returncode": 1, "stdout": "", "stderr": "selenium died", "passed": False})
    assert ct.run_browser_tests(str(tmp_path))["ok"] is False


def test_disabled_browser_tests_are_not_a_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(ct, "BROWSER_TESTS_ENABLED", False, raising=False)
    assert ct.run_browser_tests(str(tmp_path))["ok"] is True


# ── the combined suite ──────────────────────────────────────────────────────

def test_a_failing_unit_run_fails_the_whole_suite(python_project, monkeypatch):
    monkeypatch.setattr(ct, "run_unit_tests", lambda *a, **k: {"ok": False})
    monkeypatch.setattr(ct, "run_browser_tests", lambda *a, **k: {"ok": True})
    # The combined verdict is reported as `overall`, not `ok`.
    assert ct.run_suite(str(python_project))["overall"] is False


def test_a_failing_browser_run_also_fails_the_whole_suite(python_project, monkeypatch):
    monkeypatch.setattr(ct, "run_unit_tests", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(ct, "run_browser_tests", lambda *a, **k: {"ok": False})
    assert ct.run_suite(str(python_project))["overall"] is False


def test_an_all_green_suite_reports_overall_true(python_project, monkeypatch):
    monkeypatch.setattr(ct, "run_unit_tests", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(ct, "run_browser_tests", lambda *a, **k: {"ok": True})
    assert ct.run_suite(str(python_project))["overall"] is True


def test_run_suite_is_fail_soft(python_project, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("exploded")

    monkeypatch.setattr(ct, "run_unit_tests", boom)
    result = ct.run_suite(str(python_project))
    assert isinstance(result, dict)
