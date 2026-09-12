"""queue_velocity._shelve_lowest_ev must not shelve operator-origin work.

Pinning was the only exemption. A drop-box task carries no pin and usually has no
confidence score yet, so under `confidence.asc.nullsfirst` it sorted FIRST among
shelve candidates — the PID preferentially discarded the owner's own directives,
which claim ordering ranks above everything. An unscored task is unmeasured, not
low-value.
"""
from __future__ import annotations

import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import queue_velocity  # noqa: E402


def _rows(*tasks):
    return list(tasks)


@pytest.fixture()
def shelved_slugs():
    """Run _shelve_lowest_ev over a fixed queue; collect what got shelved."""
    def run(rows):
        seen = []

        def fake_update(table, where, values, *a, **kw):
            if values.get("state") == "SHELVED" or "shelve" in str(values).lower():
                seen.append(where.get("id"))
            return True

        with patch.object(queue_velocity.db, "select", return_value=rows), \
             patch.object(queue_velocity.db, "update", side_effect=fake_update), \
             patch.object(queue_velocity, "_recovery_action",
                          return_value=("shelve", "nothing recoverable")):
            queue_velocity._shelve_lowest_ev(len(rows))
        return seen
    return run


# -- the regression --------------------------------------------------------


def test_dropbox_task_is_not_shelved(shelved_slugs):
    shelved = shelved_slugs(_rows(
        {"id": "1", "slug": "dropbox-ship-it", "confidence": None},
        {"id": "2", "slug": "backlog-batch-x", "confidence": 0.1},
    ))
    assert "1" not in shelved
    assert "2" in shelved


def test_submitted_by_task_is_not_shelved(shelved_slugs):
    shelved = shelved_slugs(_rows(
        {"id": "1", "slug": "some-task", "submitted_by": "kalepasch1", "confidence": None},
        {"id": "2", "slug": "machine-task", "confidence": 0.2},
    ))
    assert shelved == ["2"]


def test_submitted_by_label_task_is_not_shelved(shelved_slugs):
    shelved = shelved_slugs(_rows(
        {"id": "1", "slug": "t", "submitted_by_label": "Piper", "confidence": None},
    ))
    assert shelved == []


def test_unscored_operator_task_sorts_first_but_survives(shelved_slugs):
    """The precise shape of the bug: nullsfirst puts the unscored operator task
    at the head of the shelve candidates."""
    shelved = shelved_slugs(_rows(
        {"id": "op", "slug": "dropbox-a", "confidence": None},
        {"id": "op2", "slug": "dropbox-b", "confidence": None},
        {"id": "m", "slug": "machine", "confidence": 0.9},
    ))
    assert "op" not in shelved and "op2" not in shelved
    assert shelved == ["m"]


def test_pinned_task_still_not_shelved(shelved_slugs):
    """Pre-existing exemption preserved."""
    shelved = shelved_slugs(_rows(
        {"id": "1", "slug": "pinned-one", "pinned": True, "confidence": None},
    ))
    assert shelved == []


def test_ordinary_machine_tasks_are_still_shelvable(shelved_slugs):
    """The controller must still do its job — this is a carve-out, not a disable."""
    shelved = shelved_slugs(_rows(
        {"id": "1", "slug": "a", "confidence": 0.1},
        {"id": "2", "slug": "b", "confidence": 0.2},
    ))
    assert sorted(shelved) == ["1", "2"]


def test_shelve_query_selects_the_operator_columns():
    """A guard that reads a column the query never selected is inert."""
    captured = {}

    def fake_select(table, params, *a, **kw):
        captured["select"] = params.get("select", "")
        return []

    with patch.object(queue_velocity.db, "select", side_effect=fake_select):
        queue_velocity._shelve_lowest_ev(5)
    assert "submitted_by" in captured["select"]
    assert "submitted_by_label" in captured["select"]
    assert "slug" in captured["select"]


def test_missing_express_lane_module_is_fail_soft(shelved_slugs, monkeypatch):
    """The controller must still run if express_lane cannot be imported."""
    monkeypatch.setattr(queue_velocity, "express_lane", None)
    shelved = shelved_slugs(_rows({"id": "1", "slug": "machine", "confidence": 0.1}))
    assert shelved == ["1"]
