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
        import os, sys
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from syntax_guard import compile_runner_module
        # cwd-independent: the old literal "runner/branch_manager.py" only resolved from the
        # repo root and raised FileNotFoundError when the suite ran from runner/.
        compile_runner_module("branch_manager.py")


if __name__ == "__main__":
    unittest.main()
