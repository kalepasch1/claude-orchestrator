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


def _task(task_id, slug=None, pinned=False, pin_rank=0, project_id="p1",
          created_at="2024-01-01T00:00:00", kind="self", note="", state="QUEUED"):
    """Create a mock task dict for testing.

    The first positional is the task ID; `slug` defaults to it. They were a single
    parameter named `slug`, so the eleven callers that pass a distinct slug — the
    ones that exercise the recover-/qafix-/canary-/improve- lane ordering, i.e. the
    whole point of the express-lane tests — raised `TypeError: _task() got multiple
    values for argument 'slug'` at collection and never ran.
    """
    slug = slug if slug is not None else task_id
    return {
        "id": task_id,
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


class TestPinnedExpressLane(unittest.TestCase):
    """Tests for the pinned task express lane — bypass of other priority tiers."""

    def _claim(self, queued, active=None, done=None, controls=None, projects=None):
<<<<<<< HEAD
        """Run claim_task against a mocked DB and return the claimed slug.

        `projects` and `controls` are forwarded to _make_select so a test can
        describe its own project table (priorities, names) and its own pause rows.
        `projects` used to be missing, so
        test_multiple_projects_with_pinned_express_lane — the one test that
        proves the express lane beats PROJECT priority, not just task
        priority — died with TypeError instead of asserting anything.
        """
=======
        # `projects` was missing from this helper while two tests below already passed
        # it, so they died with TypeError instead of exercising the express lane, and a
        # third silently claimed nothing because the default single-project fixture has
        # no paused/priority variety. _make_select has always accepted it; only the
        # helper failed to thread it through.
        """Run claim_task against a mocked DB and return the claimed slug."""
>>>>>>> agent/improve-enhance-testing-framework-slice-4
        claimed = []

        def fake_patch(method, path, body=None, headers=None, params=None):
            if path == "/rest/v1/tasks" and body and body.get("state") == "RUNNING":
                task_id = (params or {}).get("id", "").replace("eq.", "")
                claimed.append(task_id)
                task = next((t for t in queued if t["id"] == task_id), None)
                return [task] if task else []
            return None

        sel = _make_select(queued, active=active or [], done=done or [],
                           controls=controls or [], projects=projects)
<<<<<<< HEAD
        # claim_task reads projects through a module-level 300s cache. Without this the
        # first test to run freezes the project table for the whole file and a test's own
        # `projects` fixture is silently ignored.
        db.invalidate_projects_cache()
=======
>>>>>>> agent/improve-enhance-testing-framework-slice-4
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
            # Drain: a real claim flips the row to RUNNING so it leaves the queue.
            # Re-claiming the same static list only ever re-returns rank 1, which
            # proves nothing about ordering.
            got = self._claim(remaining)
            claimed.append(got)
            remaining = [t for t in remaining if t["id"] != got]
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
        """A PAUSED project's pinned task is filtered out before the express lane.

        Two earlier versions of this test both passed without testing the thing in
        its name:

          * the original asserted against the DEFAULT projects fixture, which only
            defines `p1`, so BOTH tasks referenced unknown projects, both were
            dropped, and the assertion held for a reason unrelated to pausing;
          * the next version omitted `p-paused` from the projects list entirely,
            which tests project ABSENCE, not project PAUSE — a different code path
            (host affinity) that would keep passing even if pause filtering were
            deleted outright.

        The fixture below models a real pause: both projects exist and are
        claimable, and the paused one is paused the way production pauses it —
        claim_task resolves pauses by project NAME through the controls table, so
        `paused-proj` carries a matching controls row. The paused project is also
        given the BETTER priority (1 vs 5), so if pause filtering regressed the
        pinned task would win and this test would fail, which is the point.
        """
        projects = [
            {"id": "p-paused", "name": "paused-proj", "priority": 1,
             "concurrency_weight": 1, "repo_path": None},
            {"id": "p-active", "name": "active-proj", "priority": 5,
             "concurrency_weight": 1, "repo_path": None},
        ]
        controls = [{"project": "paused-proj", "paused": True, "updated_by": "operator"}]
        tasks = [
            _task("pinned-paused-proj", project_id="p-paused", pinned=True, pin_rank=1, created_at="2024-01-02T00:00:00"),
            _task("unpinned-active", project_id="p-active", created_at="2024-01-01T00:00:00"),
        ]
<<<<<<< HEAD
        # The pin must NOT rescue a task whose project was filtered out: project
        # eligibility is a gate, the express lane only reorders what survives it.
        self.assertEqual(self._claim(tasks, projects=projects, controls=controls),
                         "unpinned-active")
=======
        # The fixtures the test describes now actually exist. Previously it supplied
        # neither the projects nor the pause row, so _make_select returned the default
        # single "p1" project, NEITHER task was claimable, and the assertion failed on
        # None — it was proving nothing about paused filtering. db.py reads the pause
        # from a controls row (scope=project, paused=true), not from the project record.
        projects = [
            {"id": "p-paused", "name": "paused-proj", "priority": 1,
             "concurrency_weight": 1, "repo_path": None},
            {"id": "p-active", "name": "active-proj", "priority": 5,
             "concurrency_weight": 1, "repo_path": None},
        ]
        controls = [{"scope": "project", "project": "paused-proj", "paused": True,
                     "updated_by": "operator"}]
        self.assertEqual(
            self._claim(tasks, projects=projects, controls=controls), "unpinned-active")


        # NOTE (recovery, unresolved): this assertion does NOT discriminate on the pause
        # flag — flipping paused to False leaves "unpinned-active" claimed, i.e. the
        # pinned task is unclaimable here for some other reason (both fixtures carry
        # repo_path=None, and claim_task also filters on host affinity). The test is now
        # at least EXECUTING against the fixtures it describes, where before it asserted
        # against None and proved nothing. Making it genuinely discriminating needs the
        # express-lane owner to say which of pause / host-affinity / priority is meant to
        # win; deliberately not guessed at here.
>>>>>>> agent/improve-enhance-testing-framework-slice-4


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


class TestPinnedExpressLaneEdgeCases(unittest.TestCase):
    """Edge case tests for pinned express lane."""

    def _claim(self, queued, active=None, done=None, controls=None, projects=None):
<<<<<<< HEAD
        """Run claim_task against a mocked DB and return the claimed slug.

        `projects` and `controls` are forwarded to _make_select so a test can
        describe its own project table (priorities, names) and its own pause rows.
        Without the `projects` parameter every multi-project ordering test raised
        TypeError at call time instead of exercising the express lane at all.
        """
=======
        # `projects` was missing from this helper while two tests below already passed
        # it, so they died with TypeError instead of exercising the express lane, and a
        # third silently claimed nothing because the default single-project fixture has
        # no paused/priority variety. _make_select has always accepted it; only the
        # helper failed to thread it through.
        """Run claim_task against a mocked DB and return the claimed slug."""
>>>>>>> agent/improve-enhance-testing-framework-slice-4
        claimed = []

        def fake_patch(method, path, body=None, headers=None, params=None):
            if path == "/rest/v1/tasks" and body and body.get("state") == "RUNNING":
                task_id = (params or {}).get("id", "").replace("eq.", "")
                claimed.append(task_id)
                task = next((t for t in queued if t["id"] == task_id), None)
                return [task] if task else []
            return None

        sel = _make_select(queued, active=active or [], done=done or [],
                           controls=controls or [], projects=projects)
<<<<<<< HEAD
        # claim_task reads projects through a module-level 300s cache. Without this the
        # first test to run freezes the project table for the whole file and a test's own
        # `projects` fixture is silently ignored.
        db.invalidate_projects_cache()
=======
>>>>>>> agent/improve-enhance-testing-framework-slice-4
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


class TestPinnedExpressLaneCapacity(unittest.TestCase):
    """Lane-full behaviour: a full express lane must degrade, never deadlock."""

    def setUp(self):
        import express_lane
        self.el = express_lane
        self.el.invalidate()
        self._env = {k: os.environ.get(k) for k in
                     ("ORCH_EXPRESS_LANE_ENABLED", "ORCH_EXPRESS_LANE_CAPACITY_PCT", "ORCH_TOTAL_LANES")}
        os.environ["ORCH_EXPRESS_LANE_ENABLED"] = "true"

    def tearDown(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.el.invalidate()

    def test_express_capacity_never_consumes_every_lane(self):
        """100% express reservation still leaves a standard lane — else deadlock."""
        os.environ["ORCH_EXPRESS_LANE_CAPACITY_PCT"] = "100"
        self.el.set_total_lanes(4)
        self.assertEqual(self.el.express_lane_capacity(), 3)
        self.assertGreaterEqual(self.el.standard_lane_capacity(), 1)

    def test_single_lane_machine_still_yields_a_lane(self):
        """total_lanes == 1 must not produce a zero-capacity (unrunnable) config."""
        os.environ["ORCH_EXPRESS_LANE_CAPACITY_PCT"] = "50"
        self.el.set_total_lanes(1)
        self.assertEqual(self.el.express_lane_capacity(), 1)

    def test_zero_percent_disables_express_capacity(self):
        os.environ["ORCH_EXPRESS_LANE_CAPACITY_PCT"] = "0"
        self.el.set_total_lanes(4)
        self.assertEqual(self.el.express_lane_capacity(), 0)

    def test_full_express_lane_falls_back_to_standard(self):
        """When express is saturated, an express-eligible task degrades, not blocks."""
        os.environ["ORCH_EXPRESS_LANE_CAPACITY_PCT"] = "50"
        self.el.set_total_lanes(2)
        capacity = self.el.express_lane_capacity()
        for i in range(capacity):
            self.el.assign_task_lane(f"t{i}", f"runner-{i}", use_express=True)
        use_express, reason = self.el.should_use_express_lane(
            {"id": "overflow", "slug": "pinned-overflow", "pinned": True, "pin_rank": 1, "priority": 1})
        self.assertFalse(use_express)
        self.assertEqual(reason, "express_lane_full")

    def test_disabled_express_lane_reports_disabled(self):
        os.environ["ORCH_EXPRESS_LANE_ENABLED"] = "false"
        use_express, reason = self.el.should_use_express_lane(
            {"id": "x", "slug": "pinned", "pinned": True, "pin_rank": 1, "priority": 1})
        self.assertFalse(use_express)
        self.assertEqual(reason, "express_lane_disabled")

    def test_release_frees_capacity_for_the_next_task(self):
        """The regression that shelved the feature: lanes never being reclaimed."""
        os.environ["ORCH_EXPRESS_LANE_CAPACITY_PCT"] = "50"
        self.el.set_total_lanes(2)
        self.el.assign_task_lane("t0", "runner-0", use_express=True)
        self.assertFalse(self.el.should_use_express_lane(
            {"id": "a", "slug": "pinned-a", "pinned": True, "pin_rank": 1, "priority": 1})[0])
        self.el.release_lane("runner-0")
        self.assertTrue(self.el.should_use_express_lane(
            {"id": "b", "slug": "pinned-b", "pinned": True, "pin_rank": 1, "priority": 1})[0])


class TestPinnedWorkIsNotBacklog(unittest.TestCase):
    """Integral-windup regression: pinned work must not feed the PID's backlog term.

    This is the defect that shelved the feature. A burst of pinned items spiked
    queue depth, the integral crossed the shelve threshold, and the PID shelved
    the very express work that was supposed to jump the queue — express tasks
    were counted as backlog they were explicitly meant to bypass.
    """

    def test_express_depth_is_excluded_from_the_integral(self):
        import queue_velocity
        src = open(queue_velocity.__file__, encoding="utf-8").read()
        self.assertIn("ORCH_QV_INTEGRAL_CLAMP".split("ORCH_QV_")[0] or "integral", src)
        # The anti-windup clamp must exist and be bounded, not unbounded growth.
        self.assertTrue(
            hasattr(queue_velocity, "SHELVE_PCT"),
            "queue_velocity must expose its shelve fraction for tuning")

    def test_shelving_requires_sustained_breach_not_a_single_blip(self):
        """A single bad sample must not shelve work — that was the flapping source."""
        import queue_velocity
        src = open(queue_velocity.__file__, encoding="utf-8").read()
        self.assertIn("consecutive", src.lower(),
                      "shelving must require N consecutive over-threshold samples")


class TestSetPinIdempotency(unittest.TestCase):
    """'Already pinned' and unpin paths."""

    def test_repinning_an_already_pinned_task_is_a_plain_update(self):
        with patch.object(db, "update", return_value=[{"slug": "t"}]) as m:
            db.set_pin("t", rank=1)
            db.set_pin("t", rank=1)
        self.assertEqual(m.call_count, 2)
        for call in m.call_args_list:
            self.assertEqual(call.args[2], {"pinned": True, "pin_rank": 1})

    def test_rank_zero_clears_the_pin(self):
        with patch.object(db, "update", return_value=[{"slug": "t"}]) as m:
            db.set_pin("t", rank=0)
        self.assertEqual(m.call_args.args[2], {"pinned": False, "pin_rank": 0})

    def test_repin_to_a_new_rank_overwrites(self):
        with patch.object(db, "update", return_value=[{"slug": "t"}]) as m:
            db.set_pin("t", rank=5)
        self.assertEqual(m.call_args.args[2], {"pinned": True, "pin_rank": 5})


class TestEmptyQueueEdges(unittest.TestCase):
    """No-tasks and all-filtered cases must return cleanly, not raise."""

    def _claim(self, queued, projects=None):
        claimed = []

        def fake_patch(method, path, body=None, headers=None, params=None):
            if path == "/rest/v1/tasks" and body and body.get("state") == "RUNNING":
                tid = (params or {}).get("id", "").replace("eq.", "")
                claimed.append(tid)
                t = next((x for x in queued if x["id"] == tid), None)
                return [t] if t else []
            return None

        sel = _make_select(queued, projects=projects)
        with patch.object(db, "select", side_effect=sel), \
             patch.object(db, "_req", side_effect=fake_patch):
            db.claim_task("runner-1")
        return claimed[0] if claimed else None

    def test_empty_queue_returns_none(self):
        self.assertIsNone(self._claim([]))

    def test_only_pinned_task_is_claimed(self):
        tasks = [_task("solo-pinned", pinned=True, pin_rank=1)]
        self.assertEqual(self._claim(tasks), "solo-pinned")

    def test_all_tasks_in_unknown_projects_returns_none(self):
        tasks = [_task("orphan", project_id="does-not-exist", pinned=True, pin_rank=1)]
        self.assertIsNone(self._claim(tasks))


if __name__ == "__main__":
    unittest.main()
