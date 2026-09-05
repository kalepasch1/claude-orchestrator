"""A self-deploy drain that cannot converge must not freeze the queue.

THE LIVE INCIDENT, 2026-09-02 13:08.

self_deploy requested a restart. The drain sets ORCH_DRAINING_FOR_RESTART, which freezes
new claims so the active lane count can fall to the threshold. Two things then combined:

  1. MAX_PARALLEL was 3, so the clamp above the drain computed
         _ceiling = _lane_cap // 4 = 3 // 4 = 0
     and the exit condition became "wait for TOTAL quiet".
  2. Three agent worker threads were alive and not finishing.

`active` never fell below 3, the threshold was 0, and nothing anywhere bounded the wait.
The runner printed

    [self-deploy] restart requested — draining lanes active=3 threshold=0

every 30 seconds for 39 minutes while 334 tasks sat QUEUED and every one of the eleven
projects reported 0 RUNNING:

    beethoven      112 queued, 0 running      tomorrow   110 queued, 0 running
    smarter         21 queued, 0 running      apparently-law  18 queued, 0 running
    ... 334 queued in total, 0 running anywhere

The drain is a courtesy -- keepalive restarts the runner and unfinished tasks are
re-claimed -- so it gets a deadline. Interrupting a hung thread costs one task's progress;
a restart that never happens costs the whole queue.
"""
import os
import re
import sys

import pytest

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RUNNER)


def _source():
    with open(os.path.join(RUNNER, "runner.py"), encoding="utf-8") as fh:
        return fh.read()


def _drain_block():
    """The whole self-deploy restart block, from the comment above it to the else branch.

    Anchored on both ends rather than a character count, so the tests below cannot pass or
    fail because the block grew.
    """
    src = _source()
    start = src.index("A DRAIN THAT CANNOT CONVERGE")
    end = src.index("No restart pending: forget any drain clock", start)
    return src[max(0, start - 2500):end]


def test_the_drain_has_a_deadline():
    """Without this the freeze is unbounded, which is what happened."""
    block = _drain_block()
    assert "ORCH_RESTART_DRAIN_MAX_S" in block, block[-900:]


def test_the_deadline_exits_even_when_lanes_are_still_alive():
    block = _drain_block()
    assert "did not converge" in block
    idx = block.index("did not converge")
    assert "sys.exit(0)" in block[idx:idx + 700], block[idx:idx + 700]


def test_the_deadline_defaults_to_something_finite():
    block = _drain_block()
    match = re.search(r'ORCH_RESTART_DRAIN_MAX_S", "(\d+)"', block)
    assert match, "no default for the drain budget"
    assert 0 < int(match.group(1)) <= 3600, match.group(1)


def test_the_drain_clock_starts_once_and_is_reset_when_no_restart_is_pending():
    src = _source()
    assert "_DRAIN_STARTED = {}" in src
    assert '_DRAIN_STARTED.pop("t", None)' in src, \
        "a finished drain must clear its clock or the next one inherits a stale start time"


def test_the_log_names_the_lanes_it_is_waiting_on():
    """39 minutes of 'active=3' never said WHICH three."""
    block = _drain_block()
    assert "waiting on:" in block
    assert "th.name for th in active" in block


def test_the_deadline_is_checked_before_the_claim_freeze():
    """Order matters: freezing first and checking later re-freezes on every pass."""
    block = _drain_block()
    give_up = block.index("did not converge")
    freeze = block.index('os.environ["ORCH_DRAINING_FOR_RESTART"] = "1"')
    assert give_up < freeze, "the deadline must be evaluated before claims are frozen again"


@pytest.mark.parametrize("lane_cap,expected_ceiling", [
    (3, 0), (4, 1), (8, 2), (12, 3),
])
def test_the_clamp_that_produced_a_zero_threshold(lane_cap, expected_ceiling):
    """Pins the arithmetic that made the threshold unreachable.

    This is NOT asserting the clamp is wrong -- a threshold of 0 is a legitimate "wait for
    quiet". It records that MAX_PARALLEL below 4 yields 0, so the deadline above is the
    only thing standing between a hung thread and a frozen fleet.
    """
    assert max(0, lane_cap // 4) == expected_ceiling


def test_deferring_a_restart_still_unfreezes_claims():
    """The pre-existing defer path had this right; the drain path is what lacked a bound."""
    src = _source()
    defer = src.index("deferring so")
    window = src[defer:defer + 600]
    assert 'os.environ.pop("ORCH_DRAINING_FOR_RESTART", None)' in window
