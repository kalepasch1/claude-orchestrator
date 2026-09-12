"""The conflict signature must survive whatever else rewrites a task's note.

The repeat-conflict guard compares this rebase attempt's conflicting-file set with the
previous attempt's. The previous attempt's set was originally appended to the task's
`note` as "[conflict-files:<sha>]".

Measured 2026-09-02, two days after that shipped: 0 of 902 task rows updated in the
previous 48h carried the tag, and the guard had fired 0 times against 71 redo events that
repeated a signature the attempt before had already produced. `note` is a shared free-text
field -- the preflight/refine stage rewrites it downstream, e.g.

    agentic-repair:conflict; scope: This task will modify ...; ambiguities: ...;
    pipeline:preflight-gate; triage-plan-code-qa-devmerge-release

-- so a marker parked at the end of it is gone by the time the next attempt reads it.

The signature now lives in a JSON ledger the train owns. These tests pin that the ledger
is authoritative, that the old note tag still resolves for rows written before it existed,
and that a clobbered note no longer loses the signature.
"""
import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import merge_train  # noqa: E402


@pytest.fixture()
def ledger(tmp_path, monkeypatch):
    path = tmp_path / "merge_train_conflict_sigs.json"
    monkeypatch.setattr(merge_train, "_conflict_ledger_path", lambda: str(path))
    return path


TASK = {"id": "11111111-1111-1111-1111-111111111111", "slug": "a-card", "note": ""}

# The exact shape observed live on remediate-cont-batch-tomorrow-45859a8-3b0df8-3b0df8.
CLOBBERED_NOTE = (
    "agentic-repair:conflict; scope: This task will modify the following files/components: "
    "CLAUDE.md (conflicting file) The codebase of the \"tomorrow\" project; ambiguities: The "
    "preflight gate is unclear.; pipeline:preflight-gate; triage-plan-code-qa-devmerge-release")


def test_signature_round_trips_through_the_ledger(ledger):
    assert merge_train._conflict_ledger_put(TASK, "deadbeef1234") is True
    assert merge_train._conflict_ledger_get(TASK) == "deadbeef1234"


def test_signature_survives_a_note_that_downstream_rewrote(ledger):
    """The regression this ledger exists for."""
    merge_train._conflict_ledger_put(TASK, "deadbeef1234")
    later = dict(TASK, note=CLOBBERED_NOTE)
    assert merge_train._recorded_conflict_signature(later) == "deadbeef1234"


def test_the_old_note_path_alone_loses_it(ledger):
    """Proof the note was never a store of record: same row, no ledger, nothing found."""
    later = dict(TASK, note=CLOBBERED_NOTE)
    assert merge_train._recorded_conflict_signature(later) == ""


def test_note_tag_still_resolves_for_rows_written_before_the_ledger(ledger):
    old = dict(TASK, note="agentic-repair:conflict [conflict-files:abc123abc123]")
    assert merge_train._recorded_conflict_signature(old) == "abc123abc123"


def test_ledger_wins_over_a_stale_note_tag(ledger):
    merge_train._conflict_ledger_put(TASK, "newnewnewnew")
    old = dict(TASK, note="x [conflict-files:oldoldoldold]")
    assert merge_train._recorded_conflict_signature(old) == "newnewnewnew"


def test_unknown_task_reads_empty(ledger):
    assert merge_train._conflict_ledger_get({"id": "nope", "note": ""}) == ""


def test_task_without_an_id_is_not_recorded(ledger):
    assert merge_train._conflict_ledger_put({"slug": "x"}, "sig") is False
    assert not ledger.exists()


def test_empty_signature_is_not_recorded(ledger):
    assert merge_train._conflict_ledger_put(TASK, "") is False


def test_entries_expire(ledger, monkeypatch):
    merge_train._conflict_ledger_put(TASK, "deadbeef1234")
    future = time.time() + merge_train._CONFLICT_LEDGER_TTL_S + 60
    monkeypatch.setattr(merge_train.time, "time", lambda: future)
    assert merge_train._conflict_ledger_get(TASK) == ""


def test_expired_entries_are_pruned_on_write(ledger):
    stale = time.time() - merge_train._CONFLICT_LEDGER_TTL_S - 60
    ledger.write_text(json.dumps({"old-id": {"sig": "s", "at": stale}}))
    merge_train._conflict_ledger_put(TASK, "deadbeef1234")
    data = json.loads(ledger.read_text())
    assert "old-id" not in data
    assert TASK["id"] in data


def test_two_tasks_do_not_overwrite_each_other(ledger):
    a = dict(TASK, id="aaaa", slug="a")
    b = dict(TASK, id="bbbb", slug="b")
    merge_train._conflict_ledger_put(a, "aaaaaaaaaaaa")
    merge_train._conflict_ledger_put(b, "bbbbbbbbbbbb")
    assert merge_train._conflict_ledger_get(a) == "aaaaaaaaaaaa"
    assert merge_train._conflict_ledger_get(b) == "bbbbbbbbbbbb"


def test_a_corrupt_ledger_reads_as_empty_and_is_recoverable(ledger):
    ledger.write_text("{not json")
    assert merge_train._conflict_ledger_get(TASK) == ""
    assert merge_train._conflict_ledger_put(TASK, "deadbeef1234") is True
    assert merge_train._conflict_ledger_get(TASK) == "deadbeef1234"


def test_a_ledger_holding_a_json_list_reads_as_empty(ledger):
    ledger.write_text("[1, 2, 3]")
    assert merge_train._conflict_ledger_get(TASK) == ""


def test_write_never_raises_when_the_directory_is_unwritable(tmp_path, monkeypatch):
    monkeypatch.setattr(merge_train, "_conflict_ledger_path",
                        lambda: "/proc/definitely/not/writable/sigs.json")
    assert merge_train._conflict_ledger_put(TASK, "deadbeef1234") is False


def test_no_temp_file_is_left_behind(ledger):
    merge_train._conflict_ledger_put(TASK, "deadbeef1234")
    assert not os.path.exists(str(ledger) + ".tmp")


def test_signature_is_order_insensitive():
    a = merge_train._conflict_signature("b.ts, a.ts.")
    b = merge_train._conflict_signature("a.ts, b.ts")
    assert a and a == b


def test_signature_is_newline_insensitive():
    a = merge_train._conflict_signature("a.ts\nb.ts.")
    b = merge_train._conflict_signature("a.ts, b.ts")
    assert a and a == b


def test_different_file_sets_differ():
    assert merge_train._conflict_signature("a.ts") != merge_train._conflict_signature("b.ts")


def test_the_redo_path_writes_the_ledger():
    """Structural: the redo branch must record before it patches the task."""
    src = open(merge_train.__file__.replace(".pyc", ".py")).read()
    # There are five `transient_retries = tr + 1` sites; anchor on the unique one that
    # writes the conflict tag, so this test cannot silently drift onto another.
    tag_at = src.index("_CONFLICT_SIG_TAG}{sig}]")
    retries_at = src.rindex('patch["transient_retries"] = tr + 1', 0, tag_at)
    window = src[retries_at:tag_at + 600]
    assert "_conflict_ledger_put(task, sig)" in window, window
    assert window.index("_conflict_ledger_put") < window.index("_task_patch(task, patch)"), window
