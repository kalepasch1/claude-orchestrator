#!/usr/bin/env python3
import os, sys, threading, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fleet_config_event_publisher import FleetConfigEventPublisher

_OLD = {"key": "ORCH_FOO", "value": "1", "updated_at": "2026-07-09T00:00:00+00:00"}
_NEW = {"key": "ORCH_FOO", "value": "2", "updated_at": "2026-07-09T00:01:00+00:00"}
_SECRET_ROW = {"key": "MY_SECRET_KEY", "value": "s3cr3t"}


class TestFleetConfigEventPublisher(unittest.TestCase):

    def setUp(self):
        self.pub = FleetConfigEventPublisher()

    # --- metadata completeness ---

    def test_event_has_all_required_fields(self):
        evt = self.pub.publish(old=_OLD, new=_NEW, change_type="updated")
        for field in ("event_id", "timestamp", "key", "old_value", "new_value",
                      "change_type", "risk_classification", "approval_status"):
            self.assertIn(field, evt, f"missing field: {field}")

    def test_create_event_old_value_is_none(self):
        evt = self.pub.publish(old=None, new=_NEW, change_type="created")
        self.assertIsNone(evt["old_value"])
        self.assertIsNotNone(evt["new_value"])

    def test_event_id_is_unique(self):
        e1 = self.pub.publish(old=None, new={"key": "ORCH_A", "value": "1"}, change_type="created")
        e2 = self.pub.publish(old=None, new={"key": "ORCH_B", "value": "2"}, change_type="created")
        self.assertNotEqual(e1["event_id"], e2["event_id"])

    # --- risk classification ---

    def test_safe_orch_key_classified_safe(self):
        evt = self.pub.publish(old=None,
                               new={"key": "ORCH_PARALLEL", "value": "4"},
                               change_type="created")
        self.assertEqual(evt["risk_classification"], "safe")

    def test_credential_key_classified_unsafe(self):
        evt = self.pub.publish(old=None, new=_SECRET_ROW, change_type="created")
        self.assertEqual(evt["risk_classification"], "unsafe_key")

    # --- approval status ---

    def test_approval_auto_approved_for_safe(self):
        evt = self.pub.publish(old=_OLD, new=_NEW, change_type="updated")
        self.assertEqual(evt["approval_status"], "auto_approved")

    def test_approval_blocked_for_unsafe_key(self):
        evt = self.pub.publish(old=None, new=_SECRET_ROW, change_type="created")
        self.assertEqual(evt["approval_status"], "blocked")

    # --- duplicate suppression ---

    def test_duplicate_suppressed_when_same_value(self):
        self.pub.publish(old=None, new=_NEW, change_type="created")
        result = self.pub.publish(old=_NEW, new=_NEW, change_type="updated")
        self.assertIsNone(result, "consecutive identical value should be suppressed")

    def test_value_change_not_suppressed(self):
        self.pub.publish(old=None, new=_OLD, change_type="created")
        result = self.pub.publish(old=_OLD, new=_NEW, change_type="updated")
        self.assertIsNotNone(result)
        self.assertEqual(result["new_value"]["value"], "2")

    def test_delete_clears_suppression_state(self):
        # Create → delete → re-create with same value must not be suppressed
        self.pub.publish(old=None, new=_NEW, change_type="created")
        self.pub.publish(old=_NEW, new=None, change_type="deleted")
        result = self.pub.publish(old=None, new=_NEW, change_type="created")
        self.assertIsNotNone(result, "re-creation after deletion must emit an event")

    # --- polling API ---

    def test_get_events_returns_stored_events(self):
        self.pub.publish(old=_OLD, new=_NEW, change_type="updated")
        evts = self.pub.get_events()
        self.assertEqual(len(evts), 1)
        self.assertEqual(evts[0]["change_type"], "updated")

    def test_get_events_since_timestamp_filter(self):
        self.pub.publish(old=_OLD, new=_NEW, change_type="updated")
        self.pub.publish(old=None,
                         new={"key": "ORCH_BAR", "value": "x"},
                         change_type="created")
        past = "2000-01-01T00:00:00+00:00"
        evts = self.pub.get_events(since_timestamp=past)
        self.assertEqual(len(evts), 2)

    def test_get_events_since_timestamp_excludes_old(self):
        self.pub.publish(old=_OLD, new=_NEW, change_type="updated")
        future = "2099-01-01T00:00:00+00:00"
        evts = self.pub.get_events(since_timestamp=future)
        self.assertEqual(evts, [])

    def test_get_events_limit(self):
        for i in range(10):
            self.pub.publish(old=None,
                             new={"key": f"ORCH_K{i}", "value": str(i)},
                             change_type="created")
        evts = self.pub.get_events(limit=3)
        self.assertEqual(len(evts), 3)

    # --- subscription API ---

    def test_subscribe_callback_called(self):
        received = []
        self.pub.subscribe(received.append)
        self.pub.publish(old=_OLD, new=_NEW, change_type="updated")
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["key"], "ORCH_FOO")

    def test_unsubscribe_stops_notifications(self):
        received = []
        self.pub.subscribe(received.append)
        self.pub.unsubscribe(received.append)
        self.pub.publish(old=_OLD, new=_NEW, change_type="updated")
        self.assertEqual(received, [])

    def test_multiple_subscribers_all_notified(self):
        r1, r2 = [], []
        self.pub.subscribe(r1.append)
        self.pub.subscribe(r2.append)
        self.pub.publish(old=_OLD, new=_NEW, change_type="updated")
        self.assertEqual(len(r1), 1)
        self.assertEqual(len(r2), 1)

    # --- concurrency ---

    def test_concurrent_publishes_thread_safe(self):
        """Concurrent publishes from different threads must not deadlock or lose events."""
        n = 10
        results = []
        errors = []

        def publish_one(i):
            try:
                evt = self.pub.publish(
                    old=None,
                    new={"key": f"ORCH_C{i}", "value": str(i)},
                    change_type="created",
                )
                results.append(evt)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=publish_one, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        self.assertEqual(errors, [], f"thread errors: {errors}")
        self.assertEqual(len(results), n)
        evts = self.pub.get_events()
        self.assertEqual(len(evts), n)


if __name__ == "__main__":
    unittest.main()
