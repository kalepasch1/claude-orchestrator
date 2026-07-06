#!/usr/bin/env python3
"""Tests for tasks.pinned / tasks.pin_rank priority override in db.claim_task."""
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db


def _task(slug, pinned=False, pin_rank=0, project_id="p1", created_at="2024-01-01T00:00:00"):
    return {
        "id": slug,
        "slug": slug,
        "project_id": project_id,
        "state": "QUEUED",
        "pinned": pinned,
        "pin_rank": pin_rank,
        "deps": [],
        "created_at": created_at,
    }


def _make_select(queued, active=None, recent=None, projects=None, done=None):
    """Return a select() mock that dispatches on the table+params the real code sends."""
    active = active or []
    recent = recent or []
    projects = projects or [{"id": "p1", "name": "proj", "priority": 5, "concurrency_weight": 1}]
    done = done or []

    def _sel(table, params=None):
        params = params or {}
        if table == "projects":
            return projects
        if table == "controls":
            return []
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


class TestPinnedTaskSorting(unittest.TestCase):

    def _claim(self, queued, active=None, done=None):
        """Run claim_task against a mocked DB and return the claimed slug."""
        claimed = []

        def fake_patch(method, path, body=None, headers=None, params=None):
            if path == "/rest/v1/tasks" and body and body.get("state") == "RUNNING":
                task_id = (params or {}).get("id", "").replace("eq.", "")
                claimed.append(task_id)
                task = next((t for t in queued if t["id"] == task_id), None)
                return [task] if task else []
            return None

        sel = _make_select(queued, active=active or [], done=done or [])
        with patch.object(db, "select", side_effect=sel), \
             patch.object(db, "_req", side_effect=fake_patch):
            db.claim_task("runner-1")

        return claimed[0] if claimed else None

    def test_pinned_task_claimed_before_normal(self):
        tasks = [
            _task("normal-a", created_at="2024-01-01T00:00:00"),
            _task("pinned-1", pinned=True, pin_rank=1, created_at="2024-01-02T00:00:00"),
        ]
        self.assertEqual(self._claim(tasks), "pinned-1")

    def test_pin_rank_order_respected(self):
        tasks = [
            _task("pin-low", pinned=True, pin_rank=5),
            _task("pin-high", pinned=True, pin_rank=1),
            _task("pin-mid", pinned=True, pin_rank=3),
        ]
        self.assertEqual(self._claim(tasks), "pin-high")

    def test_unpinned_tasks_unaffected_without_column(self):
        # Rows without pinned/pin_rank keys (old schema) should fall through as unpinned.
        old_row = {"id": "old", "slug": "old", "project_id": "p1",
                   "state": "QUEUED", "deps": [], "created_at": "2024-01-01T00:00:00"}
        pinned_row = _task("fresh-pin", pinned=True, pin_rank=1, created_at="2024-01-02T00:00:00")
        tasks = [old_row, pinned_row]
        self.assertEqual(self._claim(tasks), "fresh-pin")

    def test_normal_fifo_preserved_when_none_pinned(self):
        tasks = [
            _task("first",  created_at="2024-01-01T00:00:00"),
            _task("second", created_at="2024-01-02T00:00:00"),
        ]
        self.assertEqual(self._claim(tasks), "first")

    def test_pinned_after_unpin_rank_zero(self):
        # rank=0 means unpinned (same as pinned=False)
        tasks = [
            _task("normal",    created_at="2024-01-01T00:00:00"),
            _task("rank-zero", pinned=False, pin_rank=0, created_at="2024-01-02T00:00:00"),
        ]
        self.assertEqual(self._claim(tasks), "normal")


class TestSetPin(unittest.TestCase):

    def test_set_pin_calls_update_with_correct_fields(self):
        with patch.object(db, "update", return_value=[]) as mock_update:
            db.set_pin("my-task", rank=2)
        mock_update.assert_called_once_with("tasks", {"slug": "my-task"}, {"pinned": True, "pin_rank": 2})

    def test_set_pin_unpin_when_rank_zero(self):
        with patch.object(db, "update", return_value=[]) as mock_update:
            db.set_pin("my-task", rank=0)
        mock_update.assert_called_once_with("tasks", {"slug": "my-task"}, {"pinned": False, "pin_rank": 0})

    def test_set_pin_default_rank_is_1(self):
        with patch.object(db, "update", return_value=[]) as mock_update:
            db.set_pin("my-task")
        mock_update.assert_called_once_with("tasks", {"slug": "my-task"}, {"pinned": True, "pin_rank": 1})


if __name__ == "__main__":
    unittest.main()
