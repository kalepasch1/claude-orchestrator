#!/usr/bin/env python3
"""Integration and end-to-end tests for merged_diff_memory.py.

Tests production scenarios including idempotency, memory directory structure,
encoding edge cases, and realistic multi-agent workflows.
"""
import os
import sys
import json
import tempfile
import subprocess
import shutil
from pathlib import Path
from unittest import mock

import merged_diff_memory as mdm


def _setup_multi_agent_repo(tmp_dir: str) -> str:
    """Create a test repo with multiple agent branch merges."""
    repo = os.path.join(tmp_dir, "multi_agent_repo")
    os.makedirs(repo)

    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True, capture_output=True)

    # Initial commit
    Path(os.path.join(repo, "README.md")).write_text("# Multi-Agent Test Repo\n")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, check=True, capture_output=True)

    # Create 3 agent branches and merge them
    for i in range(3):
        branch_name = f"agent/feature-{i:03d}"
        subprocess.run(["git", "checkout", "-b", branch_name], cwd=repo, check=True, capture_output=True)

        # Add files
        feature_file = os.path.join(repo, f"feature_{i}.py")
        Path(feature_file).write_text(f"def feature_{i}():\n    return {i}\n")
        subprocess.run(["git", "add", f"feature_{i}.py"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", f"Add feature {i}"], cwd=repo, check=True, capture_output=True)

        # Merge back
        subprocess.run(["git", "checkout", "master"], cwd=repo, check=True, capture_output=True)
        subprocess.run(
            ["git", "merge", "--no-ff", "-m", f"Merge branch '{branch_name}' (auto-resolved)"],
            cwd=repo,
            check=True,
            capture_output=True,
        )

    return repo


class TestMemoryFileIdempotency:
    """Test idempotent behavior of memory file writing."""

    def test_write_twice_no_duplication(self):
        """Verify second write doesn't duplicate first."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            with mock.patch.object(Path, "home") as mock_home:
                mock_home.return_value = Path(tmp_dir)

                diff = {
                    "commit_hash": "abc123def456789",
                    "branch_name": "feature-xyz",
                    "merge_message": "Merge branch 'agent/feature-xyz'",
                    "diff": "+def func():\n+    pass",
                    "files": ["src/func.py"],
                    "author_date": "2026-08-01T10:00:00Z",
                    "extracted_at": "2026-08-01T12:01:00Z",
                }

                # Write once
                path1 = mdm.write_memory_file("test-idempotent", [diff])
                content1 = Path(path1).read_text()
                hash_count_1 = content1.count("abc123de")

                # Write same diff again
                path2 = mdm.write_memory_file("test-idempotent", [diff])

                # Should return None because no new entries
                assert path2 is None

                # Original file should be unchanged
                content2 = Path(path1).read_text()
                hash_count_2 = content2.count("abc123de")
                assert hash_count_1 == hash_count_2 == 1

    def test_write_new_diff_appends(self):
        """Verify new diffs are appended correctly."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            with mock.patch.object(Path, "home") as mock_home:
                mock_home.return_value = Path(tmp_dir)

                diff1 = {
                    "commit_hash": "hash111111111111",
                    "branch_name": "feature-1",
                    "merge_message": "Merge branch 'agent/feature-1'",
                    "diff": "+feature1",
                    "files": ["f1.py"],
                    "author_date": "2026-08-01T10:00:00Z",
                    "extracted_at": "2026-08-01T12:01:00Z",
                }

                diff2 = {
                    "commit_hash": "hash222222222222",
                    "branch_name": "feature-2",
                    "merge_message": "Merge branch 'agent/feature-2'",
                    "diff": "+feature2",
                    "files": ["f2.py"],
                    "author_date": "2026-08-01T11:00:00Z",
                    "extracted_at": "2026-08-01T12:02:00Z",
                }

                # Write first diff
                path1 = mdm.write_memory_file("test-append", [diff1])

                # Write second diff
                path2 = mdm.write_memory_file("test-append", [diff2])

                # Both should reference same file
                assert path1 == path2

                # File should contain both
                content = Path(path1).read_text()
                assert "feature-1" in content
                assert "feature-2" in content
                assert "hash11111111" in content
                assert "hash22222222" in content

    def test_write_mixed_old_and_new_diffs(self):
        """When writing mix of old and new, only new are appended."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            with mock.patch.object(Path, "home") as mock_home:
                mock_home.return_value = Path(tmp_dir)

                diff1 = {
                    "commit_hash": "existing1111111",
                    "branch_name": "feature-old",
                    "merge_message": "Merge branch 'agent/feature-old'",
                    "diff": "+old",
                    "files": ["old.py"],
                    "author_date": "2026-07-01T10:00:00Z",
                    "extracted_at": "2026-07-01T12:01:00Z",
                }

                # Write first
                path = mdm.write_memory_file("test-mixed", [diff1])

                # Now try to write both old and new
                diff2 = {
                    "commit_hash": "newentry2222222",
                    "branch_name": "feature-new",
                    "merge_message": "Merge branch 'agent/feature-new'",
                    "diff": "+new",
                    "files": ["new.py"],
                    "author_date": "2026-08-01T11:00:00Z",
                    "extracted_at": "2026-08-01T12:02:00Z",
                }

                result = mdm.write_memory_file("test-mixed", [diff1, diff2])

                # Should succeed and return path
                assert result is not None

                # Should have both
                content = Path(result).read_text()
                assert "feature-old" in content
                assert "feature-new" in content

                # But feature-old should appear only once
                assert content.count("feature-old") == 1


class TestMemoryDirectoryStructure:
    """Test memory directory creation and structure."""

    def test_memory_directory_created(self):
        """Verify memory directory is created with correct path."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            with mock.patch.object(Path, "home") as mock_home:
                mock_home.return_value = Path(tmp_dir)

                diff = {
                    "commit_hash": "abc123",
                    "branch_name": "test",
                    "merge_message": "Merge branch 'agent/test'",
                    "diff": "+code",
                    "files": ["test.py"],
                    "author_date": "2026-08-01T10:00:00Z",
                    "extracted_at": "2026-08-01T12:01:00Z",
                }

                mdm.write_memory_file("my-project", [diff])

                # Check directory structure
                expected_path = Path(tmp_dir) / ".claude" / "projects" / "-{home}-my-project" / "memory"
                assert expected_path.exists()
                assert (expected_path / "merged_changes.md").exists()

    def test_memory_path_normalization_with_slashes(self):
        """Handle project names with slashes."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            with mock.patch.object(Path, "home") as mock_home:
                mock_home.return_value = Path(tmp_dir)

                diff = {
                    "commit_hash": "def456",
                    "branch_name": "test-slash",
                    "merge_message": "Merge branch 'agent/test-slash'",
                    "diff": "+test",
                    "files": ["file.py"],
                    "author_date": "2026-08-01T10:00:00Z",
                    "extracted_at": "2026-08-01T12:01:00Z",
                }

                # Project name with slash should be normalized
                path = mdm.write_memory_file("proj/subproj", [diff])
                assert path is not None
                assert "proj-subproj" in path or "subproj" in path


class TestMemoryFileFormat:
    """Test correctness of memory file format."""

    def test_frontmatter_present_and_valid(self):
        """Verify frontmatter is valid YAML and complete."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            with mock.patch.object(Path, "home") as mock_home:
                mock_home.return_value = Path(tmp_dir)

                diff = {
                    "commit_hash": "aabbccdd11223344",
                    "branch_name": "format-test",
                    "merge_message": "Merge branch 'agent/format-test'",
                    "diff": "+def test():",
                    "files": ["test.py"],
                    "author_date": "2026-08-01T10:00:00Z",
                    "extracted_at": "2026-08-01T12:01:00Z",
                }

                path = mdm.write_memory_file("format-test", [diff])
                content = Path(path).read_text()

                # Check frontmatter
                assert content.startswith("---\n")
                assert "name: merged-changes-log" in content
                assert "type: reference" in content
                assert "updated_at:" in content
                assert content.count("---") >= 2  # Opening and closing

    def test_entry_structure_complete(self):
        """Verify each entry has all required fields."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            with mock.patch.object(Path, "home") as mock_home:
                mock_home.return_value = Path(tmp_dir)

                diff = {
                    "commit_hash": "hash1234567890ab",
                    "branch_name": "complete-test",
                    "merge_message": "Merge branch 'agent/complete-test' (auto-resolved)",
                    "diff": "+print('test')\n+pass",
                    "files": ["test1.py", "test2.py"],
                    "author_date": "2026-08-01T09:15:30Z",
                    "extracted_at": "2026-08-01T12:03:45Z",
                }

                path = mdm.write_memory_file("complete-test", [diff])
                content = Path(path).read_text()

                # Check for all fields
                assert "## complete-test" in content
                assert "author_date:" in content
                assert "commit_hash:" in content
                assert "merge_message:" in content
                assert "files_changed: 2" in content
                assert "extracted_at:" in content
                assert "### Changed files" in content
                assert "test1.py" in content
                assert "test2.py" in content
                assert "### Diff" in content
                assert "```diff" in content

    def test_diff_block_properly_formatted(self):
        """Verify diff content is wrapped in markdown code block."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            with mock.patch.object(Path, "home") as mock_home:
                mock_home.return_value = Path(tmp_dir)

                diff_content = "+def new_func():\n+    return 42\n-old line"
                diff = {
                    "commit_hash": "diffformat123456",
                    "branch_name": "diff-format",
                    "merge_message": "Merge branch 'agent/diff-format'",
                    "diff": diff_content,
                    "files": ["code.py"],
                    "author_date": "2026-08-01T10:00:00Z",
                    "extracted_at": "2026-08-01T12:01:00Z",
                }

                path = mdm.write_memory_file("diff-format", [diff])
                content = Path(path).read_text()

                # Diff should be in code block
                assert "```diff" in content
                assert "```\n" in content or content.endswith("```")
                # Content between markers
                start = content.index("```diff")
                end = content.rindex("```")
                assert start < end


class TestEncodingEdgeCases:
    """Test handling of various character encodings."""

    def test_utf8_branch_names(self):
        """Handle UTF-8 characters in branch names."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = os.path.join(tmp_dir, "utf8_repo")
            os.makedirs(repo)

            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True, capture_output=True)

            Path(os.path.join(repo, "file.txt")).write_text("initial")
            subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, check=True, capture_output=True)

            # Note: Git branch names with non-ASCII are rare, but test file content handling
            branch = "agent/feature-emoji"
            subprocess.run(["git", "checkout", "-b", branch], cwd=repo, check=True, capture_output=True)
            Path(os.path.join(repo, "emoji.py")).write_text("# 🎉 Feature with emoji\ndef test():\n    pass\n")
            subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "Add feature"], cwd=repo, check=True, capture_output=True)

            subprocess.run(["git", "checkout", "master"], cwd=repo, check=True, capture_output=True)
            subprocess.run(
                ["git", "merge", "--no-ff", "-m", f"Merge branch '{branch}' (auto-resolved)"],
                cwd=repo,
                check=True,
                capture_output=True,
            )

            # Should extract without crashing
            diffs = mdm.extract_merged_diffs(repo, limit=10)
            assert len(diffs) > 0

    def test_special_characters_in_filenames(self):
        """Handle special characters in file paths."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = os.path.join(tmp_dir, "special_repo")
            os.makedirs(repo)

            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True, capture_output=True)

            Path(os.path.join(repo, "initial.txt")).write_text("start")
            subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)

            subprocess.run(["git", "checkout", "-b", "agent/special-files"], cwd=repo, check=True, capture_output=True)

            # Files with spaces and special chars
            special_file = os.path.join(repo, "my file (1).py")
            Path(special_file).write_text("def func():\n    pass\n")
            subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "Add special"], cwd=repo, check=True, capture_output=True)

            subprocess.run(["git", "checkout", "master"], cwd=repo, check=True, capture_output=True)
            subprocess.run(
                ["git", "merge", "--no-ff", "-m", "Merge branch 'agent/special-files' (auto-resolved)"],
                cwd=repo,
                check=True,
                capture_output=True,
            )

            diffs = mdm.extract_merged_diffs(repo, limit=10)
            assert len(diffs) > 0
            assert any("my file" in f for f in diffs[0]["files"])


class TestComplexMergeScenarios:
    """Test realistic complex merge scenarios."""

    def test_multiple_agent_branches_merged_in_sequence(self):
        """Process multiple agent branch merges correctly."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = _setup_multi_agent_repo(tmp_dir)

            diffs = mdm.extract_merged_diffs(repo, limit=10)

            # Should have 3 agent branches merged
            assert len(diffs) == 3

            # All should be unique
            hashes = [d["commit_hash"] for d in diffs]
            assert len(set(hashes)) == 3

            # Branch names in order
            branch_names = [d["branch_name"] for d in diffs]
            assert "feature-000" in branch_names
            assert "feature-001" in branch_names
            assert "feature-002" in branch_names

    def test_large_diff_truncation_in_memory(self):
        """Large diffs are truncated in memory file."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            with mock.patch.object(Path, "home") as mock_home:
                mock_home.return_value = Path(tmp_dir)

                # Create very large diff
                large_diff = "+line\n" * 30000  # ~200KB
                diff = {
                    "commit_hash": "large1234567890",
                    "branch_name": "large-feature",
                    "merge_message": "Merge branch 'agent/large-feature'",
                    "diff": large_diff,
                    "files": ["huge.py"],
                    "author_date": "2026-08-01T10:00:00Z",
                    "extracted_at": "2026-08-01T12:01:00Z",
                }

                path = mdm.write_memory_file("large-test", [diff])
                content = Path(path).read_text()

                # File should still be written
                assert path is not None

                # But diff should be truncated
                assert len(content) < len(large_diff)

                # Should mention truncation via code block
                assert "```diff" in content


class TestSecurityEdgeCases:
    """Test security-related edge cases."""

    def test_secret_patterns_in_branch_name(self):
        """Branch name with secret-like content doesn't get stored."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = os.path.join(tmp_dir, "secret_branch_repo")
            os.makedirs(repo)

            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True, capture_output=True)

            Path(os.path.join(repo, "file.txt")).write_text("content")
            subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)

            # Branch name itself might have API_KEY in it (unusual but possible)
            # The filter is on diff content, not branch name
            subprocess.run(["git", "checkout", "-b", "agent/api-key-rotation"], cwd=repo, check=True, capture_output=True)
            Path(os.path.join(repo, "api.py")).write_text("api_key = 'secret123'\n")
            subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "Add api"], cwd=repo, check=True, capture_output=True)

            subprocess.run(["git", "checkout", "master"], cwd=repo, check=True, capture_output=True)
            subprocess.run(
                ["git", "merge", "--no-ff", "-m", "Merge branch 'agent/api-key-rotation' (auto-resolved)"],
                cwd=repo,
                check=True,
                capture_output=True,
            )

            diffs = mdm.extract_merged_diffs(repo, limit=10)

            # Should have extracted
            assert len(diffs) > 0

            # But secret line should be redacted
            assert "[redacted]" in diffs[0]["diff"]

    def test_multiple_secrets_handled(self):
        """Diff with multiple secret lines handled correctly."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            with mock.patch.object(Path, "home") as mock_home:
                mock_home.return_value = Path(tmp_dir)

                diff_with_secrets = """+api_key = 'secret123'
+def normal_function():
+password = 'pass123'
+    return True
+oauth_token = 'token456'
"""
                diff = {
                    "commit_hash": "multisec1234567",
                    "branch_name": "multi-secret",
                    "merge_message": "Merge branch 'agent/multi-secret'",
                    "diff": diff_with_secrets,
                    "files": ["secrets.py"],
                    "author_date": "2026-08-01T10:00:00Z",
                    "extracted_at": "2026-08-01T12:01:00Z",
                }

                path = mdm.write_memory_file("multi-secret-test", [diff])
                content = Path(path).read_text()

                # Secrets should be redacted
                assert "[redacted]" in content

                # But normal function should be visible
                assert "normal_function" in content


class TestFileListHandling:
    """Test handling of file lists in diffs."""

    def test_many_files_in_merge(self):
        """Handle merge with many file changes."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            with mock.patch.object(Path, "home") as mock_home:
                mock_home.return_value = Path(tmp_dir)

                # Simulate merge touching 100 files
                files = [f"file_{i:03d}.py" for i in range(100)]

                diff = {
                    "commit_hash": "manyfiles1234567",
                    "branch_name": "many-files",
                    "merge_message": "Merge branch 'agent/many-files'",
                    "diff": "+code",
                    "files": files,
                    "author_date": "2026-08-01T10:00:00Z",
                    "extracted_at": "2026-08-01T12:01:00Z",
                }

                path = mdm.write_memory_file("many-files-test", [diff])
                content = Path(path).read_text()

                # Should limit to 50 files in display
                assert "files_changed: 100" in content

                # Some files should be listed
                assert "file_000" in content
                assert "file_099" not in content  # Over 50 limit

    def test_no_files_in_merge(self):
        """Handle empty file list gracefully."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            with mock.patch.object(Path, "home") as mock_home:
                mock_home.return_value = Path(tmp_dir)

                diff = {
                    "commit_hash": "nofiles1234567890",
                    "branch_name": "no-files",
                    "merge_message": "Merge branch 'agent/no-files'",
                    "diff": "+some code",
                    "files": [],
                    "author_date": "2026-08-01T10:00:00Z",
                    "extracted_at": "2026-08-01T12:01:00Z",
                }

                path = mdm.write_memory_file("no-files-test", [diff])
                content = Path(path).read_text()

                assert "files_changed: 0" in content
                assert "### Changed files" in content


class TestSyncProjectMemory:
    """Test sync_project_memory integration."""

    def test_sync_with_real_repo(self):
        """Test full sync workflow with test repo."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = _setup_multi_agent_repo(tmp_dir)

            with mock.patch.object(Path, "home") as mock_home:
                mock_home.return_value = Path(tmp_dir)

                # Sync should work
                result = mdm.sync_project_memory(repo, project="test-sync")
                assert result is True

                # Memory file should exist
                memory_path = Path(tmp_dir) / ".claude" / "projects" / "-*-test-sync" / "memory" / "merged_changes.md"
                # Find it since we don't know exact path
                matches = list((Path(tmp_dir) / ".claude" / "projects").glob("**/merged_changes.md"))
                assert len(matches) > 0
                assert matches[0].exists()

    def test_sync_second_time_no_change(self):
        """Second sync doesn't re-process same commits."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = _setup_multi_agent_repo(tmp_dir)

            with mock.patch.object(Path, "home") as mock_home:
                mock_home.return_value = Path(tmp_dir)

                # First sync
                result1 = mdm.sync_project_memory(repo, project="test-sync2")
                assert result1 is True

                # Get file size
                matches = list((Path(tmp_dir) / ".claude" / "projects").glob("**/merged_changes.md"))
                size1 = matches[0].stat().st_size

                # Second sync
                result2 = mdm.sync_project_memory(repo, project="test-sync2")
                assert result2 is False  # No new diffs

                # File size unchanged
                size2 = matches[0].stat().st_size
                assert size1 == size2


class TestDateTimeHandling:
    """Test datetime parsing and formatting."""

    def test_author_date_preserved(self):
        """Author date from git is preserved."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            with mock.patch.object(Path, "home") as mock_home:
                mock_home.return_value = Path(tmp_dir)

                author_date = "2026-07-15T14:30:45Z"
                diff = {
                    "commit_hash": "datetest1234567",
                    "branch_name": "date-test",
                    "merge_message": "Merge branch 'agent/date-test'",
                    "diff": "+test",
                    "files": ["test.py"],
                    "author_date": author_date,
                    "extracted_at": "2026-08-01T12:01:00Z",
                }

                path = mdm.write_memory_file("date-test", [diff])
                content = Path(path).read_text()

                assert author_date in content

    def test_extracted_at_timestamp_recent(self):
        """Extracted_at timestamp is present and reasonable."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = _setup_multi_agent_repo(tmp_dir)

            diffs = mdm.extract_merged_diffs(repo, limit=10)

            assert len(diffs) > 0

            for diff in diffs:
                # Should be ISO format
                assert "T" in diff["extracted_at"]
                assert "Z" in diff["extracted_at"]


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
