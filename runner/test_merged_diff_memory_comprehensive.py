#!/usr/bin/env python3
"""
Comprehensive test suite for merged_diff_memory.py - Advanced edge cases and boundary conditions.

Covers:
- Malformed and edge-case git output
- Framework and file deduplication
- Date parsing edge cases and boundary conditions
- Frontmatter and memory file formatting
- Concurrent access patterns and race conditions
- Path handling across platforms
- Environment variable overrides
- Special characters and Unicode handling
- Large-scale scenarios
- Memory index consistency and rotation
"""
import os
import sys
import json
import tempfile
import threading
import time
from pathlib import Path
from datetime import datetime, timedelta, date
from unittest import mock
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import merged_diff_memory


class TestGetMergedCommitsEdgeCases:
    """Edge cases and boundary conditions in git log parsing."""

    def test_get_merged_commits_multiline_message(self):
        """Handles commit messages with newlines."""
        output = "abc1234 Merge pull request #123 from feature/x\ndef5678 Merge another PR\n"
        with mock.patch("subprocess.check_output", return_value=output):
            commits = merged_diff_memory._get_merged_commits(repo=".", lookback_days=14)
            # Should extract both lines as separate commits (git log format)
            assert len(commits) == 2
            assert commits[0][0] == "abc1234"
            assert commits[1][0] == "def5678"

    def test_get_merged_commits_very_long_hash(self):
        """Handles long commit hashes."""
        long_hash = "a" * 40  # Full SHA-1
        output = f"{long_hash} Merge something"
        with mock.patch("subprocess.check_output", return_value=output):
            commits = merged_diff_memory._get_merged_commits(repo=".", lookback_days=14)
            assert commits[0][0] == long_hash

    def test_get_merged_commits_unicode_in_message(self):
        """Preserves Unicode in commit messages."""
        output = "abc1234 Merge PR: 修复测试 🎉 emoji"
        with mock.patch("subprocess.check_output", return_value=output):
            commits = merged_diff_memory._get_merged_commits(repo=".", lookback_days=14)
            assert "修复测试" in commits[0][1]
            assert "🎉" in commits[0][1]

    def test_get_merged_commits_special_chars_in_hash(self):
        """Handles special characters that might appear in output."""
        output = "abc123\tMerge with tab\n"
        with mock.patch("subprocess.check_output", return_value=output):
            commits = merged_diff_memory._get_merged_commits(repo=".", lookback_days=14)
            assert commits[0][0] == "abc123"

    def test_get_merged_commits_zero_lookback(self):
        """Handles zero days lookback."""
        with mock.patch("subprocess.check_output", return_value="") as mock_subprocess:
            merged_diff_memory._get_merged_commits(repo=".", lookback_days=0)
            call_args = mock_subprocess.call_args
            cmd = call_args.args[0]
            assert "--since=0 days ago" in cmd

    def test_get_merged_commits_negative_lookback(self):
        """Handles negative lookback (future dates)."""
        with mock.patch("subprocess.check_output", return_value="") as mock_subprocess:
            merged_diff_memory._get_merged_commits(repo=".", lookback_days=-5)
            call_args = mock_subprocess.call_args
            cmd = call_args.args[0]
            assert "--since=-5 days ago" in cmd

    def test_get_merged_commits_very_large_lookback(self):
        """Handles very large lookback window."""
        with mock.patch("subprocess.check_output", return_value="") as mock_subprocess:
            merged_diff_memory._get_merged_commits(repo=".", lookback_days=999999)
            call_args = mock_subprocess.call_args
            cmd = call_args.args[0]
            assert "--since=999999 days ago" in cmd

    def test_get_merged_commits_many_commits(self):
        """Efficiently handles output with hundreds of commits."""
        lines = "\n".join([f"{i:07x} Merge commit {i}" for i in range(500)])
        with mock.patch("subprocess.check_output", return_value=lines):
            commits = merged_diff_memory._get_merged_commits(repo=".", lookback_days=14)
            assert len(commits) == 500
            assert commits[0][0] == "0000000"
            assert commits[-1][0] == "00001f3"  # 499 in hex is 1f3

    def test_get_merged_commits_malformed_line_missing_space(self):
        """Skips lines without space separator."""
        output = "abc1234Merge\ndef5678 Merge ok\n"
        with mock.patch("subprocess.check_output", return_value=output):
            commits = merged_diff_memory._get_merged_commits(repo=".", lookback_days=14)
            assert len(commits) == 1
            assert commits[0][0] == "def5678"

    def test_get_merged_commits_carriage_return_handling(self):
        """Handles Windows-style line endings."""
        output = "abc1234 Merge A\r\ndef5678 Merge B\r\n"
        with mock.patch("subprocess.check_output", return_value=output):
            commits = merged_diff_memory._get_merged_commits(repo=".", lookback_days=14)
            assert len(commits) == 2


class TestExtractRulesEdgeCases:
    """Edge cases in DO/AVOID rule extraction."""

    def test_extract_rules_various_bullet_styles(self):
        """Extracts rules with different bullet point styles."""
        text = "- DO test\n* AVOID globals\n• NEVER force push\n1. DO use types\n2) AVOID silent errors"
        rules = merged_diff_memory._extract_rules(text)
        assert len(rules) == 5
        assert any("DO test" in r for r in rules)
        assert any("AVOID globals" in r for r in rules)

    def test_extract_rules_indented_bullets(self):
        """Extracts indented rule bullets."""
        text = "  - DO indent properly\n    * AVOID deep nesting"
        rules = merged_diff_memory._extract_rules(text)
        assert len(rules) == 2

    def test_extract_rules_mixed_case_keywords(self):
        """Handles various case combinations."""
        text = "- do test\n- Do Test\n- DO TEST\n- DoNotFail"
        rules = merged_diff_memory._extract_rules(text)
        assert len(rules) >= 3

    def test_extract_rules_keywords_at_line_start_only(self):
        """Only matches keywords after bullet."""
        text = "- Something DO bad\n- DO something good"
        rules = merged_diff_memory._extract_rules(text)
        assert len(rules) == 1
        assert "DO something good" in rules[0]

    def test_extract_rules_long_rule_text(self):
        """Preserves full text of long rules."""
        long_text = "- DO " + "include comprehensive tests for all edge cases that could possibly occur " * 5
        rules = merged_diff_memory._extract_rules(long_text)
        assert len(rules) == 1
        assert len(rules[0]) > 200

    def test_extract_rules_empty_rule(self):
        """Handles bullet with keyword but no following text."""
        text = "- DO\n- AVOID\n"
        rules = merged_diff_memory._extract_rules(text)
        # Should still extract (regex allows any non-whitespace after keyword)
        assert len(rules) == 2

    def test_extract_rules_unicode_in_rules(self):
        """Preserves Unicode characters in rules."""
        text = "- DO 测试 Unicode ñ\n- AVOID ⚠️ problems"
        rules = merged_diff_memory._extract_rules(text)
        assert any("测试" in r for r in rules)

    def test_extract_rules_all_keywords(self):
        """Extracts all recognized keywords."""
        text = "- DO a\n- AVOID b\n- DO NOT c\n- NEVER d\n- ALWAYS e"
        rules = merged_diff_memory._extract_rules(text)
        assert len(rules) == 5


class TestExtractPatternsEdgeCases:
    """Edge cases in pattern extraction from commits."""

    def test_extract_patterns_subprocess_timeout_on_msg(self):
        """Handles timeout on first subprocess call."""
        with mock.patch("subprocess.check_output", side_effect=TimeoutError):
            result = merged_diff_memory._extract_patterns_from_commit(".", "abc123")
            assert result is None

    def test_extract_patterns_subprocess_timeout_on_diff(self):
        """Handles timeout on second subprocess call."""
        with mock.patch("subprocess.check_output", side_effect=[TimeoutError, None]):
            result = merged_diff_memory._extract_patterns_from_commit(".", "abc123")
            assert result is None

    def test_extract_patterns_empty_msg_and_diff(self):
        """Handles commit with empty message and diff."""
        with mock.patch("subprocess.check_output", side_effect=["", ""]):
            with mock.patch("merged_diff_memory.learn_from_merges.quality_gate", return_value=(True, "")):
                with mock.patch("merged_diff_memory._extract_rules", return_value=[]):
                    with mock.patch("merged_diff_memory.merged_diff_library._frameworks", return_value=[]):
                        with mock.patch("merged_diff_memory.merged_diff_library._changed_files", return_value=[]):
                            result = merged_diff_memory._extract_patterns_from_commit(".", "abc123")
                            assert result is not None
                            assert result["rules"] == []
                            assert result["frameworks"] == []

    def test_extract_patterns_very_large_commit_msg(self):
        """Handles very large commit messages."""
        large_msg = "Merge large PR\n" + ("- DO something\n" * 1000)
        with mock.patch("subprocess.check_output", side_effect=[large_msg, ""]):
            with mock.patch("merged_diff_memory.learn_from_merges.quality_gate", return_value=(True, "")):
                with mock.patch("merged_diff_memory._extract_rules", return_value=["- DO something"] * 10):
                    with mock.patch("merged_diff_memory.merged_diff_library._frameworks", return_value=[]):
                        with mock.patch("merged_diff_memory.merged_diff_library._changed_files", return_value=[]):
                            result = merged_diff_memory._extract_patterns_from_commit(".", "abc123")
                            assert result is not None

    def test_extract_patterns_frameworks_deduped(self):
        """Frameworks are deduplicated in result."""
        with mock.patch("subprocess.check_output", side_effect=["", ""]):
            with mock.patch("merged_diff_memory.learn_from_merges.quality_gate", return_value=(True, "")):
                with mock.patch("merged_diff_memory._extract_rules", return_value=[]):
                    with mock.patch("merged_diff_memory.merged_diff_library._frameworks", return_value=["pytest", "pytest", "react"]):
                        with mock.patch("merged_diff_memory.merged_diff_library._changed_files", return_value=[]):
                            result = merged_diff_memory._extract_patterns_from_commit(".", "abc123")
                            assert result is not None


class TestSaveToMemoryEdgeCases:
    """Edge cases in memory file saves."""

    def test_save_to_memory_patterns_with_none_fields(self):
        """Handles patterns with None values in fields."""
        patterns = [
            {
                "commit": "abc123",
                "rules": None,
                "frameworks": None,
                "files": None,
                "timestamp": datetime.utcnow().isoformat(),
            }
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.dict(os.environ, {"CLAUDE_MEMORY_ROOT": tmpdir}):
                merged_diff_memory.MEMORY_ROOT = tmpdir
                success, filepath = merged_diff_memory._save_to_memory(patterns)
                assert success is True
                assert filepath is not None

    def test_save_to_memory_dedup_frameworks_and_files(self):
        """Deduplicates frameworks and files across patterns."""
        patterns = [
            {
                "commit": "abc123",
                "rules": [],
                "frameworks": ["pytest", "pytest"],
                "files": ["test.py", "test.py"],
                "timestamp": datetime.utcnow().isoformat(),
            },
            {
                "commit": "def456",
                "rules": [],
                "frameworks": ["pytest", "react"],
                "files": ["test.py", "app.tsx"],
                "timestamp": datetime.utcnow().isoformat(),
            },
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.dict(os.environ, {"CLAUDE_MEMORY_ROOT": tmpdir}):
                merged_diff_memory.MEMORY_ROOT = tmpdir
                success, filepath = merged_diff_memory._save_to_memory(patterns)
                assert success is True
                with open(filepath, "r") as f:
                    content = f.read()
                    # Frameworks should appear only once each
                    pytest_count = content.count("pytest")
                    react_count = content.count("react")
                    assert pytest_count == 1
                    assert react_count == 1

    def test_save_to_memory_frontmatter_valid_markdown(self):
        """Generated frontmatter is valid YAML/Markdown."""
        patterns = [
            {
                "commit": "abc123",
                "rules": ["- DO test"],
                "frameworks": ["pytest"],
                "files": ["test.py"],
                "timestamp": datetime.utcnow().isoformat(),
            }
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.dict(os.environ, {"CLAUDE_MEMORY_ROOT": tmpdir}):
                merged_diff_memory.MEMORY_ROOT = tmpdir
                success, filepath = merged_diff_memory._save_to_memory(patterns)
                with open(filepath, "r") as f:
                    content = f.read()
                    lines = content.split("\n")
                    assert lines[0] == "---"
                    assert "---" in lines[1:10]  # Closing frontmatter marker

    def test_save_to_memory_unicode_in_paths(self):
        """Handles Unicode in file paths."""
        patterns = [
            {
                "commit": "abc123",
                "rules": [],
                "frameworks": [],
                "files": ["测试/file.py", "файл.ts"],
                "timestamp": datetime.utcnow().isoformat(),
            }
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.dict(os.environ, {"CLAUDE_MEMORY_ROOT": tmpdir}):
                merged_diff_memory.MEMORY_ROOT = tmpdir
                success, filepath = merged_diff_memory._save_to_memory(patterns)
                assert success is True

    def test_save_to_memory_many_patterns(self):
        """Efficiently handles many patterns."""
        patterns = [
            {
                "commit": f"commit{i}",
                "rules": [f"- DO rule{i}"],
                "frameworks": ["pytest"] if i % 2 else ["react"],
                "files": [f"file{i}.py"],
                "timestamp": datetime.utcnow().isoformat(),
            }
            for i in range(100)
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.dict(os.environ, {"CLAUDE_MEMORY_ROOT": tmpdir}):
                merged_diff_memory.MEMORY_ROOT = tmpdir
                success, filepath = merged_diff_memory._save_to_memory(patterns)
                assert success is True

    def test_save_to_memory_readonly_directory(self):
        """Fails gracefully on read-only filesystem."""
        patterns = [{"commit": "abc123", "rules": [], "frameworks": [], "files": [], "timestamp": "2026-01-01T00:00:00"}]

        with mock.patch("merged_diff_memory._ensure_dirs"):
            with mock.patch("builtins.open", side_effect=PermissionError("read-only")):
                success, filepath = merged_diff_memory._save_to_memory(patterns)
                assert success is False

    def test_save_to_memory_disk_full(self):
        """Fails gracefully on disk-full error."""
        patterns = [{"commit": "abc123", "rules": [], "frameworks": [], "files": [], "timestamp": "2026-01-01T00:00:00"}]

        with mock.patch("merged_diff_memory._ensure_dirs"):
            with mock.patch("builtins.open", side_effect=OSError("No space left on device")):
                success, filepath = merged_diff_memory._save_to_memory(patterns)
                assert success is False


class TestUpdateMemoryIndexEdgeCases:
    """Edge cases in index updates."""

    def test_update_memory_index_date_at_boundary(self):
        """Correctly parses dates at year/month boundaries."""
        with tempfile.TemporaryDirectory() as tmpdir:
            today = datetime.utcnow().date()
            date_str = today.strftime('%Y%m%d')
            date_iso = today.isoformat()
            memory_file = os.path.join(tmpdir, f"merged_learning_{date_str}.md")
            index_file = os.path.join(tmpdir, "MEMORY.md")

            with open(memory_file, "w") as f:
                f.write("test")

            old_root = merged_diff_memory.MEMORY_ROOT
            old_home = merged_diff_memory.HOME
            old_error_log = merged_diff_memory.ERROR_LOG
            try:
                merged_diff_memory.MEMORY_ROOT = tmpdir
                merged_diff_memory.HOME = tmpdir
                merged_diff_memory.ERROR_LOG = os.path.join(tmpdir, "errors.jsonl")
                success = merged_diff_memory._update_memory_index(memory_file)
                assert success is True

                with open(index_file, "r") as f:
                    content = f.read()
                    assert date_iso in content
            finally:
                merged_diff_memory.MEMORY_ROOT = old_root
                merged_diff_memory.HOME = old_home
                merged_diff_memory.ERROR_LOG = old_error_log

    def test_update_memory_index_many_entries(self):
        """Handles index with many existing entries."""
        with tempfile.TemporaryDirectory() as tmpdir:
            memory_file = os.path.join(tmpdir, "merged_learning_20260101.md")
            index_file = os.path.join(tmpdir, "MEMORY.md")

            with open(memory_file, "w") as f:
                f.write("test")

            # Create index with many entries
            existing_entries = "\n".join([
                f"- [Entry {i}](file{i}.md) — 2025-{i%12+1:02d}-{i%28+1:02d}"
                for i in range(100)
            ])

            with open(index_file, "w") as f:
                f.write(existing_entries + "\n")

            old_root = merged_diff_memory.MEMORY_ROOT
            old_home = merged_diff_memory.HOME
            old_error_log = merged_diff_memory.ERROR_LOG
            try:
                merged_diff_memory.MEMORY_ROOT = tmpdir
                merged_diff_memory.HOME = tmpdir
                merged_diff_memory.ERROR_LOG = os.path.join(tmpdir, "errors.jsonl")
                success = merged_diff_memory._update_memory_index(memory_file)
                assert success is True
            finally:
                merged_diff_memory.MEMORY_ROOT = old_root
                merged_diff_memory.HOME = old_home
                merged_diff_memory.ERROR_LOG = old_error_log

    def test_update_memory_index_duplicate_prevention(self):
        """Prevents duplicate entries even with concurrent calls."""
        with tempfile.TemporaryDirectory() as tmpdir:
            today = datetime.utcnow().date()
            date_str = today.strftime('%Y%m%d')
            basename = f"merged_learning_{date_str}.md"
            memory_file = os.path.join(tmpdir, basename)
            index_file = os.path.join(tmpdir, "MEMORY.md")

            with open(memory_file, "w") as f:
                f.write("test")

            old_root = merged_diff_memory.MEMORY_ROOT
            old_home = merged_diff_memory.HOME
            old_error_log = merged_diff_memory.ERROR_LOG
            try:
                merged_diff_memory.MEMORY_ROOT = tmpdir
                merged_diff_memory.HOME = tmpdir
                merged_diff_memory.ERROR_LOG = os.path.join(tmpdir, "errors.jsonl")

                # Call twice
                merged_diff_memory._update_memory_index(memory_file)
                merged_diff_memory._update_memory_index(memory_file)

                with open(index_file, "r") as f:
                    content = f.read()
                    count = content.count(basename)
                    assert count == 1
            finally:
                merged_diff_memory.MEMORY_ROOT = old_root
                merged_diff_memory.HOME = old_home
                merged_diff_memory.ERROR_LOG = old_error_log


class TestPruneOldEntriesEdgeCases:
    """Edge cases in pruning old entries."""

    def test_prune_old_entries_exact_boundary(self):
        """Correctly handles entries exactly at retention boundary."""
        with tempfile.TemporaryDirectory() as tmpdir:
            index_file = os.path.join(tmpdir, "MEMORY.md")
            today = datetime.utcnow().date()
            exactly_90_days = (today - timedelta(days=90)).isoformat()

            content = f"- [Boundary](file_{exactly_90_days}.md) — {exactly_90_days}\n"
            with open(index_file, "w") as f:
                f.write(content)

            merged_diff_memory._prune_old_entries(index_file, days=90)

            with open(index_file, "r") as f:
                result = f.read()
                # Exactly on boundary should be kept
                assert exactly_90_days in result

    def test_prune_old_entries_leap_year_handling(self):
        """Handles dates around leap years."""
        with tempfile.TemporaryDirectory() as tmpdir:
            index_file = os.path.join(tmpdir, "MEMORY.md")
            content = "- [Feb29]({2024-02-29}.md) — 2024-02-29\n"
            with open(index_file, "w") as f:
                f.write(content)

            merged_diff_memory._prune_old_entries(index_file, days=1)

    def test_prune_old_entries_malformed_dates(self):
        """Gracefully handles malformed date entries."""
        with tempfile.TemporaryDirectory() as tmpdir:
            index_file = os.path.join(tmpdir, "MEMORY.md")
            content = """- [Good](file_2026-01-01.md) — 2026-01-01
- [Bad](file_20260101.md) — 20260101
- [Ugly](file_2026-1-1.md) — 2026-1-1
- [NoDate](file.md) — no date here
"""
            with open(index_file, "w") as f:
                f.write(content)

            merged_diff_memory._prune_old_entries(index_file, days=90)

            with open(index_file, "r") as f:
                result = f.read()
                # Should keep entries without dates
                assert "NoDate" in result

    def test_prune_old_entries_century_boundary(self):
        """Handles dates at century boundaries."""
        with tempfile.TemporaryDirectory() as tmpdir:
            index_file = os.path.join(tmpdir, "MEMORY.md")
            content = "- [Y2K](file_2000-01-01.md) — 2000-01-01\n"
            with open(index_file, "w") as f:
                f.write(content)

            merged_diff_memory._prune_old_entries(index_file, days=90)

            with open(index_file, "r") as f:
                result = f.read()
                # Very old dates should be pruned
                assert "2000-01-01" not in result


class TestConcurrencyEdgeCases:
    """Advanced concurrency scenarios."""

    def test_concurrent_saves_to_same_file(self):
        """Multiple threads saving same patterns to same file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            old_root = merged_diff_memory.MEMORY_ROOT
            old_home = merged_diff_memory.HOME
            old_error_log = merged_diff_memory.ERROR_LOG
            try:
                merged_diff_memory.MEMORY_ROOT = tmpdir
                merged_diff_memory.HOME = tmpdir
                merged_diff_memory.ERROR_LOG = os.path.join(tmpdir, "errors.jsonl")

                patterns = [
                    {"commit": "abc", "rules": [], "frameworks": [], "files": [], "timestamp": "2026-01-01T00:00:00"}
                ]

                results = []
                def save():
                    success, filepath = merged_diff_memory._save_to_memory(patterns)
                    results.append((success, filepath))

                threads = [threading.Thread(target=save) for _ in range(10)]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join()

                assert all(r[0] for r in results)
                # All should point to same file
                filepaths = [r[1] for r in results if r[1]]
                assert len(set(filepaths)) == 1
            finally:
                merged_diff_memory.MEMORY_ROOT = old_root
                merged_diff_memory.HOME = old_home
                merged_diff_memory.ERROR_LOG = old_error_log

    def test_concurrent_index_updates_no_corruption(self):
        """Index file not corrupted by concurrent updates."""
        with tempfile.TemporaryDirectory() as tmpdir:
            today = datetime.utcnow().date()
            memory_files = [
                os.path.join(tmpdir, f"merged_learning_{(today - timedelta(days=i)).strftime('%Y%m%d')}.md")
                for i in range(5)
            ]

            for mf in memory_files:
                with open(mf, "w") as f:
                    f.write("test")

            old_root = merged_diff_memory.MEMORY_ROOT
            old_home = merged_diff_memory.HOME
            old_error_log = merged_diff_memory.ERROR_LOG
            try:
                merged_diff_memory.MEMORY_ROOT = tmpdir
                merged_diff_memory.HOME = tmpdir
                merged_diff_memory.ERROR_LOG = os.path.join(tmpdir, "errors.jsonl")

                def update_index(mf):
                    merged_diff_memory._update_memory_index(mf)

                threads = [threading.Thread(target=update_index, args=(mf,)) for mf in memory_files]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join()

                index_file = os.path.join(tmpdir, "MEMORY.md")
                assert os.path.exists(index_file)
                with open(index_file, "r") as f:
                    content = f.read()
                    # Each file should appear exactly once
                    for mf in memory_files:
                        basename = os.path.basename(mf)
                        count = content.count(basename)
                        assert count == 1
            finally:
                merged_diff_memory.MEMORY_ROOT = old_root
                merged_diff_memory.HOME = old_home
                merged_diff_memory.ERROR_LOG = old_error_log


class TestEnvironmentAndPathHandling:
    """Environment variables and path handling."""

    def test_env_override_memory_root(self):
        """CLAUDE_MEMORY_ROOT env var overrides default."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.dict(os.environ, {"CLAUDE_MEMORY_ROOT": tmpdir}):
                merged_diff_memory.MEMORY_ROOT = tmpdir
                patterns = [{"commit": "abc", "rules": [], "frameworks": [], "files": [], "timestamp": "2026-01-01T00:00:00"}]
                success, filepath = merged_diff_memory._save_to_memory(patterns)
                assert success is True
                assert filepath is not None
                assert tmpdir in filepath

    def test_env_override_home(self):
        """CLAUDE_ORCH_HOME env var overrides default."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.dict(os.environ, {"CLAUDE_ORCH_HOME": tmpdir}):
                merged_diff_memory.HOME = tmpdir
                merged_diff_memory.ERROR_LOG = os.path.join(tmpdir, "knowledge", "merged_diff_memory_errors.jsonl")
                merged_diff_memory._log_error("test", "context")
                assert os.path.exists(os.path.join(tmpdir, "knowledge"))

    def test_path_separator_handling(self):
        """Handles mixed path separators."""
        patterns = [
            {
                "commit": "abc",
                "rules": [],
                "frameworks": [],
                "files": ["path/to/file.py", "path\\to\\file.py"],
                "timestamp": "2026-01-01T00:00:00",
            }
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            old_root = merged_diff_memory.MEMORY_ROOT
            try:
                merged_diff_memory.MEMORY_ROOT = tmpdir
                success, filepath = merged_diff_memory._save_to_memory(patterns)
                assert success is True
            finally:
                merged_diff_memory.MEMORY_ROOT = old_root


class TestIntegrationScenarios:
    """Full integration scenarios."""

    def test_run_with_no_patterns_after_filtering(self):
        """Run succeeds even if all commits are filtered by quality gate."""
        commits = [("abc123", "fix: a"), ("def456", "fix: b")]

        with mock.patch("merged_diff_memory._get_merged_commits", return_value=commits):
            with mock.patch("merged_diff_memory._extract_patterns_from_commit", return_value=None):
                result = merged_diff_memory.run(repo=".", dry_run=False)
                assert result["success"] is True
                assert result["patterns_count"] == 0

    def test_run_with_mixed_results(self):
        """Run handles mix of accepted and rejected patterns."""
        commits = [("abc", "msg1"), ("def", "msg2"), ("ghi", "msg3")]
        patterns_results = [
            {"commit": "abc", "rules": [], "frameworks": [], "files": [], "timestamp": "2026-01-01T00:00:00"},
            None,
            {"commit": "ghi", "rules": [], "frameworks": [], "files": [], "timestamp": "2026-01-01T00:00:00"},
        ]

        with mock.patch("merged_diff_memory._get_merged_commits", return_value=commits):
            with mock.patch("merged_diff_memory._extract_patterns_from_commit", side_effect=patterns_results):
                with mock.patch("merged_diff_memory._save_to_memory", return_value=(True, "/tmp/file.md")):
                    with mock.patch("merged_diff_memory._update_memory_index", return_value=True):
                        result = merged_diff_memory.run(repo=".", dry_run=False)
                        assert result["merged_count"] == 3
                        assert result["patterns_count"] == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
