import os, sys, unittest
from unittest.mock import patch, MagicMock
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config_changelog as cl

class LogChangeTest(unittest.TestCase):
    def test_inserts_to_db(self):
        with patch.object(cl.db, "insert") as mock_insert:
            cl.log_change("KEY", "old", "new", source="test", actor="tester")
        mock_insert.assert_called_once()
        args = mock_insert.call_args[0]
        self.assertEqual(args[0], "config_changelog")
        self.assertEqual(args[1]["config_key"], "KEY")

    def test_handles_missing_table(self):
        with patch.object(cl.db, "insert", side_effect=Exception("table missing")):
            cl.log_change("KEY", "old", "new")  # should not raise

class RecentChangesTest(unittest.TestCase):
    def test_returns_list(self):
        with patch.object(cl.db, "select", return_value=[{"config_key": "A"}]):
            result = cl.recent_changes()
        self.assertEqual(len(result), 1)

    def test_returns_empty_on_error(self):
        with patch.object(cl.db, "select", side_effect=Exception("down")):
            result = cl.recent_changes()
        self.assertEqual(result, [])

class RollbackTest(unittest.TestCase):
    def test_returns_none_when_no_changes(self):
        with patch.object(cl.db, "select", return_value=[]):
            result = cl.rollback_last("KEY")
        self.assertIsNone(result)

    def test_returns_none_when_old_value_is_none(self):
        with patch.object(cl.db, "select", return_value=[{"old_value": None, "new_value": "x"}]):
            result = cl.rollback_last("KEY")
        self.assertIsNone(result)

if __name__ == "__main__":
    unittest.main()
