"""Tests for branch_manager — advanced branch management."""
import unittest
import tempfile, subprocess, os


class TestBranchManager(unittest.TestCase):

    def test_detect_base_branch_master(self):
        """Repos with master should return master."""
        from runner.branch_manager import _detect_base_branch
        # beethoven uses master
        repo = os.path.expanduser("~/Documents/beethoven/claude-orchestrator")
        if os.path.isdir(repo):
            self.assertEqual(_detect_base_branch(repo), "master")

    def test_list_agent_branches(self):
        from runner.branch_manager import list_agent_branches
        repo = os.path.expanduser("~/Documents/beethoven/claude-orchestrator")
        if os.path.isdir(repo):
            branches = list_agent_branches(repo)
            self.assertIsInstance(branches, list)
            # Should have some agent branches
            if branches:
                self.assertTrue(branches[0]["name"].startswith("agent/"))

    def test_branch_health_report_structure(self):
        from runner.branch_manager import branch_health_report
        repo = os.path.expanduser("~/Documents/beethoven/claude-orchestrator")
        if os.path.isdir(repo):
            report = branch_health_report(repo)
            self.assertIn("total_branches", report)
            self.assertIn("stale_merged", report)
            self.assertIn("active", report)

    def test_syntax_check(self):
        import py_compile
        py_compile.compile("runner/branch_manager.py", doraise=True)


if __name__ == "__main__":
    unittest.main()
