"""A rebuild that hits the same conflict twice is not converging — stop paying for it.

The merge train's redo-on-fresh-base is the right move for a STALE branch: delete it,
have an agent rebuild the task against the advanced base, and the conflict is gone. It is
useless when the branch and the base both CREATE the same file, because the rebuild
writes that file again and collides in exactly the same place.

Every conflict in this fleet's merge-train log ends the same way -- 3,468 of them, and
100% "redo cap N exhausted". The sampled ones repeat a single filename across every
attempt. smarter's bridge-consent-gate card:

    REDO  (rebase conflict Conflicting files: tests/test_consent_gate.py., 3/4)
    REDO  (rebase conflict Conflicting files: tests/test_consent_gate.py., 4/4)
    CONFLICT (redo cap 4 exhausted Conflicting files: tests/test_consent_gate.py.)

Each REDO is a full agent rebuild. Three of them were spent reproducing the first
result twice.

So the train now records which files conflicted, and stops when an attempt matches the
one before it. Identical means the rebuild changed nothing that matters. ANY difference
means it is making progress and the redo continues -- which is the half these tests
spend the most attention on, because stopping a converging redo would strand work the
old code would eventually have landed.
"""
import os

import pytest

import merge_train as mt


def test_signature_ignores_order():
    """git lists conflicts in whatever order it walked the tree."""
    assert mt._conflict_signature("a.ts, b.ts") == mt._conflict_signature("b.ts, a.ts")


def test_signature_ignores_the_callers_trailing_period():
    """files_hint is built as '... Conflicting files: {detail}.' -- the period is ours."""
    assert mt._conflict_signature("tests/x.py.") == mt._conflict_signature("tests/x.py")


def test_signature_ignores_duplicates_and_whitespace():
    assert mt._conflict_signature(" a.ts ,a.ts,\n b.ts ") == mt._conflict_signature("a.ts,b.ts")


def test_different_files_give_different_signatures():
    assert mt._conflict_signature("a.ts") != mt._conflict_signature("b.ts")


def test_an_added_file_changes_the_signature():
    """Progress. One more colliding file means the rebuild DID move; keep going."""
    assert mt._conflict_signature("a.ts") != mt._conflict_signature("a.ts, b.ts")


@pytest.mark.parametrize("detail", ["", None, "   ", ",", " . "])
def test_an_empty_conflict_detail_has_no_signature(detail):
    """No detail means no evidence. The guard must not fire on ignorance."""
    assert mt._conflict_signature(detail) == ""


def test_the_signature_round_trips_through_a_task_note():
    sig = mt._conflict_signature("tests/test_consent_gate.py")
    note = f"train: rebase conflict on agent/x. {mt._CONFLICT_SIG_TAG}{sig}]"
    assert mt._recorded_conflict_signature({"note": note}) == sig


def test_the_latest_marker_wins_when_a_note_carries_several():
    """Notes accumulate across attempts; the last one written is the previous attempt."""
    note = (f"first {mt._CONFLICT_SIG_TAG}aaaaaaaaaaaa] then "
            f"{mt._CONFLICT_SIG_TAG}bbbbbbbbbbbb]")
    assert mt._recorded_conflict_signature({"note": note}) == "bbbbbbbbbbbb"


@pytest.mark.parametrize("task", [
    {}, {"note": None}, {"note": ""}, {"note": "no marker here"},
    {"note": mt._CONFLICT_SIG_TAG + "unterminated"},
])
def test_a_note_without_a_usable_marker_reads_as_no_history(task):
    """First attempt, or a note the train did not write. Either way: no opinion."""
    assert mt._recorded_conflict_signature(task) == ""


def test_the_guard_can_be_switched_off(monkeypatch):
    monkeypatch.setenv("ORCH_STOP_ON_REPEAT_CONFLICT", "false")
    assert mt._stop_on_repeat_conflict() is False
    monkeypatch.setenv("ORCH_STOP_ON_REPEAT_CONFLICT", "true")
    assert mt._stop_on_repeat_conflict() is True


def test_the_off_switch_is_read_at_call_time(monkeypatch):
    """So an operator can change it without restarting a runner mid-pass."""
    monkeypatch.delenv("ORCH_STOP_ON_REPEAT_CONFLICT", raising=False)
    assert mt._stop_on_repeat_conflict() is True
    monkeypatch.setenv("ORCH_STOP_ON_REPEAT_CONFLICT", "0")
    assert mt._stop_on_repeat_conflict() is False


def test_the_real_case_from_the_log_is_caught():
    """smarter/bridge-consent-gate, 3/4 and 4/4, verbatim from merge-train.log."""
    attempt_3 = mt._conflict_signature("tests/test_consent_gate.py.")
    attempt_4 = mt._conflict_signature("tests/test_consent_gate.py.")
    assert attempt_3 and attempt_3 == attempt_4


def test_a_converging_redo_is_not_stopped():
    """The expensive mistake would be stopping a rebuild that IS making progress."""
    first = mt._conflict_signature("a.ts, b.ts, c.ts")
    second = mt._conflict_signature("a.ts")          # two collisions resolved
    assert first != second


def test_the_integrate_path_checks_the_signature_before_spending_a_rebuild():
    """Structural. The helpers are worthless if _integrate_card does not consult them.

    Ordering is the whole point: the comparison must happen BEFORE the `if tr < cap`
    branch that deletes the branch and calls agentic_repair, or the rebuild is already
    paid for by the time anyone notices it is pointless.
    """
    src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "merge_train.py")
    with open(src, encoding="utf-8") as fh:
        body = fh.read()
    guard = body.find("prev = _recorded_conflict_signature(task)")
    spend = body.find("patch = agentic_repair.repair_patch(", guard if guard > 0 else 0)
    assert guard > 0, "_integrate_card no longer compares the conflict signature"
    assert spend > guard, (
        "the signature check moved AFTER the rebuild is requested — the agent run it "
        "exists to avoid has already been spent by then"
    )
    assert "_stop_on_repeat_conflict()" in body, "the off switch is no longer consulted"
    assert 'patch["note"] = ' in body, (
        "the redo no longer records this attempt's signature, so the NEXT attempt has "
        "nothing to compare against and the guard can never fire"
    )
