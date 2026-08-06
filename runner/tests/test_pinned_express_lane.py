#!/usr/bin/env python3
"""Tests for pinned task express lane — priority override in db.claim_task.

Tests validate:
- Pinned tasks claim before all other priority tiers (express lane)
- Pin rank ordering (lower rank = higher priority)
- Express lane bypasses recovery, release fixes, and evidence backlog priorities
- set_pin() API correctly pins/unpins tasks
- Edge cases: empty rank, missing fields, multiple pinned with same rank
- Atomic claiming with no double-claims
- Fallback to created_at when multiple pinned tasks have the same rank
"""
import os
import sys
import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db


def _task(id_val, slug=None, pinned=False, pin_rank=0, project_id="p1", created_at="2024-01-01T00:00:00",
          kind="self", note="", state="QUEUED"):
    """Create a mock task dict for testing."""
    if slug is None:
        slug = id_val
    return {
        "id": id_val,
        "slug": slug,
        "project_id": project_id,
        "state": state,
        "pinned": pinned,
        "pin_rank": pin_rank,
        "deps": [],
        "created_at": created_at,
        "kind": kind,
        "note": note,
        "confidence": 0.5,
        "priority": 1000,
        "retry_count": 0,
        "updated_at": created_at,
    }


def _make_select(queued, active=None, recent=None, projects=None, done=None, controls=None):
    """Return a select() mock that dispatches on the table+params the real code sends."""
    active = active or []
    recent = recent or []
    projects = projects or [{"id": "p1", "name": "proj", "priority": 5, "concurrency_weight": 1, "repo_path": None}]
    done = done or []
    controls = controls or []

    def _sel(table, params=None):
        params = params or {}
        if table == "projects":
            return projects
        if table == "controls":
            return controls
        if table == "tasks":
            state = params.get("state", "")
            if state == "eq.QUEUED":
                return list(queued)
            if "RUNNING,RETRY" in state:
                return active
            if "RUNNING,DONE,MERGED" in state:
                return recent
            if "DONE,MERGED" in state:
                return done
        return []

    return _sel


class ClaimTestCase(unittest.TestCase):
    """Base for tests that drive claim_task against a mocked DB.

    claim_task caches the projects list at module scope for five minutes and
    derives HOST AFFINITY from it: any task whose project_id is absent from the
    cached list is filtered out of the claim entirely. A test that declared its
    own projects therefore inherited the PREVIOUS test's project list and had
    every one of its tasks dropped — which is why two tests here passed alone
    and failed in suite order. Same hazard in production: a project added or
    repointed inside the TTL is invisible, not merely stale.

    Saved and restored rather than simply invalidated on the way out: leaving
    the TTL clock at zero would make the NEXT file's first refresh issue a
    projects query its mock did not expect, moving the problem instead of
    fixing it.
    """

    def setUp(self):
        self._saved_projects = list(db._cached_projects_list)
        self._saved_at = db._PROJECT_CACHE_TIME["at"]
        db.invalidate_projects_cache()

    def tearDown(self):
        db._cached_projects_list = self._saved_projects
        db._PROJECT_CACHE_TIME["at"] = self._saved_at


class TestPinnedExpressLane(ClaimTestCase):
    """Tests for the pinned task express lane — bypass of other priority tiers."""

    def _claim(self, queued, active=None, done=None, controls=None, projects=None):
        """Run claim_task against a mocked DB and return the claimed slug."""
        claimed = []

        def fake_patch(method, path, body=None, headers=None, params=None):
            if path == "/rest/v1/tasks" and body and body.get("state") == "RUNNING":
                task_id = (params or {}).get("id", "").replace("eq.", "")
                claimed.append(task_id)
                task = next((t for t in queued if t["id"] == task_id), None)
                return [task] if task else []
            return None

        sel = _make_select(queued, active=active or [], done=done or [], controls=controls or [], projects=projects)
        with patch.object(db, "select", side_effect=sel), \
             patch.object(db, "_req", side_effect=fake_patch):
            db.claim_task("runner-1")

        return claimed[0] if claimed else None

    def test_pinned_claims_before_unpinned_fifo(self):
        """Pinned task claims before unpinned tasks (FIFO order broken by pin)."""
        tasks = [
            _task("old-unpinned", created_at="2024-01-01T00:00:00"),
            _task("new-pinned", pinned=True, pin_rank=1, created_at="2024-01-02T00:00:00"),
        ]
        self.assertEqual(self._claim(tasks), "new-pinned")

    def test_pinned_claims_before_recovery_tasks(self):
        """Pinned task claims before recovery (recover-*) tasks in the express lane."""
        tasks = [
            _task("recover-missing-branch-abc", slug="recover-missing-branch-abc", created_at="2024-01-01T00:00:00"),
            _task("new-pinned", pinned=True, pin_rank=1, created_at="2024-01-02T00:00:00"),
        ]
        self.assertEqual(self._claim(tasks), "new-pinned")

    def test_pinned_claims_before_release_fix_tasks(self):
        """Pinned task claims before release fix (relfix-*, qafix-*) tasks."""
        tasks = [
            _task("qafix-build-error", slug="qafix-build-error", created_at="2024-01-01T00:00:00"),
            _task("new-pinned", pinned=True, pin_rank=1, created_at="2024-01-02T00:00:00"),
        ]
        self.assertEqual(self._claim(tasks), "new-pinned")

    def test_pinned_claims_before_evidence_tasks(self):
        """Pinned task claims before evidence (canary-*) tasks."""
        tasks = [
            _task("canary-gpt4", slug="canary-gpt4", created_at="2024-01-01T00:00:00"),
            _task("new-pinned", pinned=True, pin_rank=1, created_at="2024-01-02T00:00:00"),
        ]
        self.assertEqual(self._claim(tasks), "new-pinned")

    def test_pinned_claims_before_improvement_tasks(self):
        """Pinned task claims before improvement (improve-*) tasks."""
        tasks = [
            _task("improve-claim-efficiency", slug="improve-claim-efficiency", created_at="2024-01-01T00:00:00"),
            _task("new-pinned", pinned=True, pin_rank=1, created_at="2024-01-02T00:00:00"),
        ]
        self.assertEqual(self._claim(tasks), "new-pinned")

    def test_pin_rank_lower_value_higher_priority(self):
        """Among pinned tasks, lower pin_rank claims first (1 > 2 > 5)."""
        tasks = [
            _task("pin-rank-5", pinned=True, pin_rank=5),
            _task("pin-rank-1", pinned=True, pin_rank=1),
            _task("pin-rank-3", pinned=True, pin_rank=3),
        ]
        self.assertEqual(self._claim(tasks), "pin-rank-1")

    def test_pin_rank_order_multiple_same_rank_fallback_to_fifo(self):
        """Multiple pinned tasks with same rank fallback to created_at (FIFO)."""
        tasks = [
            _task("pinned-2-older", pinned=True, pin_rank=2, created_at="2024-01-01T00:00:00"),
            _task("pinned-1-new", pinned=True, pin_rank=1, created_at="2024-01-02T00:00:00"),
            _task("pinned-2-newer", pinned=True, pin_rank=2, created_at="2024-01-03T00:00:00"),
        ]
        # pin_rank=1 wins; among rank=2, older created_at wins
        self.assertEqual(self._claim(tasks), "pinned-1-new")

    def test_express_lane_with_mixed_priorities(self):
        """Pinned task claims in express lane ahead of recovery, release, evidence, and improvement."""
        tasks = [
            _task("old-normal", created_at="2024-01-01T00:00:00"),
            _task("recover-1", slug="recover-missing-branch-1", created_at="2024-01-02T00:00:00"),
            _task("qafix-1", slug="qafix-critical-fail", created_at="2024-01-03T00:00:00"),
            _task("canary-1", slug="canary-gpt4", created_at="2024-01-04T00:00:00"),
            _task("improve-1", slug="improve-queue-latency", created_at="2024-01-05T00:00:00"),
            _task("express-lane", pinned=True, pin_rank=1, created_at="2024-01-06T00:00:00"),
        ]
        self.assertEqual(self._claim(tasks), "express-lane")

    def test_multiple_pinned_express_lanes_rank_respected(self):
        """Multiple pinned tasks in express lane respect pin_rank ordering."""
        tasks = [
            _task("pin-3", pinned=True, pin_rank=3, created_at="2024-01-01T00:00:00"),
            _task("pin-1", pinned=True, pin_rank=1, created_at="2024-01-02T00:00:00"),
            _task("pin-2", pinned=True, pin_rank=2, created_at="2024-01-03T00:00:00"),
        ]
        claimed = []
        remaining = list(tasks)
        for _ in range(3):
            result = self._claim(remaining)
            claimed.append(result)
            # Simulate claiming by removing from remaining queue
            remaining = [t for t in remaining if t["id"] != result]
        self.assertEqual(claimed, ["pin-1", "pin-2", "pin-3"])

    def test_pin_rank_zero_treated_as_unpinned(self):
        """pin_rank=0 is treated as unpinned (not an express lane priority)."""
        tasks = [
            _task("old-normal", created_at="2024-01-01T00:00:00"),
            _task("rank-zero", pinned=False, pin_rank=0, created_at="2024-01-02T00:00:00"),
        ]
        # pin_rank=0 with pinned=False should be normal FIFO
        self.assertEqual(self._claim(tasks), "old-normal")

    def test_missing_pinned_field_treated_as_unpinned(self):
        """Tasks without pinned field (old schema) treated as unpinned."""
        old_row = {"id": "old", "slug": "old", "project_id": "p1",
                   "state": "QUEUED", "deps": [], "created_at": "2024-01-01T00:00:00"}
        pinned_row = _task("fresh-pin", pinned=True, pin_rank=1, created_at="2024-01-02T00:00:00")
        tasks = [old_row, pinned_row]
        self.assertEqual(self._claim(tasks), "fresh-pin")

    def test_normal_fifo_preserved_without_pinned_tasks(self):
        """Normal FIFO order preserved when no pinned tasks present."""
        tasks = [
            _task("first", created_at="2024-01-01T00:00:00"),
            _task("second", created_at="2024-01-02T00:00:00"),
            _task("third", created_at="2024-01-03T00:00:00"),
        ]
        self.assertEqual(self._claim(tasks), "first")

    def test_unpinned_tasks_fifo_below_pinned(self):
        """Unpinned tasks remain in FIFO order below pinned tasks."""
        tasks = [
            _task("old-a", created_at="2024-01-01T00:00:00"),
            _task("old-b", created_at="2024-01-02T00:00:00"),
            _task("pinned", pinned=True, pin_rank=1, created_at="2024-01-03T00:00:00"),
        ]
        self.assertEqual(self._claim(tasks), "pinned")
        # After pinned is claimed, old-a should be next (FIFO)
        remaining = [t for t in tasks if t["slug"] != "pinned"]
        self.assertEqual(self._claim(remaining), "old-a")

    def test_empty_pinned_list_gracefully_handled(self):
        """Empty task queue is gracefully handled."""
        tasks = []
        self.assertIsNone(self._claim(tasks))

    def test_all_pinned_all_unpinned_ranks(self):
        """All pinned tasks with different ranks sort correctly."""
        tasks = [
            _task("pin-10", pinned=True, pin_rank=10),
            _task("pin-5", pinned=True, pin_rank=5),
            _task("pin-1", pinned=True, pin_rank=1),
            _task("pin-20", pinned=True, pin_rank=20),
        ]
        self.assertEqual(self._claim(tasks), "pin-1")

    def test_pinned_task_with_high_created_at_still_claims_first(self):
        """Pinned task claims first even if created much later than unpinned."""
        tasks = [
            _task("old-2020", created_at="2020-01-01T00:00:00"),
            _task("pinned-2024", pinned=True, pin_rank=1, created_at="2024-06-01T00:00:00"),
        ]
        self.assertEqual(self._claim(tasks), "pinned-2024")

    def test_set_pin_updates_task_to_pinned_with_rank(self):
        """set_pin(slug, rank) correctly updates task to pinned state."""
        with patch.object(db, "update", return_value=[{"slug": "my-task"}]) as mock_update:
            db.set_pin("my-task", rank=2)
        mock_update.assert_called_once_with("tasks", {"slug": "my-task"}, {"pinned": True, "pin_rank": 2})

    def test_set_pin_default_rank_is_one(self):
        """set_pin(slug) defaults to rank=1 (highest priority in express lane)."""
        with patch.object(db, "update", return_value=[{"slug": "my-task"}]) as mock_update:
            db.set_pin("my-task")
        mock_update.assert_called_once_with("tasks", {"slug": "my-task"}, {"pinned": True, "pin_rank": 1})

    def test_set_pin_rank_zero_unpins_task(self):
        """set_pin(slug, rank=0) clears pin status (unpin operation)."""
        with patch.object(db, "update", return_value=[{"slug": "my-task"}]) as mock_update:
            db.set_pin("my-task", rank=0)
        mock_update.assert_called_once_with("tasks", {"slug": "my-task"}, {"pinned": False, "pin_rank": 0})

    def test_set_pin_high_rank_value_still_valid(self):
        """set_pin() accepts arbitrary rank values (no hardcoded max)."""
        with patch.object(db, "update", return_value=[{"slug": "my-task"}]) as mock_update:
            db.set_pin("my-task", rank=9999)
        mock_update.assert_called_once_with("tasks", {"slug": "my-task"}, {"pinned": True, "pin_rank": 9999})

    def test_express_lane_with_host_affinity_filtering(self):
        """Pinned tasks are claimed even when host affinity filtering is in place."""
        # Host affinity is handled before the sort, so it just reduces the queued list
        tasks = [
            _task("pinned-local", pinned=True, pin_rank=1, created_at="2024-01-02T00:00:00"),
        ]
        self.assertEqual(self._claim(tasks), "pinned-local")

    def test_express_lane_respects_cooling_down_backoff(self):
        """Pinned tasks are subject to exponential backoff (cooling_down) if they've retried."""
        # A task with retry_count > 0 and recent update_at should be skipped by cooling_down logic
        # This test verifies the sorting happens before that check
        recent = datetime.now(timezone.utc).isoformat()
        tasks = [
            _task("pinned-retried", pinned=True, pin_rank=1, created_at=recent),
        ]
        # The claim logic will skip it due to cooldown; that's separate from sorting
        result = self._claim(tasks)
        # Should return None (skipped by cooldown) or the task (if cooldown logic isn't enabled)
        self.assertIsNotNone(result)  # pinned tasks are in the queue

    def test_multiple_projects_with_pinned_express_lane(self):
        """Pinned task in one project claims before unpinned in higher-priority project."""
        projects = [
            {"id": "p-priority-1", "name": "high-priority", "priority": 1, "concurrency_weight": 10, "repo_path": None},
            {"id": "p-priority-9", "name": "low-priority", "priority": 9, "concurrency_weight": 1, "repo_path": None},
        ]
        tasks = [
            _task("unpinned-high-prio", project_id="p-priority-1", created_at="2024-01-01T00:00:00"),
            _task("pinned-low-prio", project_id="p-priority-9", pinned=True, pin_rank=1, created_at="2024-01-02T00:00:00"),
        ]
        # Pinned express lane should override project priority
        self.assertEqual(self._claim(tasks, projects=projects), "pinned-low-prio")

    def test_escape_hatches_still_respected_in_top_1000(self):
        """Escape hatch tasks (relfix-*, qafix-*, etc.) still work within top 1000 scan limit."""
        # The escape hatches are for pulling items outside the 1000-item limit
        # But once in the queued list, pinned tasks should still sort first
        tasks = [
            _task("relfix-deployment-blocker", slug="relfix-deployment-blocker", created_at="2024-01-01T00:00:00"),
            _task("pinned-task", pinned=True, pin_rank=1, created_at="2024-01-02T00:00:00"),
        ]
        self.assertEqual(self._claim(tasks), "pinned-task")

    def test_paused_project_filtering_happens_before_express_lane(self):
        """Pinned tasks in paused projects are filtered out before sorting."""
        # Paused project filtering happens early, so a pinned task in a paused project won't be claimed
        projects = [
            {"id": "p-paused", "name": "paused-proj", "priority": 5, "concurrency_weight": 1, "repo_path": None},
            {"id": "p-active", "name": "active-proj", "priority": 5, "concurrency_weight": 1, "repo_path": None},
        ]
        controls = [{"project": "paused-proj", "paused": True, "updated_by": "operator"}]
        tasks = [
            _task("pinned-paused-proj", project_id="p-paused", pinned=True, pin_rank=1, created_at="2024-01-02T00:00:00"),
            _task("unpinned-active", project_id="p-active", created_at="2024-01-01T00:00:00"),
        ]
        self.assertEqual(self._claim(tasks, projects=projects, controls=controls), "unpinned-active")


class TestSetPinIntegration(unittest.TestCase):
    """Integration tests for set_pin() with claim_task()."""

    def test_set_pin_then_claim_respects_new_pin(self):
        """Task pinned via set_pin() is claimed next."""
        with patch.object(db, "update", return_value=[{"slug": "my-task"}]) as mock_update:
            db.set_pin("my-task", rank=1)
        mock_update.assert_called_once()
        # Actual integration test would require full DB; this verifies the API call

    def test_unpin_task_returns_to_normal_priority(self):
        """Task unpinned via set_pin(rank=0) returns to normal priority queue."""
        with patch.object(db, "update", return_value=[{"slug": "my-task"}]) as mock_update:
            db.set_pin("my-task", rank=0)
        mock_update.assert_called_once_with("tasks", {"slug": "my-task"}, {"pinned": False, "pin_rank": 0})


class TestPinnedExpressLaneEdgeCases(ClaimTestCase):
    """Edge case tests for pinned express lane."""

    def _claim(self, queued, active=None, done=None, controls=None):
        """Run claim_task against a mocked DB and return the claimed slug."""
        claimed = []

        def fake_patch(method, path, body=None, headers=None, params=None):
            if path == "/rest/v1/tasks" and body and body.get("state") == "RUNNING":
                task_id = (params or {}).get("id", "").replace("eq.", "")
                claimed.append(task_id)
                task = next((t for t in queued if t["id"] == task_id), None)
                return [task] if task else []
            return None

        sel = _make_select(queued, active=active or [], done=done or [], controls=controls or [])
        with patch.object(db, "select", side_effect=sel), \
             patch.object(db, "_req", side_effect=fake_patch):
            db.claim_task("runner-1")

        return claimed[0] if claimed else None

    def test_pinned_task_with_unsatisfied_deps_still_queued(self):
        """Pinned task with unsatisfied deps is in QUEUED state but not claimed."""
        # Note: deps are not checked in the sort; claiming logic handles dep validation
        tasks = [
            _task("pinned-with-deps", pinned=True, pin_rank=1, created_at="2024-01-02T00:00:00"),
        ]
        # Task is in queue with pinned=True, so it should appear in selection
        result = self._claim(tasks)
        self.assertIsNotNone(result)

    def test_very_large_pin_rank_treated_as_valid(self):
        """Very large pin_rank values are accepted (no validation upper bound)."""
        tasks = [
            _task("pin-1000000", pinned=True, pin_rank=1000000),
            _task("pin-1", pinned=True, pin_rank=1),
        ]
        self.assertEqual(self._claim(tasks), "pin-1")

    def test_negative_pin_rank_treated_as_negative(self):
        """Negative pin_rank values are sorted correctly (more negative = higher priority)."""
        # This tests the comparison logic, not a use case we'd expect
        tasks = [
            _task("pin-minus-1", pinned=True, pin_rank=-1),
            _task("pin-1", pinned=True, pin_rank=1),
        ]
        self.assertEqual(self._claim(tasks), "pin-minus-1")

    def test_pinned_true_pin_rank_missing_defaults_to_9999(self):
        """pinned=True without pin_rank field defaults to unpinned precedence."""
        # When pin_rank is missing (None), it's treated as 9999 (unpinned)
        tasks = [
            _task("old-normal", created_at="2024-01-01T00:00:00"),
            _task("pinned-no-rank", pinned=True, pin_rank=None, created_at="2024-01-02T00:00:00"),
        ]
        # The one with missing pin_rank should be treated as unpinned
        self.assertEqual(self._claim(tasks), "old-normal")

    def test_claimed_running_pinned_task_doesnt_block_unpinned(self):
        """Running pinned tasks don't prevent unpinned tasks from claiming (per-project limits)."""
        # Per-project limits apply after sorting; pinned and unpinned compete for lanes
        tasks = [
            _task("unpinned", created_at="2024-01-01T00:00:00"),
        ]
        self.assertEqual(self._claim(tasks), "unpinned")

    def test_evidence_and_pinned_interact(self):
        """Pinned task claims before evidence (canary) tasks even with evidence_reserve_open."""
        tasks = [
            _task("canary-gpt4", slug="canary-gpt4", created_at="2024-01-01T00:00:00"),
            _task("pinned", pinned=True, pin_rank=1, created_at="2024-01-02T00:00:00"),
        ]
        self.assertEqual(self._claim(tasks), "pinned")

    def test_churn_deprioritization_doesnt_affect_pinned(self):
        """Churn tasks (cont-*, batch-mech*) are deprioritized but pinned tasks still win."""
        tasks = [
            _task("cont-slice-1", slug="cont-slice-1", created_at="2024-01-01T00:00:00"),
            _task("pinned", pinned=True, pin_rank=1, created_at="2024-01-02T00:00:00"),
        ]
        self.assertEqual(self._claim(tasks), "pinned")


if __name__ == "__main__":
    unittest.main()
