"""guarded_task_update must not let one rejected row abort the caller's pass.

Root cause of the integration-sweeper crash loop: sweep() calls
guarded_task_update() in a loop over every task. db.update() raised
HTTPError 400 when the closure-evidence trigger refused a row, the exception
escaped, and the whole sweep died on the first bad row -- every run, forever.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import merge_truth


TASK = {"id": "t-1", "slug": "demo-task"}
PATCH = {"state": "DONE", "note": "x"}


def test_evidence_rejection_is_contained(monkeypatch, capsys):
    def _reject(*a, **k):
        raise RuntimeError(
            "HTTP Error 400: Bad Request -- cannot close as DONE with no "
            "artifact_commit"
        )

    monkeypatch.setattr(merge_truth.db, "update", _reject)

    result = merge_truth.guarded_task_update(TASK, dict(PATCH))

    assert result is None, "failed write must report 'nothing written'"
    out = capsys.readouterr().out
    assert "demo-task" in out
    assert "missing evidence" in out


def test_generic_write_failure_is_contained(monkeypatch, capsys):
    def _boom(*a, **k):
        raise RuntimeError("connection reset")

    monkeypatch.setattr(merge_truth.db, "update", _boom)

    assert merge_truth.guarded_task_update(TASK, dict(PATCH)) is None
    assert "non-fatal" in capsys.readouterr().out


def test_successful_write_still_returns_patch(monkeypatch):
    calls = []
    monkeypatch.setattr(
        merge_truth.db, "update", lambda *a, **k: calls.append((a, k))
    )

    result = merge_truth.guarded_task_update(TASK, dict(PATCH))

    assert result == PATCH
    assert len(calls) == 1


def test_a_bad_row_does_not_stop_the_loop(monkeypatch):
    """The behaviour sweep() depends on: keep going after a rejected row."""
    seen = []

    def _flaky(table, where, patch):
        seen.append(where["id"])
        if where["id"] == "bad":
            raise RuntimeError("400 Bad Request: no artifact_commit")

    monkeypatch.setattr(merge_truth.db, "update", _flaky)

    processed = []
    for tid in ("good-1", "bad", "good-2"):
        merge_truth.guarded_task_update({"id": tid, "slug": tid}, dict(PATCH))
        processed.append(tid)

    assert processed == ["good-1", "bad", "good-2"]
    assert seen == ["good-1", "bad", "good-2"]


@pytest.mark.parametrize(
    "detail,expected",
    [
        ("cannot close as DONE with no artifact_commit", True),
        ("put NO-ARTIFACT-JUSTIFIED in note", True),
        ("connection reset by peer", False),
        ("", False),
        (None, False),
    ],
)
def test_evidence_rejection_classifier(detail, expected):
    assert merge_truth._is_evidence_rejection(detail) is expected
