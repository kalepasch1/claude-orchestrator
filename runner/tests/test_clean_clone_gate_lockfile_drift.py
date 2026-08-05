#!/usr/bin/env python3
"""Node-modules install repair: frozen-lockfile drift must not report a tree red.

`npm ci` / `--frozen-lockfile` / `--immutable` refuse to install when the lockfile has
drifted from package.json. That is a toolchain failure, not a broken tree — the gate
retries once with the non-frozen equivalent before failing.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import clean_clone_gate as ccg  # noqa: E402


# --- unfrozen_install_command ----------------------------------------------

@pytest.mark.parametrize("frozen,expected", [
    ("npm ci", "npm install"),
    ("npm ci --no-audit --no-fund", "npm install --no-audit --no-fund"),
    ("pnpm install --frozen-lockfile", "pnpm install"),
    ("yarn install --immutable", "yarn install"),
    ("  npm ci  ", "npm install"),
])
def test_unfrozen_install_command_maps_frozen_forms(frozen, expected):
    assert ccg.unfrozen_install_command(frozen) == expected


@pytest.mark.parametrize("cmd", [
    "npm install",
    "npm install --no-audit --no-fund",
    "pnpm install",
    "yarn install",
    "pip install -r requirements.txt",
    "",
    "   ",
])
def test_unfrozen_install_command_no_fallback_for_unfrozen(cmd):
    assert ccg.unfrozen_install_command(cmd) == ""


def test_unfrozen_install_command_is_fail_soft_on_none():
    assert ccg.unfrozen_install_command(None) == ""


def test_unfrozen_install_command_collapses_whitespace():
    assert ccg.unfrozen_install_command("pnpm install --frozen-lockfile --silent") == \
        "pnpm install --silent"


def test_unfrozen_install_command_is_idempotent():
    once = ccg.unfrozen_install_command("npm ci --no-audit")
    assert ccg.unfrozen_install_command(once) == ""


# --- _LOCKFILE_DRIFT --------------------------------------------------------

DRIFT_LOGS = [
    "npm ERR! `npm ci` can only install packages when your package.json and "
    "package-lock.json or npm-shrinkwrap.json are in sync.",
    "npm ERR! Missing: left-pad@1.3.0 from lock file",
    " ERR_PNPM_OUTDATED_LOCKFILE  Cannot install with \"frozen-lockfile\" because "
    "pnpm-lock.yaml is not up to date with package.json",
    "YN0028: The lockfile would have been modified by this install, which is "
    "explicitly forbidden.",
    "error Your lockfile needs to be updated, but yarn was run with --frozen-lockfile.",
]


@pytest.mark.parametrize("log", DRIFT_LOGS)
def test_lockfile_drift_detected(log):
    assert ccg._LOCKFILE_DRIFT.search(log)


NON_DRIFT_LOGS = [
    "npm ERR! code ENOTFOUND getaddrinfo registry.npmjs.org",
    "Error: Cannot find module './missing'",
    "SyntaxError: Unexpected token",
    "npm ERR! 404 Not Found - GET https://registry.npmjs.org/does-not-exist",
    "",
]


@pytest.mark.parametrize("log", NON_DRIFT_LOGS)
def test_non_drift_logs_not_flagged(log):
    assert not ccg._LOCKFILE_DRIFT.search(log)


def test_network_failure_is_not_treated_as_drift():
    """A registry outage must stay inconclusive, never trigger the unfrozen retry."""
    log = "npm ERR! network request to https://registry.npmjs.org/x failed, reason: ETIMEDOUT"
    assert ccg._NETWORK.search(log)
    assert not ccg._LOCKFILE_DRIFT.search(log)


# --- retry wiring -----------------------------------------------------------

def _fake_steps(sequence, calls):
    """Return a _step replacement yielding (rc, out) from `sequence`, recording commands."""
    def _step(cmd, cwd, timeout, env):
        calls.append(cmd)
        return sequence[len(calls) - 1]
    return _step


def test_drift_triggers_exactly_one_unfrozen_retry(monkeypatch):
    calls = []
    drift = (1, DRIFT_LOGS[0])
    monkeypatch.setattr(ccg, "_step", _fake_steps([drift, (0, "added 1 package")], calls))
    rc, out = ccg._step("npm ci", "/tmp", 10, {})
    assert rc == 1
    fallback = ccg.unfrozen_install_command("npm ci")
    assert fallback == "npm install"
    rc2, _ = ccg._step(fallback, "/tmp", 10, {})
    assert rc2 == 0
    assert calls == ["npm ci", "npm install"]


def test_retry_not_attempted_without_a_fallback():
    """Already-unfrozen commands have nothing to retry with."""
    assert ccg.unfrozen_install_command("npm install --no-audit --no-fund") == ""


def test_verify_is_disabled_cleanly(monkeypatch):
    """Sanity: the module still degrades gracefully when the gate is off."""
    monkeypatch.setattr(ccg, "ENABLED", False)
    out = ccg.verify("/nonexistent/repo")
    assert out["skipped"] == "disabled"
    assert out["ok"] is None


def test_verify_missing_repo_is_skipped_not_red(monkeypatch):
    monkeypatch.setattr(ccg, "ENABLED", True)
    out = ccg.verify("/nonexistent/repo/for/tests")
    assert out["ok"] is None
    assert out["skipped"] == "repo not on this machine"
