"""Regression tests for the runner's empty-diff / default-response guard.

The prompt-delivery bug: the CLI opened without instructions, the model answered
"I'm ready to help. What would you like to work on?", nothing was committed, and the
only trace left on the shelf was "agent run failed" / "no file changes". These tests
pin the three conditions the guard is specified to name, and pin that a guard trip
hands the task back to the queue as RETRY rather than looping in-process.
"""
import importlib.util
import os
import sys
import types

import pytest

_RUNNER_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "runner")
if _RUNNER_DIR not in sys.path:
    sys.path.insert(0, _RUNNER_DIR)
_RUNNER_PY = os.path.join(_RUNNER_DIR, "runner.py")


@pytest.fixture(scope="module")
def r():
    """Bind `import runner` to runner/runner.py, then restore.

    Same collection-order hazard documented in test_emit_task_log.py: `runner/` is a
    package AND `runner/runner.py` is a module, both answering to the name `runner`.
    Loading the file by explicit path makes the result independent of what ran first.
    """
    saved = sys.modules.get("runner")
    spec = importlib.util.spec_from_file_location("runner", _RUNNER_PY)
    module = importlib.util.module_from_spec(spec)
    sys.modules["runner"] = module
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        if saved is not None:
            sys.modules["runner"] = saved
        else:
            sys.modules.pop("runner", None)


# --- the three guard conditions -------------------------------------------------


def test_empty_output_is_flagged(r):
    v = r.guard_check("", diff_files=["a.py"])
    assert v["ok"] is False
    assert v["reason"] == r.GUARD_EMPTY_OUTPUT
    # The spec's "HTTP 409 Conflict" is carried as a machine-readable code, since the
    # runner has no HTTP surface.
    assert v["status"] == r.GUARD_CONFLICT_STATUS

    assert r.guard_check("   \n\t ", diff_files=["a.py"])["reason"] == r.GUARD_EMPTY_OUTPUT


def test_default_greeting_response_is_flagged(r):
    v = r.guard_check("I'm ready to help. What would you like to work on?", diff_files=["a.py"])
    assert v["ok"] is False
    assert v["reason"] == r.GUARD_DEFAULT_RESPONSE
    assert v["status"] == r.GUARD_CONFLICT_STATUS


def test_empty_diff_is_flagged_but_unmeasured_diff_is_not(r):
    talked = "I analysed the module and here is what I found about the caching layer."

    v = r.guard_check(talked, diff_files=[])
    assert v["ok"] is False
    assert v["reason"] == r.GUARD_EMPTY_DIFF

    # None means "not measured". An unmeasured diff must never be reported as a
    # missing one — that would turn every un-instrumented call site into a false retry.
    assert r.guard_check(talked, diff_files=None)["ok"] is True
    assert r.guard_check(talked, diff_files=["web/app.vue"])["ok"] is True


def test_guard_is_pure_and_fails_soft_without_session_proof(r, monkeypatch):
    # A missing session_proof import must not convert every successful run into a retry.
    monkeypatch.setitem(sys.modules, "session_proof", None)
    v = r.guard_check("real work happened here", diff_files=["a.py"])
    assert v["ok"] is True
    assert v["reason"] == r.GUARD_OK


# --- what a guard trip does to the task -----------------------------------------


def test_guard_trip_sets_retry_and_records_the_reason(r, monkeypatch):
    states, recorded = [], []
    monkeypatch.setattr(r, "set_state",
                        lambda tid, state=None, note=None: states.append((tid, state, note)))
    monkeypatch.setattr(r, "regression",
                        types.SimpleNamespace(
                            record=lambda *a: recorded.append(a)))

    task = {"id": "t1", "project_name": "beethoven", "prompt": "do the thing"}
    verdict = r.guard_check("I'm ready to help. What would you like to work on?", diff_files=[])
    note = r.record_guard_trigger(task, "some-slug", "build", verdict)

    # RETRY, not RUNNING: a guard trip has to be visible to the queue, otherwise a task
    # that trips repeatedly looks like one long healthy run and nothing can count it.
    assert states == [("t1", "RETRY", note)]
    assert r.GUARD_DEFAULT_RESPONSE in note
    assert len(recorded) == 1
    assert r.GUARD_DEFAULT_RESPONSE in recorded[0]


def test_guard_trip_still_sets_retry_when_regression_logging_fails(r, monkeypatch):
    states = []
    monkeypatch.setattr(r, "set_state",
                        lambda tid, state=None, note=None: states.append((tid, state)))

    def boom(*a):
        raise RuntimeError("shelf unavailable")

    monkeypatch.setattr(r, "regression", types.SimpleNamespace(record=boom))

    verdict = r.guard_check("", diff_files=[])
    r.record_guard_trigger({"id": "t2", "prompt": "p"}, "s", "build", verdict)

    # Fail-soft: losing the audit line must not lose the state change too.
    assert states == [("t2", "RETRY")]
