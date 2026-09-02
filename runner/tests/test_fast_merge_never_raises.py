#!/usr/bin/env python3
"""on_test_completion() promises a verdict. It must keep that promise when the DB fails.

On 2026-08-30 `_create_fast_approval` wrote two columns the `approvals` table does
not have. The insert returned HTTP 400, the call site was unguarded, and a method
whose docstring says it "returns a verdict dict ... rather than raising" raised on
every green test run instead. The payload bug is fixed; this pins the contract, so
the next schema drift or network blip declines a merge rather than taking the gate
down.
"""
import os
import sys

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RUNNER)

import fast_auto_merge  # noqa: E402


class Boom(Exception):
    pass


def _low_risk_task():
    return {"id": "t1", "slug": "some-low-risk-task", "kind": "chore",
            "project_id": None, "state": "DONE"}


def _arrange(monkeypatch_target, insert_raises):
    """Point the module at a task that qualifies, with a chosen insert behaviour."""
    fast_auto_merge.event_is_passing = lambda event: True
    fast_auto_merge._task_from_event = lambda event: _low_risk_task()
    fast_auto_merge._is_low_risk = lambda task: True
    fast_auto_merge._has_approval_card = lambda task: False

    def insert(table, row, **kwargs):
        if insert_raises:
            raise Boom("HTTP 400 on POST /rest/v1/approvals: column does not exist")
        monkeypatch_target.append(row)
        return row
    fast_auto_merge.db.insert = insert


def _restore(saved):
    for name, value in saved.items():
        setattr(fast_auto_merge, name, value)


def _snapshot():
    return {name: getattr(fast_auto_merge, name)
            for name in ("event_is_passing", "_task_from_event", "_is_low_risk",
                         "_has_approval_card")} | {"db_insert": fast_auto_merge.db.insert}


def _run(insert_raises):
    saved = _snapshot()
    db_insert = saved.pop("db_insert")
    written = []
    try:
        _arrange(written, insert_raises)
        return fast_auto_merge.on_test_completion({"kind": "test:completed"}), written
    finally:
        _restore(saved)
        fast_auto_merge.db.insert = db_insert


def test_a_failing_approval_write_declines_instead_of_raising():
    result, written = _run(insert_raises=True)
    assert result["approved"] is False
    assert "could not be written" in result["reason"]
    assert result["slug"] == "some-low-risk-task"
    assert written == []


def test_the_happy_path_still_approves():
    """Guard against 'fixing' the raise by never approving anything."""
    result, written = _run(insert_raises=False)
    assert result["approved"] is True
    assert len(written) == 1
    assert written[0]["status"] == "approved"
