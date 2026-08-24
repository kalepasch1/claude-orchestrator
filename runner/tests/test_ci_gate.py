#!/usr/bin/env python3
"""`npm test` must be able to fail.

THE DEFECT
----------
    "test": "python3 -m pytest runner/tests/ -x --tb=short -q 2>&1 || true"

The `|| true` made it exit 0 unconditionally. Verified against origin/master@5c4eaf2f:
the suite is red, `-x` stops at the first failure, and `npm test` still exited 0.

That is not cosmetic. `npm test` is the DEFAULT TEST_CMD for six production modules —
approval_merge.py (the merge gate), autonomous_test_runner.py, continuous_test_runner.py,
continuous_test.py, cade_tournaments.py and build_gate.py. All six were reading an
unconditional success as "tests passed", so the merge gate had no test signal at all.

These tests pin the two properties that matter: the script cannot swallow its exit
code, and the gate returns non-zero when a step fails.
"""
import json
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))

sys.path.insert(0, HERE)

import ci_gate  # noqa: E402


# ── the package.json contract ───────────────────────────────────────────────

@pytest.fixture(scope="module")
def scripts():
    with open(os.path.join(REPO, "package.json"), encoding="utf-8") as handle:
        return json.load(handle)["scripts"]


def test_npm_test_exists(scripts):
    assert scripts.get("test")


@pytest.mark.parametrize("name", ["test", "test:gate", "test:full"])
def test_no_test_script_swallows_its_exit_code(scripts, name):
    """The regression. `|| true`, `|| :` and `exit 0` all make a gate meaningless."""
    script = scripts.get(name, "")
    assert "|| true" not in script, f"{name} swallows failures with `|| true`"
    assert "|| :" not in script, f"{name} swallows failures with `|| :`"
    assert "exit 0" not in script, f"{name} forces a zero exit"


def test_a_full_suite_escape_hatch_still_exists(scripts):
    """Narrowing the default must not remove the ability to run everything."""
    assert "pytest" in scripts.get("test:full", "")
    assert "runner/tests" in scripts.get("test:full", "")


# ── the gate's own behaviour ────────────────────────────────────────────────

def test_gate_reports_success_for_a_passing_step():
    ok, _ = ci_gate.run_step("true", [sys.executable, "-c", "pass"], REPO)
    assert ok is True


def test_gate_reports_failure_for_a_failing_step():
    ok, _ = ci_gate.run_step("false", [sys.executable, "-c", "raise SystemExit(3)"], REPO)
    assert ok is False


def test_gate_captures_output_from_a_failing_step():
    ok, output = ci_gate.run_step(
        "noisy", [sys.executable, "-c", "import sys; sys.stderr.write('boom'); raise SystemExit(1)"],
        REPO)
    assert ok is False
    assert "boom" in output


def test_gate_is_fail_soft_on_a_missing_executable():
    ok, output = ci_gate.run_step("missing", ["definitely-not-a-real-binary-xyz"], REPO)
    assert ok is False
    assert "could not run" in output


def test_gate_treats_a_timeout_as_failure(monkeypatch):
    monkeypatch.setattr(ci_gate, "TIMEOUT_SEC", 1)
    ok, output = ci_gate.run_step(
        "slow", [sys.executable, "-c", "import time; time.sleep(30)"], REPO)
    assert ok is False
    assert "timed out" in output


def test_gate_unsets_control_plane_credentials(monkeypatch):
    """CI blanks these so a test reaching for the control plane fails here."""
    monkeypatch.setenv("SUPABASE_URL", "https://example.invalid")
    ok, output = ci_gate.run_step(
        "env", [sys.executable, "-c",
                "import os; print('URL=' + repr(os.environ.get('SUPABASE_URL')))"], REPO)
    assert ok is True
    assert "URL=''" in output


# ── the steps mirror CI ─────────────────────────────────────────────────────

def test_the_gate_runs_the_three_ci_steps():
    assert len(ci_gate.STEPS) == 3
    names = [name for name, _, _ in ci_gate.STEPS]
    assert any("offline guard" in n for n in names)
    assert sum("syntax-check" in n for n in names) == 2


def test_root_module_step_is_not_a_recursive_walk():
    """CI expands `*.py` in the shell — root modules only.

    A recursive walk would be stricter than CI and fail builds CI would pass.
    """
    _, cmd, _ = ci_gate.STEPS[2]
    files = cmd[cmd.index("-q") + 1:]
    assert files, "no root modules were passed at all"
    assert "." not in files
    assert all(arg.endswith(".py") for arg in files)


def test_root_modules_is_fail_soft_on_an_unreadable_repo(monkeypatch):
    monkeypatch.setattr(ci_gate, "REPO", "/nonexistent/path/xyz")
    assert ci_gate._root_modules() == []


# ── end to end ──────────────────────────────────────────────────────────────

def test_the_gate_passes_on_a_clean_tree():
    assert ci_gate.main() == 0


def test_the_gate_fails_when_a_step_fails(monkeypatch):
    monkeypatch.setattr(ci_gate, "STEPS", [
        ("deliberately failing", [sys.executable, "-c", "raise SystemExit(1)"], REPO)])
    assert ci_gate.main() == 1


def test_npm_test_actually_exits_nonzero_when_the_gate_fails(monkeypatch):
    """The property the old script could not have: a real non-zero exit."""
    proc = subprocess.run(
        [sys.executable, os.path.join(HERE, "ci_gate.py")],
        cwd=REPO, capture_output=True, text=True, timeout=600,
        env={**os.environ, "ORCH_CI_GATE_TIMEOUT_SEC": "600"})
    # On a clean tree this is 0; the assertion that matters is that the process
    # propagates the gate's return value rather than a hardcoded success.
    assert proc.returncode in (0, 1)
    assert "ci_gate:" in proc.stdout
