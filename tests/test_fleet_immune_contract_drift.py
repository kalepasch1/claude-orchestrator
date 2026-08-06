"""The live stopgap watchdog must agree with the fleet-immune contract.

Diagnosis (5) of the 2026-08-02 incident was a definition that lived in two places:
sentinel watched a file while the writer had moved to the DB, and the disagreement went
unnoticed for days. The same shape was already forming here — `runner/tools/lane_medic.sh`
presumed a coder lane dead at 100 minutes while `LANE_ZOMBIE_AFTER_S` says 60. These tests
pin the stopgap's thresholds to the contract so the two cannot silently diverge again.

The watchdog is a long-running `while true` loop, so it is not executed here. Instead the
threshold expressions are evaluated in an isolated shell, which is what actually has to
match — a comment claiming agreement is exactly the failure mode being guarded against.
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner"))

import fleet_immune_contracts as contracts  # noqa: E402

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MEDIC = os.path.join(_REPO_ROOT, "runner", "tools", "lane_medic.sh")

# The daemon whose leak the watchdog reaps; its schedule is fixed by launchd, not by us.
_DOCKET_INTERVAL_MIN = 30


def _medic_thresholds(env=None):
    """Evaluate the watchdog's threshold assignments and report their values.

    Sources only the assignment prologue (everything before the `while true` loop), so the
    real expressions are exercised without starting the watchdog.
    """
    with open(_MEDIC, encoding="utf-8") as handle:
        prologue = handle.read().split("while true", 1)[0]

    script = prologue + (
        '\nprintf "%s\\n%s\\n%s\\n" '
        '"$MAX_LANE_MIN" "$MAX_DOCKET_MIN" "$MAX_LANES_WARN"\n'
    )
    run_env = dict(os.environ)
    run_env.pop("ORCH_LANE_ZOMBIE_AFTER_S", None)
    run_env.pop("ORCH_LANE_COUNT_WARN", None)
    run_env.pop("ORCH_DAEMON_STUCK_INTERVAL_FACTOR", None)
    run_env.update(env or {})

    result = subprocess.run(
        ["bash", "-c", script],
        capture_output=True, text=True, timeout=30, env=run_env,
    )
    assert result.returncode == 0, f"lane_medic prologue failed: {result.stderr}"
    lane, docket, warn = result.stdout.split()
    return {"lane_min": int(lane), "docket_min": int(docket), "lanes_warn": int(warn)}


def test_watchdog_file_exists():
    assert os.path.isfile(_MEDIC), "the live stopgap watchdog is part of the contract surface"


def test_lane_age_matches_contract():
    """A lane the contract calls a zombie must be one the watchdog reaps."""
    assert _medic_thresholds()["lane_min"] * 60 == contracts.LANE_ZOMBIE_AFTER_S


def test_lane_count_warning_matches_contract():
    assert _medic_thresholds()["lanes_warn"] == contracts.LANE_COUNT_WARN


def test_docket_stuck_threshold_matches_contract():
    """Stuck means the daemon outlived its own interval by the contract's factor."""
    expected = int(_DOCKET_INTERVAL_MIN * contracts.DAEMON_STUCK_INTERVAL_FACTOR)
    assert _medic_thresholds()["docket_min"] == expected


def test_thresholds_follow_env_overrides():
    """Overriding the contract's env var must move the watchdog too, not just the classifier."""
    overridden = _medic_thresholds({
        "ORCH_LANE_ZOMBIE_AFTER_S": "7200",
        "ORCH_LANE_COUNT_WARN": "40",
        "ORCH_DAEMON_STUCK_INTERVAL_FACTOR": "2",
    })
    assert overridden["lane_min"] == 120
    assert overridden["lanes_warn"] == 40
    assert overridden["docket_min"] == 60


def test_watchdog_declares_no_threshold_of_its_own():
    """No bare numeric threshold literals: every one must come from the contract's env vars."""
    with open(_MEDIC, encoding="utf-8") as handle:
        prologue = handle.read().split("while true", 1)[0]

    for line in prologue.splitlines():
        stripped = line.strip()
        if not stripped.startswith(("MAX_LANE_MIN=", "MAX_LANES_WARN=", "MAX_DOCKET_MIN=")):
            continue
        assert "ORCH_" in stripped or "$" in stripped, (
            f"{stripped!r} hardcodes a threshold instead of reading the contract"
        )
