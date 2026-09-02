"""A red suite on a saturated machine is not evidence about the candidate.

merge_train treats a TESTFAIL as a fact about the diff -- two of them quarantine the
task, which then needs a human to undo. Measured on this fleet on 2026-09-01:

    tomorrow's suite, idle machine                        131s
    tomorrow's suite, during a normal fleet pass       >10min
    1-minute load average that evening, on 18 cores    42-92

A timing-sensitive suite at five times oversubscription fails for reasons that have
nothing to do with the code being gated. Nothing recorded the load, so a red result at
load 92 and a red result at load 3 were indistinguishable afterwards.

This records it, on every failing gate result and on both timeout paths. It deliberately
stops there. Suppressing the strike is the obvious next step and is NOT taken, because
on a fleet whose load is routinely above the threshold it would mean nothing is ever
quarantined -- a change that needs the numbers this starts collecting.
"""
import os

import pytest

import merge_train as mt


def test_a_loaded_machine_is_called_out():
    note = mt._load_note(5.0)
    assert "5.00" in note
    assert "machine, not the code" in note


def test_an_idle_machine_says_so_too():
    """Both directions are useful. 'Not saturated' makes a red suite MORE damning."""
    note = mt._load_note(0.2)
    assert "0.20" in note
    assert "not saturated" in note
    assert "machine, not the code" not in note


def test_the_threshold_is_the_boundary():
    assert "not saturated" in mt._load_note(mt.GATE_LOAD_SUSPECT - 0.01)
    assert "machine, not the code" in mt._load_note(mt.GATE_LOAD_SUSPECT)


def test_an_unreadable_load_adds_nothing():
    """Silence beats a fabricated number in a note a human will read later."""
    assert mt._load_note(None) == ""


def test_the_threshold_is_tunable():
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(mt, "GATE_LOAD_SUSPECT", 100.0)
        assert "not saturated" in mt._load_note(50.0)


def test_load_per_core_is_a_ratio_not_a_raw_load():
    """16 is idle on 64 cores and fatal on 4. The raw number means nothing alone."""
    v = mt._load_per_core()
    assert v is None or (isinstance(v, float) and v >= 0.0)
    if v is not None:
        raw = os.getloadavg()[0]
        assert v == pytest.approx(raw / (os.cpu_count() or 1))


def test_load_per_core_survives_a_platform_without_getloadavg(monkeypatch):
    def _boom():
        raise OSError("not available")
    monkeypatch.setattr(mt.os, "getloadavg", _boom)
    assert mt._load_per_core() is None


def test_load_per_core_survives_an_unknown_cpu_count(monkeypatch):
    monkeypatch.setattr(mt.os, "cpu_count", lambda: None)
    v = mt._load_per_core()
    assert v is None or isinstance(v, float)   # falls back to 1 core, never divides by 0


def test_every_failing_gate_path_records_the_load():
    """Structural. Three exits report a failure, and a note on two of three is worse
    than none -- it would look like the third was measured on an idle box.
    """
    src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "merge_train.py")
    with open(src, encoding="utf-8") as fh:
        body = fh.read()
    start = body.index("def _run_tests(repo, test_cmd, ref=None):")
    end = body.index("def _test_cmd_for(", start)
    fn = body[start:end]
    assert fn.count("_load_note(_load_at_start)") == 3, (
        "a failing gate exit no longer records the load — expected the two timeout "
        "paths and the plain red-suite path, got "
        f"{fn.count('_load_note(_load_at_start)')}"
    )
    assert fn.index("_load_at_start = _load_per_core()") < fn.index("_load_note("), (
        "the load is sampled after it is used"
    )


def test_a_green_result_is_not_annotated():
    """The note exists to qualify a FAILURE. Green needs no excuse."""
    src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "merge_train.py")
    with open(src, encoding="utf-8") as fh:
        body = fh.read()
    start = body.index("def _run_tests(repo, test_cmd, ref=None):")
    end = body.index("def _test_cmd_for(", start)
    fn = body[start:end]
    for line in fn.splitlines():
        if "return True," in line:
            assert "_load_note" not in line, f"green result carries a load note: {line}"
