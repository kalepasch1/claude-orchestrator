"""The call-count circuit breaker must distinguish free subscription calls from billable ones.

Regression guard for the 2026-08-02 throughput incident: the *cost* breakers were
subscription-aware but the *call-count* breaker was not, so every free subscription call
burned the same 80/hr budget as a billable API call. With ~2,200 tasks queued the fleet was
pinned at roughly one model call per minute with no worker processes running — the queue
looked "slow" when it was actually rate-limited by an accounting bug.
"""
import os
import sys
import time
import json
import tempfile
import importlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _fresh_module(tmpdir, **env):
    """Import claude_cli with an isolated budget file and the given caps."""
    os.environ["CLAUDE_ORCH_HOME"] = tmpdir
    for k, v in env.items():
        os.environ[k] = str(v)
    import claude_cli
    importlib.reload(claude_cli)
    return claude_cli


def _write_calls(mod, entries):
    json.dump({"calls": entries, "spend": [], "sub_spend": []}, open(mod.STATE, "w"))


def test_subscription_calls_do_not_trip_the_billable_cap():
    with tempfile.TemporaryDirectory() as d:
        m = _fresh_module(d, CLAUDE_MAX_CALLS_PER_HOUR=5, CLAUDE_MAX_SUB_CALLS_PER_HOUR=500)
        now = time.time()
        # 200 free subscription calls in the last hour — well past the old 5-call cap.
        _write_calls(m, [[now - 10, 1, 0] for _ in range(200)])
        m._check_budget()  # must not raise


def test_billable_calls_still_trip_the_cap():
    with tempfile.TemporaryDirectory() as d:
        m = _fresh_module(d, CLAUDE_MAX_CALLS_PER_HOUR=5, CLAUDE_MAX_SUB_CALLS_PER_HOUR=500)
        now = time.time()
        _write_calls(m, [[now - 10, 1, 1] for _ in range(5)])
        try:
            m._check_budget()
        except m.CircuitOpen as e:
            assert "billable" in str(e)
            return
        raise AssertionError("billable cap did not trip — the wallet guard is gone")


def test_runaway_guard_still_exists():
    """The subscription ceiling is a runaway guard, not a pacer — but it must exist."""
    with tempfile.TemporaryDirectory() as d:
        m = _fresh_module(d, CLAUDE_MAX_CALLS_PER_HOUR=5, CLAUDE_MAX_SUB_CALLS_PER_HOUR=50)
        now = time.time()
        _write_calls(m, [[now - 10, 1, 0] for _ in range(50)])
        try:
            m._check_budget()
        except m.CircuitOpen as e:
            assert "runaway" in str(e)
            return
        raise AssertionError("no runaway guard — an infinite loop could burn the subscription")


def test_legacy_two_element_entries_are_not_counted_as_billable():
    """Entries written before the billable flag existed must not trip the breaker on upgrade.

    Real spend is tracked independently in `spend`, so treating them as non-billable
    cannot hide a dollar.
    """
    with tempfile.TemporaryDirectory() as d:
        m = _fresh_module(d, CLAUDE_MAX_CALLS_PER_HOUR=5, CLAUDE_MAX_SUB_CALLS_PER_HOUR=500)
        now = time.time()
        _write_calls(m, [[now - 10, 1] for _ in range(100)])
        m._check_budget()  # must not raise


def test_record_marks_billable_only_when_real_dollars_were_spent():
    with tempfile.TemporaryDirectory() as d:
        m = _fresh_module(d, CLAUDE_MAX_CALLS_PER_HOUR=80, CLAUDE_MAX_SUB_CALLS_PER_HOUR=600)
        _write_calls(m, [])
        m._record(0.0, sub_usd=0.02)      # subscription call
        m._record(0.31, sub_usd=0.0)      # real API call
        calls = json.load(open(m.STATE))["calls"]
        assert [c[2] for c in calls] == [0, 1]
        assert m._billable_calls(calls) == 1


def test_dollar_caps_are_untouched():
    """The throughput fix must not widen the spend guard."""
    with tempfile.TemporaryDirectory() as d:
        m = _fresh_module(d, CLAUDE_MAX_USD_PER_HOUR=1, CLAUDE_MAX_SUB_CALLS_PER_HOUR=9999)
        now = time.time()
        json.dump({"calls": [], "spend": [[now - 5, 1.50]], "sub_spend": []}, open(m.STATE, "w"))
        try:
            m._check_budget()
        except m.CircuitOpen as e:
            assert "$" in str(e)
            return
        raise AssertionError("hourly dollar cap no longer trips")
