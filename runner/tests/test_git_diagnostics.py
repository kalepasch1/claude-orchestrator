import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import git_diagnostics


class GitDiagnosticsTest(unittest.TestCase):

    def test_safe_git_log_returns_structured_result_on_success(self):
        result = MagicMock(returncode=0, stdout="abc123 fix login\ndef456 add tests\n")
        with patch("git_diagnostics.subprocess.run", return_value=result), \
             patch("git_diagnostics.os.path.isdir", return_value=True):
            output = git_diagnostics.safe_git_log(limit=5)

        self.assertTrue(output["success"])
        self.assertIsNone(output["error"])
        self.assertEqual(output["count"], 2)
        self.assertIn("abc123", output["output"])

    def test_safe_git_log_handles_permission_error(self):
        with patch("git_diagnostics.subprocess.run", side_effect=PermissionError("Access denied")), \
             patch("git_diagnostics.os.path.isdir", return_value=True):
            output = git_diagnostics.safe_git_log()

        self.assertFalse(output["success"])
        self.assertIn("permission", output["error"].lower())
        self.assertEqual(output["count"], 0)
        self.assertEqual(output["output"], "")

    def test_safe_git_log_detects_not_a_git_repo(self):
        with patch("git_diagnostics.os.path.isdir", return_value=False):
            output = git_diagnostics.safe_git_log()

        self.assertFalse(output["success"])
        self.assertIn("not a git repository", output["error"])
        self.assertEqual(output["count"], 0)

    def test_safe_git_log_handles_command_failure(self):
        result = MagicMock(
            returncode=128,
            stdout="",
            stderr="fatal: not a git repository"
        )
        with patch("git_diagnostics.subprocess.run", return_value=result), \
             patch("git_diagnostics.os.path.isdir", return_value=True):
            output = git_diagnostics.safe_git_log()

        self.assertFalse(output["success"])
        self.assertIn("not a git repository", output["error"])
        self.assertEqual(output["count"], 0)

    def test_safe_git_log_truncates_large_output(self):
        large_output = "a" * 20000 + "\n"
        result = MagicMock(returncode=0, stdout=large_output)
        with patch("git_diagnostics.subprocess.run", return_value=result), \
             patch("git_diagnostics.os.path.isdir", return_value=True):
            output = git_diagnostics.safe_git_log()

        self.assertTrue(output["success"])
        self.assertLess(len(output["output"]), len(large_output))
        self.assertIn("truncated", output["output"])

    def test_safe_git_log_handles_timeout(self):
        with patch("git_diagnostics.subprocess.run", side_effect=TimeoutError()), \
             patch("git_diagnostics.os.path.isdir", return_value=True):
            output = git_diagnostics.safe_git_log()

        self.assertFalse(output["success"])
        self.assertIn("timeout", output["error"].lower())

    def test_check_git_access_succeeds_with_valid_repo(self):
        result = MagicMock(returncode=0, stdout="abc123 commit\n")
        with patch("git_diagnostics.os.path.isdir") as mock_isdir, \
             patch("git_diagnostics.os.access", return_value=True), \
             patch("git_diagnostics.subprocess.run", return_value=result):
            mock_isdir.return_value = True
            output = git_diagnostics.check_git_access("/tmp/repo")

        self.assertTrue(output["success"])
        self.assertIsNone(output["error"])
        self.assertTrue(output["repo_initialized"])
        self.assertTrue(output["git_dir_readable"])
        self.assertEqual(len(output["sample_log"]), 1)

    def test_check_git_access_detects_missing_git_dir(self):
        with patch("git_diagnostics.os.path.isdir", return_value=False):
            output = git_diagnostics.check_git_access("/tmp/repo")

        self.assertFalse(output["success"])
        self.assertIn("not a git repository", output["error"])
        self.assertFalse(output["repo_initialized"])

    def test_check_git_access_detects_permission_denied_on_git_dir(self):
        with patch("git_diagnostics.os.path.isdir", return_value=True), \
             patch("git_diagnostics.os.access", return_value=False):
            output = git_diagnostics.check_git_access("/tmp/repo")

        self.assertFalse(output["success"])
        self.assertIn("permission denied", output["error"])
        self.assertTrue(output["repo_initialized"])
        self.assertFalse(output["git_dir_readable"])

    def test_check_git_access_handles_git_log_failure(self):
        result = MagicMock(returncode=1, stderr="error")
        with patch("git_diagnostics.os.path.isdir", return_value=True), \
             patch("git_diagnostics.os.access", return_value=True), \
             patch("git_diagnostics.subprocess.run", return_value=result):
            output = git_diagnostics.check_git_access("/tmp/repo")

        self.assertFalse(output["success"])
        self.assertIsNotNone(output["error"])
        self.assertTrue(output["repo_initialized"])
        self.assertTrue(output["git_dir_readable"])

    def test_check_git_access_handles_unexpected_exception(self):
        with patch("git_diagnostics.os.path.isdir", side_effect=RuntimeError("unexpected")):
            output = git_diagnostics.check_git_access("/tmp/repo")

        self.assertFalse(output["success"])
        self.assertIn("RuntimeError", output["error"])

    def test_log_diagnostic_event_inserts_to_resource_events(self):
        db = MagicMock()
        diagnostic = {"success": False, "error": "permission denied", "sample_log": []}
        inserts = []
        db.insert.side_effect = lambda table, row, upsert=False: inserts.append((table, row, upsert))

        with patch.object(git_diagnostics, "db", db):
            git_diagnostics.log_diagnostic_event(
                "check_access", "/tmp/repo", diagnostic, task_id="t1"
            )

        self.assertEqual(len(inserts), 1)
        table, row, upsert = inserts[0]
        self.assertEqual(table, "resource_events")
        self.assertTrue(upsert)
        self.assertEqual(row["event_type"], "check_access")
        self.assertEqual(row["repo_path"], "/tmp/repo")
        self.assertFalse(row["success"])
        self.assertEqual(row["task_id"], "t1")

    def test_log_diagnostic_event_handles_db_failure_gracefully(self):
        db = MagicMock()
        db.insert.side_effect = Exception("db error")
        diagnostic = {"success": False, "error": "permission denied"}

        with patch.object(git_diagnostics, "db", db):
            git_diagnostics.log_diagnostic_event("check_access", "/tmp/repo", diagnostic)

    def test_env_var_disables_diagnostics(self):
        with patch.dict(os.environ, {"ORCH_GIT_DIAGNOSTICS_ENABLED": "false"}):
            import importlib
            importlib.reload(git_diagnostics)
            output = git_diagnostics.safe_git_log()

        self.assertTrue(output["success"])
        self.assertIsNone(output["error"])
        self.assertEqual(output["count"], 0)

        importlib.reload(git_diagnostics)

    def test_check_git_access_with_custom_repo_path(self):
        result = MagicMock(returncode=0, stdout="abc123 test\n")
        with patch("git_diagnostics.os.path.isdir") as mock_isdir, \
             patch("git_diagnostics.os.access", return_value=True), \
             patch("git_diagnostics.subprocess.run", return_value=result) as mock_run:
            mock_isdir.return_value = True
            output = git_diagnostics.check_git_access("/custom/path")

            mock_run.assert_called_once()
            args, kwargs = mock_run.call_args
            self.assertEqual(kwargs["cwd"], "/custom/path")

    def test_safe_git_log_with_empty_repository(self):
        result = MagicMock(returncode=0, stdout="")
        with patch("git_diagnostics.subprocess.run", return_value=result), \
             patch("git_diagnostics.os.path.isdir", return_value=True):
            output = git_diagnostics.safe_git_log()

        self.assertTrue(output["success"])
        self.assertEqual(output["count"], 0)
        self.assertEqual(output["output"], "")

    def test_safe_git_log_counts_commits_correctly(self):
        log_output = "abc123 first\ndef456 second\nghi789 third\n"
        result = MagicMock(returncode=0, stdout=log_output)
        with patch("git_diagnostics.subprocess.run", return_value=result), \
             patch("git_diagnostics.os.path.isdir", return_value=True):
            output = git_diagnostics.safe_git_log()

        self.assertTrue(output["success"])
        self.assertEqual(output["count"], 3)

    def test_log_diagnostic_event_includes_task_id(self):
        db = MagicMock()
        diagnostic = {"success": True, "error": None}
        inserts = []
        db.insert.side_effect = lambda table, row, upsert=False: inserts.append(row)

        with patch.object(git_diagnostics, "db", db):
            git_diagnostics.log_diagnostic_event(
                "event", "/repo", diagnostic, task_id="task123"
            )

        self.assertEqual(inserts[0]["task_id"], "task123")

    def test_log_diagnostic_event_omits_task_id_when_none(self):
        db = MagicMock()
        diagnostic = {"success": True, "error": None}
        inserts = []
        db.insert.side_effect = lambda table, row, upsert=False: inserts.append(row)

        with patch.object(git_diagnostics, "db", db):
            git_diagnostics.log_diagnostic_event("event", "/repo", diagnostic)

        self.assertIsNone(inserts[0]["task_id"])


if __name__ == "__main__":
    unittest.main()
