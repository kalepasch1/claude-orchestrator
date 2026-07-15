import os
import sys
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


if __name__ == "__main__":
    unittest.main()
