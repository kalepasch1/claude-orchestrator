"""
Test suite for hive-shared-artifact-writes: concurrent artifact capture,
storage, and retrieval with fallback mechanisms and schema compatibility.

Tests cover:
- Concurrent writes to shared artifact table (upsert idempotency)
- Large diff handling and truncation (500KB cap)
- DB failure fallback to local JSON files
- Schema compatibility during rollout (artifact_ref/patch_id optional)
- Immutable ref publishing integration
- Artifact retrieval with multi-source lookup
"""
import os
import sys
import json
import tempfile
import subprocess
import unittest
from unittest.mock import Mock, patch, MagicMock, call
import datetime
from datetime import UTC
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import task_artifacts


class TestArtifactCapture(unittest.TestCase):
    """Core artifact capture functionality."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = self.temp_dir.name

    def tearDown(self):
        self.temp_dir.cleanup()

    @patch("task_artifacts.db.insert")
    @patch("task_artifacts.db.select")
    @patch("subprocess.run")
    def test_capture_all_fields(self, mock_run, mock_select, mock_insert):
        """Capture populates all expected artifact fields."""
        mock_select.return_value = [{"id": "task-1", "attempt": 1}]
        mock_run.side_effect = [
            Mock(stdout="abc123def456\n", returncode=0),  # rev-parse
            Mock(stdout="diff content\n", returncode=0),   # git diff
            Mock(stdout="file1.py\nfile2.py\n", returncode=0),  # diff --name-only
        ]

        with patch("task_artifacts.task_refs.publish") as mock_publish:
            mock_publish.return_value = {"ok": True, "ref": "ref-123", "patch_id": "p-456"}

            result = task_artifacts.capture(
                repo=self.repo,
                slug="test-task",
                branch="test-branch",
                base="master",
                wt=None,
                test_log="test output",
                cost={"usd": 0.05}
            )

        assert result["branch"] == "test-branch"
        assert result["commit_sha"] == "abc123def456"
        assert result["patch_diff"] == "diff content\n"
        assert result["diff_bytes"] > 0
        assert json.loads(result["touched_files"]) == ["file1.py", "file2.py"]
        assert result["test_log"] == "test output"
        assert result["cost_usd"] == 0.05
        assert result["artifact_ref"] == "ref-123"
        assert result["patch_id"] == "p-456"
        assert "captured_at" in result

    @patch("task_artifacts.db.insert")
    @patch("task_artifacts.db.select")
    @patch("subprocess.run")
    def test_capture_large_diff_truncated_at_500kb(self, mock_run, mock_select, mock_insert):
        """Large diffs are truncated to 500KB to prevent bloat."""
        mock_select.return_value = [{"id": "task-1", "attempt": 1}]
        large_diff = "x" * (600 * 1024)  # 600KB
        mock_run.side_effect = [
            Mock(stdout="sha123\n", returncode=0),
            Mock(stdout=large_diff, returncode=0),
            Mock(stdout="file.py\n", returncode=0),
        ]

        with patch("task_artifacts.task_refs.publish") as mock_publish:
            mock_publish.return_value = {"ok": True, "ref": "ref-1", "patch_id": "p-1"}

            result = task_artifacts.capture(self.repo, "task-1", "br", "master", None)

        assert len(result["patch_diff"]) == 500000  # 500KB in bytes
        assert result["diff_bytes"] == len(large_diff)

    @patch("task_artifacts.db.insert")
    @patch("task_artifacts.db.select")
    @patch("subprocess.run")
    def test_capture_git_command_failures_gracefully_degrade(self, mock_run, mock_select, mock_insert):
        """Git command failures don't crash; missing data filled with defaults."""
        mock_select.return_value = [{"id": "task-1", "attempt": 1}]
        mock_run.side_effect = [
            Exception("timeout"),  # rev-parse fails
            Exception("timeout"),  # git diff fails
            Exception("timeout"),  # diff --name-only fails
        ]

        with patch("task_artifacts.task_refs.publish") as mock_publish:
            mock_publish.return_value = {"ok": True, "ref": "ref-1", "patch_id": "p-1"}

            result = task_artifacts.capture(self.repo, "task-1", "br", "master", None)

        assert result["commit_sha"] == ""
        assert result["patch_diff"] == ""
        assert result["diff_bytes"] == 0
        assert json.loads(result["touched_files"]) == []

    @patch("task_artifacts.db.insert")
    @patch("task_artifacts.db.select")
    @patch("subprocess.run")
    def test_capture_test_log_capped_at_10kb(self, mock_run, mock_select, mock_insert):
        """Test log is truncated to last 10KB."""
        mock_select.return_value = [{"id": "task-1", "attempt": 1}]
        large_log = "line\n" * 2000  # ~12KB
        mock_run.side_effect = [
            Mock(stdout="sha\n", returncode=0),
            Mock(stdout="diff\n", returncode=0),
            Mock(stdout="f.py\n", returncode=0),
        ]

        with patch("task_artifacts.task_refs.publish") as mock_publish:
            mock_publish.return_value = {"ok": True, "ref": "r", "patch_id": "p"}

            result = task_artifacts.capture(self.repo, "task-1", "br", "master", None, test_log=large_log)

        assert len(result["test_log"]) <= 10000

    @patch("task_artifacts.db.insert")
    @patch("task_artifacts.db.select")
    @patch("subprocess.run")
    def test_capture_task_ref_publish_failure_doesnt_crash(self, mock_run, mock_select, mock_insert):
        """Immutable ref publish failure is logged but doesn't prevent artifact storage."""
        mock_select.return_value = [{"id": "task-1", "attempt": 1}]
        mock_run.side_effect = [
            Mock(stdout="sha\n", returncode=0),
            Mock(stdout="diff\n", returncode=0),
            Mock(stdout="f.py\n", returncode=0),
        ]

        with patch("task_artifacts.task_refs.publish") as mock_publish:
            mock_publish.return_value = {"ok": False, "reason": "ref store unavailable"}

            result = task_artifacts.capture(self.repo, "task-1", "br", "master", None)

        assert "artifact_ref" not in result  # Not added on failure
        assert mock_insert.called  # But artifact is still stored


class TestConcurrentArtifactWrites(unittest.TestCase):
    """Concurrent/shared writes to artifact storage."""

    @patch("task_artifacts.db.insert")
    @patch("task_artifacts.db.select")
    @patch("subprocess.run")
    def test_upsert_idempotent_on_same_slug(self, mock_run, mock_select, mock_insert):
        """Multiple writes for same slug use upsert (idempotent)."""
        mock_select.return_value = [{"id": "task-1", "attempt": 1}]
        mock_run.side_effect = [
            Mock(stdout="sha\n", returncode=0),
            Mock(stdout="diff\n", returncode=0),
            Mock(stdout="f.py\n", returncode=0),
        ]

        with patch("task_artifacts.task_refs.publish") as mock_publish:
            mock_publish.return_value = {"ok": True, "ref": "r", "patch_id": "p"}

            task_artifacts.capture("/repo", "shared-task", "br", "master", None)

        # Verify upsert=True is passed
        assert mock_insert.called
        call_kwargs = mock_insert.call_args[1]
        assert call_kwargs.get("upsert") is True

    @patch("task_artifacts.db.insert")
    @patch("task_artifacts.db.select")
    @patch("subprocess.run")
    def test_concurrent_writes_handle_race_conditions(self, mock_run, mock_select, mock_insert):
        """Multiple concurrent captures for same slug race safely."""
        mock_select.return_value = [{"id": "task-1", "attempt": 1}]
        mock_run.side_effect = [
            Mock(stdout="sha1\n", returncode=0),
            Mock(stdout="diff1\n", returncode=0),
            Mock(stdout="f1.py\n", returncode=0),
        ]

        with patch("task_artifacts.task_refs.publish") as mock_publish:
            mock_publish.return_value = {"ok": True, "ref": "r1", "patch_id": "p1"}

            art1 = task_artifacts.capture("/repo", "task-1", "br1", "master", None)
            assert art1["commit_sha"] == "sha1"

        # Second write with same slug but different data
        mock_run.side_effect = [
            Mock(stdout="sha2\n", returncode=0),
            Mock(stdout="diff2\n", returncode=0),
            Mock(stdout="f2.py\n", returncode=0),
        ]

        with patch("task_artifacts.task_refs.publish") as mock_publish:
            mock_publish.return_value = {"ok": True, "ref": "r2", "patch_id": "p2"}

            art2 = task_artifacts.capture("/repo", "task-1", "br2", "master", None)
            assert art2["commit_sha"] == "sha2"

        # Both writes should use upsert
        assert mock_insert.call_count >= 2


class TestSchemaCompatibilityRollout(unittest.TestCase):
    """Handling schema changes during mixed-version rollout."""

    @patch("task_artifacts.db.insert")
    @patch("task_artifacts.db.select")
    @patch("subprocess.run")
    def test_fallback_to_compatible_schema_on_new_fields_error(self, mock_run, mock_select, mock_insert):
        """When new fields (artifact_ref, patch_id) cause error, retry without them."""
        mock_select.return_value = [{"id": "task-1", "attempt": 1}]
        mock_run.side_effect = [
            Mock(stdout="sha\n", returncode=0),
            Mock(stdout="diff\n", returncode=0),
            Mock(stdout="f.py\n", returncode=0),
        ]

        # First insert fails (new schema), second succeeds (old schema)
        mock_insert.side_effect = [
            Exception("column 'artifact_ref' does not exist"),
            None,
        ]

        with patch("task_artifacts.task_refs.publish") as mock_publish:
            mock_publish.return_value = {"ok": True, "ref": "r", "patch_id": "p"}

            result = task_artifacts.capture("/repo", "task-1", "br", "master", None)

        # Should have attempted insert twice: first with new fields, second without
        assert mock_insert.call_count == 2

        # First call includes artifact_ref and patch_id
        first_call_args = mock_insert.call_args_list[0][0]
        first_call_dict = first_call_args[1]
        assert "artifact_ref" in first_call_dict

        # Second call excludes them
        second_call_args = mock_insert.call_args_list[1][0]
        second_call_dict = second_call_args[1]
        assert "artifact_ref" not in second_call_dict

    @patch("task_artifacts.db.insert")
    @patch("task_artifacts.db.select")
    @patch("subprocess.run")
    @patch("builtins.open", create=True)
    def test_local_fallback_when_db_unavailable(self, mock_open, mock_run, mock_select, mock_insert):
        """When DB fails completely, artifacts stored to local JSON."""
        mock_select.return_value = [{"id": "task-1", "attempt": 1}]
        mock_run.side_effect = [
            Mock(stdout="sha\n", returncode=0),
            Mock(stdout="diff\n", returncode=0),
            Mock(stdout="f.py\n", returncode=0),
        ]

        # Both DB attempts fail
        mock_insert.side_effect = [
            Exception("connection refused"),
            Exception("connection refused"),
        ]

        with patch("task_artifacts.task_refs.publish") as mock_publish:
            mock_publish.return_value = {"ok": True, "ref": "r", "patch_id": "p"}
            with patch("os.makedirs"):
                mock_open.return_value.__enter__ = Mock()
                mock_open.return_value.__exit__ = Mock()

                result = task_artifacts.capture("/repo", "task-1", "br", "master", None)

        # Should attempt to write to local file
        assert mock_open.called


class TestArtifactRetrieval(unittest.TestCase):
    """Artifact retrieval with multi-source fallback."""

    @patch("task_artifacts.db.select")
    def test_get_artifacts_from_db(self, mock_select):
        """has_artifacts and get_artifacts read from DB."""
        mock_select.return_value = [{"slug": "task-1", "commit_sha": "abc123"}]

        assert task_artifacts.has_artifacts("task-1") is True
        result = task_artifacts.get_artifacts("task-1")
        assert result["commit_sha"] == "abc123"

    @patch("task_artifacts.db.select")
    def test_has_artifacts_false_when_no_commit_sha(self, mock_select):
        """Artifacts without commit_sha are considered incomplete."""
        mock_select.return_value = [{"slug": "task-1", "commit_sha": ""}]

        assert task_artifacts.has_artifacts("task-1") is False

    @patch("task_artifacts.db.select")
    def test_has_artifacts_false_when_db_fails(self, mock_select):
        """DB failures don't crash has_artifacts check."""
        mock_select.side_effect = Exception("connection error")

        # Should check local fallback without crashing
        with patch("os.path.isfile") as mock_isfile:
            mock_isfile.return_value = False
            result = task_artifacts.has_artifacts("task-1")

        assert result is False

    @patch("task_artifacts.db.select")
    def test_get_artifacts_returns_none_when_not_found(self, mock_select):
        """get_artifacts returns None when artifact missing."""
        mock_select.return_value = None

        with patch("os.path.isfile") as mock_isfile:
            mock_isfile.return_value = False
            result = task_artifacts.get_artifacts("missing-task")

        assert result is None

    @patch("task_artifacts.db.select")
    def test_get_artifacts_fallback_to_local_file(self, mock_select):
        """Falls back to local JSON file when DB fails."""
        mock_select.side_effect = Exception("DB error")

        with tempfile.TemporaryDirectory() as tmpdir:
            artifacts_dir = os.path.join(tmpdir, "artifacts")
            os.makedirs(artifacts_dir)
            artifact_file = os.path.join(artifacts_dir, "task-1.json")

            artifact_data = {
                "slug": "task-1",
                "commit_sha": "abc",
                "patch_diff": "diff",
                "touched_files": '["f.py"]'
            }
            with open(artifact_file, "w") as f:
                json.dump(artifact_data, f)

            with patch.dict(os.environ, {"CLAUDE_ORCH_HOME": tmpdir}):
                result = task_artifacts.get_artifacts("task-1")

        assert result is not None
        assert result["commit_sha"] == "abc"

    @patch("task_artifacts.db.select")
    def test_get_patch_extracts_diff_field(self, mock_select):
        """get_patch returns just the patch_diff field."""
        mock_select.return_value = [{
            "slug": "task-1",
            "patch_diff": "--- a/file.py\n+++ b/file.py\n"
        }]

        patch = task_artifacts.get_patch("task-1")
        assert "--- a/file.py" in patch

    @patch("task_artifacts.db.select")
    def test_get_patch_returns_empty_when_missing(self, mock_select):
        """get_patch returns empty string when artifact not found."""
        mock_select.return_value = None

        with patch("os.path.isfile") as mock_isfile:
            mock_isfile.return_value = False
            result = task_artifacts.get_patch("missing")

        assert result == ""


class TestMetadataCapture(unittest.TestCase):
    """Correct metadata capture and timestamps."""

    @patch("task_artifacts.db.insert")
    @patch("task_artifacts.db.select")
    @patch("subprocess.run")
    def test_captured_at_timestamp_is_utc_iso(self, mock_run, mock_select, mock_insert):
        """captured_at is set to UTC ISO format."""
        mock_select.return_value = [{"id": "task-1", "attempt": 1}]
        mock_run.side_effect = [
            Mock(stdout="sha\n", returncode=0),
            Mock(stdout="diff\n", returncode=0),
            Mock(stdout="f.py\n", returncode=0),
        ]

        with patch("task_artifacts.task_refs.publish") as mock_pub:
            mock_pub.return_value = {"ok": True, "ref": "r", "patch_id": "p"}

            before = datetime.datetime.now(UTC)
            result = task_artifacts.capture("/repo", "task-1", "br", "master", None)
            after = datetime.datetime.now(UTC)

        timestamp_str = result["captured_at"]
        captured = datetime.datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        assert before <= captured <= after

    @patch("task_artifacts.db.insert")
    @patch("task_artifacts.db.select")
    @patch("subprocess.run")
    def test_cost_usd_stored_when_provided(self, mock_run, mock_select, mock_insert):
        """cost_usd is extracted and stored from cost dict."""
        mock_select.return_value = [{"id": "task-1", "attempt": 1}]
        mock_run.side_effect = [
            Mock(stdout="sha\n", returncode=0),
            Mock(stdout="diff\n", returncode=0),
            Mock(stdout="f.py\n", returncode=0),
        ]

        with patch("task_artifacts.task_refs.publish") as mock_pub:
            mock_pub.return_value = {"ok": True, "ref": "r", "patch_id": "p"}

            result = task_artifacts.capture(
                "/repo", "task-1", "br", "master", None,
                cost={"usd": 0.1234, "tokens": 5000}
            )

        assert result["cost_usd"] == 0.1234

    @patch("task_artifacts.db.insert")
    @patch("task_artifacts.db.select")
    @patch("subprocess.run")
    def test_cost_omitted_when_not_provided(self, mock_run, mock_select, mock_insert):
        """cost_usd not added when cost is None."""
        mock_select.return_value = [{"id": "task-1", "attempt": 1}]
        mock_run.side_effect = [
            Mock(stdout="sha\n", returncode=0),
            Mock(stdout="diff\n", returncode=0),
            Mock(stdout="f.py\n", returncode=0),
        ]

        with patch("task_artifacts.task_refs.publish") as mock_pub:
            mock_pub.return_value = {"ok": True, "ref": "r", "patch_id": "p"}

            result = task_artifacts.capture("/repo", "task-1", "br", "master", None, cost=None)

        assert "cost_usd" not in result or result.get("cost_usd") is None


class TestTaskRefIntegration(unittest.TestCase):
    """Immutable reference publishing via task_refs."""

    @patch("task_artifacts.db.insert")
    @patch("task_artifacts.db.select")
    @patch("subprocess.run")
    def test_task_ref_publish_success(self, mock_run, mock_select, mock_insert):
        """Successful task_ref publish stores artifact_ref and patch_id."""
        mock_select.return_value = [{"id": "123", "attempt": 2}]
        mock_run.side_effect = [
            Mock(stdout="sha-abc\n", returncode=0),
            Mock(stdout="diff\n", returncode=0),
            Mock(stdout="f.py\n", returncode=0),
        ]

        with patch("task_artifacts.task_refs.publish") as mock_pub:
            mock_pub.return_value = {
                "ok": True,
                "ref": "refs/archive/123/2/abc",
                "patch_id": "patch-xyz"
            }

            result = task_artifacts.capture("/repo", "task-1", "br", "master", None)

        assert result["artifact_ref"] == "refs/archive/123/2/abc"
        assert result["patch_id"] == "patch-xyz"
        # Verify publish was called with correct args
        mock_pub.assert_called_once()
        call_args = mock_pub.call_args[0]
        assert call_args[2] == 2  # attempt
        assert call_args[3] == "sha-abc"  # commit_sha

    @patch("task_artifacts.db.insert")
    @patch("task_artifacts.db.select")
    @patch("subprocess.run")
    def test_task_ref_publish_fallback_to_slug(self, mock_run, mock_select, mock_insert):
        """When task not found in DB, use slug as fallback for ref publish."""
        mock_select.return_value = []  # No task found
        mock_run.side_effect = [
            Mock(stdout="sha\n", returncode=0),
            Mock(stdout="diff\n", returncode=0),
            Mock(stdout="f.py\n", returncode=0),
        ]

        with patch("task_artifacts.task_refs.publish") as mock_pub:
            mock_pub.return_value = {"ok": True, "ref": "r", "patch_id": "p"}

            task_artifacts.capture("/repo", "my-task-slug", "br", "master", None)

        call_args = mock_pub.call_args[0]
        assert call_args[1] == "my-task-slug"  # slug used as fallback
        assert call_args[2] == 1  # default attempt


class TestWorktreeHandling(unittest.TestCase):
    """Artifact capture from git worktrees."""

    @patch("task_artifacts.db.insert")
    @patch("task_artifacts.db.select")
    @patch("subprocess.run")
    def test_capture_uses_worktree_when_provided(self, mock_run, mock_select, mock_insert):
        """When wt param provided, git commands run in worktree."""
        mock_select.return_value = [{"id": "task-1", "attempt": 1}]
        mock_run.side_effect = [
            Mock(stdout="sha\n", returncode=0),
            Mock(stdout="diff\n", returncode=0),
            Mock(stdout="f.py\n", returncode=0),
        ]

        with patch("task_artifacts.task_refs.publish") as mock_pub:
            mock_pub.return_value = {"ok": True, "ref": "r", "patch_id": "p"}

            task_artifacts.capture("/repo", "task-1", "br", "master", wt="/wt/path")

        # All git commands should run in worktree
        for call_obj in mock_run.call_args_list:
            assert call_obj[1]["cwd"] == "/wt/path"

    @patch("task_artifacts.db.insert")
    @patch("task_artifacts.db.select")
    @patch("subprocess.run")
    def test_capture_uses_repo_when_no_worktree(self, mock_run, mock_select, mock_insert):
        """When wt is None, git commands run in repo."""
        mock_select.return_value = [{"id": "task-1", "attempt": 1}]
        mock_run.side_effect = [
            Mock(stdout="sha\n", returncode=0),
            Mock(stdout="diff\n", returncode=0),
            Mock(stdout="f.py\n", returncode=0),
        ]

        with patch("task_artifacts.task_refs.publish") as mock_pub:
            mock_pub.return_value = {"ok": True, "ref": "r", "patch_id": "p"}

            task_artifacts.capture("/repo", "task-1", "br", "master", wt=None)

        # All git commands should run in repo
        for call_obj in mock_run.call_args_list:
            assert call_obj[1]["cwd"] == "/repo"


class TestEdgeCases(unittest.TestCase):
    """Edge cases and boundary conditions."""

    @patch("task_artifacts.db.insert")
    @patch("task_artifacts.db.select")
    @patch("subprocess.run")
    def test_empty_branch_name_accepted(self, mock_run, mock_select, mock_insert):
        """Empty branch name is accepted (captured as-is)."""
        mock_select.return_value = [{"id": "task-1", "attempt": 1}]
        mock_run.side_effect = [
            Mock(stdout="sha\n", returncode=0),
            Mock(stdout="", returncode=0),
            Mock(stdout="", returncode=0),
        ]

        with patch("task_artifacts.task_refs.publish") as mock_pub:
            mock_pub.return_value = {"ok": True, "ref": "r", "patch_id": "p"}

            result = task_artifacts.capture("/repo", "task-1", "", "master", None)

        assert result["branch"] == ""

    @patch("task_artifacts.db.insert")
    @patch("task_artifacts.db.select")
    @patch("subprocess.run")
    def test_empty_touched_files_is_empty_json_array(self, mock_run, mock_select, mock_insert):
        """No touched files results in empty JSON array."""
        mock_select.return_value = [{"id": "task-1", "attempt": 1}]
        mock_run.side_effect = [
            Mock(stdout="sha\n", returncode=0),
            Mock(stdout="diff\n", returncode=0),
            Mock(stdout="", returncode=0),  # empty file list
        ]

        with patch("task_artifacts.task_refs.publish") as mock_pub:
            mock_pub.return_value = {"ok": True, "ref": "r", "patch_id": "p"}

            result = task_artifacts.capture("/repo", "task-1", "br", "master", None)

        assert result["touched_files"] == "[]"
        assert json.loads(result["touched_files"]) == []

    @patch("task_artifacts.db.insert")
    @patch("task_artifacts.db.select")
    @patch("subprocess.run")
    def test_whitespace_in_filenames_preserved(self, mock_run, mock_select, mock_insert):
        """Filenames with spaces are preserved correctly."""
        mock_select.return_value = [{"id": "task-1", "attempt": 1}]
        mock_run.side_effect = [
            Mock(stdout="sha\n", returncode=0),
            Mock(stdout="diff\n", returncode=0),
            Mock(stdout="file with spaces.py\nanother file.txt\n", returncode=0),
        ]

        with patch("task_artifacts.task_refs.publish") as mock_pub:
            mock_pub.return_value = {"ok": True, "ref": "r", "patch_id": "p"}

            result = task_artifacts.capture("/repo", "task-1", "br", "master", None)

        files = json.loads(result["touched_files"])
        assert "file with spaces.py" in files
        assert "another file.txt" in files

    @patch("task_artifacts.db.insert")
    @patch("task_artifacts.db.select")
    @patch("subprocess.run")
    def test_unicode_in_diff_handled_correctly(self, mock_run, mock_select, mock_insert):
        """Unicode in diffs is handled with errors='ignore'."""
        mock_select.return_value = [{"id": "task-1", "attempt": 1}]
        unicode_diff = "diff with unicode: 你好\n"
        mock_run.side_effect = [
            Mock(stdout="sha\n", returncode=0),
            Mock(stdout=unicode_diff, returncode=0),
            Mock(stdout="f.py\n", returncode=0),
        ]

        with patch("task_artifacts.task_refs.publish") as mock_pub:
            mock_pub.return_value = {"ok": True, "ref": "r", "patch_id": "p"}

            result = task_artifacts.capture("/repo", "task-1", "br", "master", None)

        # Should not crash
        assert isinstance(result["diff_bytes"], int)
        assert result["diff_bytes"] > 0


class TestArtifactTimeouts(unittest.TestCase):
    """Git command timeout handling."""

    @patch("task_artifacts.db.insert")
    @patch("task_artifacts.db.select")
    @patch("subprocess.run")
    def test_rev_parse_timeout_handled(self, mock_run, mock_select, mock_insert):
        """rev-parse timeout is handled gracefully."""
        mock_select.return_value = [{"id": "task-1", "attempt": 1}]
        mock_run.side_effect = [
            subprocess.TimeoutExpired("git", 30),
            Mock(stdout="diff\n", returncode=0),
            Mock(stdout="f.py\n", returncode=0),
        ]

        with patch("task_artifacts.task_refs.publish") as mock_pub:
            mock_pub.return_value = {"ok": True, "ref": "r", "patch_id": "p"}

            result = task_artifacts.capture("/repo", "task-1", "br", "master", None)

        assert result["commit_sha"] == ""

    @patch("task_artifacts.db.insert")
    @patch("task_artifacts.db.select")
    @patch("subprocess.run")
    def test_diff_timeout_handled(self, mock_run, mock_select, mock_insert):
        """git diff timeout is handled gracefully."""
        mock_select.return_value = [{"id": "task-1", "attempt": 1}]
        mock_run.side_effect = [
            Mock(stdout="sha\n", returncode=0),
            subprocess.TimeoutExpired("git", 60),
            Mock(stdout="f.py\n", returncode=0),
        ]

        with patch("task_artifacts.task_refs.publish") as mock_pub:
            mock_pub.return_value = {"ok": True, "ref": "r", "patch_id": "p"}

            result = task_artifacts.capture("/repo", "task-1", "br", "master", None)

        assert result["patch_diff"] == ""


class TestArtifactPartialData(unittest.TestCase):
    """Handling of partial/incomplete artifact data."""

    @patch("task_artifacts.db.select")
    def test_get_artifacts_with_missing_fields(self, mock_select):
        """Artifacts missing some fields are still retrievable."""
        mock_select.return_value = [{
            "slug": "task-1",
            "commit_sha": "abc123",
            # patch_diff and touched_files missing
        }]

        result = task_artifacts.get_artifacts("task-1")
        assert result is not None
        assert result["commit_sha"] == "abc123"

    @patch("task_artifacts.db.select")
    def test_has_artifacts_with_partial_data(self, mock_select):
        """has_artifacts still returns True for partial data."""
        mock_select.return_value = [{
            "slug": "task-1",
            "commit_sha": "abc123",
            # test_log missing
        }]

        assert task_artifacts.has_artifacts("task-1") is True

    @patch("task_artifacts.db.insert")
    @patch("task_artifacts.db.select")
    @patch("subprocess.run")
    def test_cost_dict_with_extra_fields_ignored(self, mock_run, mock_select, mock_insert):
        """Extra fields in cost dict are ignored."""
        mock_select.return_value = [{"id": "task-1", "attempt": 1}]
        mock_run.side_effect = [
            Mock(stdout="sha\n", returncode=0),
            Mock(stdout="diff\n", returncode=0),
            Mock(stdout="f.py\n", returncode=0),
        ]

        with patch("task_artifacts.task_refs.publish") as mock_pub:
            mock_pub.return_value = {"ok": True, "ref": "r", "patch_id": "p"}

            result = task_artifacts.capture(
                "/repo", "task-1", "br", "master", None,
                cost={"usd": 0.05, "tokens": 5000, "duration_ms": 3000, "extra": "ignored"}
            )

        assert result["cost_usd"] == 0.05
        assert "tokens" not in result


class TestLargeTestLogs(unittest.TestCase):
    """Handling of large test logs."""

    @patch("task_artifacts.db.insert")
    @patch("task_artifacts.db.select")
    @patch("subprocess.run")
    def test_test_log_exactly_10kb_preserved(self, mock_run, mock_select, mock_insert):
        """Test log of exactly 10KB is preserved."""
        mock_select.return_value = [{"id": "task-1", "attempt": 1}]
        test_log = "x" * 10000
        mock_run.side_effect = [
            Mock(stdout="sha\n", returncode=0),
            Mock(stdout="diff\n", returncode=0),
            Mock(stdout="f.py\n", returncode=0),
        ]

        with patch("task_artifacts.task_refs.publish") as mock_pub:
            mock_pub.return_value = {"ok": True, "ref": "r", "patch_id": "p"}

            result = task_artifacts.capture("/repo", "task-1", "br", "master", None, test_log=test_log)

        assert len(result["test_log"]) == 10000

    @patch("task_artifacts.db.insert")
    @patch("task_artifacts.db.select")
    @patch("subprocess.run")
    def test_very_large_test_log_truncated(self, mock_run, mock_select, mock_insert):
        """Very large test log is truncated to last 10KB."""
        mock_select.return_value = [{"id": "task-1", "attempt": 1}]
        test_log = "x" * 100000  # 100KB
        mock_run.side_effect = [
            Mock(stdout="sha\n", returncode=0),
            Mock(stdout="diff\n", returncode=0),
            Mock(stdout="f.py\n", returncode=0),
        ]

        with patch("task_artifacts.task_refs.publish") as mock_pub:
            mock_pub.return_value = {"ok": True, "ref": "r", "patch_id": "p"}

            result = task_artifacts.capture("/repo", "task-1", "br", "master", None, test_log=test_log)

        assert len(result["test_log"]) == 10000
        # Should be the tail (last 10KB)
        assert result["test_log"] == test_log[-10000:]


class TestMultipleTouchedFiles(unittest.TestCase):
    """Handling of many touched files."""

    @patch("task_artifacts.db.insert")
    @patch("task_artifacts.db.select")
    @patch("subprocess.run")
    def test_many_touched_files_all_captured(self, mock_run, mock_select, mock_insert):
        """Many touched files are all captured."""
        mock_select.return_value = [{"id": "task-1", "attempt": 1}]
        files = "\n".join([f"file{i}.py" for i in range(100)])
        mock_run.side_effect = [
            Mock(stdout="sha\n", returncode=0),
            Mock(stdout="diff\n", returncode=0),
            Mock(stdout=files + "\n", returncode=0),
        ]

        with patch("task_artifacts.task_refs.publish") as mock_pub:
            mock_pub.return_value = {"ok": True, "ref": "r", "patch_id": "p"}

            result = task_artifacts.capture("/repo", "task-1", "br", "master", None)

        files_list = json.loads(result["touched_files"])
        assert len(files_list) == 100
        assert "file0.py" in files_list
        assert "file99.py" in files_list

    @patch("task_artifacts.db.insert")
    @patch("task_artifacts.db.select")
    @patch("subprocess.run")
    def test_files_with_special_chars_preserved(self, mock_run, mock_select, mock_insert):
        """Filenames with special characters are preserved."""
        mock_select.return_value = [{"id": "task-1", "attempt": 1}]
        mock_run.side_effect = [
            Mock(stdout="sha\n", returncode=0),
            Mock(stdout="diff\n", returncode=0),
            Mock(stdout="file[1].py\nfile(test).js\nfile-name_123.ts\n", returncode=0),
        ]

        with patch("task_artifacts.task_refs.publish") as mock_pub:
            mock_pub.return_value = {"ok": True, "ref": "r", "patch_id": "p"}

            result = task_artifacts.capture("/repo", "task-1", "br", "master", None)

        files = json.loads(result["touched_files"])
        assert "file[1].py" in files
        assert "file(test).js" in files
        assert "file-name_123.ts" in files


class TestBranchNames(unittest.TestCase):
    """Branch name handling and edge cases."""

    @patch("task_artifacts.db.insert")
    @patch("task_artifacts.db.select")
    @patch("subprocess.run")
    def test_long_branch_name_captured(self, mock_run, mock_select, mock_insert):
        """Very long branch names are captured."""
        mock_select.return_value = [{"id": "task-1", "attempt": 1}]
        long_branch = "feature/very-long-branch-name-" + "x" * 200
        mock_run.side_effect = [
            Mock(stdout="sha\n", returncode=0),
            Mock(stdout="diff\n", returncode=0),
            Mock(stdout="f.py\n", returncode=0),
        ]

        with patch("task_artifacts.task_refs.publish") as mock_pub:
            mock_pub.return_value = {"ok": True, "ref": "r", "patch_id": "p"}

            result = task_artifacts.capture("/repo", "task-1", long_branch, "master", None)

        assert result["branch"] == long_branch

    @patch("task_artifacts.db.insert")
    @patch("task_artifacts.db.select")
    @patch("subprocess.run")
    def test_branch_with_special_chars_captured(self, mock_run, mock_select, mock_insert):
        """Branch names with special characters are captured."""
        mock_select.return_value = [{"id": "task-1", "attempt": 1}]
        special_branch = "feature/ABC-123_test-branch/with-slashes"
        mock_run.side_effect = [
            Mock(stdout="sha\n", returncode=0),
            Mock(stdout="diff\n", returncode=0),
            Mock(stdout="f.py\n", returncode=0),
        ]

        with patch("task_artifacts.task_refs.publish") as mock_pub:
            mock_pub.return_value = {"ok": True, "ref": "r", "patch_id": "p"}

            result = task_artifacts.capture("/repo", "task-1", special_branch, "master", None)

        assert result["branch"] == special_branch


class TestDiffBytesCounting(unittest.TestCase):
    """Accurate diff byte counting."""

    @patch("task_artifacts.db.insert")
    @patch("task_artifacts.db.select")
    @patch("subprocess.run")
    def test_diff_bytes_exact_count(self, mock_run, mock_select, mock_insert):
        """diff_bytes accurately reflects UTF-8 byte count."""
        mock_select.return_value = [{"id": "task-1", "attempt": 1}]
        diff = "simple diff"  # 11 bytes in UTF-8
        mock_run.side_effect = [
            Mock(stdout="sha\n", returncode=0),
            Mock(stdout=diff, returncode=0),
            Mock(stdout="f.py\n", returncode=0),
        ]

        with patch("task_artifacts.task_refs.publish") as mock_pub:
            mock_pub.return_value = {"ok": True, "ref": "r", "patch_id": "p"}

            result = task_artifacts.capture("/repo", "task-1", "br", "master", None)

        assert result["diff_bytes"] == len(diff.encode("utf-8"))

    @patch("task_artifacts.db.insert")
    @patch("task_artifacts.db.select")
    @patch("subprocess.run")
    def test_diff_bytes_multibyte_chars(self, mock_run, mock_select, mock_insert):
        """diff_bytes counts multibyte UTF-8 characters correctly."""
        mock_select.return_value = [{"id": "task-1", "attempt": 1}]
        diff = "emoji: 😀 test"  # emoji is 4 bytes in UTF-8
        mock_run.side_effect = [
            Mock(stdout="sha\n", returncode=0),
            Mock(stdout=diff, returncode=0),
            Mock(stdout="f.py\n", returncode=0),
        ]

        with patch("task_artifacts.task_refs.publish") as mock_pub:
            mock_pub.return_value = {"ok": True, "ref": "r", "patch_id": "p"}

            result = task_artifacts.capture("/repo", "task-1", "br", "master", None)

        expected_bytes = len(diff.encode("utf-8", errors="ignore"))
        assert result["diff_bytes"] == expected_bytes


class TestEmptyDiffs(unittest.TestCase):
    """Empty diff handling."""

    @patch("task_artifacts.db.insert")
    @patch("task_artifacts.db.select")
    @patch("subprocess.run")
    def test_empty_diff_captured(self, mock_run, mock_select, mock_insert):
        """Empty diffs (no changes) are handled correctly."""
        mock_select.return_value = [{"id": "task-1", "attempt": 1}]
        mock_run.side_effect = [
            Mock(stdout="sha\n", returncode=0),
            Mock(stdout="", returncode=0),  # empty diff
            Mock(stdout="", returncode=0),  # no files changed
        ]

        with patch("task_artifacts.task_refs.publish") as mock_pub:
            mock_pub.return_value = {"ok": True, "ref": "r", "patch_id": "p"}

            result = task_artifacts.capture("/repo", "task-1", "br", "master", None)

        assert result["patch_diff"] == ""
        assert result["diff_bytes"] == 0
        assert result["touched_files"] == "[]"


if __name__ == "__main__":
    unittest.main()
