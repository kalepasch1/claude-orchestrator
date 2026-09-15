"""The DO NOT WIRE manifest, pinned.

runner/do_not_touch.py's own docstring says "Removing an entry requires satisfying its
prerequisite first, which is asserted by tests/test_do_not_touch.py". That file did not
exist. The manifest that records why four dangerous jobs stay unscheduled was itself
unasserted, which is how `remotegc` came to sit unwired for five weeks after the gate
that made it safe had already landed — nothing compared the manifest to reality.

Run:  python3 -m pytest runner/tests/test_do_not_touch.py -q
"""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import do_not_touch  # noqa: E402

RUNNER_PY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "runner.py")


def _schedule_job_names():
    """Job names appearing in runner.py's _SCHEDULE table, read as text.

    Deliberately textual: importing runner.py starts a fleet.
    """
    src = open(RUNNER_PY, encoding="utf-8").read()
    return set(re.findall(r'\(\s*"[\w.-]+",\s*"([\w.-]+)"\s*,\s*"(?:interval|daily|weekly)"', src))


def test_nothing_on_the_do_not_wire_list_is_scheduled():
    scheduled = _schedule_job_names()
    for job in do_not_touch.DO_NOT_WIRE:
        assert job not in scheduled, (
            f"{job} is on DO_NOT_WIRE but appears in runner.py's _SCHEDULE. "
            f"Reason it must not be: {do_not_touch.reason(job)}"
        )


def test_every_job_wired_after_its_prerequisite_is_actually_scheduled():
    """The inverse, and the one that would have caught this bug.

    A job recorded as wired that is not in _SCHEDULE means the decision was made and
    the wiring was forgotten — exactly what happened to remotegc.
    """
    scheduled = _schedule_job_names()
    for job in getattr(do_not_touch, "WIRED_AFTER_PREREQUISITE", {}):
        assert job in scheduled, (
            f"{job} is recorded as wired after its prerequisite was met, but it is not in "
            f"runner.py's _SCHEDULE. Either schedule it or move it back to DO_NOT_WIRE."
        )


def test_a_job_is_never_in_both_lists():
    both = set(do_not_touch.DO_NOT_WIRE) & set(getattr(do_not_touch, "WIRED_AFTER_PREREQUISITE", {}))
    assert not both, f"contradictory manifest entries: {sorted(both)}"


def test_every_do_not_wire_entry_explains_itself():
    for job, (why, _pre) in do_not_touch.DO_NOT_WIRE.items():
        assert why.strip(), f"{job} is on the list with no reason — the next audit will just rewire it"


def test_blocked_jobs_excludes_anything_already_satisfied():
    for job in do_not_touch.blocked_jobs():
        assert job not in do_not_touch.PREREQUISITE_SATISFIED


def test_helpers_fail_soft_on_unknown_input():
    """CLAUDE.md's rule: unknown job -> False, never an exception."""
    for bad in (None, 123, object(), ""):
        assert do_not_touch.is_deliberately_unscheduled(bad) is False
        assert do_not_touch.reason(bad) == ""
        assert do_not_touch.prerequisite(bad) == ""


def test_render_never_raises():
    assert isinstance(do_not_touch.render(), str)
