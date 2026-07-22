import os
import sys
import types
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Provide a stub db before importing build_gate
_fake_db = types.ModuleType("db")
_fake_db.select = MagicMock(return_value=[])
_fake_db.insert = MagicMock()
_fake_db.update = MagicMock()
sys.modules.setdefault("db", _fake_db)

import build_gate


class TestScanBranches(unittest.TestCase):
    """scan_branches finds agent/* branches."""

    @patch.object(build_gate, "_git")
    def test_scan_finds_agent_branches(self, mock_git):
        mock_git.return_value = (0, "  agent/fix-auth\n  agent/add-table\n  agent/refactor", "")
        branches = build_gate.scan_branches("/fake/repo")
        self.assertEqual(branches, ["agent/fix-auth", "agent/add-table", "agent/refactor"])

    @patch.object(build_gate, "_git")
    def test_scan_empty_when_no_branches(self, mock_git):
        mock_git.return_value = (0, "", "")
        branches = build_gate.scan_branches("/fake/repo")
        self.assertEqual(branches, [])

    @patch.object(build_gate, "_git")
    def test_scan_fails_soft_on_error(self, mock_git):
        mock_git.return_value = (128, "", "fatal: not a git repo")
        branches = build_gate.scan_branches("/fake/repo")
        self.assertEqual(branches, [])

    def test_scan_disabled_returns_empty(self):
        with patch.object(build_gate, "ENABLED", False):
            self.assertEqual(build_gate.scan_branches("/fake"), [])


class TestCheckBuildStatus(unittest.TestCase):
    """check_build_status extracts failure reasons."""

    @patch.object(build_gate, "db")
    @patch.object(build_gate, "_git")
    def test_extracts_missing_module(self, mock_git, mock_db):
        mock_db.select = MagicMock(return_value=[])
        mock_git.side_effect = [
            (0, "ModuleNotFoundError: No module named 'utils.helpers'\n---", ""),
            (1, "", ""),  # notes
        ]
        result = build_gate.check_build_status("agent/fix-auth", repo="/fake")
        self.assertTrue(result["has_failures"])
        self.assertEqual(result["reasons"][0]["type"], "missing_module")
        self.assertIn("utils.helpers", result["reasons"][0]["detail"])

    @patch.object(build_gate, "db")
    @patch.object(build_gate, "_git")
    def test_extracts_missing_table(self, mock_git, mock_db):
        mock_db.select = MagicMock(return_value=[])
        mock_git.side_effect = [
            (0, 'relation "accounts" does not exist\n---', ""),
            (1, "", ""),
        ]
        result = build_gate.check_build_status("agent/add-table", repo="/fake")
        self.assertTrue(result["has_failures"])
        self.assertEqual(result["reasons"][0]["type"], "missing_table")
        self.assertEqual(result["reasons"][0]["detail"], "accounts")

    @patch.object(build_gate, "db")
    @patch.object(build_gate, "_git")
    def test_no_failures_clean_branch(self, mock_git, mock_db):
        mock_db.select = MagicMock(return_value=[])
        mock_git.side_effect = [
            (0, "feat: add login page\n---", ""),
            (1, "", ""),
        ]
        result = build_gate.check_build_status("agent/clean", repo="/fake")
        self.assertFalse(result["has_failures"])
        self.assertEqual(result["reasons"], [])

    @patch.object(build_gate, "db")
    @patch.object(build_gate, "_git")
    def test_extracts_from_task_note(self, mock_git, mock_db):
        mock_db.select = MagicMock(return_value=[{
            "note": "ModuleNotFoundError: No module named 'config_loader'",
            "log_tail": "",
        }])
        mock_git.side_effect = [
            (0, "feat: something\n---", ""),
            (1, "", ""),
        ]
        result = build_gate.check_build_status("agent/needs-config", repo="/fake")
        self.assertTrue(result["has_failures"])
        self.assertEqual(result["reasons"][0]["type"], "missing_module")


class TestGetFailureReasons(unittest.TestCase):
    """Batch failure reason checking."""

    @patch.object(build_gate, "check_build_status")
    def test_batch_returns_dict(self, mock_check):
        mock_check.side_effect = [
            {"branch": "agent/a", "has_failures": True, "reasons": [{"type": "missing_module", "detail": "foo"}]},
            {"branch": "agent/b", "has_failures": False, "reasons": []},
        ]
        result = build_gate.get_failure_reasons(["agent/a", "agent/b"], repo="/fake")
        self.assertEqual(len(result), 2)
        self.assertEqual(len(result["agent/a"]), 1)
        self.assertEqual(len(result["agent/b"]), 0)

    def test_empty_branches(self):
        result = build_gate.get_failure_reasons([], repo="/fake")
        self.assertEqual(result, {})


class TestStats(unittest.TestCase):
    """stats() output."""

    @patch.object(build_gate, "get_failure_reasons", return_value={})
    @patch.object(build_gate, "scan_branches", return_value=[])
    def test_stats_keys(self, mock_scan, mock_failures):
        s = build_gate.stats()
        self.assertIn("enabled", s)
        self.assertIn("unmerged_agent_branches", s)
        self.assertIn("branches_with_failures", s)


if __name__ == "__main__":
    unittest.main(verbosity=2)
