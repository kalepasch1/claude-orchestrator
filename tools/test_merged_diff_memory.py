#!/usr/bin/env python3
"""Unit tests for merged_diff_memory.py."""
import os
import sys
import tempfile
import subprocess
import shutil
from pathlib import Path
from unittest import mock

import merged_diff_memory as mdm


def _setup_test_repo(tmp_dir: str) -> str:
    """Create a minimal git repo with some agent branch merges for testing."""
    repo = os.path.join(tmp_dir, "test_repo")
    os.makedirs(repo)

    # Initialize repo
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True, capture_output=True)

    # Create initial commit
    initial_file = os.path.join(repo, "README.md")
    Path(initial_file).write_text("# Test Repo\n")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial commit"], cwd=repo, check=True, capture_output=True)

    # Create and merge an agent branch
    subprocess.run(["git", "checkout", "-b", "agent/test-feature-123"], cwd=repo, check=True, capture_output=True)
    test_file = os.path.join(repo, "feature.py")
    Path(test_file).write_text("def hello():\n    return 'world'\n")
    subprocess.run(["git", "add", "feature.py"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "agent: test-feature-123"], cwd=repo, check=True, capture_output=True)

    # Merge back to main/master
    subprocess.run(["git", "checkout", "master"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "merge", "--no-ff", "-m", "Merge branch 'agent/test-feature-123' (auto-resolved)"],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    return repo


class TestSecretDetection:
    def test_has_secrets_api_key(self):
        assert mdm._has_secrets("api_key = 'secret123'")
        assert mdm._has_secrets("API_KEY: abc123def456")

    def test_has_secrets_private_key(self):
        assert mdm._has_secrets("-----BEGIN PRIVATE KEY-----")
        assert mdm._has_secrets("private_key=xyz")

    def test_has_secrets_oauth_token(self):
        assert mdm._has_secrets("oauth_token: token123")
        assert mdm._has_secrets("access_token='abc'")

    def test_has_secrets_password(self):
        assert mdm._has_secrets("password=secret")

    def test_no_secrets_normal_code(self):
        assert not mdm._has_secrets("def hello():\n    return 'world'")
        assert not mdm._has_secrets("import os")
        assert not mdm._has_secrets("class MyClass:")

    def test_has_secrets_aws(self):
        assert mdm._has_secrets("aws_access_key_id=AKIAIOSFODNN7EXAMPLE")


class TestSanitizeDiff:
    def test_sanitize_removes_secret_lines(self):
        diff = """+api_key = 'secret123'
+normal_line()"""
        sanitized = mdm._sanitize_diff(diff)
        assert "[redacted]" in sanitized
        assert "normal_line()" in sanitized

    def test_sanitize_truncates(self):
        big_diff = "x" * 100000
        sanitized = mdm._sanitize_diff(big_diff, max_chars=50000)
        assert len(sanitized) <= 50000

    def test_sanitize_empty_input(self):
        assert mdm._sanitize_diff("") == ""
        assert mdm._sanitize_diff(None) == ""


class TestAgentBranchPattern:
    def test_agent_branch_pattern_matches(self):
        assert mdm.AGENT_BRANCH_PATTERN.match("agent/feature-123")
        assert mdm.AGENT_BRANCH_PATTERN.match("agent/qafix-beethoven-08020135")

    def test_agent_branch_pattern_no_match(self):
        assert not mdm.AGENT_BRANCH_PATTERN.match("feature/something")
        assert not mdm.AGENT_BRANCH_PATTERN.match("main")


class TestMergeCommitPattern:
    def test_merge_commit_pattern_matches(self):
        msg = "Merge branch 'agent/qafix-beethoven-08020135' (auto-resolved)"
        m = mdm.MERGE_COMMIT_PATTERN.match(msg)
        assert m
        assert m.group(1) == "qafix-beethoven-08020135"

    def test_merge_commit_pattern_double_quotes(self):
        msg = 'Merge branch "agent/feature-xyz" (auto-resolved)'
        m = mdm.MERGE_COMMIT_PATTERN.match(msg)
        assert m
        assert m.group(1) == "feature-xyz"


class TestNormalizeProjectPath:
    def test_normalize_project_path_with_beethoven(self):
        path = "/Users/kpasch/Documents/beethoven/claude-orchestrator"
        result = mdm._normalize_project_path(path)
        assert result == "claude-orchestrator"

    def test_normalize_project_path_with_documents(self):
        path = "/Users/kpasch/Documents/apparently"
        result = mdm._normalize_project_path(path)
        assert result in ("apparently", "orchestrator")

    def test_normalize_project_path_fallback(self):
        path = "/tmp/somerepo"
        result = mdm._normalize_project_path(path)
        assert result == "orchestrator"


class TestExtractMergedDiffs:
    def test_extract_merged_diffs_from_test_repo(self):
        """Integration test: extract diffs from actual test repo."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = _setup_test_repo(tmp_dir)

            diffs = mdm.extract_merged_diffs(repo, limit=10)

            assert len(diffs) > 0
            assert diffs[0]["branch_name"] == "test-feature-123"
            assert "feature.py" in diffs[0]["files"]
            assert "def hello()" in diffs[0]["diff"]
            assert diffs[0]["commit_hash"]
            assert diffs[0]["author_date"]

    def test_extract_deduplicates_by_hash(self):
        """Verify dedupe logic."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = _setup_test_repo(tmp_dir)

            diffs1 = mdm.extract_merged_diffs(repo, limit=10)
            diffs2 = mdm.extract_merged_diffs(repo, limit=10)

            assert len(diffs1) == len(diffs2)
            hashes1 = {d["commit_hash"] for d in diffs1}
            hashes2 = {d["commit_hash"] for d in diffs2}
            assert hashes1 == hashes2


class TestMemoryFileWrite:
    def test_write_memory_file_creates_file(self):
        """Test that write_memory_file creates a memory file with frontmatter."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            # Mock home directory
            with mock.patch.object(Path, "home") as mock_home:
                mock_home.return_value = Path(tmp_dir)

                merged_diffs = [
                    {
                        "commit_hash": "abc123def456",
                        "branch_name": "test-feature-123",
                        "merge_message": "Merge branch 'agent/test-feature-123'",
                        "diff": "+def new_func():\n+    pass\n",
                        "files": ["test.py"],
                        "author_date": "2026-08-01T12:00:00Z",
                        "extracted_at": "2026-08-01T12:01:00Z",
                    }
                ]

                path = mdm.write_memory_file("test-project", merged_diffs)

                assert path is not None
                assert Path(path).exists()
                content = Path(path).read_text()
                assert "merged-changes-log" in content
                assert "test-feature-123" in content
                assert "abc123de" in content

    def test_write_memory_file_idempotent(self):
        """Test that write_memory_file doesn't duplicate entries with same commit hash."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            with mock.patch.object(Path, "home") as mock_home:
                mock_home.return_value = Path(tmp_dir)

                merged_diffs = [
                    {
                        "commit_hash": "abc123def456",
                        "branch_name": "test-feature-123",
                        "merge_message": "Merge branch 'agent/test-feature-123'",
                        "diff": "+test",
                        "files": ["test.py"],
                        "author_date": "2026-08-01T12:00:00Z",
                        "extracted_at": "2026-08-01T12:01:00Z",
                    }
                ]

                path1 = mdm.write_memory_file("test-project", merged_diffs)
                size1 = Path(path1).stat().st_size

                # Write same diff again
                path2 = mdm.write_memory_file("test-project", merged_diffs)

                if path2:
                    size2 = Path(path2).stat().st_size
                    # Size should be same (no duplication)
                    assert size2 == size1
                else:
                    # Or return None if no new entries
                    assert path2 is None


class TestGetRecentMergedAgentBranches:
    def test_get_recent_merged_agent_branches(self):
        """Test fetching recent merged agent branches."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = _setup_test_repo(tmp_dir)

            branches = mdm.get_recent_merged_agent_branches(repo, limit=10)

            assert len(branches) > 0
            assert branches[0]["branch_name"] == "test-feature-123"
            assert branches[0]["commit_hash"]
            assert "Merge branch" in branches[0]["merge_message"]

    def test_get_recent_merged_agent_branches_no_matches(self):
        """Test behavior when no agent branches exist."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            # Create repo with no agent branches
            repo = os.path.join(tmp_dir, "empty_repo")
            os.makedirs(repo)
            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True, capture_output=True)

            # Create a regular (non-agent) branch and merge it
            Path(os.path.join(repo, "file.txt")).write_text("initial")
            subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, check=True, capture_output=True)

            subprocess.run(["git", "checkout", "-b", "feature/something"], cwd=repo, check=True, capture_output=True)
            Path(os.path.join(repo, "other.txt")).write_text("content")
            subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "feat"], cwd=repo, check=True, capture_output=True)

            subprocess.run(["git", "checkout", "master"], cwd=repo, check=True, capture_output=True)
            subprocess.run(
                ["git", "merge", "--no-ff", "-m", "Merge branch 'feature/something'"],
                cwd=repo,
                check=True,
                capture_output=True,
            )

            branches = mdm.get_recent_merged_agent_branches(repo, limit=10)

            # Should be empty since the branch is 'feature/*', not 'agent/*'
            assert len(branches) == 0


class TestGetMergeDiff:
    def test_get_merge_diff(self):
        """Test extracting diff from a merge commit."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = _setup_test_repo(tmp_dir)

            # Get the merge commit hash
            output = subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=repo,
                text=True,
            )
            merge_commit = output.strip()

            diff = mdm.get_merge_diff(repo, merge_commit)

            assert "feature.py" in diff or "def hello" in diff
            assert len(diff) > 0


class TestGetChangedFiles:
    def test_get_changed_files(self):
        """Test getting list of changed files from merge commit."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = _setup_test_repo(tmp_dir)

            output = subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=repo,
                text=True,
            )
            merge_commit = output.strip()

            files = mdm.get_changed_files(repo, merge_commit)

            assert "feature.py" in files


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
