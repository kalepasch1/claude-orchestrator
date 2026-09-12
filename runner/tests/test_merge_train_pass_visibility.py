"""A merge-train pass that prints nothing for 45 minutes is not diagnosable.

On 2026-09-01 a pass ran for its full ORCH_MERGE_TRAIN_MAX_RUNTIME_S budget (2700s),
was killed by its own watchdog, merged nothing, and left a log containing four lines
and a thread dump. Three separate reasons, all fixed here:

  * stdout is a log FILE (runner._launch opens one per job), so Python block-buffers it
    at 8KB. The pass prints four short lines up front and then nothing until a candidate
    resolves, so the buffer never filled — and os._exit(3) discarded it.
  * nothing timed the gate's steps. A candidate's gate is a full repo overlay in /tmp, a
    node_modules copy, `npm install`, a Vue compile of every component, and only then
    the suite: five things with very different costs and no way to tell which one ate
    the budget. That is exactly the number needed to decide whether the watchdog budget
    is wrong or the candidate is.
  * the watchdog dumped thread stacks, which give line numbers but not which PROJECT or
    which CARD was in flight.
"""
import re
import time
import os

import pytest

import merge_train as mt


SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "merge_train.py")


def test_phase_reports_a_step_that_took_time(capsys):
    with mt._Phase("suite `npm test`", "/Users/k/Documents/tomorrow"):
        time.sleep(1.05)
    out = capsys.readouterr().out
    assert "gate:tomorrow" in out, "the line must name the repo, not a path"
    assert "suite `npm test`" in out
    assert re.search(r"\b1\.\ds\b", out), f"no duration in {out!r}"


def test_phase_stays_quiet_about_sub_second_steps(capsys):
    """Every candidate runs several of these. Noise would bury the slow one."""
    with mt._Phase("share-deps", "/tmp/repo"):
        pass
    assert capsys.readouterr().out == ""


def test_phase_reports_and_re_raises_on_failure(capsys):
    """A step that BLEW UP after four minutes is the most interesting timing of all."""
    with pytest.raises(ValueError):
        with mt._Phase("ensure-node-deps", "/tmp/repo"):
            raise ValueError("npm exploded")
    out = capsys.readouterr().out
    assert "ensure-node-deps" in out and "ValueError" in out


def test_phase_survives_a_repo_of_none():
    with mt._Phase("x", None):
        pass


def test_in_flight_is_empty_between_cards():
    assert mt._IN_FLIGHT == {}, (
        "_IN_FLIGHT leaked an entry — the finally: in the card loop did not run, and the "
        "watchdog will name a card that finished long ago"
    )


def test_the_card_loop_records_and_clears_in_flight():
    """Structural: the entry must be popped in a finally, not after the call.

    _integrate_card raising is precisely when the watchdog most needs the truth, and
    a pop placed after the call is skipped on exactly that path.
    """
    with open(SRC, encoding="utf-8") as fh:
        body = fh.read()
    m = re.search(r"_IN_FLIGHT\[_pname_\] = .*?_IN_FLIGHT\.pop\(_pname_, None\)",
                  body, re.S)
    assert m, "the card loop no longer records in-flight state around _integrate_card"
    between = m.group(0)
    assert "try:" in between and "finally:" in between, (
        "_IN_FLIGHT is cleared outside a finally — an exception from _integrate_card "
        "would leave a stale entry and the watchdog would report the wrong card"
    )


def test_the_watchdog_names_what_it_killed():
    with open(SRC, encoding="utf-8") as fh:
        body = fh.read()
    watchdog = body[body.index("def _deadline():"):]
    assert "_IN_FLIGHT" in watchdog, (
        "the watchdog no longer names the in-flight project and card — a killed pass is "
        "back to being a thread dump with no idea what it was working on"
    )


def test_stdout_is_line_buffered_at_import():
    """The one line that turns a 45-minute black box into a live log."""
    with open(SRC, encoding="utf-8") as fh:
        head = fh.read(4000)
    assert "line_buffering=True" in head, (
        "merge_train no longer reconfigures stdout; its output goes to a log file, so "
        "Python will block-buffer it at 8KB and a pass will print nothing again"
    )


@pytest.mark.parametrize("phase", [
    "overlay-checkout", "share-deps", "ensure-node-deps", "vue-template-check", "suite ",
])
def test_every_expensive_gate_step_is_timed(phase):
    """These five are the whole per-candidate cost. Missing one hides it."""
    with open(SRC, encoding="utf-8") as fh:
        body = fh.read()
    assert f'_Phase(f"{phase}' in body or f'_Phase("{phase}' in body, (
        f"the {phase!r} step of the gate is no longer timed"
    )
