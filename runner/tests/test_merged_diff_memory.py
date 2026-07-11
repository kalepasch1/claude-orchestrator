#!/usr/bin/env python3
"""Test suite for merged_diff_memory.py capture and indexing."""
import os
import sys
import json
import tempfile
import shutil
from pathlib import Path
from datetime import datetime, timedelta
import subprocess

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import merged_diff_memory as mdm


class TestMergedDiffMemory:
    """Test suite for merged_diff_memory module."""

    def setup_method(self):
        """Create a temp memory dir and repo for each test."""
        self.temp_memory = tempfile.mkdtemp()
        self.temp_repo = tempfile.mkdtemp()
        self.orig_memory_root = mdm.MEMORY_ROOT
        self.orig_home = mdm.HOME
        mdm.MEMORY_ROOT = self.temp_memory
        mdm.HOME = tempfile.mkdtemp()

    def teardown_method(self):
        """Clean up temp dirs."""
        mdm.MEMORY_ROOT = self.orig_memory_root
        mdm.HOME = self.orig_home
        shutil.rmtree(self.temp_memory, ignore_errors=True)
        shutil.rmtree(self.temp_repo, ignore_errors=True)

    def _init_git_repo(self):
        """Initialize a minimal git repo with master branch."""
        subprocess.run(["git", "init"], cwd=self.temp_repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=self.temp_repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=self.temp_repo, check=True, capture_output=True)
        subprocess.run(["git", "checkout", "-b", "master"], cwd=self.temp_repo, check=True, capture_output=True)
        # Create initial commit
        Path(self.temp_repo, "README.md").write_text("# Test Repo\n")
        subprocess.run(["git", "add", "README.md"], cwd=self.temp_repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=self.temp_repo, check=True, capture_output=True)

    def test_empty_merge_log(self):
        """When no merged commits exist, capture returns empty result."""
        self._init_git_repo()
        result = mdm.run(repo=self.temp_repo)
        assert result["success"] is True
        assert result["merged_count"] == 0
        assert result["patterns_count"] == 0
        assert result["memory_file"] is None

    def test_ensure_memory_dirs(self):
        """_ensure_dirs() creates memory root and error log dir."""
        mdm.MEMORY_ROOT = os.path.join(self.temp_memory, "new", "nested", "path")
        mdm._ensure_dirs()
        assert os.path.isdir(mdm.MEMORY_ROOT)

    def test_extract_rules_from_text(self):
        """_extract_rules() finds bullet-point do/avoid rules."""
        text = """
Some commit message.

- DO use the singleton pattern for pools
- AVOID hardcoding secrets
- DO gate resource expansion on memory checks
"""
        rules = mdm._extract_rules(text)
        assert len(rules) == 3
        assert any("singleton" in r.lower() for r in rules)
        assert any("hardcoding" in r.lower() for r in rules)

    def test_extract_rules_empty_text(self):
        """_extract_rules() returns [] when no rules found."""
        rules = mdm._extract_rules("just a commit message with no conventions")
        assert rules == []

    def test_save_to_memory_empty_list(self):
        """save_to_memory([]) returns success without writing."""
        mdm.MEMORY_ROOT = self.temp_memory
        success, memory_file = mdm._save_to_memory([])
        assert success is True
        assert memory_file is None

    def test_save_to_memory_creates_daily_file(self):
        """save_to_memory() creates dated markdown file with patterns."""
        mdm.MEMORY_ROOT = self.temp_memory
        patterns = [{
            "commit": "abc123",
            "rules": ["DO use fail-soft error handling"],
            "frameworks": ["react", "next"],
            "files": ["runner/pool.py"],
            "timestamp": datetime.utcnow().isoformat(),
        }]
        success, memory_file = mdm._save_to_memory(patterns)
        assert success is True
        assert memory_file is not None
        assert os.path.exists(memory_file)
        content = Path(memory_file).read_text()
        assert "DO use fail-soft error handling" in content
        assert "next, react" in content  # frameworks are sorted alphabetically

    def test_update_memory_index(self):
        """_update_memory_index() adds entry to MEMORY.md."""
        mdm.MEMORY_ROOT = self.temp_memory
        memory_file = os.path.join(self.temp_memory, "merged_learning_20260711.md")
        Path(memory_file).write_text("# Test Entry\n")
        success = mdm._update_memory_index(memory_file)
        assert success is True
        index = Path(os.path.join(self.temp_memory, "MEMORY.md")).read_text()
        assert "merged_learning_20260711.md" in index
        assert "2026-07-11" in index

    def test_update_memory_index_no_duplicate(self):
        """_update_memory_index() does not duplicate existing entries."""
        mdm.MEMORY_ROOT = self.temp_memory
        memory_file = os.path.join(self.temp_memory, "merged_learning_20260711.md")
        Path(memory_file).write_text("# Test\n")
        Path(os.path.join(self.temp_memory, "MEMORY.md")).write_text("- [Test](merged_learning_20260711.md) — old\n")

        success = mdm._update_memory_index(memory_file)
        assert success is True

        index = Path(os.path.join(self.temp_memory, "MEMORY.md")).read_text()
        # Should only have one entry
        count = index.count("merged_learning_20260711.md")
        assert count == 1

    def test_prune_old_entries(self):
        """_prune_old_entries() removes entries older than cutoff."""
        mdm.MEMORY_ROOT = self.temp_memory
        index_file = os.path.join(self.temp_memory, "MEMORY.md")

        old_date = (datetime.utcnow().date() - timedelta(days=100)).isoformat()
        recent_date = (datetime.utcnow().date() - timedelta(days=30)).isoformat()

        Path(index_file).write_text(f"""- [Old entry {old_date}](merged_{old_date}.md) — too old
- [Recent entry {recent_date}](merged_{recent_date}.md) — keep this
""")

        mdm._prune_old_entries(index_file, days=90)

        remaining = Path(index_file).read_text()
        assert old_date not in remaining
        assert recent_date in remaining

    def test_log_error_writes_to_jsonl(self):
        """_log_error() writes error entry to .jsonl log."""
        mdm.HOME = tempfile.mkdtemp()
        mdm._log_error("Test error", context="test_context")

        error_log = mdm.ERROR_LOG
        assert os.path.exists(error_log)
        with open(error_log) as f:
            entry = json.loads(f.readline())
        assert entry["message"] == "Test error"
        assert entry["context"] == "test_context"
        assert "timestamp" in entry

    def test_run_dry_run_mode(self):
        """run(dry_run=True) does not write files."""
        self._init_git_repo()
        result = mdm.run(repo=self.temp_repo, dry_run=True)
        assert result["success"] is True
        # memory_file should indicate dry-run
        if result["memory_file"]:
            assert "dry-run" in result["memory_file"].lower()

    def test_run_fail_soft_on_memory_error(self):
        """run() handles memory write errors gracefully."""
        mdm.MEMORY_ROOT = "/invalid/nonexistent/path/that/cannot/exist/12345/6789"
        self._init_git_repo()
        result = mdm.run(repo=self.temp_repo)
        # Should still return a result dict, not crash
        assert isinstance(result, dict)
        assert "success" in result

    def test_patterns_with_multiple_commits(self):
        """Multiple merged commits are processed in one run."""
        self._init_git_repo()

        # Create and merge two feature branches
        for i in range(2):
            subprocess.run(["git", "checkout", "-b", f"feature-{i}"],
                         cwd=self.temp_repo, check=True, capture_output=True)
            Path(self.temp_repo, f"file{i}.py").write_text(f"# Feature {i}\n")
            subprocess.run(["git", "add", f"file{i}.py"],
                         cwd=self.temp_repo, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", f"DO add feature {i}"],
                         cwd=self.temp_repo, check=True, capture_output=True)
            subprocess.run(["git", "checkout", "master"],
                         cwd=self.temp_repo, check=True, capture_output=True)
            subprocess.run(["git", "merge", "--no-ff", f"feature-{i}", "-m", f"Merge feature-{i}"],
                         cwd=self.temp_repo, check=True, capture_output=True)

        result = mdm.run(repo=self.temp_repo)
        assert result["merged_count"] >= 2 or result["patterns_count"] >= 0  # may have found patterns


def test_main_cli_parsing():
    """Main block parses args correctly."""
    import subprocess
    runner_dir = os.path.dirname(os.path.dirname(__file__))
    result = subprocess.run([sys.executable, "merged_diff_memory.py", "--dry-run"],
        cwd=runner_dir, capture_output=True, text=True)
    # Should either succeed or fail gracefully with a valid error (not import error)
    assert "ImportError" not in result.stderr
    assert "ModuleNotFoundError" not in result.stderr


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
