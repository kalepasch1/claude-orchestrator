"""Four project trains on a saturated box do not produce four verdicts. They produce
four unreliable ones.

resource_governor has clamped TASK LANES on load for a long time -- soft 1.5, hard 3.0
per core. It never saw merge_train's project workers, because four workers each running
a suite and a production build are gate machinery, not lanes. So the fleet could be
clamped to a single lane while four trains hammered the machine.

Measured 2026-09-02 across the 42 TESTFAILs carrying a load annotation, split in half by
time (the second half is after three paused projects were resumed):

    first half    n=21   median load/core 1.65   67% over the 1.50 threshold   max 2.80
    second half   n=21   median load/core 3.32   86% over                      max 4.85

The second half sits above the governor's own HARD threshold. merge_train's _load_note
says a result taken there "may be about the machine, not the code", and two TESTFAILs
quarantine a task -- so those are false quarantines that cost a human to undo. Four
workers is what produces that load, and therefore what buys the false quarantines.

The clamp reuses the governor's existing curve instead of adding a knob, and it is
adaptive in both directions: a quiet machine gets all four workers back on the next
pass. It fails open, because an unreadable load average is not evidence of load.
"""
import ast
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import resource_governor  # noqa: E402

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _train_run_unleashed_source():
    with open(os.path.join(RUNNER, "merge_train.py")) as fh:
        src = fh.read()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_train_run_unleased":
            return src, node
    raise AssertionError("_train_run_unleased() not found")


# ── the curve this reuses ─────────────────────────────────────────────────────

def test_a_quiet_machine_keeps_every_worker():
    assert resource_governor.cpu_budget(4, 0.8) == 4
    assert resource_governor.cpu_budget(4, resource_governor._cpu_soft()) == 4


def test_a_saturated_machine_is_cut_to_one():
    assert resource_governor.cpu_budget(4, resource_governor._cpu_hard()) == 1
    assert resource_governor.cpu_budget(4, 3.32) == 1      # the measured median
    assert resource_governor.cpu_budget(4, 4.85) == 1      # the measured max


def test_the_curve_is_monotonic():
    values = [resource_governor.cpu_budget(4, x / 10.0) for x in range(0, 60)]
    assert all(a >= b for a, b in zip(values, values[1:]))


def test_the_budget_never_returns_zero():
    for x in range(0, 200):
        assert resource_governor.cpu_budget(4, x / 10.0) >= 1


# ── the wiring ────────────────────────────────────────────────────────────────

def test_the_worker_count_is_clamped_by_the_cpu_budget():
    """Structural: the clamp must sit between the env read and the pool."""
    src, node = _train_run_unleashed_source()
    seg = ast.get_source_segment(src, node) or ""
    assert "MERGE_TRAIN_PROJECT_WORKERS" in seg
    assert "cpu_budget" in seg, (
        "the project-worker count ignores the fleet's own CPU curve")
    env_at = seg.index("MERGE_TRAIN_PROJECT_WORKERS")
    clamp_at = seg.index("cpu_budget")
    pool_at = seg.index("ThreadPoolExecutor")
    assert env_at < clamp_at < pool_at, (
        "the clamp must run after the configured value is read and before the pool "
        "is built; got env=%d clamp=%d pool=%d" % (env_at, clamp_at, pool_at))


def test_the_clamp_is_fail_open():
    """An unreadable load average is not evidence of load."""
    src, node = _train_run_unleashed_source()
    seg = ast.get_source_segment(src, node) or ""
    clamp_at = seg.index("cpu_budget")
    guarded = False
    for child in ast.walk(node):
        if isinstance(child, ast.Try):
            csrc = ast.get_source_segment(src, child) or ""
            if "cpu_budget" in csrc and child.handlers:
                guarded = True
    assert guarded, "the CPU budget check is not inside a try/except"
    assert clamp_at >= 0


def test_the_clamp_says_what_it_did():
    """A silent reduction in throughput is indistinguishable from a stall."""
    src, _node = _train_run_unleashed_source()
    assert "project worker(s) instead of" in src
    assert "load/core" in src


def test_the_clamp_never_raises_the_worker_count():
    """It may only reduce. A governor that adds workers is a different feature and a
    much worse bug."""
    src, node = _train_run_unleashed_source()
    seg = ast.get_source_segment(src, node) or ""
    window = seg[seg.index("cpu_budget"):seg.index("ThreadPoolExecutor")]
    assert "if _budget < workers" in window, (
        "the clamp does not guard against increasing the worker count")


@pytest.mark.parametrize("per_core,expected", [(0.5, 4), (1.5, 4), (2.0, 2), (3.5, 1)])
def test_the_measured_points_land_where_the_docstring_says(per_core, expected):
    assert resource_governor.cpu_budget(4, per_core) == expected
