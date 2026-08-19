"""Losing a git ref lock is not a divergence, and it must not cost a whole cycle.

Observed on mac-lan 2026-08-19, hours after self-deploy was taught to track origin. Every
180s pass did this:

    self_deploy: merged d29db799 cleanly as ef7617a3 but could not fast-forward the live
    tree onto it (in-flight work would be overwritten) - leaving it alone.
    fatal: update_ref failed for ref 'HEAD': cannot lock ref 'HEAD': Unable to create
    '.../.git/HEAD.lock': File exists.

The live tree is a SHARED workspace: the merge train, stash apply, auto_conflict_resolver
and every agent commit take .git/HEAD.lock continuously, so a single-shot
`git merge --ff-only` loses the race on a busy node. The node sat two commits behind origin
indefinitely while reporting a clean merge every cycle.

Two distinct defects:

  * no retry -- a lock that clears in seconds cost a full 180s cycle, every cycle;
  * the message asserted "in-flight work would be overwritten" for ANY fast-forward
    failure. That diagnosis is right for a dirty worktree and wrong for a lock, and the two
    call for opposite responses (investigate vs wait). It also filed a divergence APPROVAL
    CARD every pass, for a condition that resolves itself.

The distinction has to hold in both directions: a genuine non-fast-forward must still be
reported and carded, or this fix would replace a noisy failure with a silent one.
"""
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import self_deploy  # noqa: E402


LOCK_STDERR = (
    "fatal: update_ref failed for ref 'HEAD': cannot lock ref 'HEAD': Unable to create "
    "'/Users/kpasch/Documents/beethoven/claude-orchestrator/.git/HEAD.lock': File exists.\n"
    "\nAnother git process seems to be running in this repository, e.g.\n"
    "an editor opened by 'git commit'.")
DIRTY_STDERR = (
    "error: Your local changes to the following files would be overwritten by merge:\n"
    "\trunner/runner.py\nPlease commit your changes or stash them before you merge.")
NOT_FF_STDERR = "fatal: Not possible to fast-forward, aborting."


def _cp(returncode, stderr=""):
    return subprocess.CompletedProcess(args=["git"], returncode=returncode,
                                       stdout="", stderr=stderr)


@pytest.fixture(autouse=True)
def no_sleeping(monkeypatch):
    """Assert on the retry COUNT, not on wall-clock: 45s of real backoff in a unit test is
    the kind of thing that gets a whole file marked slow and then skipped."""
    slept = []
    monkeypatch.setattr(self_deploy.time, "sleep", lambda s: slept.append(s))
    monkeypatch.setattr(self_deploy, "FF_LOCK_RETRIES", 6)
    monkeypatch.setattr(self_deploy, "FF_LOCK_BACKOFF_S", 3.0)
    return slept


def _git_returning(*results):
    """Stub _git that yields the given CompletedProcesses in order, then repeats the last."""
    calls = []

    def fake(repo, args, timeout=None):
        calls.append(list(args))
        i = min(len(calls) - 1, len(results) - 1)
        return results[i]

    return fake, calls


# --- classification ---------------------------------------------------------------------

def test_a_head_lock_failure_is_recognised_as_contention():
    assert self_deploy._is_lock_contention(_cp(128, LOCK_STDERR))


def test_an_index_lock_failure_is_recognised_too():
    assert self_deploy._is_lock_contention(
        _cp(128, "fatal: Unable to create '/repo/.git/index.lock': File exists."))


def test_a_dirty_worktree_is_not_contention():
    """This one really IS 'in-flight work would be overwritten' — the old message's case."""
    assert not self_deploy._is_lock_contention(_cp(1, DIRTY_STDERR))


def test_a_genuine_non_fast_forward_is_not_contention():
    assert not self_deploy._is_lock_contention(_cp(128, NOT_FF_STDERR))


def test_a_missing_result_is_not_contention():
    """_git returns None when it could not run at all; that is not a lock we can wait out."""
    assert not self_deploy._is_lock_contention(None)


# --- retry ------------------------------------------------------------------------------

def test_it_retries_while_the_lock_is_held(monkeypatch, no_sleeping):
    fake, calls = _git_returning(_cp(128, LOCK_STDERR))
    monkeypatch.setattr(self_deploy, "_git", fake)

    ok, contended, _why = self_deploy._fast_forward("/repo", "abc123")

    assert (ok, contended) == (False, True)
    assert len(calls) == 6, f"gave up after {len(calls)} attempts"
    assert no_sleeping == [3.0, 6.0, 9.0, 12.0, 15.0], \
        "backoff must grow, and must not sleep after the final attempt"


def test_a_lock_that_clears_mid_retry_succeeds(monkeypatch):
    fake, calls = _git_returning(_cp(128, LOCK_STDERR), _cp(128, LOCK_STDERR), _cp(0))
    monkeypatch.setattr(self_deploy, "_git", fake)

    ok, contended, _why = self_deploy._fast_forward("/repo", "abc123")

    assert (ok, contended) == (True, False)
    assert len(calls) == 3, "must stop the moment it wins the lock"


def test_a_non_lock_failure_is_not_retried(monkeypatch):
    """Retrying a genuine non-fast-forward six times just delays the report by 45s."""
    fake, calls = _git_returning(_cp(128, NOT_FF_STDERR))
    monkeypatch.setattr(self_deploy, "_git", fake)

    ok, contended, why = self_deploy._fast_forward("/repo", "abc123")

    assert (ok, contended) == (False, False)
    assert len(calls) == 1
    assert "fast-forward" in why


def test_success_on_the_first_try_costs_nothing(monkeypatch, no_sleeping):
    fake, calls = _git_returning(_cp(0))
    monkeypatch.setattr(self_deploy, "_git", fake)

    assert self_deploy._fast_forward("/repo", "abc123")[0] is True
    assert len(calls) == 1 and no_sleeping == []


def test_the_retry_count_is_configurable(monkeypatch):
    monkeypatch.setattr(self_deploy, "FF_LOCK_RETRIES", 2)
    fake, calls = _git_returning(_cp(128, LOCK_STDERR))
    monkeypatch.setattr(self_deploy, "_git", fake)

    self_deploy._fast_forward("/repo", "abc123")

    assert len(calls) == 2


def test_zero_retries_still_makes_one_attempt(monkeypatch):
    """A misconfigured 0 must not silently disable self-deploy's fast-forward entirely."""
    monkeypatch.setattr(self_deploy, "FF_LOCK_RETRIES", 0)
    fake, calls = _git_returning(_cp(0))
    monkeypatch.setattr(self_deploy, "_git", fake)

    assert self_deploy._fast_forward("/repo", "abc123")[0] is True
    assert len(calls) == 1


# --- reporting --------------------------------------------------------------------------

@pytest.fixture
def reconcilable(monkeypatch):
    """Drive reconcile_origin to the point where it fast-forwards onto a scratch merge."""
    cards = []
    monkeypatch.setattr(self_deploy, "TRACK_ORIGIN", True)
    monkeypatch.setattr(self_deploy, "_git_ok", lambda *a, **k: True)
    monkeypatch.setattr(self_deploy, "_remote_head", lambda repo: "r" * 40)
    monkeypatch.setattr(self_deploy, "current_commit", lambda repo: "h" * 40)
    monkeypatch.setattr(self_deploy, "_is_ancestor",
                        lambda repo, a, b: False)          # genuinely diverged, so it merges
    monkeypatch.setattr(self_deploy, "merge_in_scratch", lambda *a, **k: ("m" * 40, ""))
    monkeypatch.setattr(self_deploy, "_file_divergence_card",
                        lambda *a, **k: cards.append(a))
    monkeypatch.setattr(self_deploy, "_git",
                        lambda repo, args, timeout=None:
                        _cp(0, "") if args[0] in ("rev-list", "merge-tree") else _cp(0))
    return cards


def test_contention_is_reported_as_its_own_action(monkeypatch, reconcilable, no_sleeping):
    monkeypatch.setattr(self_deploy, "_fast_forward",
                        lambda repo, target: (False, True, LOCK_STDERR))

    result = self_deploy.reconcile_origin("/repo")

    assert result["action"] == "fast_forward_lock_contended", \
        "a lock and a divergence must not share an action string — monitors cannot tell " \
        "a self-clearing condition from one needing a human"
    assert result["ok"] is False


def test_contention_does_not_file_a_divergence_card(monkeypatch, reconcilable, no_sleeping):
    """It filed one every 180s, for hours, for a condition that resolves itself."""
    monkeypatch.setattr(self_deploy, "_fast_forward",
                        lambda repo, target: (False, True, LOCK_STDERR))

    self_deploy.reconcile_origin("/repo")

    assert reconcilable == [], "carded a transient lock as a divergence needing review"


def test_contention_does_not_claim_in_flight_work_would_be_overwritten(
        monkeypatch, reconcilable, no_sleeping, capsys):
    monkeypatch.setattr(self_deploy, "_fast_forward",
                        lambda repo, target: (False, True, LOCK_STDERR))

    self_deploy.reconcile_origin("/repo")

    out = capsys.readouterr().out
    assert "in-flight work would be" not in out, \
        "the old message sent an operator hunting a conflict that does not exist"
    assert "lock" in out and "retrying next cycle" in out


def test_a_real_divergence_is_still_reported_and_carded(
        monkeypatch, reconcilable, no_sleeping, capsys):
    """The fix must not turn a noisy real failure into a silent one."""
    monkeypatch.setattr(self_deploy, "_fast_forward",
                        lambda repo, target: (False, False, DIRTY_STDERR))

    result = self_deploy.reconcile_origin("/repo")

    assert result["action"] == "fast_forward_failed"
    assert len(reconcilable) == 1, "a genuine divergence must still raise a card"
    assert "in-flight work would be" in capsys.readouterr().out


def test_a_successful_fast_forward_still_reports_merged(
        monkeypatch, reconcilable, no_sleeping):
    monkeypatch.setattr(self_deploy, "_fast_forward", lambda repo, target: (True, False, ""))

    result = self_deploy.reconcile_origin("/repo")

    assert result["action"] == "merged" and result["ok"] is True
    assert reconcilable == []
