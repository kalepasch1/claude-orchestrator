"""Tests for scoreboard — routing score persistence and dashboard."""
import unittest
import tempfile, os, json


class TestScoreboard(unittest.TestCase):
    def test_read_history_empty(self):
        from runner.scoreboard import read_history
        # Should handle missing file gracefully
        import runner.scoreboard as sb
        old = sb._SCOREBOARD_FILE
        sb._SCOREBOARD_FILE = "/tmp/nonexistent-scoreboard-test.jsonl"
        try:
            result = read_history()
            self.assertEqual(result, [])
        finally:
            sb._SCOREBOARD_FILE = old

    def test_read_history_with_data(self):
        from runner import scoreboard as sb
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(json.dumps({"timestamp": "2026-01-01", "routes": {}}) + "\n")
            f.write(json.dumps({"timestamp": "2026-01-02", "routes": {}}) + "\n")
            tmp = f.name
        old = sb._SCOREBOARD_FILE
        sb._SCOREBOARD_FILE = tmp
        try:
            result = sb.read_history()
            self.assertEqual(len(result), 2)
        finally:
            sb._SCOREBOARD_FILE = old
            os.unlink(tmp)

    def test_dashboard_summary_no_data(self):
        from runner import scoreboard as sb
        old = sb._SCOREBOARD_FILE
        sb._SCOREBOARD_FILE = "/tmp/nonexistent-sb.jsonl"
        try:
            summary = sb.dashboard_summary()
            self.assertEqual(summary["status"], "no data")
        finally:
            sb._SCOREBOARD_FILE = old

    def test_syntax(self):
        import py_compile
        py_compile.compile("runner/scoreboard.py", doraise=True)


if __name__ == "__main__":
    unittest.main()
