"""Regression: gating one task must not read the same `projects` row twice.

`gate_merged_patch()` calls `resolve_target()` to learn the integration branch -- which
reads the project row -- and then read that row a second time to learn the production
branch. Two control-plane round-trips to answer one question about one row, on every
gated task, with `reconcile()` walking hundreds of tasks per cycle.

The obvious fix is to thread the row through as a fourth parameter. That is the wrong
fix: `resolve_target(task, repo, prod_branch)`'s 3-arg signature is public and is stubbed
by name elsewhere in the suite, so widening it breaks callers that have every right to
exist. `_project_row()` caches instead, so the signature is untouched.

These tests assert the round-trip COUNT, not just the returned value -- a cache that
returns the right answer while still hitting the network would pass a value-only test and
fix nothing.
"""
import os
import sys
import time

RUNNER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner")
if RUNNER not in sys.path:
    sys.path.insert(0, RUNNER)

import merge_truth  # noqa: E402

ROW = {
    "id": "p1", "name": "beethoven", "repo_path": "/tmp/beethoven",
    "staging_branch": "orchestrator/dev", "prod_branch": "master", "default_base": "master",
}


class CountingDB:
    """Records every select so tests can assert on round-trip count, not just values."""

    def __init__(self, rows_by_id=None, raises=None):
        self.rows_by_id = {"p1": [ROW]} if rows_by_id is None else rows_by_id
        self.raises = raises
        self.calls = []

    def select(self, table, params):
        self.calls.append((table, params))
        if self.raises:
            raise self.raises
        pid = str(params.get("id", "")).replace("eq.", "")
        return list(self.rows_by_id.get(pid, []))

    @property
    def project_selects(self):
        return [c for c in self.calls if c[0] == "projects"]


_REAL_DB = merge_truth.db
_REAL_TTL = merge_truth._PROJECT_ROW_TTL_S


def _install(db, ttl=60):
    """Point merge_truth at a counting db with a known TTL and an empty cache."""
    merge_truth.db = db
    merge_truth._PROJECT_ROW_TTL_S = ttl
    merge_truth.invalidate_project_cache()
    return db


def teardown_function(_):
    """Restore module state. These tests patch a module-level singleton by assignment, so
    leaving it swapped would silently corrupt every later test in the session."""
    merge_truth.db = _REAL_DB
    merge_truth._PROJECT_ROW_TTL_S = _REAL_TTL
    merge_truth.invalidate_project_cache()


def test_row_is_returned_correctly():
    _install(CountingDB())
    assert merge_truth._project_row("p1") == ROW


def test_second_read_inside_ttl_does_not_hit_the_database():
    db = _install(CountingDB())
    merge_truth._project_row("p1")
    merge_truth._project_row("p1")
    merge_truth._project_row("p1")
    assert len(db.project_selects) == 1


def test_cache_expires_after_ttl():
    db = _install(CountingDB(), ttl=1)
    merge_truth._project_row("p1")
    # Age the cache entry rather than sleeping.
    with merge_truth._project_rows_lock:
        stamp, row = merge_truth._project_rows["p1"]
        merge_truth._project_rows["p1"] = (stamp - 5, row)
    merge_truth._project_row("p1")
    assert len(db.project_selects) == 2


def test_invalidate_forces_a_fresh_read():
    db = _install(CountingDB())
    merge_truth._project_row("p1")
    merge_truth.invalidate_project_cache()
    merge_truth._project_row("p1")
    assert len(db.project_selects) == 2


def test_use_cache_false_bypasses_the_cache():
    db = _install(CountingDB())
    merge_truth._project_row("p1")
    merge_truth._project_row("p1", use_cache=False)
    assert len(db.project_selects) == 2


def test_ttl_zero_disables_caching_entirely():
    db = _install(CountingDB(), ttl=0)
    merge_truth._project_row("p1")
    merge_truth._project_row("p1")
    assert len(db.project_selects) == 2
    assert merge_truth._project_rows == {}


def test_distinct_projects_are_cached_independently():
    db = _install(CountingDB({"p1": [ROW], "p2": [dict(ROW, id="p2", name="pareto")]}))
    assert merge_truth._project_row("p1")["name"] == "beethoven"
    assert merge_truth._project_row("p2")["name"] == "pareto"
    assert merge_truth._project_row("p1")["name"] == "beethoven"
    assert len(db.project_selects) == 2


def test_database_error_is_fail_soft_and_not_cached():
    db = _install(CountingDB(raises=RuntimeError("control plane down")))
    assert merge_truth._project_row("p1") is None
    assert merge_truth._project_row("p1") is None
    # A transient outage must not pin "unresolvable" for the whole TTL.
    assert len(db.project_selects) == 2
    assert merge_truth._project_rows == {}


def test_missing_project_is_not_cached():
    db = _install(CountingDB({}))
    assert merge_truth._project_row("nope") is None
    assert merge_truth._project_row("nope") is None
    assert len(db.project_selects) == 2


def test_none_project_id_never_touches_the_database():
    db = _install(CountingDB())
    assert merge_truth._project_row(None) is None
    assert db.project_selects == []


def test_cache_is_bounded():
    _install(CountingDB({str(i): [dict(ROW, id=str(i))]
                         for i in range(merge_truth._PROJECT_ROW_CACHE_MAX + 5)}))
    for i in range(merge_truth._PROJECT_ROW_CACHE_MAX + 5):
        merge_truth._project_row(str(i))
    assert len(merge_truth._project_rows) <= merge_truth._PROJECT_ROW_CACHE_MAX


def test_gating_one_task_reads_the_project_row_once(monkeypatch):
    """The actual payoff: one gated task, one projects round-trip (was two)."""
    db = _install(CountingDB())
    monkeypatch.setattr(merge_truth, "verify_merge_reachable",
                        lambda *a, **k: (merge_truth.OK, "ancestor"))
    task = {"id": "t1", "slug": "s", "project_id": "p1", "artifact_commit": "abc123"}
    patch = {"state": "MERGED", "artifact_commit": "abc123"}

    assert merge_truth.gate_merged_patch(task, patch, fetch=False) == patch
    assert len(db.project_selects) == 1


def test_gate_still_sees_the_production_branch_through_the_cache(monkeypatch):
    """Caching must not cost the prod-branch evidence the preceding commit added."""
    _install(CountingDB())
    seen = {}
    monkeypatch.setattr(merge_truth, "verify_merge_reachable",
                        lambda *a, **k: (seen.update(k) or (merge_truth.OK, "ancestor")))
    task = {"id": "t1", "slug": "s", "project_id": "p1", "artifact_commit": "abc123"}
    merge_truth.gate_merged_patch(task, {"state": "MERGED", "artifact_commit": "abc123"},
                                  fetch=False)
    assert seen.get("also_branches") == ("master",)


def test_cache_survives_concurrent_readers():
    """Module-level singleton + lock: concurrent gating must still collapse the reads."""
    import threading
    db = _install(CountingDB())
    barrier = threading.Barrier(8)

    def read():
        barrier.wait()
        merge_truth._project_row("p1")

    threads = [threading.Thread(target=read) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # Racing readers may legitimately double-read before the first write lands, but the
    # cache must collapse 8 readers to fewer than 8 round-trips and end up populated.
    assert len(db.project_selects) < 8
    assert "p1" in merge_truth._project_rows


def test_non_merged_patch_never_reads_the_project_row():
    db = _install(CountingDB())
    task = {"id": "t1", "slug": "s", "project_id": "p1"}
    patch = {"state": "QUEUED"}
    assert merge_truth.gate_merged_patch(task, patch) == patch
    assert db.project_selects == []


def test_ttl_is_env_tunable():
    """ORCH_-prefixed so the TTL is fleet-pushable via fleet_control.py."""
    assert merge_truth._PROJECT_ROW_TTL_S is not None
    with open(os.path.join(RUNNER, "merge_truth.py")) as fh:
        assert "ORCH_MERGE_TRUTH_PROJECT_TTL_S" in fh.read()


def test_cached_row_is_not_copied_for_callers():
    """The cache hands back the same object, so callers must treat it as read-only.

    This test exists to make that contract explicit and to fail loudly if a future change
    starts copying -- which would be fine, but is a behaviour change worth noticing.
    """
    _install(CountingDB())
    first = merge_truth._project_row("p1")
    second = merge_truth._project_row("p1")
    assert second is first


def test_cache_stamps_the_wall_clock():
    _install(CountingDB())
    merge_truth._project_row("p1")
    with merge_truth._project_rows_lock:
        stamp, _ = merge_truth._project_rows["p1"]
    assert abs(time.time() - stamp) < 5
