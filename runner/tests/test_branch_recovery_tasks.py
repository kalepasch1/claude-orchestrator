#!/usr/bin/env python3
"""
Test suite for Task 1 and Task 2 of branch recovery orchestration.

Task 1: Branch status verification and patch artifact retrieval
Task 2: Patch adaptation and application to recovery branch
"""
import os, sys, json, tempfile, unittest, shutil, subprocess
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import branch_recovery_tasks


class TestTask1BranchStatusVerification(unittest.TestCase):
    """Task 1: Branch status verification."""

    def test_branch_exists_and_valid(self):
        """Branch status correctly reports existing valid branch."""
        with patch.object(branch_recovery_tasks, "_is_git_repo", return_value=True), \
             patch.object(branch_recovery_tasks, "_git") as mock_git:

            def git_side_effect(repo, *args):
                if "rev-parse" in args and "--verify" in args:
                    return 0, "abc1234567890", ""
                if "rev-parse" in args and "refs/heads/" in str(args):
                    return 0, "abc1234567890", ""
                if "cat-file" in args:
                    return 0, "commit", ""
                if "merge-base" in args:
                    return 0, "", ""
                return 0, "", ""

            mock_git.side_effect = git_side_effect

            status = branch_recovery_tasks._get_branch_status("/repo", "test-branch")

            self.assertTrue(status["exists"])
            self.assertEqual(status["last_commit_sha"], "abc1234567890")
            self.assertEqual(status["corruption_flags"], [])
            self.assertFalse(status["orphaned"])

    def test_branch_missing(self):
        """Branch status correctly reports missing branch."""
        with patch.object(branch_recovery_tasks, "_is_git_repo", return_value=True), \
             patch.object(branch_recovery_tasks, "_git") as mock_git:

            mock_git.return_value = (1, "", "not found")

            status = branch_recovery_tasks._get_branch_status("/repo", "missing-branch")

            self.assertFalse(status["exists"])
            self.assertIsNone(status["last_commit_sha"])
            self.assertEqual(status["corruption_flags"], [])

    def test_branch_corrupted_commit_missing(self):
        """Branch status detects missing commit object."""
        with patch.object(branch_recovery_tasks, "_is_git_repo", return_value=True), \
             patch.object(branch_recovery_tasks, "_git") as mock_git:

            def git_side_effect(repo, *args):
                if "--verify" in args:
                    return 0, "corrupted_sha", ""
                if "cat-file" in args:
                    return 1, "", "not found"
                return 0, "", ""

            mock_git.side_effect = git_side_effect

            status = branch_recovery_tasks._get_branch_status("/repo", "corrupt-branch")

            self.assertTrue(status["exists"])
            self.assertIn("commit_object_missing", status["corruption_flags"])

    def test_branch_orphaned(self):
        """Branch status detects orphaned branches."""
        with patch.object(branch_recovery_tasks, "_is_git_repo", return_value=True), \
             patch.object(branch_recovery_tasks, "_git") as mock_git:

            def git_side_effect(repo, *args):
                if "--verify" in args:
                    return 0, "orphan_sha", ""
                if "cat-file" in args:
                    return 0, "commit", ""
                if "merge-base" in args:
                    return 1, "", "no common ancestor"
                return 0, "", ""

            mock_git.side_effect = git_side_effect

            status = branch_recovery_tasks._get_branch_status("/repo", "orphan-branch")

            self.assertTrue(status["orphaned"])

    def test_branch_ref_file_truncated(self):
        """Branch status detects truncated ref files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create minimal git repo
            repo_path = tmpdir
            os.makedirs(os.path.join(repo_path, ".git", "refs", "heads"), exist_ok=True)

            # Create truncated ref file
            ref_file = os.path.join(repo_path, ".git", "refs", "heads", "bad-branch")
            with open(ref_file, "w") as f:
                f.write("ab")

            with patch.object(branch_recovery_tasks, "_is_git_repo", return_value=True), \
                 patch.object(branch_recovery_tasks, "_git") as mock_git:

                mock_git.return_value = (0, "abc123", "")

                status = branch_recovery_tasks._get_branch_status(repo_path, "bad-branch")

                self.assertIn("ref_file_truncated", status["corruption_flags"])


class TestTask1PatchArtifactRetrieval(unittest.TestCase):
    """Task 1: Patch artifact retrieval."""

    def test_artifact_loaded_and_verified(self):
        """Patch artifact is loaded and hash verified."""
        with patch("sys.modules") as mock_modules:
            mock_lib = MagicMock()
            mock_lib.list_patches.return_value = [
                {
                    "template_id": "06b43339ce93",
                    "id": "06b43339ce93",
                    "content": b"patch content here",
                }
            ]
            mock_modules.__contains__.return_value = True
            mock_modules.__getitem__.return_value = mock_lib

            with patch.object(sys, "modules", mock_modules):
                result = branch_recovery_tasks._load_patch_artifact(
                    "/path/to/library.py", "06b43339ce93"
                )

                self.assertTrue(result["found"])
                self.assertIsNotNone(result["patch_data"])

    def test_artifact_not_found(self):
        """Missing patch artifact returns error."""
        with patch.object(os.path, "exists", return_value=False):
            result = branch_recovery_tasks._load_patch_artifact(
                "/nonexistent/library.py", "missing_id"
            )

            self.assertFalse(result["found"])
            self.assertIsNone(result["patch_data"])
            self.assertIn("not found", result["error"])

    def test_artifact_import_error(self):
        """Library import error handled gracefully."""
        with patch.object(os.path, "exists", return_value=True), \
             patch("builtins.open", side_effect=ImportError("bad module")):

            result = branch_recovery_tasks._load_patch_artifact(
                "/path/to/library.py", "some_id"
            )

            self.assertFalse(result["found"])
            self.assertIsNotNone(result["error"])


class TestTask1ArtifactStaging(unittest.TestCase):
    """Task 1: Artifact staging."""

    def test_artifacts_staged_successfully(self):
        """Artifacts are staged in recovery directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            branch_status = {"exists": True, "last_commit_sha": "abc123"}
            patch_artifact = {"found": True, "hash_verified": True}

            result = branch_recovery_tasks._stage_artifacts(
                tmpdir, "1", branch_status, patch_artifact
            )

            self.assertTrue(result["success"])
            self.assertIsNotNone(result["staging_path"])

            # Verify files exist
            staging_path = result["staging_path"]
            self.assertTrue(os.path.exists(os.path.join(staging_path, "branch_status.json")))
            self.assertTrue(os.path.exists(os.path.join(staging_path, "patch_artifact.json")))

    def test_artifacts_staging_permission_error(self):
        """Staging handles permission errors gracefully."""
        with patch.object(os, "makedirs", side_effect=PermissionError("denied")):
            result = branch_recovery_tasks._stage_artifacts(
                "/restricted", "1", {}, {}
            )

            self.assertFalse(result["success"])
            self.assertIsNotNone(result["error"])


class TestTask1Integration(unittest.TestCase):
    """Task 1: Complete integration test."""

    def test_task_1_complete_flow(self):
        """Task 1 successfully verifies branch and retrieves artifact."""
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.object(branch_recovery_tasks, "_is_git_repo", return_value=True), \
             patch.object(branch_recovery_tasks, "_git") as mock_git, \
             patch.object(branch_recovery_tasks, "_load_patch_artifact") as mock_load:

            mock_git.return_value = (0, "abc123", "")
            mock_load.return_value = {
                "found": True,
                "patch_data": {"content": "patch"},
                "hash_verified": True,
                "error": None,
            }

            result = branch_recovery_tasks.task_1_verify_and_retrieve(
                tmpdir, "test-branch", "06b43339ce93", "/lib/path.py"
            )

            self.assertTrue(result["success"])
            self.assertTrue(result["branch_status"]["exists"])
            self.assertTrue(result["patch_artifact"]["found"])
            self.assertIsNotNone(result["staging_path"])


class TestTask2WorktreeCreation(unittest.TestCase):
    """Task 2: Worktree creation."""

    def test_worktree_created(self):
        """Worktree is created from master."""
        with patch.object(branch_recovery_tasks, "_is_git_repo", return_value=True), \
             patch.object(branch_recovery_tasks, "_git") as mock_git:

            mock_git.return_value = (0, "", "")

            result = branch_recovery_tasks._create_worktree("/repo", "recovery-task-2-test")

            self.assertTrue(result["success"])
            self.assertIsNotNone(result["worktree_path"])

    def test_worktree_invalid_repo(self):
        """Worktree creation fails for invalid repo."""
        with patch.object(branch_recovery_tasks, "_is_git_repo", return_value=False):
            result = branch_recovery_tasks._create_worktree("/invalid", "task")

            self.assertFalse(result["success"])
            self.assertIn("invalid", result["error"].lower())


class TestTask2PatchApplication(unittest.TestCase):
    """Task 2: Patch application."""

    def test_patch_applies_cleanly(self):
        """Patch applies without conflicts."""
        patch_content = b"""--- a/test.py
+++ b/test.py
@@ -1,3 +1,4 @@
+# new line
 original
 content
"""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stderr=b"")

            result = branch_recovery_tasks._apply_patch("/worktree", patch_content)

            self.assertTrue(result["success"])
            self.assertEqual(result["conflicts"], [])

    def test_patch_conflicts(self):
        """Patch application detects conflicts."""
        patch_content = b"conflicted patch"

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stderr=b"FAILED: test.py\nreject in test.py"
            )

            result = branch_recovery_tasks._apply_patch("/worktree", patch_content)

            self.assertFalse(result["success"])
            self.assertGreater(len(result["conflicts"]), 0)


class TestTask2SyntaxValidation(unittest.TestCase):
    """Task 2: Syntax validation."""

    def test_python_syntax_valid(self):
        """Valid Python syntax passes validation."""
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.object(branch_recovery_tasks, "_git") as mock_git:

            # Create valid Python file
            test_file = os.path.join(tmpdir, "test.py")
            with open(test_file, "w") as f:
                f.write("def foo():\n    return 42\n")

            mock_git.return_value = (0, "M  test.py", "")

            result = branch_recovery_tasks._validate_syntax(tmpdir)

            self.assertTrue(result["valid"])
            self.assertEqual(result["errors"], [])

    def test_python_syntax_invalid(self):
        """Invalid Python syntax is detected."""
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.object(branch_recovery_tasks, "_git") as mock_git:

            # Create invalid Python file
            test_file = os.path.join(tmpdir, "bad.py")
            with open(test_file, "w") as f:
                f.write("def foo((\n")

            mock_git.return_value = (0, "M  bad.py", "")

            result = branch_recovery_tasks._validate_syntax(tmpdir)

            self.assertFalse(result["valid"])
            self.assertGreater(len(result["errors"]), 0)

    def test_json_syntax_valid(self):
        """Valid JSON syntax passes validation."""
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.object(branch_recovery_tasks, "_git") as mock_git:

            # Create valid JSON file
            test_file = os.path.join(tmpdir, "config.json")
            with open(test_file, "w") as f:
                json.dump({"key": "value"}, f)

            mock_git.return_value = (0, "M  config.json", "")

            result = branch_recovery_tasks._validate_syntax(tmpdir)

            self.assertTrue(result["valid"])

    def test_json_syntax_invalid(self):
        """Invalid JSON syntax is detected."""
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.object(branch_recovery_tasks, "_git") as mock_git:

            # Create invalid JSON file
            test_file = os.path.join(tmpdir, "bad.json")
            with open(test_file, "w") as f:
                f.write("{invalid json}")

            mock_git.return_value = (0, "M  bad.json", "")

            result = branch_recovery_tasks._validate_syntax(tmpdir)

            self.assertFalse(result["valid"])


class TestTask2CommitAndPush(unittest.TestCase):
    """Task 2: Commit and push."""

    def test_commit_successful(self):
        """Commit is created with correct author."""
        with patch.object(branch_recovery_tasks, "_git") as mock_git:

            def git_side_effect(repo, *args):
                if "config" in args:
                    return 0, "", ""
                if "add" in args:
                    return 0, "", ""
                if "commit" in args:
                    return 0, "", ""
                if "rev-parse" in args:
                    return 0, "commit_sha_123", ""
                return 0, "", ""

            mock_git.side_effect = git_side_effect

            result = branch_recovery_tasks._commit_recovery_branch(
                "/worktree", "recovery", "testuser", "test@example.com"
            )

            self.assertTrue(result["success"])
            self.assertEqual(result["commit_sha"], "commit_sha_123")

    def test_commit_fails_on_git_error(self):
        """Commit handles git errors gracefully."""
        with patch.object(branch_recovery_tasks, "_git") as mock_git:
            mock_git.return_value = (1, "", "git error")

            result = branch_recovery_tasks._commit_recovery_branch(
                "/worktree", "recovery", "user", "user@example.com"
            )

            self.assertFalse(result["success"])


class TestTask2Integration(unittest.TestCase):
    """Task 2: Complete integration test."""

    def test_task_2_complete_flow(self):
        """Task 2 creates worktree, applies patch, validates, and commits."""
        patch_content = b"""--- a/test.py
+++ b/test.py
"""
        with patch.object(branch_recovery_tasks, "_is_git_repo", return_value=True), \
             patch.object(branch_recovery_tasks, "_create_worktree") as mock_create, \
             patch.object(branch_recovery_tasks, "_apply_patch") as mock_apply, \
             patch.object(branch_recovery_tasks, "_validate_syntax") as mock_validate, \
             patch.object(branch_recovery_tasks, "_commit_recovery_branch") as mock_commit, \
             patch.object(branch_recovery_tasks, "_cleanup_worktree") as mock_cleanup:

            mock_create.return_value = {"success": True, "worktree_path": "/wt/path"}
            mock_apply.return_value = {"success": True, "conflicts": []}
            mock_validate.return_value = {"valid": True, "errors": []}
            mock_commit.return_value = {"success": True, "commit_sha": "abc123"}

            result = branch_recovery_tasks.task_2_adapt_and_apply(
                "/repo", patch_content
            )

            self.assertTrue(result["success"])
            self.assertIsNotNone(result["commit_sha"])
            mock_cleanup.assert_called()

    def test_task_2_handles_patch_failure(self):
        """Task 2 handles patch application failure gracefully."""
        with patch.object(branch_recovery_tasks, "_is_git_repo", return_value=True), \
             patch.object(branch_recovery_tasks, "_create_worktree") as mock_create, \
             patch.object(branch_recovery_tasks, "_apply_patch") as mock_apply, \
             patch.object(branch_recovery_tasks, "_cleanup_worktree"):

            mock_create.return_value = {"success": True, "worktree_path": "/wt/path"}
            mock_apply.return_value = {
                "success": False,
                "conflicts": ["test.py"],
                "error": "patch failed"
            }

            result = branch_recovery_tasks.task_2_adapt_and_apply("/repo", b"patch")

            self.assertFalse(result["success"])
            self.assertEqual(result["validation_errors"], ["test.py"])


class TestErrorHandlingAndEdgeCases(unittest.TestCase):
    """Error handling and edge cases."""

    def test_empty_repo_path_handled(self):
        """Empty repo path returns meaningful error."""
        status = branch_recovery_tasks._get_branch_status("", "branch")
        self.assertFalse(status["exists"])

    def test_none_repo_path_handled(self):
        """None repo path returns meaningful error."""
        status = branch_recovery_tasks._get_branch_status(None, "branch")
        self.assertFalse(status["exists"])

    def test_unicode_branch_names(self):
        """Unicode branch names don't crash."""
        with patch.object(branch_recovery_tasks, "_is_git_repo", return_value=True), \
             patch.object(branch_recovery_tasks, "_git", return_value=(1, "", "")):

            result = branch_recovery_tasks._get_branch_status("/repo", "feature-🚀")
            self.assertIsNotNone(result)

    def test_very_long_patch_content(self):
        """Large patch content is handled."""
        large_patch = b"--- a/file.py\n" + b"+line\n" * 10000

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stderr=b"")

            result = branch_recovery_tasks._apply_patch("/worktree", large_patch)
            self.assertTrue(result["success"])

    def test_timeout_handling(self):
        """Command timeout is handled gracefully."""
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 30)):
            result = branch_recovery_tasks._apply_patch("/worktree", b"patch")
            self.assertFalse(result["success"])
            self.assertIn("timeout", result["error"].lower())


if __name__ == "__main__":
    unittest.main()
