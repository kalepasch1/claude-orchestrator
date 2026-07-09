#!/usr/bin/env python3
"""Tests for merge_stall_monitor.py — the stall-detection safeguard added after the
2026-07-08 incident (0 merges for 32+ hours with no automated signal anywhere)."""
import datetime
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import merge_stall_monitor as mon


def _iso(hours_ago):
    t = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=hours_ago)
    return t.isoformat()


class TestMergeStallMonitor(unittest.TestCase):
    def _select_router(self, cards=None, done=None, merged_age_h=None, existing_alert=None):
        """Build a fake db.select that dispatches on table/params like the real one."""
        def _select(table, params=None):
            params = params or {}
            if table == "tasks" and params.get("state") == "eq.MERGED":
                if merged_age_h is None:
                    return []
                return [{"updated_at": _iso(merged_age_h)}]
            if table == "tasks" and params.get("state") == "eq.DONE":
                return done or []
            if table == "approvals" and params.get("kind") == "in.(verify,material,integrate)":
                return cards or []
            if table == "approvals" and params.get("kind") == "eq.merge_stall":
                return [existing_alert] if existing_alert else []
            return []
        return _select

    def test_no_backlog_is_ok_even_with_old_merge(self):
        with mock.patch.object(mon.db, "select", self._select_router(cards=[], done=[], merged_age_h=100)):
            result = mon.check()
        self.assertEqual(result["status"], "ok")

    def test_recent_merge_with_backlog_is_ok(self):
        cards = [{"id": i} for i in range(5)]
        with mock.patch.object(mon.db, "select", self._select_router(cards=cards, merged_age_h=0.5)):
            result = mon.check()
        self.assertEqual(result["status"], "ok")

    def test_no_merge_history_is_not_a_stall(self):
        cards = [{"id": i} for i in range(5)]
        with mock.patch.object(mon.db, "select", self._select_router(cards=cards, merged_age_h=None)):
            result = mon.check()
        self.assertEqual(result["status"], "ok")
        self.assertIn("no merge history", result["reason"])

    def test_old_merge_with_backlog_alerts(self):
        cards = [{"id": i} for i in range(5)]
        inserted = []
        notified = []
        with mock.patch.object(mon.db, "select", self._select_router(cards=cards, merged_age_h=10)), \
             mock.patch.object(mon.db, "insert", side_effect=lambda t, row: inserted.append((t, row))), \
             mock.patch("notify.send", side_effect=lambda m: notified.append(m)):
            result = mon.check()
        self.assertEqual(result["status"], "alerted")
        self.assertTrue(any(t == "approvals" and row.get("kind") == "merge_stall" for t, row in inserted))
        self.assertTrue(notified)

    def test_does_not_rebuild_a_code_merge_card(self):
        """The alert card must never look like a code-merge card to approval_merge's
        _is_code_merge_card (no slug, title doesn't match 'merge of') so merge_train
        never tries to 'integrate' the alert itself."""
        cards = [{"id": i} for i in range(5)]
        inserted = []
        with mock.patch.object(mon.db, "select", self._select_router(cards=cards, merged_age_h=10)), \
             mock.patch.object(mon.db, "insert", side_effect=lambda t, row: inserted.append((t, row))), \
             mock.patch("notify.send"):
            mon.check()
        alert_rows = [row for t, row in inserted if t == "approvals"]
        self.assertTrue(alert_rows)
        for row in alert_rows:
            self.assertNotIn("slug", row)
            self.assertNotRegex(row.get("title", ""), r"(?i)\bmerge of\b")

    def test_renotify_throttled_within_window(self):
        cards = [{"id": i} for i in range(5)]
        existing = {"id": "abc", "created_at": _iso(1)}  # alerted 1h ago, window is 6h
        inserted = []
        with mock.patch.object(mon.db, "select",
                                self._select_router(cards=cards, merged_age_h=10, existing_alert=existing)), \
             mock.patch.object(mon.db, "insert", side_effect=lambda t, row: inserted.append((t, row))):
            result = mon.check()
        self.assertEqual(result["status"], "already-alerted")
        self.assertFalse(inserted)

    def test_renotifies_after_window_elapses(self):
        cards = [{"id": i} for i in range(5)]
        existing = {"id": "abc", "created_at": _iso(10)}  # alerted 10h ago, window is 6h
        inserted = []
        with mock.patch.object(mon.db, "select",
                                self._select_router(cards=cards, merged_age_h=20, existing_alert=existing)), \
             mock.patch.object(mon.db, "insert", side_effect=lambda t, row: inserted.append((t, row))), \
             mock.patch("notify.send"):
            result = mon.check()
        self.assertEqual(result["status"], "alerted")
        self.assertTrue(inserted)

    def test_fail_soft_on_db_error(self):
        with mock.patch.object(mon.db, "select", side_effect=RuntimeError("db down")):
            result = mon.check()
        self.assertEqual(result["status"], "error")


if __name__ == "__main__":
    unittest.main()
