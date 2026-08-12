"""Consolidated stale-backlog recovery must never reap or duplicate work.

`stale_backlog_recovery.run_recovery_pipeline` is the consolidation pass that
turns a snapshot of RUNNING tasks into a recovery plan. It had no test, so the
two properties the fleet actually depends on were unpinned:

  1. A slug running more than once yields exactly ONE keeper (the oldest run)
     and cancels the younger duplicates — no task is both cancelled and
     requeued, and no duplicate survives to burn a second executor.
  2. Every entry point is fail-soft. A malformed timestamp, a missing field or
     a non-dict row must degrade to "treat as fresh", never raise, because a
     bad clock reaping healthy tasks is worse than a late recovery.

These tests are snapshot-only: the pipeline is side-effect free by contract, so
they need no DB, no git and no clock control beyond the injected threshold.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner"))
import stale_backlog_recovery as sbr


NOW = 1_800_000_000.0


@pytest.fixture(autouse=True)
def clean():
    sbr.invalidate()
    yield
    sbr.invalidate()


def _task(tid, slug, age_s, state="RUNNING", **extra):
    """A task snapshot row `age_s` seconds old."""
    import time
    return {"id": tid, "slug": slug, "state": state,
            "started_at": time.time() - age_s, **extra}


# --------------------------------------------------------------------------
# 1. detection
# --------------------------------------------------------------------------
def test_only_running_tasks_past_the_threshold_are_stale():
    tasks = [
        _task("a", "old-run", 3600),
        _task("b", "fresh-run", 5),
        _task("c", "done-but-old", 3600, state="COMPLETED"),
    ]
    stale = sbr.detect_stale_tasks(tasks, threshold_sec=600)
    assert [t["id"] for t in stale] == ["a"]


def test_stale_tasks_are_ordered_most_stale_first():
    tasks = [_task("young", "s1", 700), _task("older", "s2", 9000),
             _task("mid", "s3", 3000)]
    stale = sbr.detect_stale_tasks(tasks, threshold_sec=600)
    assert [t["id"] for t in stale] == ["older", "mid", "young"]


@pytest.mark.parametrize("bad", [
    {"id": "x", "slug": "s", "state": "RUNNING"},                     # no timestamp
    {"id": "x", "slug": "s", "state": "RUNNING", "started_at": None},
    {"id": "x", "slug": "s", "state": "RUNNING", "started_at": "nope"},
    {"id": "x", "slug": "s", "state": "RUNNING", "started_at": 4e18},  # future clock
    "not-a-dict",
    None,
])
def test_unusable_rows_are_treated_as_fresh_not_reaped(bad):
    """A bad clock must never cause a healthy task to be reaped."""
    assert sbr.detect_stale_tasks([bad], threshold_sec=1) == []


def test_detect_stale_tasks_tolerates_none_input():
    assert sbr.detect_stale_tasks(None) == []


# --------------------------------------------------------------------------
# 2. consolidation — the behaviour this slice exists to prove
# --------------------------------------------------------------------------
def test_duplicate_runs_keep_the_oldest_and_cancel_the_rest():
    tasks = [_task("newer", "dup", 1000), _task("oldest", "dup", 5000),
             _task("newest", "dup", 100)]
    groups = sbr.consolidate_duplicates(tasks)
    assert set(groups) == {"dup"}
    assert groups["dup"]["keeper"]["id"] == "oldest"
    assert {t["id"] for t in groups["dup"]["to_cancel"]} == {"newer", "newest"}


def test_a_slug_running_once_is_not_consolidated():
    assert sbr.consolidate_duplicates([_task("solo", "unique", 5000)]) == {}


def test_consolidation_is_capped_per_slug_per_pass():
    tasks = [_task(f"d{i}", "dup", 5000 - i * 10)
             for i in range(sbr.MAX_CONSOLIDATIONS + 3)]
    groups = sbr.consolidate_duplicates(tasks)
    assert len(groups["dup"]["to_cancel"]) == sbr.MAX_CONSOLIDATIONS


def test_a_run_with_an_unknown_start_time_never_becomes_the_keeper():
    tasks = [{"id": "unknown", "slug": "dup", "state": "RUNNING"},
             _task("known", "dup", 900)]
    groups = sbr.consolidate_duplicates(tasks)
    assert groups["dup"]["keeper"]["id"] == "known"


# --------------------------------------------------------------------------
# 3. the pipeline: one action per task, cancel wins over requeue
# --------------------------------------------------------------------------
def test_pipeline_cancels_duplicates_and_requeues_the_keeper_only_once():
    tasks = [_task("keep", "dup", 9000), _task("dupe", "dup", 3000),
             _task("lonely", "solo", 4000)]
    result = sbr.run_recovery_pipeline(tasks, threshold_sec=600)

    assert result["detected_stale"] == 3
    assert result["consolidated"] == 1

    by_id = {a["task_id"]: a for a in result["actions"]}
    # every stale task gets exactly one action — no task is both cancelled and requeued
    assert len(result["actions"]) == len(by_id) == 3
    assert by_id["dupe"]["action"] == "cancel"
    assert by_id["dupe"]["target_state"] == "CANCELLED"
    assert by_id["keep"]["action"] == "requeue"
    assert by_id["keep"]["target_state"] == "QUEUED"
    assert by_id["lonely"]["action"] == "requeue"


def test_pipeline_is_idempotent_on_the_same_snapshot():
    """Side-effect free by contract: re-running yields the same plan."""
    tasks = [_task("keep", "dup", 9000), _task("dupe", "dup", 3000)]
    first = sbr.run_recovery_pipeline(tasks, threshold_sec=600)
    second = sbr.run_recovery_pipeline(tasks, threshold_sec=600)
    strip = lambda r: [(a["task_id"], a["action"]) for a in r["actions"]]
    assert strip(first) == strip(second)
    assert first["detected_stale"] == second["detected_stale"]


def test_pipeline_honours_the_batch_limit():
    tasks = [_task(f"t{i}", f"s{i}", 9000) for i in range(20)]
    result = sbr.run_recovery_pipeline(tasks, threshold_sec=600, batch_limit=5)
    assert result["detected_stale"] == 5


def test_pipeline_never_raises_on_garbage():
    result = sbr.run_recovery_pipeline([None, "junk", 42, {"state": "RUNNING"}],
                                       threshold_sec=1)
    assert result["actions_queued"] == 0
    assert sbr.run_recovery_pipeline(None)["detected_stale"] == 0


# --------------------------------------------------------------------------
# 4. action construction + backoff
# --------------------------------------------------------------------------
def test_build_recovery_action_rejects_unknown_action_types():
    assert sbr.build_recovery_action({"id": "a"}, "explode") is None
    assert sbr.build_recovery_action(None, "requeue") is None


def test_backoff_grows_then_caps():
    delays = [sbr.calculate_backoff_delay(n) for n in range(1, 12)]
    assert delays == sorted(delays)
    assert max(delays) <= sbr.MAX_BACKOFF
    assert sbr.calculate_backoff_delay("bad") == float(sbr.RETRY_BACKOFF_BASE)
