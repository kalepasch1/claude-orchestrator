"""The load a gate verdict was taken under must survive long enough to be counted.

`_load_note` says, in its own docstring, that suppressing a load-suspect strike
"is NOT taken here ... a change that needs the numbers this line is about to
start collecting". Measured 2026-09-03, long after it shipped:

    select count(*) from tasks where note like '%load/core%'   ->  0

The note IS written, at the front, exactly as that docstring describes. It is
then OVERWRITTEN. Three tasks the train marked TESTFAIL with a load annotation in
the preceding forty minutes all read `note = 'agentic-repair:rework'` seconds
later, back in QUEUED — an agent dispatched to fix a suite that had failed at
load/core 10.96.

Same lesson `_CONFLICT_SIG_TAG` learned two days earlier: `note` is a shared
free-text field that downstream stages rewrite. Same answer: a ledger the train
owns outright.

This records evidence and changes NO verdict, and these tests pin that.
"""
import json
import os

import pytest

import merge_train as mt


@pytest.fixture
def ledger(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_ORCH_HOME", str(tmp_path))
    monkeypatch.setattr(mt, "GATE_LOAD_SUSPECT", 1.5)
    return tmp_path / "merge_train_gate_load.json"


def test_a_saturated_verdict_is_recorded_as_suspect(ledger):
    assert mt.record_gate_load("card-a", "smarter", "TESTFAIL", per_core=10.96) is True
    rows = json.loads(ledger.read_text())
    assert len(rows) == 1
    assert rows[0]["slug"] == "card-a"
    assert rows[0]["project"] == "smarter"
    assert rows[0]["verdict"] == "TESTFAIL"
    assert rows[0]["per_core"] == 10.96
    assert rows[0]["suspect"] is True


def test_a_calm_verdict_is_recorded_as_trustworthy(ledger):
    mt.record_gate_load("card-b", "racefeed", "TESTFAIL", per_core=0.39)
    assert json.loads(ledger.read_text())[0]["suspect"] is False


def test_the_ledger_survives_where_the_note_did_not(ledger):
    """The whole point: a downstream stage rewriting `note` cannot reach this."""
    mt.record_gate_load("card-c", "darwn", "TESTFAIL", per_core=8.24)
    # ...downstream overwrites the task note entirely, as agentic-repair does...
    assert json.loads(ledger.read_text())[0]["per_core"] == 8.24


def test_stats_answer_the_question_the_docstring_asked(ledger):
    for i, pc in enumerate([0.5, 2.13, 4.36, 10.96, 1.2]):
        mt.record_gate_load(f"c{i}", "p", "TESTFAIL", per_core=pc)
    stats = mt.gate_load_stats()
    assert stats["total"] == 5
    assert stats["suspect"] == 3                 # 2.13, 4.36, 10.96
    assert stats["suspect_pct"] == 60.0
    assert stats["max_per_core"] == 10.96
    assert stats["by_verdict"] == {"TESTFAIL": 5}


def test_stats_on_an_empty_ledger_do_not_divide_by_zero(ledger):
    assert mt.gate_load_stats() == {
        "total": 0, "suspect": 0, "suspect_pct": 0.0,
        "median_per_core": None, "max_per_core": None, "by_verdict": {},
    }


def test_the_ledger_is_bounded(ledger, monkeypatch):
    monkeypatch.setattr(mt, "_GATE_LOAD_LEDGER_CAP", 10)
    for i in range(25):
        mt.record_gate_load(f"c{i}", "p", "TESTFAIL", per_core=2.0)
    rows = json.loads(ledger.read_text())
    assert len(rows) == 10
    assert rows[-1]["slug"] == "c24"             # newest kept, oldest dropped


def test_no_load_reading_records_nothing(ledger, monkeypatch):
    """A gate that never measured load has nothing to say, and says nothing."""
    monkeypatch.setattr(mt._GATE_LOAD, "per_core", None, raising=False)
    assert mt.record_gate_load("card-d", "p", "TESTFAIL") is False
    assert not ledger.exists()


def test_an_unwritable_ledger_never_raises(monkeypatch):
    """Best-effort: bookkeeping must not fail a merge pass."""
    monkeypatch.setattr(mt, "_gate_load_ledger_path",
                        lambda: "/nonexistent/dir/ledger.json")
    assert mt.record_gate_load("card-e", "p", "TESTFAIL", per_core=3.0) is False


def test_a_corrupt_ledger_is_replaced_not_propagated(ledger):
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text("{not json at all")
    assert mt.record_gate_load("card-f", "p", "TESTFAIL", per_core=2.0) is True
    assert json.loads(ledger.read_text())[0]["slug"] == "card-f"


def test_the_ledger_honours_the_test_home(monkeypatch, tmp_path):
    """A test driving the real gate path must not write into the running fleet."""
    monkeypatch.setenv("CLAUDE_ORCH_HOME", str(tmp_path))
    assert mt._gate_load_ledger_path().startswith(str(tmp_path))


def test_recording_changes_no_verdict(ledger):
    """The deferred decision stays deferred. This adds evidence, not behaviour."""
    import inspect
    source = inspect.getsource(mt.record_gate_load)
    for verdict_word in ("quarantine", "MERGED", "_task_patch", "_retire_card"):
        assert verdict_word not in source, \
            f"record_gate_load must not touch verdicts (found {verdict_word!r})"
