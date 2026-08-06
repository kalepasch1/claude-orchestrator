"""The scheduler must not stack a duplicate copy of a periodic job.

Incident of record: legal_docket.py accumulated 14 concurrent copies aged 8-10 hours
on a 30-minute interval. The cause was not one runaway job. _PERIODIC_PIDS is
in-process state and keepalive restarts runner.py routinely, so each fresh runner
started with an empty map, could not see the child its predecessor had left running,
and launched another one on top.

These tests pin the fix: the "already running?" answer must survive a runner restart.
"""
import importlib.util
import os
import subprocess
import sys
import time

import pytest

_RUNNER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _RUNNER_DIR)

# Load runner/runner.py by path: a bare `import runner` resolves to the runner
# PACKAGE, not the scheduler module.
_RUNNER_PY = os.path.join(_RUNNER_DIR, "runner.py")
_spec = importlib.util.spec_from_file_location("_runner_module_under_test", _RUNNER_PY)
R = importlib.util.module_from_spec(_spec)
sys.modules["_runner_module_under_test"] = R
_spec.loader.exec_module(R)


@pytest.fixture(autouse=True)
def _clean_pid_map():
    before = dict(R._PERIODIC_PIDS)
    R._PERIODIC_PIDS.clear()
    yield
    R._PERIODIC_PIDS.clear()
    R._PERIODIC_PIDS.update(before)


@pytest.fixture
def live_job(tmp_path):
    """A real process whose command line contains runner/<job>."""
    job = "fake_periodic_job.py"
    target = os.path.join(_RUNNER_DIR, job)
    p = subprocess.Popen([sys.executable, "-c",
                          f"import time,sys; sys.argv.append({target!r}); time.sleep(30)",
                          target])
    time.sleep(0.3)
    yield job, p
    p.kill()
    p.wait(timeout=5)


# --- in-process bookkeeping (pre-existing behaviour, must not regress) --------

def test_a_tracked_live_child_counts_as_running():
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        R._PERIODIC_PIDS["x.py"] = (p.pid, time.time())
        assert R._is_still_running("x.py") is True
    finally:
        p.kill()
        p.wait(timeout=5)


def test_a_tracked_dead_child_is_forgotten():
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait(timeout=10)
    R._PERIODIC_PIDS["x.py"] = (p.pid, time.time())
    R._is_still_running("x.py")
    assert "x.py" not in R._PERIODIC_PIDS


def test_no_record_and_no_process_means_not_running():
    assert R._is_still_running("definitely_not_a_real_job_xyz.py") is False


# --- the restart hole ---------------------------------------------------------

def test_an_orphan_from_a_previous_runner_is_detected(live_job):
    """The regression that produced 14 legal_docket.py copies."""
    job, _ = live_job
    assert R._PERIODIC_PIDS == {}, "simulates a freshly restarted runner"
    assert R._is_still_running(job) is True, (
        "a job left running by the previous runner must block a duplicate launch")


def test_the_orphan_is_adopted_so_the_reaper_can_lease_kill_it(live_job):
    job, p = live_job
    R._is_still_running(job)
    assert job in R._PERIODIC_PIDS
    assert R._PERIODIC_PIDS[job][0] == p.pid


def test_adoption_does_not_overwrite_an_existing_record(live_job):
    job, _ = live_job
    R._PERIODIC_PIDS[job] = (424242, 1.0)
    R._external_instance_running(job)
    assert R._PERIODIC_PIDS[job] == (424242, 1.0)


def test_our_own_pid_is_never_mistaken_for_an_orphan():
    assert R._external_instance_running("runner.py") is False, (
        "runner.py must not detect itself and refuse to schedule")


def test_a_different_job_name_does_not_match(live_job):
    job, _ = live_job
    assert R._external_instance_running("some_other_job.py") is False


def test_check_can_be_disabled_by_env(live_job, monkeypatch):
    job, _ = live_job
    monkeypatch.setenv("ORCH_SCHED_EXTERNAL_INSTANCE_CHECK", "false")
    assert R._external_instance_running(job) is False


def test_is_fail_soft_when_the_process_table_is_unreadable(monkeypatch):
    def _boom(*a, **k):
        raise OSError("pgrep unavailable")
    monkeypatch.setattr(R.subprocess, "run", _boom)
    assert R._external_instance_running("anything.py") is False, (
        "an unreadable process table must not permanently block a job")


# --- config sanity ------------------------------------------------------------

def test_job_max_runtime_is_defined_once():
    """A duplicated literal silently overwrote the first copy; they will diverge."""
    with open(_RUNNER_PY) as f:
        body = f.read()
    assert body.count("\n_JOB_MAX_RUNTIME = {") == 1


def test_legal_docket_is_scheduled_on_its_documented_interval():
    intervals = {job: args for (_k, job, stype, args) in R._SCHEDULE if stype == "interval"}
    assert intervals.get("legal_docket.py") == 1800
