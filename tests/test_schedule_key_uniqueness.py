"""Every `_SCHEDULE` entry must carry a unique key.

`_scheduler_tick` keys last-fire times as `_sched_last[key]`, so two entries
sharing a key share ONE timestamp: whichever fires first stamps it and starves
the other for a full interval. Nothing raised and nothing logged, so
`pipelineselftest-3600` (two entries) and `cadeextras-dy` (two entries) each ran
at half their configured cadence, indefinitely. `_DISABLED_JOBS` matches on the
same key, so disabling one silently disabled the other too.

These tests are the regression guard: the collision fails here instead of
quietly halving a monitor's cadence in production.
"""
import collections
import importlib.util
import os
import sys

import pytest

_RUNNER_DIR = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "runner")
)


@pytest.fixture(scope="module")
def runner():
    """Load runner/runner.py BY PATH.

    `runner/` is both a package and the directory holding runner.py, so a bare
    `import runner` resolves to whichever landed on sys.path first and
    sys.modules caches that choice for the rest of the session — the answer
    then depends on pytest's collection order. Loading by explicit location
    removes the ambiguity. The alias keeps `sys.modules["runner"]` untouched.
    """
    if _RUNNER_DIR not in sys.path:
        sys.path.insert(0, _RUNNER_DIR)
    path = os.path.join(_RUNNER_DIR, "runner.py")
    spec = importlib.util.spec_from_file_location("_runner_under_test", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["_runner_under_test"] = module
    spec.loader.exec_module(module)
    return module


def test_no_duplicate_schedule_keys(runner):
    counts = collections.Counter(entry[0] for entry in runner._SCHEDULE)
    dupes = {k: v for k, v in counts.items() if v > 1}
    assert dupes == {}, (
        "duplicate _SCHEDULE keys share one _sched_last slot and starve each "
        f"other: {sorted(dupes)}"
    )


def test_duplicate_schedule_keys_reports_the_colliding_entries(runner):
    schedule = [
        ("a-60", "a", "interval", 60),
        ("b-60", "b", "interval", 60),
        ("a-60", "a_other", "interval", 60),
    ]
    found = runner.duplicate_schedule_keys(schedule)
    assert set(found) == {"a-60"}
    assert [e[1] for e in found["a-60"]] == ["a", "a_other"]


def test_duplicate_schedule_keys_is_clean_on_a_unique_schedule(runner):
    schedule = [("a-60", "a", "interval", 60), ("b-60", "b", "interval", 60)]
    assert runner.duplicate_schedule_keys(schedule) == {}


def test_duplicate_schedule_keys_is_fail_soft_on_junk(runner):
    """A malformed schedule must not wedge the scheduler's boot."""
    assert runner.duplicate_schedule_keys([None, 7]) == {}
    assert runner.duplicate_schedule_keys(object()) == {}


def test_the_live_schedule_is_checked_by_default(runner):
    """Calling with no argument reads the real _SCHEDULE, not a copy."""
    assert runner.duplicate_schedule_keys() == {}


def test_both_pipeline_selftest_entries_survived_the_rename(runner):
    """The fix was unique keys, not deleting one of the two jobs."""
    jobs = [entry[1] for entry in runner._SCHEDULE]
    assert "pipeline_selftest.py" in jobs
    assert "pipelineselftest" in jobs


def test_both_cadeextras_times_survived_the_rename(runner):
    times = sorted(entry[3] for entry in runner._SCHEDULE
                   if entry[1] == "cadeextras" and entry[2] == "daily")
    assert times == [(3, 15), (4, 30)]
