"""Tests for integration_sweeper.local_branch_audit — read-only branch state audit."""
import os, sys, subprocess, unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import integration_sweeper as mod


class TestLocalBranchAudit(unittest.TestCase):

    @patch.object(mod, "db")
    @patch("subprocess.run")
    def test_classifies_local_remote_missing(self, mock_run, mock_db):
        def fake_run(cmd, **kw):
            m = MagicMock()
            m.returncode = 0
            joined = " ".join(cmd)
            if "branch --list agent" in joined:
                m.stdout = "agent/slug-a\nagent/slug-b\n"
            elif "branch -r" in joined:
                m.stdout = "origin/agent/slug-a\norigin/agent/slug-c\n"
            elif "worktree list" in joined:
                m.stdout = ""
            elif "fetch" in joined:
                m.stdout = ""
            elif "reflog" in joined:
                m.stdout = ""
            else:
                m.stdout = ""
            return m
        mock_run.side_effect = fake_run
        mock_db.select.return_value = []
        mod._FETCHED_AGENT_REFS.clear()
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            result = mod.local_branch_audit(td, slugs=["slug-a", "slug-b", "slug-c", "slug-d"])
        self.assertEqual(len(result["local"]), 2)
        self.assertEqual(len(result["remote_only"]), 1)
        self.assertEqual(len(result["missing"]), 1)

    @patch.object(mod, "db")
    @patch("subprocess.run")
    def test_stale_worktrees_detected(self, mock_run, mock_db):
        def fake_run(cmd, **kw):
            m = MagicMock()
            m.returncode = 0
            joined = " ".join(cmd)
            if "branch --list agent" in joined:
                m.stdout = "agent/running-task\nagent/done-task\n"
            elif "branch -r" in joined:
                m.stdout = ""
            elif "worktree list" in joined:
                m.stdout = "worktree /repo\nbranch refs/heads/master\n\nworktree /tmp/wt-done\nbranch refs/heads/agent/done-task\n\nworktree /tmp/wt-running\nbranch refs/heads/agent/running-task\n\n"
            elif "fetch" in joined:
                m.stdout = ""
            else:
                m.stdout = ""
            return m
        mock_db.select.side_effect = lambda table, params=None, **kw: (
            [{"slug": "running-task"}] if params and params.get("state") == "eq.RUNNING" else []
        )
        mod._FETCHED_AGENT_REFS.clear()
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            result = mod.local_branch_audit(td, slugs=["running-task", "done-task"])
        self.assertEqual(len(result["stale_worktrees"]), 1)
        self.assertEqual(result["stale_worktrees"][0]["branch"], "agent/done-task")

    @patch.object(mod, "db")
    def test_nonexistent_repo_returns_empty(self, mock_db):
        mock_db.select.return_value = []
        result = mod.local_branch_audit("/nonexistent/path", slugs=["x"])
        self.assertEqual(len(result["missing"]), 1)
        self.assertEqual(result["local"], [])

    @patch.object(mod, "db")
    def test_none_repo_returns_empty(self, mock_db):
        mock_db.select.return_value = []
        result = mod.local_branch_audit(None, slugs=["y"])
        self.assertEqual(len(result["missing"]), 1)

if __name__ == "__main__":
    unittest.main()
