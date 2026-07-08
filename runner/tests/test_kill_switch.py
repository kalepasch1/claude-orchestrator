import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import kill_switch


class KillSwitchTest(unittest.TestCase):
    def test_resume_updates_existing_global_control_before_insert(self):
        fake_db = MagicMock()
        fake_db.update.return_value = [{"scope": "global", "paused": False}]

        with patch.object(kill_switch, "db", fake_db):
            out = kill_switch.resume(scope="global", by="test")

        self.assertEqual(out, "RESUMED global")
        fake_db.update.assert_called_once()
        fake_db.insert.assert_not_called()
        table, match, patch_row = fake_db.update.call_args.args
        self.assertEqual(table, "controls")
        self.assertEqual(match, {"scope": "global"})
        self.assertEqual(patch_row["paused"], False)

    def test_project_pause_does_not_update_every_project_row(self):
        fake_db = MagicMock()
        fake_db.update.return_value = [{"scope": "project", "project": "tomorrow", "paused": True}]

        with patch.object(kill_switch, "db", fake_db):
            kill_switch.pause(scope="project", project="tomorrow", by="test")

        _table, match, _patch = fake_db.update.call_args.args
        self.assertEqual(match, {"scope": "project", "project": "tomorrow"})

    def test_host_scoped_pause_halts_only_this_machine(self):
        fake_db = MagicMock()
        # a pause targeted at THIS host (matched via alias) must register as paused...
        fake_db.select.return_value = [
            {"scope": "host", "project": "mac-2", "paused": True, "updated_at": "2026-07-08T00:00:00"},
        ]
        with patch.object(kill_switch, "db", fake_db), \
             patch.object(kill_switch, "HOST", "mac-2.local"):
            self.assertTrue(kill_switch.is_paused())

    def test_host_scoped_pause_for_other_machine_is_ignored(self):
        fake_db = MagicMock()
        # a pause for a DIFFERENT host must not pause this one.
        fake_db.select.return_value = [
            {"scope": "host", "project": "mac-1", "paused": True, "updated_at": "2026-07-08T00:00:00"},
        ]
        with patch.object(kill_switch, "db", fake_db), \
             patch.object(kill_switch, "HOST", "mac-2.local"):
            self.assertFalse(kill_switch.is_paused())

    def test_latest_host_decision_wins(self):
        fake_db = MagicMock()
        # rows arrive newest-first (order=updated_at.desc); a later resume lifts an earlier pause.
        fake_db.select.return_value = [
            {"scope": "host", "project": "mac-2", "paused": False, "updated_at": "2026-07-08T01:00:00"},
        ]
        with patch.object(kill_switch, "db", fake_db), \
             patch.object(kill_switch, "HOST", "mac-2"):
            self.assertFalse(kill_switch.is_paused())


if __name__ == "__main__":
    unittest.main()
