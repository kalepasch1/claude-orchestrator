"""The reaper's lease for self_deploy.py must outlast a worst-case canary pass.

selfdeploy-180 runs on a 180-second cadence. _reap_stale_periodic's fallback lease is
`expected_interval * 5`, so self_deploy.py got 900 seconds -- while a full gate pass on a
loaded node costs fetch (<=120) + scratch merge (<=300) + worktree add (<=300) +
compile (<=CANARY_TIMEOUT) + collection (<=180) + behaviour pytest (<=CANARY_TIMEOUT),
which is ~2100s at the current CANARY_TIMEOUT of 600.

The failure was silent and self-perpetuating: SIGKILL landed mid-pytest, so there was no
verdict, no restart request, and the pinned canary worktree leaked because `finally:
unpin()` never ran. Merged code simply stopped deploying -- the exact condition self-deploy
exists to prevent -- and nothing in the logs said "killed" loudly enough to notice.

These are parsed from source rather than imported: runner.py boots the whole orchestrator at
import time, which a unit test must not do.
"""
import os
import re

import pytest

_RUNNER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _source(name):
    with open(os.path.join(_RUNNER_DIR, name)) as fh:
        return fh.read()


def _int_default(src, pattern):
    """Pull the literal default out of an `int(os.environ.get("X", "N"))` expression."""
    match = re.search(pattern, src)
    assert match, f"pattern not found: {pattern}"
    return int(match.group(1))


def test_self_deploy_has_an_explicit_lease():
    """Without an entry it silently falls back to interval*5 = 900s."""
    src = _source("runner.py")
    block = src.split("_JOB_MAX_RUNTIME = {", 1)[1].split("}", 1)[0]
    assert '"self_deploy.py"' in block, \
        "no explicit lease: the reaper will SIGKILL the gate at interval*5 = 900s"


def test_the_lease_is_configurable():
    assert "ORCH_SELF_DEPLOY_MAX_RUNTIME_S" in _source("runner.py")


def test_the_lease_covers_the_worst_case_gate_pass():
    """The two files are separately editable; this is the constraint that ties them."""
    runner_src = _source("runner.py")
    deploy_src = _source("self_deploy.py")

    lease = _int_default(runner_src,
                         r'ORCH_SELF_DEPLOY_MAX_RUNTIME_S",\s*"(\d+)"')
    canary = _int_default(deploy_src, r'ORCH_CANARY_TIMEOUT",\s*"(\d+)"')
    collection = _int_default(deploy_src, r'ORCH_CANARY_COLLECTION_TIMEOUT",\s*"(\d+)"')
    fetch = _int_default(deploy_src, r'ORCH_ORIGIN_FETCH_TIMEOUT",\s*"(\d+)"')
    reconcile = _int_default(deploy_src, r'ORCH_RECONCILE_TIMEOUT",\s*"(\d+)"')

    # compile stage and behaviour stage each get CANARY_TIMEOUT; worktree add and the
    # scratch merge each get RECONCILE_TIMEOUT.
    worst_case = fetch + (2 * reconcile) + (2 * canary) + collection

    assert lease >= worst_case, (
        f"lease {lease}s < worst-case pass {worst_case}s "
        f"(fetch {fetch} + 2x reconcile {reconcile} + 2x canary {canary} "
        f"+ collection {collection}). Raise ORCH_SELF_DEPLOY_MAX_RUNTIME_S's default or "
        f"lower CANARY_TIMEOUT -- do not leave them out of step.")


def test_the_old_fallback_would_not_have_covered_it():
    """Guards the premise. If this ever fails the fix is obsolete, not merely redundant."""
    deploy_src = _source("self_deploy.py")
    canary = _int_default(deploy_src, r'ORCH_CANARY_TIMEOUT",\s*"(\d+)"')
    assert 180 * 5 < 2 * canary, \
        "interval*5 now exceeds even two canary stages; re-derive this test's premise"


def test_both_files_cross_reference_each_other():
    """A comment is the only thing stopping the next editor from bumping one alone."""
    assert "ORCH_SELF_DEPLOY_MAX_RUNTIME_S" in _source("self_deploy.py"), \
        "self_deploy.py must name the lease it depends on"
    assert "ORCH_CANARY_TIMEOUT" in _source("runner.py"), \
        "runner.py must name the timeout its lease is sized against"


def test_overlap_is_still_prevented_independently_of_the_lease():
    """A long lease is only safe because a second instance cannot be launched alongside.

    _is_still_running is what makes 'skip this cycle' the outcome instead of 'pile up eight
    concurrent gates', which is how merge_train.py once accumulated 8+ instances.
    """
    src = _source("runner.py")
    assert "def _is_still_running(job)" in src
    assert "_PERIODIC_PIDS" in src
