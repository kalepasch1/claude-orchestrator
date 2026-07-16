"""Tests for repair_committer."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from repair_committer import (
    categorize_changes, build_commit_message, stage_and_commit,
    CommitResult,
)

def test_categorize_source():
    cats = categorize_changes(["runner/foo.py", "runner/bar.py"])
    assert len(cats["source"]) == 2

def test_categorize_tests():
    cats = categorize_changes(["runner/tests/test_foo.py"])
    assert len(cats["test"]) == 1

def test_categorize_config():
    cats = categorize_changes(["setup.cfg", "pyproject.toml"])
    assert len(cats["config"]) == 2

def test_categorize_docs():
    cats = categorize_changes(["README.md", "CHANGELOG.rst"])
    assert len(cats["docs"]) == 2

def test_categorize_mixed():
    files = ["foo.py", "test_bar.py", "config.yml", "notes.md", "Makefile"]
    cats = categorize_changes(files)
    assert len(cats["source"]) == 1
    assert len(cats["test"]) == 1
    assert len(cats["config"]) == 1
    assert len(cats["docs"]) == 1
    assert len(cats["other"]) == 1

def test_build_commit_message_source():
    cats = {"source": ["a.py", "b.py"], "test": [], "config": [], "docs": []}
    msg = build_commit_message(cats)
    assert "source (2 files)" in msg

def test_build_commit_message_empty():
    cats = {"source": [], "test": [], "config": [], "docs": []}
    msg = build_commit_message(cats)
    assert "changes" in msg

def test_commit_result():
    r = CommitResult(True, "abc123", "done")
    assert r.success is True
    assert r.commit_hash == "abc123"

def test_stage_and_commit_success():
    calls = []
    def runner(cmd, cwd):
        calls.append(cmd)
        if "commit" in cmd:
            return (0, "committed", "")
        if "rev-parse" in cmd:
            return (0, "abc123", "")
        return (0, "", "")
    result = stage_and_commit("/repo", "test msg", run_command=runner)
    assert result.success is True
    assert result.commit_hash == "abc123"

def test_stage_and_commit_nothing():
    def runner(cmd, cwd):
        if "commit" in cmd:
            return (1, "nothing to commit", "")
        return (0, "", "")
    result = stage_and_commit("/repo", "test", run_command=runner)
    assert result.success is True

def test_stage_and_commit_failure():
    def runner(cmd, cwd):
        if "commit" in cmd:
            return (1, "", "error")
        return (0, "", "")
    result = stage_and_commit("/repo", "test", run_command=runner)
    assert result.success is False

def test_stage_specific_files():
    calls = []
    def runner(cmd, cwd):
        calls.append(cmd)
        if "commit" in cmd: return (0, "ok", "")
        if "rev-parse" in cmd: return (0, "def456", "")
        return (0, "", "")
    stage_and_commit("/repo", "msg", files=["a.py", "b.py"], run_command=runner)
    add_calls = [c for c in calls if c[1] == "add"]
    assert len(add_calls) == 2
