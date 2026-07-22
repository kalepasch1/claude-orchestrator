"""Tests for preflight_reprocessing_gate — block stale re-integration."""
import os, sys, unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import preflight_reprocessing_gate as gate


class TestCheckReintegration(unittest.TestCase):

    @patch("subprocess.run")
    def test_branch_not_found_allows(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        result = gate.check_reintegration("/tmp/repo", "my-slug")
        self.assertTrue(result["allowed"])
        self.assertIn("not found", result["reason"])

    @patch("subprocess.run")
    def test_branch_tip_in_integration_blocks(self, mock_run):
        def fake_run(cmd, **kw):
            m = MagicMock()
            joined = " ".join(cmd)
            if "rev-parse" in joined:
                m.returncode = 0
                m.stdout = "abc123def456\n"
            elif "merge-base" in joined:
                m.returncode = 0  # is ancestor
            elif "log" in joined:
                m.returncode = 0
                m.stdout = "agent: my-slug\nsome body\n"  # no reprocessed marker
            else:
                m.returncode = 1
                m.stdout = ""
            return m
        mock_run.side_effect = fake_run

        import tempfile
        with tempfile.TemporaryDirectory() as td:
            result = gate.check_reintegration(td, "my-slug")
        self.assertFalse(result["allowed"])
        self.assertIn("BLOCKED", result["reason"])
        self.assertIn("re-processing", result["reason"])

    @patch("subprocess.run")
    def test_fresh_marker_allows_reintegration(self, mock_run):
        def fake_run(cmd, **kw):
            m = MagicMock()
            joined = " ".join(cmd)
            if "rev-parse" in joined:
                m.returncode = 0
                m.stdout = "abc123def456\n"
            elif "merge-base" in joined:
                m.returncode = 0
            elif "log" in joined:
                m.returncode = 0
                m.stdout = "agent: my-slug\nagent-reprocessed:2026-07-18T00:00:00Z\n"
            else:
                m.returncode = 1
                m.stdout = ""
            return m
        mock_run.side_effect = fake_run

        import tempfile
        with tempfile.TemporaryDirectory() as td:
            result = gate.check_reintegration(td, "my-slug")
        self.assertTrue(result["allowed"])
        self.assertIn("marker", result["reason"])

    @patch("subprocess.run")
    def test_branch_not_in_integration_allows(self, mock_run):
        call_count = [0]
        def fake_run(cmd, **kw):
            m = MagicMock()
            joined = " ".join(cmd)
            if "rev-parse" in joined:
                call_count[0] += 1
                if call_count[0] <= 1:
                    m.returncode = 0
                    m.stdout = "abc123\n"
                else:
                    m.returncode = 1  # target branch doesn't exist
                    m.stdout = ""
            elif "merge-base" in joined:
                m.returncode = 1  # not ancestor
            else:
                m.returncode = 0
                m.stdout = ""
            return m
        mock_run.side_effect = fake_run

        import tempfile
        with tempfile.TemporaryDirectory() as td:
            result = gate.check_reintegration(td, "my-slug")
        self.assertTrue(result["allowed"])

    def test_nonexistent_repo(self):
        result = gate.check_reintegration("/nonexistent", "slug")
        self.assertTrue(result["allowed"])


if __name__ == "__main__":
    unittest.main()
