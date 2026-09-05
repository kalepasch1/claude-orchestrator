"""Both of the medic's process reapers were blind, and neither said so.

`etimes` (elapsed seconds) is a procps keyword. macOS ships BSD ps, which does not
have it. Asked for a column it does not know, BSD ps writes

    ps: etimes: keyword not found

to stderr, returns 1 — and then prints every row anyway, WITHOUT that column. So the
caller gets well-formed output with one field missing. Both reapers split each row and
require a fixed field count, so every row fell one short and was skipped, and the loops
saw an empty process table.

Measured on this Mac, 2026-09-02, with 771 processes running and a deliberately spawned
parentless `nuxt build` sitting in front of it:

    _agent_procs()            -> []
    _orphaned_build_procs()   -> []
    reap_orphaned_builds()    -> 0     the orphan survived

Nothing errored. `sh()` does not check returncode here, and even if it did, ps returns
1 while still producing usable output. A reaper that silently reaps nothing looks
exactly like a machine with nothing to reap, which is why the pre-existing
multi-hour-agent reaper had been inert for as long as it has existed on macOS.

The fix is `etime` — the portable, formatted column ([[DD-]HH:]MM:SS) — parsed to
seconds. The tests below cover the parser and then pin the ps invocation itself,
because the parser being right does not help if the wrong keyword is asked for again.
"""
import os
import re
import subprocess

import pytest

import resource_medic as rm


@pytest.mark.parametrize("text,seconds", [
    ("00:04", 4),
    ("08:42", 522),
    ("1:00", 60),
    ("05:53:29", 5 * 3600 + 53 * 60 + 29),
    ("12:53:07", 12 * 3600 + 53 * 60 + 7),
    ("2-03:04:05", 2 * 86400 + 3 * 3600 + 4 * 60 + 5),
    ("10-00:00:00", 10 * 86400),
])
def test_etime_parses_every_shape_ps_emits(text, seconds):
    assert rm._etime_seconds(text) == seconds


@pytest.mark.parametrize("junk", ["", "   ", None, "abc", "1:2:3:4", "x-01:00", "--"])
def test_unparseable_elapsed_times_are_dropped_not_guessed(junk):
    """A row whose age cannot be read must be skipped, never treated as age 0 —
    age 0 with a low threshold would make the reaper kill a process that just started."""
    assert rm._etime_seconds(junk) is None


def test_this_platforms_ps_actually_understands_the_keyword_we_ask_for():
    """The test that would have caught the original bug in one second.

    It runs the real ps with the real column list and requires every row to carry all
    four fields. On macOS with `etimes` this fails; with `etime` it passes. On Linux
    both work, so the test is portable and still meaningful.
    """
    out = subprocess.run(["ps", "-axo", "pid=,ppid=,etime=,command="],
                         capture_output=True, text=True, timeout=30).stdout
    rows = [l for l in out.splitlines() if l.strip()]
    assert len(rows) > 20, "ps returned almost nothing; this check is not looking at anything"
    short = [l for l in rows if len(l.strip().split(None, 3)) < 4]
    assert not short, (
        f"{len(short)} of {len(rows)} ps rows are missing a column — this platform's ps "
        f"does not understand the keyword list. First: {short[0]!r}"
    )


def test_the_elapsed_column_is_readable_on_every_row():
    """Not just present — parseable. A column that is there but in an unexpected
    format leaves the reaper just as blind, only noisier."""
    out = subprocess.run(["ps", "-axo", "pid=,ppid=,etime=,command="],
                         capture_output=True, text=True, timeout=30).stdout
    bad = []
    for line in out.splitlines():
        parts = line.strip().split(None, 3)
        if len(parts) < 4:
            continue
        if rm._etime_seconds(parts[2]) is None:
            bad.append(parts[2])
    assert not bad, f"unparseable elapsed times from the real ps: {bad[:5]}"


@pytest.mark.parametrize("fn", ["_agent_procs", "_orphaned_build_procs"])
def test_neither_reaper_asks_for_the_procps_only_keyword(fn):
    """Structural, and aimed squarely at the regression. Both call sites had it."""
    import inspect
    src = inspect.getsource(getattr(rm, fn))
    # Match the ps ARGUMENT LIST only. The prose above it deliberately names the broken
    # keyword to explain the bug, and a whole-source grep would trip on that.
    cols = re.findall(r'sh\(\s*"ps"\s*,\s*"-axo"\s*,\s*"([^"]+)"', src)
    assert cols, f"{fn} no longer calls ps with an explicit column list"
    for spec in cols:
        assert "etimes" not in spec, (
            f"{fn} asks ps for `etimes`, which BSD ps does not have. It will silently "
            f"see an empty process table on macOS and reap nothing. Column spec: {spec!r}"
        )
        assert "etime=" in spec, f"{fn} no longer asks ps for an elapsed time: {spec!r}"


def test_the_reaper_can_see_a_real_process_on_this_machine():
    """Sanity: with the fix, the scan reads a populated table rather than nothing.

    Asserted on the FULL row set, not on orphans — a healthy machine legitimately has
    zero orphaned builds, and asserting on that would make this test flap.
    """
    out = subprocess.run(["ps", "-axo", "pid=,ppid=,etime=,command="],
                         capture_output=True, text=True, timeout=30).stdout
    parsed = 0
    for line in out.splitlines():
        parts = line.strip().split(None, 3)
        if len(parts) == 4 and rm._etime_seconds(parts[2]) is not None:
            parsed += 1
    assert parsed > 20, f"only {parsed} process rows survived parsing; the scan is blind"
