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
        # Absolute path derived from THIS file. The literal "runner/branch_manager.py" only
        # resolved when pytest happened to run from the repo root; CI runs the runner
        # suite with working-directory: runner, where it raised FileNotFoundError —
        # so the syntax guard failed for a reason that had nothing to do with syntax.
        import os
        target = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "branch_manager.py")
        py_compile.compile(target, doraise=True)


if __name__ == "__main__":
    unittest.main()
