import os, sys, unittest, time
from unittest.mock import patch, MagicMock
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import branch_cleanup as bc

def _proc(rc=0, stdout="", stderr=""):
    p = MagicMock(); p.returncode = rc; p.stdout = stdout; p.stderr = stderr; return p

REPO = "/fake/repo"

class ListAgentBranchesTest(unittest.TestCase):
    def test_parses_branches(self):
        out = "agent/task-1 1720000000\nagent/task-2 1710000000\n"
        with patch("subprocess.run", return_value=_proc(0, stdout=out)):
            result = bc.list_agent_branches(REPO)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["name"], "agent/task-1")

    def test_empty_on_failure(self):
        with patch("subprocess.run", return_value=_proc(1)):
            result = bc.list_agent_branches(REPO)
        self.assertEqual(result, [])

class ClassifyBranchesTest(unittest.TestCase):
    def test_merged_tasks_classified_as_merged(self):
        branches = [{"name": "agent/done-task", "last_commit_ts": int(time.time())}]
        with patch.object(bc, "list_agent_branches", return_value=branches), \
             patch.object(bc.db, "select", return_value=[{"slug": "done-task", "state": "MERGED"}]):
            result = bc.classify_branches(REPO)
        self.assertIn("agent/done-task", result["merged"])

class CleanupTest(unittest.TestCase):
    def test_dry_run_does_not_delete(self):
        classified = {"merged": ["agent/x"], "stale": [], "orphaned": [], "active": ["agent/y"]}
        with patch.object(bc, "classify_branches", return_value=classified), \
             patch("subprocess.run") as mock_run:
            result = bc.cleanup(REPO, dry_run=True)
        mock_run.assert_not_called()
        self.assertTrue(result["dry_run"])
        self.assertEqual(len(result["removed"]), 1)
        self.assertIn("[dry-run]", result["removed"][0])

if __name__ == "__main__":
    unittest.main()
