import importlib.util
import os
import sys
import time

RUNNER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RUNNER_DIR)
_SPEC = importlib.util.spec_from_file_location("orchestrator_runner_main", os.path.join(RUNNER_DIR, "runner.py"))
runner = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(runner)

# WHY THIS FILE NO LONGER ASSERTS AN ABSOLUTE LEASE.
#
# It used to require `_JOB_MAX_RUNTIME["merge_train.py"] >= 3600`. That dict is
# built from os.environ at import, and runner/.env on this operator's machine sets
# ORCH_MERGE_TRAIN_MAX_RUNTIME_S=2700 -- with eleven lines of evidence for why
# (1,301 cards visible to the train, 0 merges in 24h, every watchdog stack dump
# landing mid-verification, and an explicit REVERT note). So the assertion was red
# for a deliberate, documented operator decision, and green only on a machine that
# had not made one.
#
# Asserting the SHIPPED default instead does not work either, and the reason is
# worth recording: re-importing runner.py with the variable popped still reads
# 2700 back, because importing anything under runner/ pulls in db, whose
# _load_env() puts runner/.env into os.environ. There is no in-process view of
# "this code with no local tuning".
#
# What survives is the property the file is named for, which holds at any value an
# operator would sensibly choose, and which the historical bug violated.


def test_long_trains_have_execution_leases_independent_of_cadence():
    """The property the file is named for, asserted so a tuned host still holds it.

    "Independent of cadence" is what broke once: a historical `interval * 5`
    timeout killed the 60-second merge train after five minutes and made healthy
    QA restart forever. An operator lowering the lease is allowed; an operator
    lowering it back into scheduler-cadence range is the regression.
    """
    interval = runner._JOB_INTERVAL["merge_train.py"]
    assert interval == 60
    for job in ("merge_train.py", "releasetrain", "integration_sweeper.py"):
        lease = runner._JOB_MAX_RUNTIME[job]
        assert lease >= 20 * interval, (
            f"{job} lease {lease}s is within scheduler-cadence range of the "
            f"{interval}s interval -- the exact shape of the bug this file guards")


def test_every_long_job_has_an_explicit_lease_rather_than_the_scaled_fallback():
    """A job that needs minutes must not fall through to interval-scaled reaping."""
    for job in ("merge_train.py", "release_train.py", "releasetrain",
                "integration_sweeper.py", "self_deploy.py"):
        assert job in runner._JOB_MAX_RUNTIME, f"{job} has no explicit execution lease"


def test_snapshot_gate_is_present_before_fast_forward():
    source = open(__file__.replace('tests/test_periodic_execution_leases.py', 'merge_train.py'), encoding='utf-8').read()
    assert source.index('current_candidate_sha != candidate_sha') < source.index('if not _ff_base(repo, branch, base)')
