import os
import sys
import time
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fleet_control


class FleetControlTest(unittest.TestCase):

    def test_safe_key_rejects_credentials(self):
        self.assertTrue(fleet_control._safe_key("ORCH_AUTO_PULL"))
        self.assertTrue(fleet_control._safe_key("MAX_PARALLEL"))
        self.assertFalse(fleet_control._safe_key("OPENAI_API_KEY"))
        self.assertFalse(fleet_control._safe_key("ORCH_SECRET_TOKEN"))

    def test_all_target_done_when_expected_hosts_ack(self):
        fake_db = MagicMock()
        fake_db.select.side_effect = [
            [{
                "id": "ctrl-1",
                "target": "all",
                "action": "reload_config",
                "handled_by": ["mac1"],
                "params": {"expected_hosts": ["mac1", "mac2"]},
            }],
            [],
        ]

        with patch.object(fleet_control, "db", fake_db), patch.object(fleet_control, "HOST", "mac2"):
            self.assertEqual(fleet_control.process_controls(), 1)

        update_patch = fake_db.update.call_args.args[2]
        self.assertEqual(update_patch["handled_by"], ["mac1", "mac2"])
        self.assertTrue(update_patch["done"])

    def test_all_target_without_expected_hosts_stays_open_for_other_machines(self):
        fake_db = MagicMock()
        fake_db.select.side_effect = [
            [{
                "id": "ctrl-1",
                "target": "all",
                "action": "reload_config",
                "handled_by": [],
                "params": {},
            }],
            [],
        ]

        with patch.object(fleet_control, "db", fake_db), patch.object(fleet_control, "HOST", "mac2"):
            self.assertEqual(fleet_control.process_controls(), 1)

        update_patch = fake_db.update.call_args.args[2]
        self.assertEqual(update_patch["handled_by"], ["mac2"])
        self.assertFalse(update_patch["done"])

    def test_pause_action_sets_host_scoped_kill_switch_and_acks(self):
        fake_db = MagicMock()
        fake_db.select.return_value = [{
            "id": "ctrl-p",
            "target": "Mac-2.local",
            "action": "pause",
            "handled_by": [],
            "params": {"reason": "cost spike"},
        }]
        fake_ks = MagicMock()

        with patch.object(fleet_control, "db", fake_db), \
             patch.object(fleet_control, "kill_switch", fake_ks), \
             patch.object(fleet_control, "HOST", "Mac-2.local"):
            self.assertEqual(fleet_control.process_controls(), 1)

        # soft-pauses THIS host only (not global), and does not restart/exit.
        fake_ks.pause.assert_called_once()
        kwargs = fake_ks.pause.call_args.kwargs
        self.assertEqual(kwargs.get("scope"), "host")
        self.assertEqual(kwargs.get("project"), "Mac-2.local")
        self.assertEqual(kwargs.get("reason"), "cost spike")
        # single-host target -> row closes immediately after this host acks.
        update_patch = fake_db.update.call_args.args[2]
        self.assertEqual(update_patch["handled_by"], ["Mac-2.local"])
        self.assertTrue(update_patch["done"])

    def test_resume_action_lifts_host_pause(self):
        fake_db = MagicMock()
        fake_db.select.return_value = [{
            "id": "ctrl-r",
            "target": "Mac-2.local",
            "action": "resume",
            "handled_by": [],
            "params": {},
        }]
        fake_ks = MagicMock()

        with patch.object(fleet_control, "db", fake_db), \
             patch.object(fleet_control, "kill_switch", fake_ks), \
             patch.object(fleet_control, "HOST", "Mac-2.local"):
            self.assertEqual(fleet_control.process_controls(), 1)

        fake_ks.resume.assert_called_once()
        self.assertEqual(fake_ks.resume.call_args.kwargs.get("scope"), "host")
        self.assertEqual(fake_ks.resume.call_args.kwargs.get("project"), "Mac-2.local")
        fake_ks.pause.assert_not_called()


    def _make_db(self, old_value=None):
        fake_db = MagicMock()
        fake_db.select.return_value = [{"value": old_value}] if old_value is not None else []
        fake_db.insert.return_value = None
        return fake_db

    def test_update_fleet_config_emits_event_on_orch_key_change(self):
        fake_db = self._make_db(old_value="false")
        fake_ws = MagicMock()
        before_ms = int(time.time() * 1000)

        with patch.object(fleet_control, "db", fake_db), \
             patch.object(fleet_control, "_ws_server", fake_ws):
            fleet_control.update_fleet_config("ORCH_AUTO_PULL", "true")

        after_ms = int(time.time() * 1000)

        fake_ws.publish_event.assert_called_once()
        channel, payload = fake_ws.publish_event.call_args.args
        self.assertEqual(channel, "config/*")
        self.assertEqual(payload["event_type"], "config_changed")
        self.assertEqual(payload["key"], "ORCH_AUTO_PULL")
        self.assertEqual(payload["old_value"], "false")
        self.assertEqual(payload["new_value"], "true")
        self.assertEqual(payload["publisher"], "fleet_control")
        self.assertGreaterEqual(payload["timestamp"], before_ms)
        self.assertLessEqual(payload["timestamp"], after_ms + 100)

    def test_update_fleet_config_emits_event_when_key_is_new(self):
        fake_db = self._make_db(old_value=None)
        fake_ws = MagicMock()

        with patch.object(fleet_control, "db", fake_db), \
             patch.object(fleet_control, "_ws_server", fake_ws):
            fleet_control.update_fleet_config("ORCH_EXTRA_CODERS", "3")

        fake_ws.publish_event.assert_called_once()
        _, payload = fake_ws.publish_event.call_args.args
        self.assertIsNone(payload["old_value"])
        self.assertEqual(payload["new_value"], "3")

    def test_update_fleet_config_no_event_for_non_orch_key(self):
        fake_db = self._make_db(old_value="4")
        fake_ws = MagicMock()

        with patch.object(fleet_control, "db", fake_db), \
             patch.object(fleet_control, "_ws_server", fake_ws):
            fleet_control.update_fleet_config("MAX_PARALLEL", "8")

        fake_ws.publish_event.assert_not_called()

    def test_update_fleet_config_no_event_when_value_unchanged(self):
        fake_db = self._make_db(old_value="true")
        fake_ws = MagicMock()

        with patch.object(fleet_control, "db", fake_db), \
             patch.object(fleet_control, "_ws_server", fake_ws):
            fleet_control.update_fleet_config("ORCH_AUTO_PULL", "true")

        fake_ws.publish_event.assert_not_called()

    def test_update_fleet_config_no_event_without_ws_server(self):
        fake_db = self._make_db(old_value="false")

        with patch.object(fleet_control, "db", fake_db), \
             patch.object(fleet_control, "_ws_server", None):
            row = fleet_control.update_fleet_config("ORCH_AUTO_PULL", "true")

        self.assertEqual(row["key"], "ORCH_AUTO_PULL")
        self.assertEqual(row["value"], "true")

    def test_update_fleet_config_rejects_unsafe_key(self):
        with self.assertRaises(ValueError):
            fleet_control.update_fleet_config("OPENAI_API_KEY", "sk-abc")


if __name__ == "__main__":
    unittest.main()
