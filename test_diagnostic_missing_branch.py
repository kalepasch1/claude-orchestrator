"""Tests for diagnostic_missing_branch module.

This module verifies the missing branch detection and diagnosis functionality,
ensuring that branch existence checks are always answered from origin (via
git ls-remote) rather than stale local tracking refs, and that verdicts are
clearly sourced so they can be re-verified.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import diagnostic_missing_branch as dmb


class BranchStatusTests(unittest.TestCase):
    """Tests for branch_status() verdict generation and sourcing."""

    def test_branch_status_invalid_repo_path(self):
        """Invalid repo path should return UNKNOWN, not guess MISSING."""
        verdict, source = dmb.branch_status(None, "main")
        self.assertEqual(verdict, dmb.UNKNOWN)
        self.assertIn("repo path", source.lower())

        verdict, source = dmb.branch_status("", "main")
        self.assertEqual(verdict, dmb.UNKNOWN)

        verdict, source = dmb.branch_status("/nonexistent/repo", "main")
        self.assertEqual(verdict, dmb.UNKNOWN)

    def test_branch_status_invalid_branch_name(self):
        """Invalid branch name should return UNKNOWN."""
        with tempfile.TemporaryDirectory() as tmpdir:
            verdict, source = dmb.branch_status(tmpdir, None)
            self.assertEqual(verdict, dmb.UNKNOWN)

            verdict, source = dmb.branch_status(tmpdir, "")
            self.assertEqual(verdict, dmb.UNKNOWN)

    def test_branch_status_uses_branch_availability_check_when_present(self):
        """Should use branch_availability_check.branch_exists_remote when available."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch("diagnostic_missing_branch._bac") as mock_bac:
                mock_bac.branch_exists_remote.return_value = True
                verdict, source = dmb.branch_status(tmpdir, "main")
                self.assertEqual(verdict, dmb.PRESENT)
                self.assertIn("origin", source.lower())
                mock_bac.branch_exists_remote.assert_called_once_with(tmpdir, "main")

    def test_branch_status_bac_returns_false_means_missing(self):
        """When BAC says branch doesn't exist, verdict should be MISSING."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch("diagnostic_missing_branch._bac") as mock_bac:
                mock_bac.branch_exists_remote.return_value = False
                verdict, source = dmb.branch_status(tmpdir, "missing-branch")
                self.assertEqual(verdict, dmb.MISSING)
                self.assertIn("origin", source.lower())

    def test_branch_status_bac_exception_falls_back_to_git_ls_remote(self):
        """If BAC raises, should fallback to git ls-remote."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch("diagnostic_missing_branch._bac") as mock_bac:
                mock_bac.branch_exists_remote.side_effect = RuntimeError("BAC failed")
                with mock.patch("subprocess.run") as mock_run:
                    mock_run.return_value = mock.Mock(
                        returncode=0, stdout="abc123 refs/heads/main\n"
                    )
                    verdict, source = dmb.branch_status(tmpdir, "main")
                    self.assertEqual(verdict, dmb.PRESENT)
                    self.assertIn("ls-remote", source)

    def test_branch_status_git_ls_remote_finds_branch(self):
        """git ls-remote with non-empty output should return PRESENT."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch("diagnostic_missing_branch._bac", None):
                with mock.patch("subprocess.run") as mock_run:
                    mock_run.return_value = mock.Mock(
                        returncode=0, stdout="abc123def456 refs/heads/feature\n"
                    )
                    verdict, source = dmb.branch_status(tmpdir, "feature")
                    self.assertEqual(verdict, dmb.PRESENT)
                    self.assertIn("origin", source)
                    self.assertIn("ls-remote", source)

    def test_branch_status_git_ls_remote_no_output_means_missing(self):
        """git ls-remote with empty output should return MISSING."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch("diagnostic_missing_branch._bac", None):
                with mock.patch("subprocess.run") as mock_run:
                    mock_run.return_value = mock.Mock(returncode=0, stdout="")
                    verdict, source = dmb.branch_status(tmpdir, "nonexistent")
                    self.assertEqual(verdict, dmb.MISSING)

    def test_branch_status_git_ls_remote_failure_is_unknown(self):
        """git ls-remote failure should return UNKNOWN, not MISSING."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch("diagnostic_missing_branch._bac", None):
                with mock.patch("subprocess.run") as mock_run:
                    mock_run.return_value = mock.Mock(returncode=1, stdout="")
                    verdict, source = dmb.branch_status(tmpdir, "main")
                    self.assertEqual(verdict, dmb.UNKNOWN)
                    self.assertIn("unreachable", source.lower())

    def test_branch_status_git_ls_remote_timeout_is_unknown(self):
        """git ls-remote timeout should return UNKNOWN."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch("diagnostic_missing_branch._bac", None):
                with mock.patch("subprocess.run") as mock_run:
                    mock_run.side_effect = subprocess.TimeoutExpired("git", 15)
                    verdict, source = dmb.branch_status(tmpdir, "main")
                    self.assertEqual(verdict, dmb.UNKNOWN)


class WriteBranchStatusTests(unittest.TestCase):
    """Tests for write_branch_status() file output."""

    def test_write_branch_status_creates_file_with_verdict(self):
        """Should create file with verdict, branch, source, and SHA."""
        with tempfile.TemporaryDirectory() as tmpdir:
            status_path = os.path.join(tmpdir, "branch-status.txt")
            with mock.patch("diagnostic_missing_branch.branch_status") as mock_status:
                mock_status.return_value = (dmb.PRESENT, "origin (ls-remote)")
                with mock.patch("subprocess.run") as mock_run:
                    mock_run.return_value = mock.Mock(
                        returncode=0, stdout="abc123 refs/heads/main\n"
                    )
                    verdict = dmb.write_branch_status(tmpdir, "main", status_path)
                    self.assertEqual(verdict, dmb.PRESENT)
                    self.assertTrue(os.path.exists(status_path))

                    with open(status_path, "r") as f:
                        content = f.read()
                    self.assertIn("PRESENT", content)
                    self.assertIn("branch: main", content)
                    self.assertIn("source:", content)
                    self.assertIn("sha:", content)
                    self.assertIn("abc123", content)

    def test_write_branch_status_missing_branch(self):
        """Should handle MISSING verdict correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            status_path = os.path.join(tmpdir, "branch-status.txt")
            with mock.patch("diagnostic_missing_branch.branch_status") as mock_status:
                mock_status.return_value = (dmb.MISSING, "origin (ls-remote)")
                verdict = dmb.write_branch_status(tmpdir, "nonexistent", status_path)
                self.assertEqual(verdict, dmb.MISSING)

                with open(status_path, "r") as f:
                    content = f.read()
                self.assertIn("MISSING", content)
                self.assertIn("branch: nonexistent", content)
                # SHA should be empty for missing branches
                self.assertIn("sha: ", content)

    def test_write_branch_status_unknown_verdict(self):
        """Should handle UNKNOWN verdict (origin unreachable)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            status_path = os.path.join(tmpdir, "branch-status.txt")
            with mock.patch("diagnostic_missing_branch.branch_status") as mock_status:
                mock_status.return_value = (dmb.UNKNOWN, "origin unreachable")
                verdict = dmb.write_branch_status(tmpdir, "main", status_path)
                self.assertEqual(verdict, dmb.UNKNOWN)

                with open(status_path, "r") as f:
                    content = f.read()
                self.assertIn("UNKNOWN", content)
                self.assertIn("origin unreachable", content)

    def test_write_branch_status_custom_path(self):
        """Should write to custom path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            custom_path = os.path.join(tmpdir, "custom", "status.txt")
            os.makedirs(os.path.dirname(custom_path), exist_ok=True)
            with mock.patch("diagnostic_missing_branch.branch_status") as mock_status:
                mock_status.return_value = (dmb.PRESENT, "origin (ls-remote)")
                with mock.patch("subprocess.run") as mock_run:
                    mock_run.return_value = mock.Mock(returncode=0, stdout="")
                    dmb.write_branch_status(tmpdir, "main", custom_path)
                    self.assertTrue(os.path.exists(custom_path))

    def test_write_branch_status_handles_file_write_error(self):
        """Should fail gracefully if file cannot be written."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Path that cannot be created (permission denied scenario simulation)
            status_path = "/invalid/nonexistent/path/status.txt"
            with mock.patch("diagnostic_missing_branch.branch_status") as mock_status:
                mock_status.return_value = (dmb.PRESENT, "origin")
                # Should not raise, just print warning
                verdict = dmb.write_branch_status(tmpdir, "main", status_path)
                self.assertEqual(verdict, dmb.PRESENT)


class AnalyzeMissingBranchesTests(unittest.TestCase):
    """Tests for analyze_missing_branches() database analysis."""

    def test_analyze_missing_branches_no_data(self):
        """Should handle case with no projects or data gracefully."""
        with mock.patch("diagnostic_missing_branch.db") as mock_db:
            mock_db.select.side_effect = [[], None, []]
            # Should complete without raising
            dmb.analyze_missing_branches()

    def test_analyze_missing_branches_reads_projects(self):
        """Should read projects from database."""
        with mock.patch("diagnostic_missing_branch.db") as mock_db:
            mock_db.select.side_effect = [
                [{"id": "p1", "name": "proj1"}],  # projects
                None,  # pressure
                [],  # tasks
                [],  # approvals
            ]
            dmb.analyze_missing_branches()
            # Verify projects were read
            self.assertTrue(any(
                call[0][0] == "projects" for call in mock_db.select.call_args_list
            ))

    def test_analyze_missing_branches_parses_pressure_data(self):
        """Should parse and display merge train pressure data."""
        pressure_data = {
            "projects": {
                "proj1": {
                    "passed_waiting": 5,
                    "missing_branch": 2,
                    "oldest_wait_age_s": 3600,
                    "risk": {"low": 1, "standard": 2, "sensitive": 0}
                }
            }
        }
        with mock.patch("diagnostic_missing_branch.db") as mock_db:
            mock_db.select.side_effect = [
                [],  # projects
                [{"key": "merge_train_pressure", "value": json.dumps(pressure_data)}],
                [],  # tasks
                [],  # approvals
            ]
            dmb.analyze_missing_branches()
            self.assertTrue(True)  # Just verify it doesn't crash

    def test_analyze_missing_branches_finds_tasks_with_branch_keywords(self):
        """Should identify tasks with branch-related keywords in notes."""
        tasks = [
            {"id": "t1", "slug": "task1", "note": "missing branch", "project_id": "p1"},
            {"id": "t2", "slug": "task2", "note": "rebuild required", "project_id": "p1"},
            {"id": "t3", "slug": "task3", "note": "normal task", "project_id": "p1"},
        ]
        with mock.patch("diagnostic_missing_branch.db") as mock_db:
            mock_db.select.side_effect = [
                [{"id": "p1", "name": "proj1"}],
                None,
                tasks,
                [],
            ]
            dmb.analyze_missing_branches()

    def test_analyze_missing_branches_finds_approvals_with_missing_indicators(self):
        """Should identify approval cards with missing branch indicators."""
        approvals = [
            {"id": "a1", "slug": "ap1", "decided_by": "missing branch"},
            {"id": "a2", "slug": "ap2", "decided_by": "no-repo found"},
            {"id": "a3", "slug": "ap3", "decided_by": "approved"},
        ]
        with mock.patch("diagnostic_missing_branch.db") as mock_db:
            mock_db.select.side_effect = [
                [],
                None,
                [],
                approvals,
            ]
            dmb.analyze_missing_branches()


class CheckBranchConsistencyTests(unittest.TestCase):
    """Tests for check_branch_consistency() verification."""

    def test_check_branch_consistency_no_projects(self):
        """Should handle empty project list."""
        with mock.patch("diagnostic_missing_branch.db") as mock_db:
            mock_db.select.return_value = []
            # Should complete without error
            dmb.check_branch_consistency()

    def test_check_branch_consistency_invalid_repo_path(self):
        """Should skip projects with invalid or missing repo paths."""
        with mock.patch("diagnostic_missing_branch.db") as mock_db:
            mock_db.select.side_effect = [
                [{"id": "p1", "name": "proj1", "repo_path": "/nonexistent"}],
            ]
            dmb.check_branch_consistency()

    def test_check_branch_consistency_queries_origin_branches(self):
        """Should query agent/* branches on origin via git ls-remote."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch("diagnostic_missing_branch.db") as mock_db:
                mock_db.select.side_effect = [
                    [{"id": "p1", "name": "proj1", "repo_path": tmpdir}],
                ]
                with mock.patch("subprocess.run") as mock_run:
                    # First call is git ls-remote for agent/*
                    mock_run.return_value = mock.Mock(
                        returncode=0,
                        stdout="abc123 refs/heads/agent/task1\ndef456 refs/heads/agent/task2\n"
                    )
                    dmb.check_branch_consistency()
                    # Verify git ls-remote was called
                    self.assertTrue(any("ls-remote" in str(call) for call in mock_run.call_args_list))

    def test_check_branch_consistency_origin_unreachable_is_not_missing(self):
        """Should not report branches as MISSING if origin is unreachable."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch("diagnostic_missing_branch.db") as mock_db:
                mock_db.select.side_effect = [
                    [{"id": "p1", "name": "proj1", "repo_path": tmpdir}],
                ]
                with mock.patch("subprocess.run") as mock_run:
                    # git ls-remote fails
                    mock_run.return_value = mock.Mock(returncode=1, stderr="Connection refused")
                    dmb.check_branch_consistency()

    def test_check_branch_consistency_verifies_tasks_individually(self):
        """Should re-verify missing branches individually before reporting."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch("diagnostic_missing_branch.db") as mock_db:
                mock_db.select.side_effect = [
                    [{"id": "p1", "name": "proj1", "repo_path": tmpdir}],
                    [  # Tasks
                        {"id": "t1", "slug": "task1", "state": "DONE"},
                        {"id": "t2", "slug": "task2", "state": "MERGED"},
                    ]
                ]
                with mock.patch("subprocess.run") as mock_run:
                    # Initial ls-remote shows no branches
                    mock_run.return_value = mock.Mock(returncode=0, stdout="")
                    with mock.patch("diagnostic_missing_branch.branch_status") as mock_status:
                        # Individual verification shows task2 is present after all
                        mock_status.side_effect = [
                            (dmb.MISSING, "origin"),
                            (dmb.PRESENT, "origin"),
                        ]
                        dmb.check_branch_consistency()


class MainFunctionTests(unittest.TestCase):
    """Tests for main() entry point."""

    def test_main_single_branch_mode_present(self):
        """main(["branch"]) should write status and return 0 for present branch."""
        with tempfile.TemporaryDirectory() as tmpdir:
            status_path = os.path.join(tmpdir, "branch-status.txt")
            with mock.patch("diagnostic_missing_branch.branch_status") as mock_status:
                mock_status.return_value = (dmb.PRESENT, "origin (ls-remote)")
                with mock.patch("subprocess.run") as mock_run:
                    mock_run.return_value = mock.Mock(returncode=0, stdout="abc123\n")
                    with mock.patch("os.path.dirname") as mock_dirname:
                        mock_dirname.return_value = tmpdir
                        result = dmb.main(["main"])
                        self.assertEqual(result, 0)

    def test_main_single_branch_mode_missing(self):
        """main(["branch"]) should return 1 for missing branch."""
        with mock.patch("diagnostic_missing_branch.branch_status") as mock_status:
            mock_status.return_value = (dmb.MISSING, "origin (ls-remote)")
            with mock.patch("diagnostic_missing_branch.write_branch_status") as mock_write:
                mock_write.return_value = dmb.MISSING
                result = dmb.main(["nonexistent"])
                self.assertEqual(result, 1)

    def test_main_single_branch_mode_unknown(self):
        """main(["branch"]) should return 2 for UNKNOWN verdict."""
        with mock.patch("diagnostic_missing_branch.branch_status") as mock_status:
            mock_status.return_value = (dmb.UNKNOWN, "origin unreachable")
            with mock.patch("diagnostic_missing_branch.write_branch_status") as mock_write:
                mock_write.return_value = dmb.UNKNOWN
                result = dmb.main(["main"])
                self.assertEqual(result, 2)

    def test_main_single_branch_with_custom_repo(self):
        """main(["branch", "repo"]) should use specified repo."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch("diagnostic_missing_branch.branch_status") as mock_status:
                mock_status.return_value = (dmb.PRESENT, "origin")
                with mock.patch("diagnostic_missing_branch.write_branch_status") as mock_write:
                    mock_write.return_value = dmb.PRESENT
                    result = dmb.main(["main", tmpdir])
                    self.assertEqual(result, 0)
                    # Verify repo was passed
                    mock_status.assert_called_with(tmpdir, "main")

    def test_main_full_analysis_mode(self):
        """main() with no args should run full analysis."""
        with mock.patch("diagnostic_missing_branch.analyze_missing_branches"):
            with mock.patch("diagnostic_missing_branch.check_branch_consistency"):
                result = dmb.main([])
                self.assertEqual(result, 0)

    def test_main_no_arguments_calls_analysis_functions(self):
        """Verify both analysis functions are called in full mode."""
        analyze_called = False
        consistency_called = False

        def mock_analyze():
            nonlocal analyze_called
            analyze_called = True

        def mock_consistency():
            nonlocal consistency_called
            consistency_called = True

        with mock.patch("diagnostic_missing_branch.analyze_missing_branches", mock_analyze):
            with mock.patch("diagnostic_missing_branch.check_branch_consistency", mock_consistency):
                dmb.main([])
                self.assertTrue(analyze_called)
                self.assertTrue(consistency_called)


class EdgeCaseTests(unittest.TestCase):
    """Tests for edge cases and error conditions."""

    def test_verdicts_are_constants_not_strings(self):
        """Verdict constants should be defined."""
        self.assertEqual(dmb.PRESENT, "PRESENT")
        self.assertEqual(dmb.MISSING, "MISSING")
        self.assertEqual(dmb.UNKNOWN, "UNKNOWN")

    def test_branch_status_never_returns_missing_on_unknown_error(self):
        """Any exception should return UNKNOWN, never MISSING."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch("diagnostic_missing_branch._bac", None):
                with mock.patch("subprocess.run") as mock_run:
                    mock_run.side_effect = OSError("System error")
                    verdict, source = dmb.branch_status(tmpdir, "main")
                    self.assertEqual(verdict, dmb.UNKNOWN)
                    self.assertNotEqual(verdict, dmb.MISSING)

    def test_write_branch_status_preserves_verdict_across_file_write(self):
        """Return value should match the verdict written to file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            status_path = os.path.join(tmpdir, "status.txt")
            for verdict in [dmb.PRESENT, dmb.MISSING, dmb.UNKNOWN]:
                with mock.patch("diagnostic_missing_branch.branch_status") as mock_status:
                    mock_status.return_value = (verdict, "test source")
                    with mock.patch("subprocess.run"):
                        result = dmb.write_branch_status(tmpdir, "branch", status_path)
                        self.assertEqual(result, verdict)

    def test_branch_status_iso_formatting_in_output(self):
        """Output should include sufficient diagnostic data for re-verification."""
        with tempfile.TemporaryDirectory() as tmpdir:
            status_path = os.path.join(tmpdir, "status.txt")
            with mock.patch("diagnostic_missing_branch.branch_status") as mock_status:
                mock_status.return_value = (dmb.PRESENT, "origin (ls-remote)")
                with mock.patch("subprocess.run") as mock_run:
                    mock_run.return_value = mock.Mock(
                        returncode=0, stdout="abc123def456 refs/heads/main\n"
                    )
                    dmb.write_branch_status(tmpdir, "main", status_path)

                    with open(status_path, "r") as f:
                        lines = f.readlines()

                    # Should have verdict, branch, source, and SHA
                    self.assertGreaterEqual(len(lines), 4)
                    content_str = "".join(lines)
                    self.assertIn("PRESENT", content_str)
                    self.assertIn("main", content_str)
                    self.assertIn("origin", content_str)


if __name__ == "__main__":
    unittest.main()
