#!/usr/bin/env python3
"""An empty scoreboard snapshot must say WHY it is empty.

Between 2026-08-22 and 2026-08-30 the file took 634 consecutive records of
`{"timestamp": ..., "routes": {}}`. Nothing in them distinguished "the fleet did
no work" from "the collector died", and reading the file back it was impossible
to tell — which is the worst property a diagnostic can have. Worse still, when
router_stats raised, persist_snapshot() returned None and wrote nothing at all,
so a real outage left a clean gap that looked like an idle weekend.
"""
import json
import os
import sys
import tempfile

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RUNNER)

# A stand-in age for the idle case: old enough that no rolling window contains it.
STALE_OUTCOME_AGE_H = 150.2
WINDOW_H = 72


def _module_with_tmp_file(tmpdir):
    """Fresh scoreboard bound to a temp file, so no test writes .runtime/."""
    for name in ("scoreboard",):
        sys.modules.pop(name, None)
    os.environ["ORCH_SCOREBOARD_DIR"] = tmpdir
    import scoreboard
    return scoreboard


def _run(tmpdir, table=None, rebuild_raises=None, why=None):
    scoreboard = _module_with_tmp_file(tmpdir)

    class FakeRouterStats:
        WINDOW_H = 72

        @staticmethod
        def _rebuild():
            if rebuild_raises:
                raise rebuild_raises
            return table or {}

    sys.modules["router_stats"] = FakeRouterStats
    if why is not None:
        scoreboard._why_empty = lambda: why
    try:
        return scoreboard, scoreboard.persist_snapshot()
    finally:
        sys.modules.pop("router_stats", None)


def test_idle_fleet_records_why_not_just_an_empty_dict():
    with tempfile.TemporaryDirectory() as sandbox:
        _, snap = _run(sandbox, table={},
                       why={"cause": "no_outcomes_in_window",
                            "window_h": WINDOW_H,
                            "newest_outcome_age_h": STALE_OUTCOME_AGE_H})
    assert snap["routes"] == {}
    assert snap["empty_reason"]["cause"] == "no_outcomes_in_window"
    assert snap["empty_reason"]["newest_outcome_age_h"] == STALE_OUTCOME_AGE_H


def test_a_dead_collector_is_recorded_rather_than_silent():
    with tempfile.TemporaryDirectory() as sandbox:
        scoreboard, snap = _run(sandbox, rebuild_raises=RuntimeError("supabase down"))
        assert snap is not None, "an outage must still write a record"
        assert snap["empty_reason"]["cause"] == "router_stats_unavailable"
        assert "supabase down" in snap["empty_reason"]["error"]

        # And it must actually reach the file, not just the return value.
        with open(scoreboard._SCOREBOARD_FILE) as fh:
            written = [json.loads(line) for line in fh if line.strip()]
        assert len(written) == 1
        assert written[0]["empty_reason"]["cause"] == "router_stats_unavailable"


def test_a_populated_snapshot_carries_no_empty_reason():
    table = {"plan": [{"coder": "claude", "score": 0.9, "rate": 0.8, "n": 12}]}
    with tempfile.TemporaryDirectory() as sandbox:
        _, snap = _run(sandbox, table=table)
    assert "empty_reason" not in snap
    assert snap["routes"]["plan"][0]["coder"] == "claude"


def test_why_empty_never_raises_when_the_database_is_unreachable():
    """The explanation must not be able to take down the writer it explains."""
    with tempfile.TemporaryDirectory() as sandbox:
        scoreboard = _module_with_tmp_file(sandbox)

        class ExplodingDb:
            @staticmethod
            def select(*a, **k):
                raise RuntimeError("no route to host")

        saved = sys.modules.get("db")
        sys.modules["db"] = ExplodingDb
        try:
            detail = scoreboard._why_empty()
        finally:
            if saved is not None:
                sys.modules["db"] = saved
            else:
                sys.modules.pop("db", None)
    assert detail["cause"] == "outcomes_unreadable"
    assert "no route to host" in detail["error"]
