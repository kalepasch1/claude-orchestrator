"""A hung periodic job must be killed at its budget, not left holding the singleton lock.

Regression test for 'wedged-quarantine': JOBS['quarantine'] ran unbounded, held its flock for
2906s, and the three invocations behind it each printed "skipped" and exited 0 — so nothing
downstream ever noticed the job had stopped running.
"""
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import periodic  # noqa: E402


@pytest.fixture
def no_escalation(monkeypatch):
    """_escalate_timeout writes to the DB; keep the unit test offline but assert it fired."""
    calls = []
    monkeypatch.setattr(periodic, "_escalate_timeout",
                        lambda job, held, budget: calls.append((job, held, budget)))
    return calls


def test_hung_job_is_aborted_at_its_budget(monkeypatch, no_escalation):
    monkeypatch.setitem(periodic.JOBS, "hangs", lambda: time.sleep(30))
    monkeypatch.setenv("ORCH_PERIODIC_JOB_TIMEOUT_S__hangs", "1")

    started = time.time()
    outcome = periodic._invoke_job("hangs")
    elapsed = time.time() - started

    assert isinstance(outcome, periodic._TimedOut)
    assert outcome.job == "hangs"
    # The point of the fix: bounded by the budget, not by the job's own (30s) duration.
    assert elapsed < 10, f"job ran {elapsed:.1f}s despite a 1s budget"
    assert no_escalation, "a timeout must be escalated, not merely printed"


def test_timeout_releases_the_singleton_lock(monkeypatch, no_escalation, tmp_path):
    """The wedge was a *lock* problem: the next invocation must be able to run."""
    if periodic.fcntl is None:
        pytest.skip("no fcntl on this platform")
    monkeypatch.setattr(periodic, "_PERIODIC_LOCK_DIR", str(tmp_path))
    monkeypatch.setenv("ORCH_PERIODIC_JOB_TIMEOUT_S__hangs", "1")
    monkeypatch.setitem(periodic.JOBS, "hangs", lambda: time.sleep(30))

    assert isinstance(periodic._run_job_locked("hangs"), periodic._TimedOut)

    # Lock must be free now, so a healthy follow-up invocation actually runs.
    ran = []
    monkeypatch.setitem(periodic.JOBS, "hangs", lambda: ran.append(True) or "ok")
    assert periodic._run_job_locked("hangs") == "ok"
    assert ran == [True], "second invocation was skipped — the lock was never released"


def test_healthy_job_is_untouched(monkeypatch, no_escalation):
    monkeypatch.setitem(periodic.JOBS, "quick", lambda: {"created": 3})
    monkeypatch.setenv("ORCH_PERIODIC_JOB_TIMEOUT_S__quick", "30")

    assert periodic._invoke_job("quick") == {"created": 3}
    assert not no_escalation


def test_alarm_is_disarmed_after_a_healthy_run(monkeypatch, no_escalation):
    """A leaked alarm would fire into whatever ran next — worse than the original bug."""
    import signal

    monkeypatch.setitem(periodic.JOBS, "quick", lambda: "ok")
    monkeypatch.setenv("ORCH_PERIODIC_JOB_TIMEOUT_S__quick", "5")
    periodic._invoke_job("quick")

    remaining = signal.alarm(0)
    assert remaining == 0, f"alarm left armed with {remaining}s to run"
    assert signal.getsignal(signal.SIGALRM) in (signal.SIG_DFL, signal.SIG_IGN)


def test_timeout_can_be_disabled_per_job(monkeypatch, no_escalation):
    """<= 0 is the escape hatch for a genuinely long batch job."""
    monkeypatch.setitem(periodic.JOBS, "batch", lambda: "done")
    monkeypatch.setenv("ORCH_PERIODIC_JOB_TIMEOUT_S__batch", "0")

    assert periodic._job_timeout_s("batch") == 0
    assert periodic._invoke_job("batch") == "done"


def test_per_job_override_beats_the_global_budget(monkeypatch):
    monkeypatch.setattr(periodic, "_JOB_HARD_TIMEOUT_S", 3600)
    monkeypatch.setenv("ORCH_PERIODIC_JOB_TIMEOUT_S__quarantine", "300")

    assert periodic._job_timeout_s("quarantine") == 300
    assert periodic._job_timeout_s("other") == 3600


def test_garbage_override_falls_back_to_the_global_budget(monkeypatch):
    monkeypatch.setattr(periodic, "_JOB_HARD_TIMEOUT_S", 3600)
    monkeypatch.setenv("ORCH_PERIODIC_JOB_TIMEOUT_S__quarantine", "not-a-number")

    assert periodic._job_timeout_s("quarantine") == 3600


def test_timeout_is_a_noop_off_the_main_thread(no_escalation):
    """SIGALRM cannot be armed from a worker; the job must still run rather than crash."""
    import threading

    result = {}

    def worker():
        with periodic._hard_timeout(1, "threaded"):
            result["ran"] = True

    t = threading.Thread(target=worker)
    t.start()
    t.join(timeout=10)
    assert result.get("ran") is True
