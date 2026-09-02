"""
The repair ceilings must not be defeated by a narrow SELECT.

WHAT WENT WRONG
---------------
repair_patch() read its bound off the row the caller passed in:

    rc = int(task.get("remediation_count") or 0)
    if rc >= GLOBAL_REPAIR_CEILING: park it

A sweep that selected a narrow column set handed it no remediation_count at all,
so `rc` evaluated to 0 and the ceiling did not apply. The same row's `attempt`
was advanced only `if "attempt" in task`, so that counter did not move either.

The result, measured in production 2026-08-23:

    slug                                             attempt   remediation_count
    copyfix-…-public-landing-domain-intent-labels        170                   6
    copyfix-…-public-landing-founder-navigation          131                   2
    copyfix-…-public-landing-hero-control                124                   4
    factory-unblock-…-fix-compilation-types              108                   5

Every one of those is UNDER the ceiling of 8. The ceiling was never broken. It
was counting roughly 3.5% of the work being done and concluding, correctly from
what it could see, that the task had barely been tried.

1,735 build tasks sat QUEUED behind this.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import agentic_repair  # noqa: E402

EVIDENCE = "Traceback (most recent call last): ValueError: something concrete failed here"


def test_absent_remediation_count_is_not_treated_as_zero(monkeypatch):
    """A caller that did not select the column must not get a free pass."""
    calls = []

    class FakeDB:
        @staticmethod
        def select(table, params):
            calls.append((table, params))
            return [{"remediation_count": 9, "attempt": 40}]

    monkeypatch.setitem(sys.modules, "db", FakeDB)

    # The row the sweep selected: no remediation_count, no attempt.
    task = {"id": "abc-123", "slug": "narrow-select", "note": ""}
    patch = agentic_repair.repair_patch(task, EVIDENCE, category="rework")

    assert calls, "the ceiling did not re-read the counters it was missing"
    assert patch["state"] == "QUARANTINED", (
        "remediation_count=9 is over the ceiling of 8, but the narrow SELECT "
        "hid it and the task was re-queued anyway"
    )
    assert agentic_repair.TERMINAL_NOTE_PREFIX in patch["note"]


def test_high_attempt_parks_even_when_remediation_count_is_low():
    """attempt=170 / remediation_count=6 is the production case."""
    task = {
        "id": "abc-124",
        "slug": "copyfix-beethoven-public-landing-domain-intent-labels-copy",
        "attempt": 170,
        "remediation_count": 6,
        "note": "",
    }
    patch = agentic_repair.repair_patch(task, EVIDENCE, category="conflict")
    assert patch["state"] == "QUARANTINED", (
        "a task attempted 170 times is not converging, whatever the "
        "remediation counter says"
    )


def test_a_task_under_both_ceilings_is_still_repaired():
    """The bound must not be so eager that ordinary retries stop working."""
    task = {"id": "abc-125", "slug": "ordinary", "attempt": 2,
            "remediation_count": 1, "note": "", "prompt": "do the thing"}
    patch = agentic_repair.repair_patch(task, EVIDENCE, category="rework")
    assert patch["state"] == "QUEUED"
    assert patch["attempt"] == 3, "attempt must advance from the true count"


def test_attempt_advances_even_when_the_caller_did_not_select_it(monkeypatch):
    class FakeDB:
        @staticmethod
        def select(table, params):
            return [{"remediation_count": 1, "attempt": 5}]

    monkeypatch.setitem(sys.modules, "db", FakeDB)
    task = {"id": "abc-126", "slug": "narrow", "note": ""}
    patch = agentic_repair.repair_patch(task, EVIDENCE, category="rework")
    assert patch["state"] == "QUEUED"
    assert patch["attempt"] == 6, (
        "the counter must advance from the real value, not stay put because "
        "the caller's SELECT was narrow"
    )


def test_operator_escalations_are_still_never_repaired():
    """The escalation guard runs before every ceiling and must keep doing so."""
    task = {"id": "abc-127", "slug": "escalate-p1-queue-clearance-no-improvement-20260810-nk73",
            "attempt": 400, "remediation_count": 99, "note": ""}
    patch = agentic_repair.repair_patch(task, EVIDENCE, category="rework")
    assert patch["state"] != "QUARANTINED", (
        "an escalation is a question for a person, not a failing build — it must "
        "not be parked by a ceiling any more than it should be repaired"
    )
