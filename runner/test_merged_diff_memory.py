#!/usr/bin/env python3
"""
Test suite for merged_diff_memory.py - Capture learned patterns from merged commits.

Tests cover:
- Git merge log extraction with lookback windows
- Pattern extraction with quality gates
- Rule parsing from commit messages
- Memory file saves with daily rollup (idempotency, no duplicates)
- Index updates and pruning (date parsing, retention limits)
- Fail-soft error handling (no wedging on file I/O, DB, subprocess errors)
- Thread safety (concurrent writes)
"""
import os
import sys
import json
import tempfile
import threading
from pathlib import Path
from datetime import datetime, timedelta
from unittest import mock
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import merged_diff_memory


class TestGetMergedCommits:
    """Test git log extraction for merged commits."""

    def test_get_merged_commits_normal(self):
        """Returns list of (hash, msg) tuples from git log --merges."""
        output = "abc1234 Merge pull request #123\n"
        output += "def5678 Merge branch 'feature'\n"
        with mock.patch("subprocess.check_output", return_value=output):
            commits = merged_diff_memory._get_merged_commits(repo=".", lookback_days=14)
            assert len(commits) == 2
            assert commits[0] == ("abc1234", "Merge pull request #123")
            assert commits[1] == ("def5678", "Merge branch 'feature'")

    def test_get_merged_commits_empty(self):
        """Returns empty list when no merges found."""
        with mock.patch("subprocess.check_output", return_value=""):
            commits = merged_diff_memory._get_merged_commits(repo=".", lookback_days=14)
            assert commits == []

    def test_get_merged_commits_whitespace(self):
        """Ignores blank lines in output."""
        output = "abc1234 Merge A\n\ndef5678 Merge B\n  \n"
        with mock.patch("subprocess.check_output", return_value=output):
            commits = merged_diff_memory._get_merged_commits(repo=".", lookback_days=14)
            assert len(commits) == 2
            assert commits[0][0] == "abc1234"
            assert commits[1][0] == "def5678"

    def test_get_merged_commits_subprocess_timeout(self):
        """Returns empty list on subprocess timeout."""
        with mock.patch("subprocess.check_output", side_effect=TimeoutError):
            commits = merged_diff_memory._get_merged_commits(repo=".", lookback_days=14)
            assert commits == []

    def test_get_merged_commits_subprocess_error(self):
        """Returns empty list on git command failure."""
        with mock.patch("subprocess.check_output", side_effect=Exception("git not found")):
            commits = merged_diff_memory._get_merged_commits(repo=".", lookback_days=14)
            assert commits == []

    def test_get_merged_commits_lookback_default(self):
        """Uses LOOKBACK env var as default."""
        with mock.patch.dict(os.environ, {"MERGED_MEMORY_LOOKBACK": "7"}):
            merged_diff_memory.LOOKBACK = 7
            with mock.patch("subprocess.check_output", return_value="abc1234 Merge A\n") as mock_subprocess:
                merged_diff_memory._get_merged_commits(repo=".", lookback_days=None)
                call_args = mock_subprocess.call_args
                cmd = call_args.args[0]
                assert "--since=7 days ago" in cmd

    def test_get_merged_commits_explicit_lookback(self):
        """Uses explicit lookback parameter."""
        with mock.patch("subprocess.check_output", return_value="") as mock_subprocess:
            merged_diff_memory._get_merged_commits(repo=".", lookback_days=30)
            call_args = mock_subprocess.call_args
            cmd = call_args.args[0]
            assert "--since=30 days ago" in cmd


class TestExtractRules:
    """Test extraction of DO/AVOID bullet points from text."""

    def test_extract_rules_do_bullet(self):
        """Extracts lines starting with '- DO'."""
        text = "Some intro\n- DO include tests\nOther text"
        rules = merged_diff_memory._extract_rules(text)
        assert len(rules) == 1
        assert "DO include tests" in rules[0]

    def test_extract_rules_avoid_bullet(self):
        """Extracts lines starting with '- AVOID'."""
        text = "- AVOID hardcoded secrets\n- DO NOT use global state"
        rules = merged_diff_memory._extract_rules(text)
        assert len(rules) == 2
        assert any("AVOID hardcoded secrets" in r for r in rules)
        assert any("DO NOT" in r for r in rules)

    def test_extract_rules_never_always(self):
        """Extracts NEVER and ALWAYS keywords."""
        text = "• NEVER skip hooks\n* ALWAYS validate input"
        rules = merged_diff_memory._extract_rules(text)
        assert len(rules) == 2

    def test_extract_rules_numbered(self):
        """Extracts numbered lists (1., 2), etc.)."""
        text = "1. DO commit changes\n2) AVOID force push"
        rules = merged_diff_memory._extract_rules(text)
        assert len(rules) == 2

    def test_extract_rules_case_insensitive(self):
        """Matches DO/AVOID case-insensitively."""
        text = "- do check permissions\n- Avoid circular imports"
        rules = merged_diff_memory._extract_rules(text)
        assert len(rules) == 2

    def test_extract_rules_no_match(self):
        """Ignores lines without DO/AVOID keywords."""
        text = "This is a comment\n- This is a list item\nOther text"
        rules = merged_diff_memory._extract_rules(text)
        assert len(rules) == 0

    def test_extract_rules_empty_text(self):
        """Returns empty list for empty text."""
        rules = merged_diff_memory._extract_rules("")
        assert rules == []

    def test_extract_rules_none_text(self):
        """Handles None input safely."""
        rules = merged_diff_memory._extract_rules(None)
        assert rules == []

    def test_extract_rules_dedup_by_content(self):
        """Multiple identical rules are returned as-is (set union applied later)."""
        text = "- DO test\n- DO test"
        rules = merged_diff_memory._extract_rules(text)
        assert len(rules) == 2  # _extract_rules returns list; dedup happens in _save_to_memory


class TestExtractPatternsFromCommit:
    """Test pattern extraction from individual commits with quality gating."""

    def test_extract_patterns_normal_pass_quality_gate(self):
        """Extracts rules/frameworks when quality gate passes."""
        commit_hash = "abc123"
        msg = "fix: improve error handling\n- DO add tests"
        diff = "file.py | 10 ++"

        with mock.patch("subprocess.check_output", side_effect=[msg, diff]):
            with mock.patch("merged_diff_memory.learn_from_merges.quality_gate", return_value=(True, "")):
                with mock.patch("merged_diff_memory._extract_rules", return_value=["- DO add tests"]):
                    with mock.patch("merged_diff_memory.merged_diff_library._frameworks", return_value=["pytest"]):
                        with mock.patch("merged_diff_memory.merged_diff_library._changed_files", return_value=["file.py"]):
                            result = merged_diff_memory._extract_patterns_from_commit(".", commit_hash)
                            assert result is not None
                            assert result["commit"] == commit_hash
                            assert "- DO add tests" in result["rules"]
                            assert "pytest" in result["frameworks"]
                            assert "file.py" in result["files"]

    def test_extract_patterns_quality_gate_reject(self):
        """Returns None when quality gate rejects."""
        commit_hash = "abc123"
        msg = "wip"
        diff = ""

        with mock.patch("subprocess.check_output", side_effect=[msg, diff]):
            with mock.patch("merged_diff_memory.learn_from_merges.quality_gate", return_value=(False, "too short")):
                result = merged_diff_memory._extract_patterns_from_commit(".", commit_hash)
                assert result is None

    def test_extract_patterns_subprocess_error(self):
        """Returns None on subprocess error."""
        commit_hash = "abc123"
        with mock.patch("subprocess.check_output", side_effect=Exception("git error")):
            result = merged_diff_memory._extract_patterns_from_commit(".", commit_hash)
            assert result is None

    def test_extract_patterns_has_timestamp(self):
        """Includes UTC timestamp in result."""
        commit_hash = "abc123"
        msg = "fix: something\n- DO test"
        diff = "file | ++"

        before = datetime.utcnow().isoformat()
        with mock.patch("subprocess.check_output", side_effect=[msg, diff]):
            with mock.patch("merged_diff_memory.learn_from_merges.quality_gate", return_value=(True, "")):
                with mock.patch("merged_diff_memory._extract_rules", return_value=["- DO test"]):
                    with mock.patch("merged_diff_memory.merged_diff_library._frameworks", return_value=[]):
                        with mock.patch("merged_diff_memory.merged_diff_library._changed_files", return_value=[]):
                            result = merged_diff_memory._extract_patterns_from_commit(".", commit_hash)
                            assert result is not None
                            assert "timestamp" in result
                            ts = datetime.fromisoformat(result["timestamp"])
                            assert ts >= datetime.fromisoformat(before)


class TestSaveToMemory:
    """Test daily rollup saves to memory system."""

    def test_save_to_memory_empty_patterns(self):
        """Returns (True, None) for empty patterns list."""
        success, filepath = merged_diff_memory._save_to_memory([])
        assert success is True
        assert filepath is None

    def test_save_to_memory_first_save(self):
        """Creates memory file on first save."""
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
                assert success is True
                assert filepath is not None
                assert os.path.exists(filepath)
                with open(filepath, "r") as f:
                    content = f.read()
                    assert "merged_learning_" in content
                    assert "- DO test" in content

    def test_save_to_memory_idempotent(self):
        """Does not overwrite existing file on second save."""
        patterns = [
            {
                "commit": "abc123",
                "rules": ["- DO test"],
                "frameworks": [],
                "files": [],
                "timestamp": datetime.utcnow().isoformat(),
            }
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.dict(os.environ, {"CLAUDE_MEMORY_ROOT": tmpdir}):
                merged_diff_memory.MEMORY_ROOT = tmpdir
                success1, filepath1 = merged_diff_memory._save_to_memory(patterns)
                assert success1 is True

                with open(filepath1, "r") as f:
                    first_content = f.read()

                success2, filepath2 = merged_diff_memory._save_to_memory(patterns)
                assert success2 is True
                assert filepath2 == filepath1

                with open(filepath1, "r") as f:
                    second_content = f.read()

                assert first_content == second_content

    def test_save_to_memory_dedup_rules(self):
        """Uses set union to deduplicate rules across patterns."""
        patterns = [
            {"commit": "abc123", "rules": ["- DO test", "- DO test"], "frameworks": [], "files": [], "timestamp": "2026-01-01T00:00:00"},
            {"commit": "def456", "rules": ["- DO test", "- AVOID globals"], "frameworks": [], "files": [], "timestamp": "2026-01-01T00:00:00"},
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.dict(os.environ, {"CLAUDE_MEMORY_ROOT": tmpdir}):
                merged_diff_memory.MEMORY_ROOT = tmpdir
                success, filepath = merged_diff_memory._save_to_memory(patterns)
                assert success is True
                with open(filepath, "r") as f:
                    content = f.read()
                    count_do_test = content.count("- DO test")
                    assert count_do_test == 1
                    assert "- AVOID globals" in content

    def test_save_to_memory_permission_error(self):
        """Returns (False, None) on permission error."""
        patterns = [{"commit": "abc123", "rules": [], "frameworks": [], "files": [], "timestamp": "2026-01-01T00:00:00"}]

        with mock.patch("builtins.open", side_effect=PermissionError("denied")):
            success, filepath = merged_diff_memory._save_to_memory(patterns)
            assert success is False
            assert filepath is None


class TestUpdateMemoryIndex:
    """Test MEMORY.md index updates and pruning."""

    def test_update_memory_index_new_entry(self):
        """Adds entry to MEMORY.md if not already present."""
        with tempfile.TemporaryDirectory() as tmpdir:
            today = datetime.utcnow().date().strftime("%Y%m%d")
            memory_file = os.path.join(tmpdir, f"merged_learning_{today}.md")
            index_file = os.path.join(tmpdir, "MEMORY.md")

            with open(memory_file, "w") as f:
                f.write("---\nname: test\n---\n")

            old_root = merged_diff_memory.MEMORY_ROOT
            old_home = merged_diff_memory.HOME
            old_error_log = merged_diff_memory.ERROR_LOG
            try:
                merged_diff_memory.MEMORY_ROOT = tmpdir
                merged_diff_memory.HOME = tmpdir
                merged_diff_memory.ERROR_LOG = os.path.join(tmpdir, "errors.jsonl")
                success = merged_diff_memory._update_memory_index(memory_file)
                assert success is True

                assert os.path.exists(index_file), f"Index file not created at {index_file}"
                with open(index_file, "r") as f:
                    content = f.read()
                    assert content.strip(), f"Index file is empty"
                    assert f"merged_learning_{today}.md" in content
                    assert today[:4] in content  # Check year is present
            finally:
                merged_diff_memory.MEMORY_ROOT = old_root
                merged_diff_memory.HOME = old_home
                merged_diff_memory.ERROR_LOG = old_error_log

    def test_update_memory_index_already_present(self):
        """Skips adding entry if already in MEMORY.md."""
        with tempfile.TemporaryDirectory() as tmpdir:
            memory_file = os.path.join(tmpdir, "merged_learning_20260101.md")
            index_file = os.path.join(tmpdir, "MEMORY.md")

            with open(memory_file, "w") as f:
                f.write("---\nname: test\n---\n")

            with open(index_file, "w") as f:
                f.write("- [Merged patterns 2026-01-01](merged_learning_20260101.md) — conventions\n")

            with mock.patch.dict(os.environ, {"CLAUDE_MEMORY_ROOT": tmpdir}):
                merged_diff_memory.MEMORY_ROOT = tmpdir
                success = merged_diff_memory._update_memory_index(memory_file)
                assert success is True

                with open(index_file, "r") as f:
                    lines = f.readlines()
                    count = sum(1 for line in lines if "merged_learning_20260101" in line)
                    assert count == 1

    def test_update_memory_index_none_filepath(self):
        """Returns True for None filepath (no-op)."""
        success = merged_diff_memory._update_memory_index(None)
        assert success is True

    def test_update_memory_index_parse_error(self):
        """Returns False on date parse error but continues."""
        with tempfile.TemporaryDirectory() as tmpdir:
            memory_file = os.path.join(tmpdir, "merged_learning_invalid.md")
            index_file = os.path.join(tmpdir, "MEMORY.md")

            with open(memory_file, "w") as f:
                f.write("test")

            with mock.patch.dict(os.environ, {"CLAUDE_MEMORY_ROOT": tmpdir}):
                merged_diff_memory.MEMORY_ROOT = tmpdir
                success = merged_diff_memory._update_memory_index(memory_file)
                assert success is False


class TestPruneOldEntries:
    """Test removal of entries older than retention limit."""

    def test_prune_old_entries_keep_recent(self):
        """Keeps entries within retention window."""
        with tempfile.TemporaryDirectory() as tmpdir:
            index_file = os.path.join(tmpdir, "MEMORY.md")
            today = datetime.utcnow().date()
            recent_date = (today - timedelta(days=30)).isoformat()
            old_date = (today - timedelta(days=100)).isoformat()

            content = f"- [Recent]({recent_date}.md) — recent\n- [Old]({old_date}.md) — old\n"
            with open(index_file, "w") as f:
                f.write(content)

            merged_diff_memory._prune_old_entries(index_file, days=90)

            with open(index_file, "r") as f:
                result = f.read()
                assert recent_date in result
                assert old_date not in result

    def test_prune_old_entries_preserves_non_dated(self):
        """Preserves entries without dates in filename."""
        with tempfile.TemporaryDirectory() as tmpdir:
            index_file = os.path.join(tmpdir, "MEMORY.md")
            content = "# Memory Index\n- [Some memory](file.md) — no date\n"
            with open(index_file, "w") as f:
                f.write(content)

            merged_diff_memory._prune_old_entries(index_file, days=90)

            with open(index_file, "r") as f:
                result = f.read()
                assert "Some memory" in result

    def test_prune_old_entries_file_not_found(self):
        """Handles missing index file gracefully."""
        merged_diff_memory._prune_old_entries("/nonexistent/MEMORY.md", days=90)


class TestRunMainFlow:
    """Test main entry point with full flow."""

    def test_run_success_with_patterns(self):
        """Main flow returns success with pattern count."""
        commits = [("abc123", "fix: something\n- DO test")]
        patterns = [
            {
                "commit": "abc123",
                "rules": ["- DO test"],
                "frameworks": ["pytest"],
                "files": ["test.py"],
                "timestamp": datetime.utcnow().isoformat(),
            }
        ]

        with mock.patch("merged_diff_memory._get_merged_commits", return_value=commits):
            with mock.patch("merged_diff_memory._extract_patterns_from_commit", return_value=patterns[0]):
                with mock.patch("merged_diff_memory._save_to_memory", return_value=(True, "/tmp/file.md")):
                    with mock.patch("merged_diff_memory._update_memory_index", return_value=True):
                        result = merged_diff_memory.run(repo=".", dry_run=False)
                        assert result["success"] is True
                        assert result["merged_count"] == 1
                        assert result["patterns_count"] == 1
                        assert result["memory_file"] == "/tmp/file.md"

    def test_run_no_merges(self):
        """Returns success when no merged commits found."""
        with mock.patch("merged_diff_memory._get_merged_commits", return_value=[]):
            result = merged_diff_memory.run(repo=".", dry_run=False)
            assert result["success"] is True
            assert result["merged_count"] == 0
            assert result["patterns_count"] == 0

    def test_run_dry_run_no_write(self):
        """Dry run does not write to memory."""
        commits = [("abc123", "fix: something")]
        patterns = [
            {"commit": "abc123", "rules": [], "frameworks": [], "files": [], "timestamp": "2026-01-01T00:00:00"}
        ]

        with mock.patch("merged_diff_memory._get_merged_commits", return_value=commits):
            with mock.patch("merged_diff_memory._extract_patterns_from_commit", return_value=patterns[0]):
                with mock.patch("merged_diff_memory._save_to_memory") as mock_save:
                    result = merged_diff_memory.run(repo=".", dry_run=True)
                    assert result["success"] is True
                    assert "[dry-run]" in result["memory_file"]
                    mock_save.assert_not_called()

    def test_run_unhandled_error(self):
        """Returns error dict on unhandled exception."""
        with mock.patch("merged_diff_memory._get_merged_commits", side_effect=RuntimeError("unexpected")):
            result = merged_diff_memory.run(repo=".", dry_run=False)
            assert result["success"] is False
            assert "unexpected" in result["error"]

    def test_run_filters_rejected_patterns(self):
        """Does not count patterns rejected by quality gate."""
        commits = [("abc123", "fix: a"), ("def456", "fix: b")]

        with mock.patch("merged_diff_memory._get_merged_commits", return_value=commits):
            with mock.patch("merged_diff_memory._extract_patterns_from_commit", side_effect=[
                {"commit": "abc123", "rules": [], "frameworks": [], "files": [], "timestamp": "2026-01-01T00:00:00"},
                None,  # rejected by quality gate
            ]):
                with mock.patch("merged_diff_memory._save_to_memory", return_value=(True, "/tmp/file.md")):
                    with mock.patch("merged_diff_memory._update_memory_index", return_value=True):
                        result = merged_diff_memory.run(repo=".", dry_run=False)
                        assert result["merged_count"] == 2
                        assert result["patterns_count"] == 1


class TestThreadSafety:
    """Test concurrent access to shared resources."""

    def test_save_to_memory_concurrent_writes(self):
        """Multiple threads can save patterns without corruption."""
        patterns = [
            {"commit": f"commit{i}", "rules": [], "frameworks": [], "files": [], "timestamp": "2026-01-01T00:00:00"}
            for i in range(5)
        ]

        results = []

        def save_patterns():
            success, filepath = merged_diff_memory._save_to_memory(patterns)
            results.append((success, filepath))

        threads = [threading.Thread(target=save_patterns) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert all(r[0] for r in results)

    def test_update_memory_index_concurrent_updates(self):
        """Multiple threads updating index does not corrupt file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            index_file = os.path.join(tmpdir, "MEMORY.md")
            today = datetime.utcnow().date()
            memory_files = [os.path.join(tmpdir, f"merged_learning_{(today - timedelta(days=i)).strftime('%Y%m%d')}.md") for i in range(3)]

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

                assert os.path.exists(index_file), f"Index file not created at {index_file}"
                with open(index_file, "r") as f:
                    content = f.read()
                    assert content.strip(), f"Index file is empty"
                    for mf in memory_files:
                        basename = os.path.basename(mf)
                        count = content.count(basename)
                        assert count == 1, f"Basename {basename} appears {count} times (expected 1)"
            finally:
                merged_diff_memory.MEMORY_ROOT = old_root
                merged_diff_memory.HOME = old_home
                merged_diff_memory.ERROR_LOG = old_error_log


class TestEnsureDirs:
    """Test directory creation and error handling."""

    def test_ensure_dirs_creates_paths(self):
        """Creates memory and error log directories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            memory_dir = os.path.join(tmpdir, "memory")
            error_dir = os.path.join(tmpdir, "knowledge")

            old_mem_root = merged_diff_memory.MEMORY_ROOT
            old_home = merged_diff_memory.HOME
            old_error_log = merged_diff_memory.ERROR_LOG
            try:
                merged_diff_memory.MEMORY_ROOT = memory_dir
                merged_diff_memory.HOME = error_dir
                merged_diff_memory.ERROR_LOG = os.path.join(error_dir, "errors.jsonl")
                merged_diff_memory._ensure_dirs()

                assert os.path.exists(memory_dir)
                assert os.path.exists(error_dir)
            finally:
                merged_diff_memory.MEMORY_ROOT = old_mem_root
                merged_diff_memory.HOME = old_home
                merged_diff_memory.ERROR_LOG = old_error_log

    def test_ensure_dirs_idempotent(self):
        """Can be called multiple times safely."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.dict(os.environ, {"CLAUDE_MEMORY_ROOT": tmpdir}):
                merged_diff_memory.MEMORY_ROOT = tmpdir
                merged_diff_memory._ensure_dirs()
                merged_diff_memory._ensure_dirs()
                assert os.path.exists(tmpdir)


class TestErrorLogging:
    """Test fail-soft error logging."""

    def test_log_error_creates_entry(self):
        """Writes error to JSONL log."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = os.path.join(tmpdir, "errors.jsonl")
            with mock.patch.dict(os.environ, {"CLAUDE_ORCH_HOME": tmpdir}):
                merged_diff_memory.HOME = tmpdir
                merged_diff_memory.ERROR_LOG = log_file
                merged_diff_memory._log_error("test error", "test context")

                assert os.path.exists(log_file)
                with open(log_file, "r") as f:
                    line = f.readline()
                    entry = json.loads(line)
                    assert "test error" in entry["message"]
                    assert entry["context"] == "test context"

    def test_log_error_nonfatal(self):
        """Logging error does not raise."""
        with mock.patch("builtins.open", side_effect=IOError("disk full")):
            merged_diff_memory._log_error("unloggable error", "context")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
