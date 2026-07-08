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


if __name__ == "__main__":
    unittest.main()
