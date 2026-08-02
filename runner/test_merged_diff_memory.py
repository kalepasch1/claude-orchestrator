"""Test suite for merged_diff_memory module."""

import json
import tempfile
from pathlib import Path
from unittest import mock

import pytest

import merged_diff_memory as mdm


@pytest.fixture
def temp_memory():
    """Provide a temporary memory directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        original_dir = mdm.MEMORY_DIR
        mdm.MEMORY_DIR = Path(tmpdir)
        mdm.MERGED_DIFF_FILE = Path(tmpdir) / "merged_diff_memory.json"
        yield Path(tmpdir)
        mdm.MEMORY_DIR = original_dir
        mdm.MERGED_DIFF_FILE = original_dir / "merged_diff_memory.json"


def test_read_memory_empty(temp_memory):
    """Test reading from non-existent memory file returns empty list."""
    assert mdm._read_memory() == []


def test_write_and_read_memory(temp_memory):
    """Test writing and reading merge metadata."""
    merges = [
        {"commit": "abc123", "branch": "feature", "author": "test", "date": "2026-08-02", "message": "test", "files_affected": ["file.py"]},
    ]
    mdm._write_memory(merges)
    result = mdm._read_memory()
    assert len(result) == 1
    assert result[0]["commit"] == "abc123"


def test_write_memory_respects_max_stored(temp_memory):
    """Test that memory respects MAX_STORED_MERGES limit."""
    merges = [{"commit": f"hash{i}", "branch": "test", "author": "test", "date": "2026-08-02", "message": "test", "files_affected": []} for i in range(60)]
    mdm._write_memory(merges)
    result = mdm._read_memory()
    assert len(result) == mdm.MAX_STORED_MERGES
    assert result[0]["commit"] == "hash10"  # oldest 10 should be dropped


def test_capture_merge_new_commit(temp_memory):
    """Test capturing a new merge commit."""
    with mock.patch("merged_diff_memory._safe_run") as mock_run:
        mock_run.side_effect = ["test_author", "2026-08-02T10:00:00Z", "test commit", "file.py\nfile2.py"]
        mdm.capture_merge("abc123", "feature", "/repo")
        result = mdm._read_memory()
        assert len(result) == 1
        assert result[0]["commit"] == "abc123"
        assert result[0]["branch"] == "feature"
        assert result[0]["author"] == "test_author"
        assert result[0]["files_affected"] == ["file.py", "file2.py"]


def test_capture_merge_duplicate_ignored(temp_memory):
    """Test that duplicate commits are not captured twice."""
    with mock.patch("merged_diff_memory._safe_run") as mock_run:
        mock_run.side_effect = ["test_author", "2026-08-02T10:00:00Z", "test", "file.py"] * 2
        mdm.capture_merge("abc123", "feature", "/repo")
        mdm.capture_merge("abc123", "feature", "/repo")
        result = mdm._read_memory()
        assert len(result) == 1


def test_get_recent_merges(temp_memory):
    """Test retrieving recent merges with limit."""
    merges = [{"commit": f"hash{i}", "branch": "test", "author": "test", "date": "2026-08-02", "message": "test", "files_affected": []} for i in range(30)]
    mdm._write_memory(merges)
    result = mdm.get_recent_merges(limit=10)
    assert len(result) == 10
    assert result[0]["commit"] == "hash20"


def test_stats(temp_memory):
    """Test stats output."""
    merges = [{"commit": f"hash{i}", "branch": "test", "author": "test", "date": "2026-08-02", "message": "test", "files_affected": []} for i in range(10)]
    mdm._write_memory(merges)
    result = mdm.stats()
    assert result["total_tracked"] == 10
    assert result["max_capacity"] == mdm.MAX_STORED_MERGES
    assert result["file_exists"] is True


def test_invalidate(temp_memory):
    """Test clearing all tracked merges."""
    merges = [{"commit": f"hash{i}", "branch": "test", "author": "test", "date": "2026-08-02", "message": "test", "files_affected": []} for i in range(5)]
    mdm._write_memory(merges)
    mdm.invalidate()
    result = mdm._read_memory()
    assert len(result) == 0


def test_safe_run_success():
    """Test safe_run with successful command."""
    result = mdm._safe_run(["echo", "test"])
    assert result == "test"


def test_safe_run_failure():
    """Test safe_run returns empty string on command failure."""
    result = mdm._safe_run(["false"])
    assert result == ""


def test_safe_run_exception():
    """Test safe_run returns empty string on exception."""
    result = mdm._safe_run(["nonexistent_command_xyz"])
    assert result == ""


def test_read_memory_corrupted_file(temp_memory):
    """Test reading corrupted JSON returns empty list."""
    mdm.MERGED_DIFF_FILE.write_text("{ invalid json }")
    result = mdm._read_memory()
    assert result == []


def test_capture_merge_no_files(temp_memory):
    """Test capturing merge with no files affected."""
    with mock.patch("merged_diff_memory._safe_run") as mock_run:
        mock_run.side_effect = ["author", "2026-08-02T10:00:00Z", "msg", ""]
        mdm.capture_merge("hash1", "branch", "/repo")
        result = mdm._read_memory()
        assert result[0]["files_affected"] == []
