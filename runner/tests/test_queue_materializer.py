"""
test_queue_materializer.py - correctness for the DECOMPOSED-parent housekeeping job.

2026-07-11 production bug: _children_by_parent() did a single unordered, unpaginated 6000-row
fetch of the tasks table to build its parent->children map. Once the fleet-wide tasks table
grew past that cap (observed ~8700+ total rows, no ORDER BY, so which 6000 rows came back was
arbitrary), real children silently fell outside the snapshot. That made genuinely in-progress
DECOMPOSED parents look "orphaned" and get incorrectly quarantined -- the dominant driver of a
2,400+ task false-positive QUARANTINED spike. These tests cover: (1) pagination finds children
beyond a single page, (2) an incomplete scan is never treated as "no children" -- orphan
detection is skipped rather than acting on a partial view, and (3) genuinely orphaned tasks
(complete scan, truly zero children, aged past 24h) still get quarantined as originally intended.
"""
import datetime
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import queue_materializer as qm


def _task(tid, slug, state="QUEUED", deps=None):
    return {"id": tid, "slug": slug, "state": state, "deps": deps or []}


class ChildrenByParentPaginationTest(unittest.TestCase):
    """Unit tests for _children_by_parent()'s paginated scan."""

    def test_finds_children_beyond_a_single_page(self):
        """A child that would have fallen outside the OLD 6000-row single-fetch cap must still
        be found once real pagination walks the whole table."""
        page_size = 3
        # page 1: unrelated filler rows; page 2: the actual child of "parent-a"
        page1 = [_task(f"filler-{i}", f"filler-{i}") for i in range(page_size)]
        page2 = [_task("c1", "child-of-a", deps=["parent-a"])]

        fake_db = MagicMock()
        fake_db.select.side_effect = [page1, page2]

        with patch.object(qm, "db", fake_db), \
             patch.object(qm, "CHILD_SCAN_PAGE_SIZE", page_size):
            child_map, complete = qm._children_by_parent(["parent-a"])

        self.assertTrue(complete)
        self.assertEqual(len(child_map["parent-a"]), 1)
        self.assertEqual(child_map["parent-a"][0]["slug"], "child-of-a")

    def test_scan_error_reports_incomplete_not_empty(self):
        fake_db = MagicMock()
        fake_db.select.side_effect = Exception("connection reset")

        with patch.object(qm, "db", fake_db):
            child_map, complete = qm._children_by_parent(["parent-a"])

        self.assertFalse(complete)
        # An error must not be indistinguishable from "genuinely zero children" -- the map
        # can be empty, but the completeness flag must say so explicitly.
        self.assertEqual(child_map["parent-a"], [])

    def test_hitting_page_ceiling_reports_incomplete(self):
        page_size = 2
        max_pages = 2
        # every page comes back completely full, so the scan never naturally terminates
        full_page = [_task(f"x-{i}", f"x-{i}") for i in range(page_size)]

        fake_db = MagicMock()
        fake_db.select.return_value = full_page

        with patch.object(qm, "db", fake_db), \
             patch.object(qm, "CHILD_SCAN_PAGE_SIZE", page_size), \
             patch.object(qm, "CHILD_SCAN_MAX_PAGES", max_pages):
            child_map, complete = qm._children_by_parent(["parent-a"])

        self.assertFalse(complete)
        self.assertEqual(fake_db.select.call_count, max_pages)

    def test_empty_parent_list_is_trivially_complete(self):
        fake_db = MagicMock()
        with patch.object(qm, "db", fake_db):
            child_map, complete = qm._children_by_parent([])
        self.assertTrue(complete)
        self.assertEqual(child_map, {})
        fake_db.select.assert_not_called()


class RunOrphanDetectionTest(unittest.TestCase):
    """Integration-level tests for run()'s orphan-quarantine gating."""

    def _mock_db(self, parents, child_scan_result):
        fake_db = MagicMock()

        def _select(table, params=None):
            if table == "tasks" and (params or {}).get("state") == "eq.DECOMPOSED":
                return parents
            return []

        fake_db.select.side_effect = _select
        fake_db.update = MagicMock()
        return fake_db

    def test_incomplete_scan_never_quarantines_a_parent(self):
        """Core regression: if the child scan couldn't be trusted, a parent with zero VISIBLE
        children must NOT be quarantined -- it might simply have children we didn't see yet."""
        old_parent = {
            "id": "p1", "slug": "old-parent", "state": "DECOMPOSED",
            "created_at": "2020-01-01T00:00:00", "note": "",
        }
        fake_db = self._mock_db([old_parent], None)

        with patch.object(qm, "db", fake_db), \
             patch.object(qm, "_children_by_parent", return_value=({"old-parent": []}, False)):
            result = qm.run()

        self.assertEqual(result["parked"], 0)
        fake_db.update.assert_not_called()

    def test_complete_scan_still_quarantines_genuine_orphan(self):
        """Guard against overcorrecting: a parent that's genuinely childless after a COMPLETE
        scan and old enough must still be quarantined, preserving the original intended cleanup
        behavior for real orphans."""
        old_parent = {
            "id": "p1", "slug": "old-parent", "state": "DECOMPOSED",
            "created_at": "2020-01-01T00:00:00", "note": "",
        }
        fake_db = self._mock_db([old_parent], None)

        with patch.object(qm, "db", fake_db), \
             patch.object(qm, "_children_by_parent", return_value=({"old-parent": []}, True)):
            result = qm.run()

        self.assertEqual(result["parked"], 1)
        fake_db.update.assert_called_once()
        _table, match, patch_body = fake_db.update.call_args.args
        self.assertEqual(match, {"id": "p1"})
        self.assertEqual(patch_body["state"], "QUARANTINED")

    def test_complete_scan_does_not_quarantine_recent_orphan(self):
        """A childless parent younger than 24h must not be quarantined yet -- children may
        still be in the process of being created."""
        recent_parent = {
            "id": "p2", "slug": "recent-parent", "state": "DECOMPOSED",
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "note": "",
        }
        fake_db = self._mock_db([recent_parent], None)

        with patch.object(qm, "db", fake_db), \
             patch.object(qm, "_children_by_parent", return_value=({"recent-parent": []}, True)):
            result = qm.run()

        self.assertEqual(result["parked"], 0)
        fake_db.update.assert_not_called()

    def test_parent_with_visible_children_is_never_treated_as_orphan_regardless_of_completeness(self):
        parent = {
            "id": "p3", "slug": "has-kids", "state": "DECOMPOSED",
            "created_at": "2020-01-01T00:00:00", "note": "",
        }
        child = _task("c1", "kid-1", state="DONE")
        fake_db = self._mock_db([parent], None)

        with patch.object(qm, "db", fake_db), \
             patch.object(qm, "_children_by_parent", return_value=({"has-kids": [child]}, True)):
            result = qm.run()

        # all children DONE/MERGED -> parent should close, not be quarantined as orphaned
        self.assertEqual(result["closed"], 1)
        self.assertEqual(result["parked"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
