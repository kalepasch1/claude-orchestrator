"""The medic must reap parentless build/test processes, and only those.

Why this exists. On 2026-09-01 this Mac was carrying twelve orphaned build and test
processes, the oldest a `npm run dev:full` for the tomorrow project at 12h53m and
415% CPU, plus two `nuxt build`s inside _ARCHIVED-apparently-do-not-use — a project
that had been archived. The 1-minute load average was 59. Consequences, in order of
how much they cost:

  * every test verdict the merge train produced on that box is suspect, because a
    timing-sensitive suite at load 59 fails for reasons that have nothing to do with
    the diff being gated;
  * production_push_guard's load cool-down waits for load to fall under cores x 0.5
    and gives up after ORCH_QUIET_MAX_WAIT_S. At load 59 it could never settle, so
    every red suite it saw cost the full wait before a re-run that was just as
    contended; and
  * MERGE_TRAIN_TEST_TIMEOUT expiries look exactly like a red suite from the outside,
    and a timeout is NO verdict, not a failing one.

resource_medic.process_hygiene already reaped two orphan classes — multi-hour coding
agents and parentless llama-servers holding VRAM. Build and test processes, which are
what the gates actually spawn and by far the heaviest, were not among them.

The safety argument for killing by command pattern is entirely in the two constants,
so the tests below spend most of their attention there: ppid must be exactly 1, the
command must match a named build tool, and the runner's own long-lived processes are
excluded whatever else they match.
"""
import os
from unittest.mock import patch

import pytest

import resource_medic as rm


class _Out:
    def __init__(self, stdout=""):
        self.stdout = stdout
        self.stderr = ""
        self.returncode = 0


def _ps(rows):
    """Render (pid, ppid, etime, command) rows the way `ps -axo` does.

    `etime`, not `etimes`: BSD ps has no `etimes` column, and asking for one made
    both of the medic's reapers see an empty process table. See
    tests/test_ps_etime_parsing.py.
    """
    return _Out("\n".join(f"{p} {pp} {e} {c}" for p, pp, e, c in rows))


ORPHAN_NUXT = ("86289", "1", "12:53:07",
               "node /Users/k/Documents/tomorrow/node_modules/.bin/../nuxt/bin/nuxt.mjs dev --port 3005")
ORPHAN_BUILD = ("53072", "1", "01:20:14",
                "node /Users/k/Documents/_ARCHIVED-apparently/node_modules/.bin/nuxt build")
ORPHAN_PNPM = ("20149", "1", "04:58:24", "node /opt/homebrew/bin/pnpm run build:vercel")
ORPHAN_PYTEST = ("35316", "1", "05:33:20", "python3.14 -m pytest test_slice4.py")


def _procs(rows):
    return patch.object(rm, "sh", lambda *a, **k: _ps(rows))


def test_a_parentless_build_past_the_threshold_is_reaped():
    killed = []
    with patch.object(rm, "sh", lambda *a, **k: (
            killed.append(a) if a[:2] == ("kill", "-9") else None) or _ps([ORPHAN_NUXT])):
        with patch.object(rm, "journal", lambda *a, **k: None):
            n = rm.reap_orphaned_builds()
    assert n == 1
    assert ("kill", "-9", "86289") in killed


def test_a_build_that_still_has_a_parent_is_never_touched():
    """The whole justification is that nothing can read an orphan's exit status.

    A build with a live parent is a gate doing its job, however long it has run.
    """
    live = ("86289", "77267", "12:53:07",
            "node /Users/k/Documents/tomorrow/node_modules/.bin/nuxt build")
    with _procs([live]):
        assert rm._orphaned_build_procs() == []


def test_a_young_orphan_is_left_alone():
    """30 minutes, not 30 seconds: a gate can outlive its shell by a moment."""
    young = ("86289", "1", "01:00", "node node_modules/.bin/nuxt build")
    killed = []
    with patch.object(rm, "sh", lambda *a, **k: (
            killed.append(a) if a[:2] == ("kill", "-9") else None) or _ps([young])):
        with patch.object(rm, "journal", lambda *a, **k: None):
            assert rm.reap_orphaned_builds() == 0
    assert killed == []


@pytest.mark.parametrize("row", [ORPHAN_NUXT, ORPHAN_BUILD, ORPHAN_PNPM, ORPHAN_PYTEST])
def test_each_orphan_class_seen_on_the_box_is_recognised(row):
    """Regression pin: these four shapes were all present at load 59."""
    with _procs([row]):
        assert [p for _, p, _ in rm._orphaned_build_procs()] == [row[0]]


@pytest.mark.parametrize("cmd", [
    "python runner.py",
    "/bin/zsh /Users/k/Documents/beethoven/claude-orchestrator/runner/keepalive.sh",
    "python sentinel.py",
    "python merge_train.py",
    "python resource_medic.py",
])
def test_the_fleets_own_long_lived_processes_are_never_reaped(cmd):
    """The medic must not be able to kill the runner, or itself.

    keepalive.sh and runner.py are parentless by design under launchd, and runner.py
    spawns `npm test` subprocesses whose command lines it also logs, so a looser
    pattern here is a fleet-wide outage rather than a bug.
    """
    with _procs([("999", "1", "27:46:39", cmd)]):
        assert rm._orphaned_build_procs() == []


@pytest.mark.parametrize("cmd", [
    "node /Applications/SomeApp/server.js",
    "/usr/bin/ssh -N -L 3000:localhost:3000 host",
    "ollama serve",
    "node scripts/watch-assets.mjs",
])
def test_unrelated_parentless_processes_are_not_matched(cmd):
    """Killing by pattern is only safe if the pattern names build tools."""
    with _procs([("999", "1", "27:46:39", cmd)]):
        assert rm._orphaned_build_procs() == []


def test_the_reaper_can_be_switched_off():
    """An operator on a machine doing something unusual needs an off switch."""
    killed = []
    with patch.object(rm, "BUILD_ORPHAN_MAX_MIN", 0):
        with patch.object(rm, "sh", lambda *a, **k: (
                killed.append(a) if a[:2] == ("kill", "-9") else None) or _ps([ORPHAN_NUXT])):
            assert rm.reap_orphaned_builds() == 0
    assert killed == []


def test_oldest_first():
    """Ordering matters when a cap is added later; pin it now."""
    with _procs([ORPHAN_PNPM, ORPHAN_NUXT, ORPHAN_BUILD]):
        ages = [secs for secs, _, _ in rm._orphaned_build_procs()]
    assert ages == sorted(ages, reverse=True)


def test_a_ps_failure_does_not_raise():
    """Fail-soft is the module's contract: a medic bug must not take the fleet down."""
    def _boom(*a, **k):
        raise OSError("ps unavailable")
    with patch.object(rm, "sh", _boom):
        assert rm._orphaned_build_procs() == []


def test_process_hygiene_calls_the_reaper():
    """Structural: the function is worthless if nothing schedules it.

    _agent_procs and the llama-server sweep both live in process_hygiene, which the
    runner runs periodically. A reaper defined and never called is the shape of bug
    this repo already had once — generator_feedback.should_generate() existed with
    zero callers for weeks.
    """
    called = []
    with patch.object(rm, "reap_orphaned_builds", lambda: called.append(True) or 0):
        with patch.object(rm, "_agent_procs", lambda: []):
            with patch.object(rm, "sh", lambda *a, **k: _Out("")):
                with patch.object(rm, "journal", lambda *a, **k: None):
                    rm.process_hygiene()
    assert called == [True], "process_hygiene no longer reaps orphaned builds"
