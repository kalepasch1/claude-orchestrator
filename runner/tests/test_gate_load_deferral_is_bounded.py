"""The deferral cap that never once fired.

merge_train defers a card when the box is over CPU_HARD_LOAD, so a suite is not judged
on a saturated machine. GATE_LOAD_DEFER_MAX bounds that, and its own comment states the
reason plainly:

    Bounded, because "wait for a calm machine" must not become "never": after
    GATE_LOAD_DEFER_MAX deferrals the card is gated regardless, saturated or not.

It never happened. The counter was a module-level dict, and a merge_train pass is a
PROCESS -- so every pass started at zero, deferred the card to 1/3, and exited.

MEASURED 2026-09-04, one merge-train log window:

    36 x "not gating yet (1/3)"
     0 x "(2/3)"
     0 x "(3/3)"

with the box at load/core 4.6 and 374 tasks sitting in DONE. That is not a delay, it is
a dead end -- precisely the failure the cap was written to prevent.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import merge_train


@pytest.fixture(autouse=True)
def ledger_in_tmp(tmp_path, monkeypatch):
    """Never write the running fleet's ledger from a test."""
    monkeypatch.setenv("CLAUDE_ORCH_HOME", str(tmp_path))
    monkeypatch.setattr(merge_train, "GATE_LOAD_DEFER", 3.0)
    monkeypatch.setattr(merge_train, "GATE_LOAD_DEFER_MAX", 3)
    merge_train._DEFER_COUNTS.clear()
    return tmp_path


def _fresh_process():
    """What a new merge_train pass starts with: an empty in-memory counter."""
    merge_train._DEFER_COUNTS.clear()


def test_the_cap_survives_process_restarts(ledger_in_tmp):
    """THE REGRESSION. Each call below is a separate pass on a still-busy box."""
    seen = []
    for _ in range(5):
        _fresh_process()
        deferred, why = merge_train._should_defer_for_load("card-a", per_core=9.0)
        seen.append(deferred)
    assert seen == [True, True, True, False, False], (
        f"deferrals across passes were {seen}; the cap must stop deferring after "
        f"{merge_train.GATE_LOAD_DEFER_MAX}, whatever the process boundary")


def test_the_message_counts_up_across_passes(ledger_in_tmp):
    """36 log lines all reading (1/3) is how this was found."""
    notes = []
    for _ in range(3):
        _fresh_process()
        _deferred, why = merge_train._should_defer_for_load("card-b", per_core=9.0)
        notes.append(why)
    assert "(1/3)" in notes[0] and "(2/3)" in notes[1] and "(3/3)" in notes[2], notes


def test_a_calm_box_still_gates_immediately(ledger_in_tmp):
    deferred, why = merge_train._should_defer_for_load("card-c", per_core=0.4)
    assert deferred is False and why == ""


def test_gating_a_card_forgets_its_deferrals(ledger_in_tmp):
    """Otherwise a card sits at 3/3 forever and the next busy stretch skips its cap."""
    for _ in range(3):
        _fresh_process()
        merge_train._should_defer_for_load("card-d", per_core=9.0)
    assert merge_train._should_defer_for_load("card-d", per_core=9.0)[0] is False

    merge_train.clear_defer_count("card-d")
    _fresh_process()
    assert merge_train._should_defer_for_load("card-d", per_core=9.0)[0] is True


def test_stale_entries_expire(ledger_in_tmp, monkeypatch):
    """A burst last Tuesday must not gate-regardless a card today."""
    for _ in range(3):
        _fresh_process()
        merge_train._should_defer_for_load("card-e", per_core=9.0)
    path = merge_train._defer_ledger_path()
    data = json.load(open(path))
    data["card-e"]["at"] = 0            # long ago
    json.dump(data, open(path, "w"))

    _fresh_process()
    assert merge_train._should_defer_for_load("card-e", per_core=9.0)[0] is True


def test_cards_do_not_share_a_budget(ledger_in_tmp):
    for _ in range(3):
        _fresh_process()
        merge_train._should_defer_for_load("card-f", per_core=9.0)
    _fresh_process()
    assert merge_train._should_defer_for_load("card-g", per_core=9.0)[0] is True


def test_an_unreadable_ledger_gates_rather_than_stalls(ledger_in_tmp, monkeypatch):
    """Fail-open, in the direction the function already documents."""
    monkeypatch.setattr(merge_train, "_defer_counts_load",
                        lambda: (_ for _ in ()).throw(OSError("boom")))
    deferred, _why = merge_train._should_defer_for_load("card-h", per_core=9.0)
    assert deferred is False
