"""The merge gate must test the branch it is gating, not the checked-out tree.

`run_tests(repo, branch=...)` documented branch isolation but ignored the
argument entirely, so merge_gate_check ran the test command against whatever
happened to be checked out in `repo`. A red branch could pass the gate purely
because master was green. These tests pin the fixed behaviour.
"""
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner"))
import continuous_test_runner as ctr


def _git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True,
                   capture_output=True, text=True)


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    """A repo whose master says 'master' and whose feature branch says 'feature'."""
    path = tmp_path / "repo"
    path.mkdir()
    _git(path, "init", "-q", "-b", "master")
    _git(path, "config", "user.email", "t@example.com")
    _git(path, "config", "user.name", "t")
    (path / "marker.txt").write_text("master\n")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "master")

    _git(path, "checkout", "-q", "-b", "feature")
    (path / "marker.txt").write_text("feature\n")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "feature")
    _git(path, "checkout", "-q", "master")

    # Keep the test hermetic: no DB writes, no flake-retry sleeps.
    monkeypatch.setattr(ctr, "_record_test_run", lambda result: None)
    monkeypatch.setattr(ctr, "_max_flake_retries", lambda: 0)
    monkeypatch.setenv("TEST_CMD", "cat marker.txt")
    return str(path)


def test_branch_is_checked_out_before_tests_run(repo):
    result = ctr.run_tests(repo, branch="feature", mode="merge-gate")
    assert result["passed"] is True
    assert "feature" in result["output"]
    assert "master" not in result["output"]


def test_no_branch_uses_the_repo_as_is(repo):
    result = ctr.run_tests(repo, branch=None, mode="merge-gate")
    assert result["passed"] is True
    assert "master" in result["output"]


def test_failing_branch_fails_the_gate_even_when_master_is_green(repo):
    """The regression that mattered: a red branch must not inherit master's green."""
    os.environ["TEST_CMD"] = "test \"$(cat marker.txt)\" = master"
    assert ctr.merge_gate_check(repo, "master", "master", None) is True
    assert ctr.merge_gate_check(repo, "feature", "master", None) is False


def test_unknown_branch_falls_back_to_repo_and_says_so(repo):
    """Fail-soft: an unresolvable ref degrades to an in-place run, annotated."""
    result = ctr.run_tests(repo, branch="no-such-branch", mode="merge-gate")
    assert result["passed"] is True
    assert "could not check out no-such-branch" in result["output"]


def test_fallback_note_does_not_perturb_the_flake_hash(repo):
    """output_hash compares test signal; tree provenance must stay out of it."""
    plain = ctr.run_tests(repo, branch=None, mode="merge-gate")
    fell_back = ctr.run_tests(repo, branch="no-such-branch", mode="merge-gate")
    assert plain["output_hash"] == fell_back["output_hash"]


def test_temp_worktree_is_cleaned_up(repo):
    ctr.run_tests(repo, branch="feature", mode="merge-gate")
    listed = subprocess.run(["git", "worktree", "list"], cwd=repo,
                            capture_output=True, text=True).stdout
    assert "ctr-" not in listed
