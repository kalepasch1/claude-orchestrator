#!/usr/bin/env python3
import os, sys, time, threading, unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fleet_config_watcher import FleetConfigWatcher
import fleet_config_watcher as fcw

_ROW_A  = {"key": "ORCH_FOO", "value": "1", "updated_at": "2026-07-09T00:00:00+00:00"}
_ROW_A2 = {"key": "ORCH_FOO", "value": "2", "updated_at": "2026-07-09T00:01:00+00:00"}
_ROW_B  = {"key": "ORCH_BAR", "value": "x", "updated_at": "2026-07-09T00:00:00+00:00"}


class TestDetectChanges(unittest.TestCase):

    def setUp(self):
        self.w = FleetConfigWatcher()

    def test_create_detected(self):
        self.w._snapshot = {}
        changes = self.w.detect_changes({"ORCH_FOO": _ROW_A})
        self.assertEqual(len(changes), 1)
        kind, old, new = changes[0]
        self.assertEqual(kind, "created")
        self.assertIsNone(old)
        self.assertEqual(new["key"], "ORCH_FOO")

    def test_update_detected(self):
        self.w._snapshot = {"ORCH_FOO": _ROW_A}
        changes = self.w.detect_changes({"ORCH_FOO": _ROW_A2})
        self.assertEqual(len(changes), 1)
        kind, old, new = changes[0]
        self.assertEqual(kind, "updated")
        self.assertEqual(old["value"], "1")
        self.assertEqual(new["value"], "2")

    def test_delete_detected(self):
        self.w._snapshot = {"ORCH_FOO": _ROW_A}
        changes = self.w.detect_changes({})
        self.assertEqual(len(changes), 1)
        kind, old, new = changes[0]
        self.assertEqual(kind, "deleted")
        self.assertEqual(old["key"], "ORCH_FOO")
        self.assertIsNone(new)

    def test_no_change_when_value_unchanged(self):
        self.w._snapshot = {"ORCH_FOO": _ROW_A}
        # Same value, different metadata fields — not a change
        same = dict(_ROW_A, updated_at="2026-07-09T00:05:00+00:00", note="updated note")
        changes = self.w.detect_changes({"ORCH_FOO": same})
        self.assertEqual(changes, [])

    def test_multiple_changes_detected_in_one_poll(self):
        self.w._snapshot = {"ORCH_FOO": _ROW_A}
        current = {"ORCH_FOO": _ROW_A2, "ORCH_BAR": _ROW_B}
        changes = self.w.detect_changes(current)
        types = {c[0] for c in changes}
        self.assertIn("updated", types)
        self.assertIn("created", types)
        self.assertEqual(len(changes), 2)

    def test_publisher_called_with_correct_args(self):
        pub = MagicMock()
        self.w.set_publisher(pub)
        self.w._snapshot = {}
        current = {"ORCH_FOO": _ROW_A}
        changes = self.w.detect_changes(current)
        with self.w._lock:
            self.w._snapshot = current
        for change_type, old, new in changes:
            pub.publish(old=old, new=new, change_type=change_type)
        pub.publish.assert_called_once()
        _, kwargs = pub.publish.call_args
        self.assertEqual(kwargs["change_type"], "created")
        self.assertIsNone(kwargs["old"])
        self.assertEqual(kwargs["new"]["key"], "ORCH_FOO")

    def test_fetch_current_returns_keyed_dict(self):
        fake_db = MagicMock()
        fake_db.select.return_value = [_ROW_A, _ROW_B]
        w = FleetConfigWatcher()
        with patch.object(fcw, "db", fake_db):
            result = w._fetch_current()
        self.assertIn("ORCH_FOO", result)
        self.assertIn("ORCH_BAR", result)
        self.assertEqual(result["ORCH_FOO"]["value"], "1")

    def test_change_detected_within_1_second(self):
        """End-to-end: subscriber receives event within 1 s of a mocked DB change."""
        call_count = [0]

        def mock_select(table, params=None):
            call_count[0] += 1
            if call_count[0] <= 1:
                return []           # initial snapshot: empty
            return [_ROW_A]         # all subsequent polls: one new row

        fake_db = MagicMock()
        fake_db.select.side_effect = mock_select

        pub = MagicMock()
        w = FleetConfigWatcher(poll_interval=0.05)   # 50 ms for fast test

        with patch.object(fcw, "db", fake_db):
            w.set_publisher(pub)
            start = time.time()
            w.start()
            deadline = start + 1.0
            while time.time() < deadline:
                if pub.publish.called:
                    break
                time.sleep(0.01)
            elapsed = time.time() - start
            w.stop()

        self.assertTrue(pub.publish.called, "publisher should have been called within 1 s")
        self.assertLess(elapsed, 1.0, f"latency {elapsed:.3f}s exceeds 1 s target")
        _, kwargs = pub.publish.call_args
        self.assertEqual(kwargs["change_type"], "created")


if __name__ == "__main__":
    unittest.main()
