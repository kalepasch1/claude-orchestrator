"""A pass that cannot get the lease should not first spend 100s earning that right.

2026-09-02. train_run() called done_to_merged.reconcile_missing_cards() -- the
"500 scanned, 498 carded" step, 20-100s against Supabase -- and only THEN tried to
acquire the global integration lease. Measured over one merge-train log:

    passes total                                          659
    ended lease-not-acquired                    70   (11%)
    wall time those 70 spent before finding out      1403s   (mean 20s)

and in the recent window, where a working pass runs 1284-2137s, ten of the last
twelve passes ended lease-not-acquired at 60-105s apiece. That is not only the 60s
scheduler: runner.integrate() calls train_run() inline the moment each task
finishes, so a dozen callers queue up behind one pass, and every one of them paid a
full card-reconciliation scan to be told another train owns the lease.

Nothing is lost by moving the call inside the lease. The reconciler writes cards for
whichever pass actually runs, and that pass reconciles first thing after acquiring.
The requirement in its own comment -- reconcile BEFORE this cycle's scan -- still
holds, and now it holds exactly once per pass that does work.
"""
import ast
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _train_run_source():
    with open(os.path.join(RUNNER, "merge_train.py")) as fh:
        src = fh.read()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "train_run":
            return src, node
    raise AssertionError("train_run() not found in merge_train.py")


def _lease_with(node):
    """The `with integration_runtime.global_lease(...)` statement inside train_run."""
    for child in ast.walk(node):
        if not isinstance(child, ast.With):
            continue
        for item in child.items:
            call = item.context_expr
            if (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                    and call.func.attr == "global_lease"):
                return child
    raise AssertionError("train_run() no longer takes a global lease")


def _reconcile_calls(node):
    return [c.lineno for c in ast.walk(node)
            if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
            and c.func.attr == "reconcile_missing_cards"]


def test_the_reconcile_scan_happens_inside_the_lease():
    """The regression: 70 passes paid for a scan they were about to throw away."""
    _src, train_run = _train_run_source()
    lease = _lease_with(train_run)
    calls = _reconcile_calls(train_run)
    assert calls, "train_run() no longer reconciles missing cards at all"
    outside = [ln for ln in calls if not (lease.lineno < ln <= lease.end_lineno)]
    assert not outside, (
        "reconcile_missing_cards() runs at line(s) %s, before the lease is held at "
        "line %d. A pass that loses the lease then discards 20-100s of Supabase "
        "scanning." % (outside, lease.lineno))


def test_the_reconcile_still_runs_before_the_pass_body():
    """Moving it must not move it past the scan it exists to feed."""
    _src, train_run = _train_run_source()
    reconcile = min(_reconcile_calls(train_run))
    body = [c.lineno for c in ast.walk(train_run)
            if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
            and c.func.id == "_train_run_unleased"]
    assert body, "_train_run_unleased() is no longer called from train_run()"
    assert reconcile < min(body), (
        "the card reconciler now runs after the scan it is meant to feed")


def test_the_lease_refusal_is_still_reported_not_silent():
    """FAILURE 2: an operator pause and a wedged train must not look the same."""
    src, _node = _train_run_source()
    assert '_end("lease-not-acquired"' in src
    assert "another integration or release train owns the global lease" in src


def test_the_reconcile_is_still_fail_soft():
    """A reconciler outage must degrade to the old behaviour, not stop integration."""
    _src, train_run = _train_run_source()
    line = min(_reconcile_calls(train_run))
    guarded = False
    for node in ast.walk(train_run):
        if isinstance(node, ast.Try) and node.lineno <= line <= node.end_lineno:
            if any(isinstance(h, ast.ExceptHandler) for h in node.handlers):
                guarded = True
    assert guarded, "reconcile_missing_cards() is no longer inside a try/except"


def test_the_host_pause_check_still_precedes_the_lease():
    """A paused host must not even try to acquire the lease."""
    _src, train_run = _train_run_source()
    lease = _lease_with(train_run)
    pauses = [c.lineno for c in ast.walk(train_run)
              if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
              and c.func.attr == "refuse"]
    assert pauses, "the paused-host guard is gone from train_run()"
    assert min(pauses) < lease.lineno
