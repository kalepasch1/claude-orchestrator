"""Tests for worktree_gc edge cases — verify gc_repo handles invalid inputs gracefully."""
import sys
import os
import types

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Mock db module before importing worktree_gc
mock_db = types.ModuleType("db")
mock_db.select = lambda *a, **kw: []
mock_db.insert = lambda *a, **kw: None
sys.modules.setdefault("db", mock_db)

import worktree_gc  # noqa: E402


def test_gc_repo_none_returns_zero():
    """gc_repo(None) should return 0 without raising."""
    assert worktree_gc.gc_repo(None) == 0


def test_gc_repo_empty_string_returns_zero():
    """gc_repo('') should return 0 without raising."""
    assert worktree_gc.gc_repo("") == 0


def test_gc_repo_nonexistent_path_returns_zero():
    """gc_repo with a path that doesn't exist should return 0."""
    assert worktree_gc.gc_repo("/tmp/__no_such_repo_path__") == 0


if __name__ == "__main__":
    test_gc_repo_none_returns_zero()
    test_gc_repo_empty_string_returns_zero()
    test_gc_repo_nonexistent_path_returns_zero()
    print("All worktree_gc edge-case tests passed.")
