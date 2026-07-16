import os
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import realtime_approval_monitor


class RealtimeApprovalMonitorTest(unittest.TestCase):
    def setUp(self):
        realtime_approval_monitor._stats.update({
            "started": False, "polls": 0, "approvals_checked": 0,
            "auto_approved": 0, "manual_flagged": 0, "errors": 0,
            "last_poll": None, "realtime_events": 0,
        })
        realtime_approval_monitor._stop_event.clear()

    def test_stats_returns_dict_copy(self):
        s = realtime_approval_monitor.stats()
        self.assertIsInstance(s, dict)
        self.assertIn("polls", s)
        s["polls"] = 999
        self.assertEqual(realtime_approval_monitor._stats["polls"], 0)

    def test_is_alarm_detects_patterns(self):
        card = {"title": "Key Leak detected in production", "why": "", "value": ""}
        self.assertTrue(realtime_approval_monitor._is_alarm(card))

    def test_is_alarm_returns_false_for_normal_card(self):
        card = {"title": "Deploy update", "why": "routine", "value": "ok"}
        self.assertFalse(realtime_approval_monitor._is_alarm(card))

    def test_check_auto_rules_approves_non_legal(self):
        card = {"kind": "merge", "status": "pending"}
        action, reason = realtime_approval_monitor._check_auto_rules(card)
        self.assertEqual(action, "auto_approve")

    def test_check_auto_rules_flags_secret(self):
        card = {"kind": "secret", "status": "pending"}
        action, reason = realtime_approval_monitor._check_auto_rules(card)
        self.assertEqual(action, "manual")
        self.assertIn("secret", reason)

    def test_check_auto_rules_flags_novel_legal(self):
        card = {"kind": "legal", "status": "pending", "legal_risk_level": "novel"}
        action, reason = realtime_approval_monitor._check_auto_rules(card)
        self.assertEqual(action, "manual")
        self.assertIn("novel", reason)

    def test_check_auto_rules_flags_alarm(self):
        card = {"kind": "merge", "status": "pending",
                "title": "Key Leak in staging", "why": "", "value": ""}
        action, reason = realtime_approval_monitor._check_auto_rules(card)
        self.assertEqual(action, "manual")
        self.assertIn("alarm", reason)

    @mock.patch.object(realtime_approval_monitor, "AUTO_RULES_ENABLED", False)
    def test_check_auto_rules_disabled(self):
        card = {"kind": "merge", "status": "pending"}
        action, reason = realtime_approval_monitor._check_auto_rules(card)
        self.assertEqual(action, "manual")
        self.assertIn("disabled", reason)

    @mock.patch.object(realtime_approval_monitor.db, "select", return_value=[
        {"id": "a1", "kind": "merge", "status": "pending", "title": "t", "why": "", "value": ""}
    ])
    @mock.patch.object(realtime_approval_monitor.db, "update")
    def test_check_pending_approvals_processes_cards(self, update_mock, select_mock):
        count = realtime_approval_monitor.check_pending_approvals()
        self.assertEqual(count, 1)
        self.assertEqual(realtime_approval_monitor._stats["polls"], 1)
        self.assertEqual(realtime_approval_monitor._stats["approvals_checked"], 1)
        update_mock.assert_called()

    @mock.patch.object(realtime_approval_monitor.db, "select", side_effect=Exception("db down"))
    def test_check_pending_approvals_handles_db_error(self, _sel):
        count = realtime_approval_monitor.check_pending_approvals()
        self.assertEqual(count, 0)
        self.assertGreater(realtime_approval_monitor._stats["errors"], 0)

    def test_realtime_callback_processes_pending(self):
        payload = {"record": {"id": "x1", "kind": "merge", "status": "pending",
                              "title": "ok", "why": "", "value": ""}}
        with mock.patch.object(realtime_approval_monitor, "_process_approval") as proc:
            realtime_approval_monitor._realtime_callback(payload)
            proc.assert_called_once()
        self.assertEqual(realtime_approval_monitor._stats["realtime_events"], 1)

    def test_realtime_callback_ignores_non_pending(self):
        payload = {"record": {"id": "x2", "kind": "merge", "status": "approved"}}
        with mock.patch.object(realtime_approval_monitor, "_process_approval") as proc:
            realtime_approval_monitor._realtime_callback(payload)
            proc.assert_not_called()

    @mock.patch.object(realtime_approval_monitor, "ENABLED", False)
    def test_run_disabled_returns_skipped(self):
        result = realtime_approval_monitor.run()
        self.assertTrue(result.get("skipped"))

    @mock.patch.object(realtime_approval_monitor, "ENABLED", True)
    @mock.patch.object(realtime_approval_monitor, "check_pending_approvals", return_value=3)
    def test_run_enabled_returns_processed(self, _check):
        result = realtime_approval_monitor.run()
        self.assertEqual(result["processed"], 3)

    @mock.patch.object(realtime_approval_monitor, "ENABLED", False)
    def test_start_monitor_disabled(self):
        result = realtime_approval_monitor.start_monitor()
        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
