#!/usr/bin/env python3
"""Tests for premerge_predict — merge train conflict prediction."""
import os, sys, tempfile, subprocess
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import premerge_predict


def _init_repo():
    """Create a temp git repo with a base branch and return its path."""
    d = tempfile.mkdtemp(prefix="premerge-test-")
    subprocess.run(["git", "init", "-b", "main"], cwd=d, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=d, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=d, capture_output=True)
    # initial commit
    with open(os.path.join(d, "base.txt"), "w") as f:
        f.write("base\n")
    subprocess.run(["git", "add", "."], cwd=d, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init", "--no-verify"], cwd=d, capture_output=True)
    return d


def _make_branch(repo, name, files):
    """Create a branch that modifies the given files."""
    subprocess.run(["git", "checkout", "-b", name, "main"], cwd=repo, capture_output=True)
    for fname in files:
        path = os.path.join(repo, fname)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(f"change in {name}\n")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
    subprocess.run(["git", "commit", "-m", f"branch {name}", "--no-verify"], cwd=repo, capture_output=True)
    subprocess.run(["git", "checkout", "main"], cwd=repo, capture_output=True)


def test_disjoint_branches_no_conflicts():
    repo = _init_repo()
    _make_branch(repo, "agent/a", ["fileA.ts"])
    _make_branch(repo, "agent/b", ["fileB.ts"])
    result = premerge_predict.predict_conflicts(repo, "main", ["agent/a", "agent/b"])
    assert len(result["conflicts"]) == 0
    assert result["batch_count"] == 1  # both in one batch


def test_overlapping_branches_detected():
    repo = _init_repo()
    _make_branch(repo, "agent/x", ["shared.ts", "onlyX.ts"])
    _make_branch(repo, "agent/y", ["shared.ts", "onlyY.ts"])
    result = premerge_predict.predict_conflicts(repo, "main", ["agent/x", "agent/y"])
    assert len(result["conflicts"]) == 1
    assert "shared.ts" in result["conflicts"][0]["files"]
    assert result["batch_count"] == 2  # separate batches


def test_three_branches_partial_overlap():
    repo = _init_repo()
    _make_branch(repo, "agent/a", ["fileA.ts"])
    _make_branch(repo, "agent/b", ["fileA.ts", "fileB.ts"])
    _make_branch(repo, "agent/c", ["fileC.ts"])
    result = premerge_predict.predict_conflicts(repo, "main", ["agent/a", "agent/b", "agent/c"])
    assert len(result["conflicts"]) == 1  # a-b conflict only
    # c should batch with a or b (no overlap with c)
    assert result["batch_count"] == 2


def test_changed_files_returns_set():
    repo = _init_repo()
    _make_branch(repo, "agent/t", ["x.ts", "y.ts"])
    files = premerge_predict.changed_files(repo, "main", "agent/t")
    assert isinstance(files, set)
    assert "x.ts" in files
    assert "y.ts" in files


def test_fail_soft_on_bad_repo():
    result = premerge_predict.predict_conflicts("/nonexistent", "main", ["a", "b"])
    assert isinstance(result, dict)
    assert result["batch_count"] == 1  # no detected conflicts → single batch


def test_empty_branches():
    result = premerge_predict.predict_conflicts("/tmp", "main", [])
    assert result["batch_count"] == 0
    assert result["conflicts"] == []


if __name__ == "__main__":
    passed = failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  PASS  {name}")
                passed += 1
            except Exception as e:
                print(f"  FAIL  {name}: {e}")
                failed += 1
    print(f"\npremerge_predict tests: {passed} passed, {failed} failed")
