"""Do not take a verdict the machine cannot give — and do not call that forgiveness.

Measured from the merge train's own log, 2026-09-03:

    annotated gate results        168   (every single one a TESTFAIL)
    over the soft threshold       144   (85%)
    load/core  median 2.13   p90 4.36   max 10.96

A TESTFAIL is not free. It retires the card, marks the task, and queues an
agentic-repair rework. Three tasks failed at load/core 8-11 inside one
forty-minute window and each dispatched an agent to fix a suite that had not
really failed — and those agents then add load, so the next suite fails the same
way. That is the loop that produced 0 merges in 90 minutes.

This is NOT the strike suppression `_load_note` deliberately left undone. Nothing
is forgiven and no failure is recorded: the card is not gated yet, left exactly as
a branch that does not exist yet is left. The distinction is what these tests pin.
"""
import pytest

import merge_train as mt


@pytest.fixture(autouse=True)
def clean_counters(monkeypatch):
    monkeypatch.setattr(mt, "_DEFER_COUNTS", {})
    monkeypatch.setattr(mt, "GATE_LOAD_DEFER", 3.0)
    monkeypatch.setattr(mt, "GATE_LOAD_DEFER_MAX", 3)


def test_a_saturated_box_defers_the_gate():
    deferred, why = mt._should_defer_for_load("card-a", per_core=10.96)
    assert deferred is True
    assert "10.96" in why and "3.00" in why
    assert "nothing recorded against it" in why


def test_a_calm_box_gates_normally():
    assert mt._should_defer_for_load("card-b", per_core=0.8) == (False, "")


def test_the_median_pass_still_runs():
    """2.13 is the measured median. Deferring it would stall the fleet, not help it."""
    assert mt._should_defer_for_load("card-c", per_core=2.13)[0] is False


def test_the_soft_threshold_alone_does_not_defer():
    """The author's warning, honoured: on a fleet routinely over 1.5, deferring at 1.5
    would mean nothing is ever gated."""
    assert mt.GATE_LOAD_SUSPECT < mt.GATE_LOAD_DEFER
    assert mt._should_defer_for_load("card-d", per_core=mt.GATE_LOAD_SUSPECT)[0] is False


def test_deferral_is_bounded_so_a_card_is_never_stalled_forever():
    for i in range(mt.GATE_LOAD_DEFER_MAX):
        deferred, why = mt._should_defer_for_load("card-e", per_core=9.0)
        assert deferred is True, f"deferral {i + 1} should have been allowed"
        assert f"{i + 1}/{mt.GATE_LOAD_DEFER_MAX}" in why
    # Cap reached: the card is now gated regardless of how saturated the box is.
    assert mt._should_defer_for_load("card-e", per_core=99.0) == (False, "")


def test_the_cap_is_per_card():
    for _ in range(mt.GATE_LOAD_DEFER_MAX):
        mt._should_defer_for_load("card-f", per_core=9.0)
    assert mt._should_defer_for_load("card-f", per_core=9.0)[0] is False
    assert mt._should_defer_for_load("card-g", per_core=9.0)[0] is True


def test_an_unreadable_load_gates_normally(monkeypatch):
    """Fail-open in the direction that costs least: a gate that runs by accident just
    produces the verdict we already produce; a deferral by accident stalls work."""
    monkeypatch.setattr(mt, "_load_per_core", lambda: None)
    assert mt._should_defer_for_load("card-h") == (False, "")


def test_a_raising_load_reader_gates_normally(monkeypatch):
    def boom():
        raise OSError("no loadavg")

    monkeypatch.setattr(mt, "_load_per_core", boom)
    assert mt._should_defer_for_load("card-i") == (False, "")


def test_the_deferral_can_be_switched_off(monkeypatch):
    monkeypatch.setattr(mt, "GATE_LOAD_DEFER", 0.0)
    assert mt._should_defer_for_load("card-j", per_core=99.0) == (False, "")


def test_deferring_records_no_verdict():
    """The line between this and the suppression that was deliberately not taken."""
    import inspect
    source = inspect.getsource(mt._should_defer_for_load)
    for forbidden in ("_task_patch", "_retire_card", "record_gate_load",
                      "quarantine", "TESTFAIL", "MERGED"):
        assert forbidden not in source, \
            f"the deferral must not touch verdicts (found {forbidden!r})"


def test_the_card_path_returns_a_non_verdict_outcome():
    """`load-deferred` must sit with waiting-branch, not with testfail."""
    import inspect
    source = inspect.getsource(mt._process_card) if hasattr(mt, "_process_card") else ""
    if not source:                       # the card body is a nested/renamed function
        source = inspect.getsource(mt)
    assert 'return "load-deferred"' in source
    marker = source.index('return "load-deferred"')
    before = source[max(0, marker - 2000):marker]
    for forbidden in ("_retire_card", "_task_patch(task, {\"state\": \"TESTFAIL\""):
        assert forbidden not in before[-400:], \
            "the deferral must not run through a verdict-recording path"
