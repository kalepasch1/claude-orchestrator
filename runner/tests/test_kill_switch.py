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


if __name__ == "__main__":
    unittest.main()
