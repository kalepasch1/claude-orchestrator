"""Operator-origin work is express, and the queue-velocity PID may not shelve it.

The gap: claim ordering ranks drop-box / attributed-submitter tasks at 0, ahead of
every machine-generated repair task. But claim ORDER is not the only thing deciding
whether operator work runs — queue_velocity's PID shelves the lowest-EV slice of the
queue and exempted ONLY `pinned`. A drop-box task carries no pin and usually has no
confidence score yet, so under `confidence.asc.nullsfirst` it sorted FIRST among
shelve candidates: the controller preferentially discarded the owner's own directives.

"shelved by queue-velocity PID (low EV, integral too high)" is the recorded failure
on the two tasks that produced this fix.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import express_lane  # noqa: E402


# -- is_operator_origin ----------------------------------------------------


def test_dropbox_slug_is_operator_origin():
    ok, why = express_lane.is_operator_origin({"slug": "dropbox-fix-the-thing"})
    assert ok and why == "operator_dropbox"


def test_submitted_by_is_operator_origin():
    ok, why = express_lane.is_operator_origin({"submitted_by": "kalepasch1"})
    assert ok and why == "operator_submitted"


def test_submitted_by_label_is_operator_origin():
    ok, why = express_lane.is_operator_origin({"submitted_by_label": "Piper"})
    assert ok and why == "operator_submitted_label"


def test_machine_task_is_not_operator_origin():
    ok, why = express_lane.is_operator_origin(
        {"slug": "backlog-batch-beethoven-22ee5bc", "kind": "recovery"})
    assert not ok and why == "not_operator_origin"


@pytest.mark.parametrize("task", [
    {"submitted_by": None},
    {"submitted_by": ""},
    {"submitted_by_label": ""},
    {"submitted_by_label": "   "},
    {"slug": "not-dropbox-prefixed"},
    {},
])
def test_empty_markers_are_not_operator_origin(task):
    assert express_lane.is_operator_origin(task)[0] is False


@pytest.mark.parametrize("junk", [None, "str", 42, [], ("a",)])
def test_junk_task_is_fail_soft(junk):
    ok, why = express_lane.is_operator_origin(junk)
    assert ok is False and why == "not_a_task"


def test_slug_prefix_is_env_configurable():
    assert express_lane.ORCH_OPERATOR_SLUG_PREFIX == "dropbox-"


# -- is_express_task now recognises operator origin ------------------------


def test_operator_task_is_express_without_pin_or_priority():
    """THE regression. No pin, no priority — previously not express at all."""
    task = {"slug": "dropbox-ship-the-landing-page"}
    express, why = express_lane.is_express_task(task)
    assert express is True
    assert why == "operator_dropbox"


def test_operator_task_with_low_urgency_priority_is_still_express():
    """Operator origin outranks a bad numeric priority; it is checked first."""
    task = {"slug": "dropbox-x", "priority": 9999}
    assert express_lane.is_express_task(task)[0] is True


def test_operator_origin_wins_over_pinned_reason():
    task = {"slug": "dropbox-x", "pinned": True, "pin_rank": 3}
    assert express_lane.is_express_task(task)[1] == "operator_dropbox"


def test_pinned_with_rank_still_express():
    """Pre-existing behaviour preserved."""
    express, why = express_lane.is_express_task({"pinned": True, "pin_rank": 1})
    assert express is True and why == "pinned"


def test_pinned_with_zero_rank_still_not_express():
    """Unchanged: db.pin() never writes pinned=True with rank 0, and claim
    ordering treats that combination as unpinned."""
    assert express_lane.is_express_task({"pinned": True, "pin_rank": 0})[0] is False


def test_low_numeric_priority_still_express():
    express, why = express_lane.is_express_task({"priority": 5})
    assert express is True and why == "express_priority"


def test_ordinary_machine_task_still_not_express():
    express, why = express_lane.is_express_task(
        {"slug": "backlog-batch-x", "priority": 1000})
    assert express is False and why == "not_express_priority"


def test_non_dict_still_not_a_task():
    assert express_lane.is_express_task("nope") == (False, "not_a_task")
