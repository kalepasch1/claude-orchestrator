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


def _src():
    p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "merge_train.py")
    with open(p, encoding="utf-8") as fh:
        return fh.read()


def test_the_load_is_sampled_when_the_suite_starts():
    """Not when it finishes. A suite that ran for 13 minutes says nothing useful about
    the load at the moment it ended."""
    body = _src()
    fn = body[body.index("def _run_tests(repo, test_cmd, ref=None):"):
              body.index("def _test_cmd_for(")]
    assert "_record_gate_load()" in fn
    assert fn.index("_record_gate_load()") < fn.index("subprocess.run"), (
        "the load is sampled after the suite has already run"
    )


def test_the_note_is_written_in_front_of_the_truncated_tail():
    """THE BUG THIS PINS. The first version appended the note to the gate's returned
    detail -- up to 12,000 characters of test output -- and the caller stores
    `tail[:200]`. The annotation was cut off every time: after nine hours and 135
    touched tasks, `select count(*) from tasks where note like '%load/core%'` was 0.
    """
    body = _src()
    i = body.index('"state": "TESTFAIL"')
    note = body[body.index("_gl = _gate_load_note()", i - 400):body.index("_retire_card", i)]
    assert "{_gl}" in note, "the TESTFAIL note no longer carries the load"
    # The evidence half of this note used to be `tail[:200]` -- the FRONT of a
    # 12,000-character window, which is why 75% of TESTFAIL records named no failure at
    # all (see failure_excerpt.py). It is now `_why`, the excerpt that actually describes
    # the failure. Either way the load has to come FIRST, or truncation eats it exactly
    # as it did before.
    evidence = "_why" if "_why" in note else "tail[:200]"
    assert note.index("{_gl}") < note.index(evidence), (
        "the load note is written AFTER the failure evidence — it will be cut off, "
        "exactly as it was before"
    )


def test_the_note_survives_the_200_character_truncation():
    """Behavioural version of the above: build the note the way the caller does and
    check the load is still in it after truncation."""
    mt._record_gate_load()
    gl = mt._gate_load_note()
    tail = "x" * 12000
    note = f"train:{gl} tests failed on rebased agent/whatever: {tail[:200]}"
    assert "load/core" in note[:200], (
        f"the load did not survive truncation; first 200 chars: {note[:200]!r}"
    )


def test_each_thread_measures_its_own_load():
    """merge_train runs several projects concurrently. A module global would hand one
    project's load to another project's note."""
    import threading
    mt._GATE_LOAD.per_core = 0.11
    seen = {}

    def _worker():
        seen["before"] = getattr(mt._GATE_LOAD, "per_core", None)
        mt._GATE_LOAD.per_core = 9.99
        seen["after"] = mt._GATE_LOAD.per_core

    t = threading.Thread(target=_worker)
    t.start()
    t.join()
    assert seen["before"] is None, "a thread inherited another thread's gate load"
    assert seen["after"] == 9.99
    assert mt._GATE_LOAD.per_core == 0.11, "a worker thread's load leaked into its parent"


def test_a_thread_that_never_ran_a_suite_has_no_opinion():
    import threading
    out = {}

    def _worker():
        out["note"] = mt._gate_load_note()

    t = threading.Thread(target=_worker)
    t.start()
    t.join()
    assert out["note"] == ""


def test_a_green_result_is_not_annotated():
    """The note exists to qualify a FAILURE. Green needs no excuse."""
    body = _src()
    fn = body[body.index("def _run_tests(repo, test_cmd, ref=None):"):
              body.index("def _test_cmd_for(")]
    for line in fn.splitlines():
        if "return True," in line:
            assert "_load_note" not in line and "_gate_load_note" not in line, (
                f"green result carries a load note: {line}"
            )
