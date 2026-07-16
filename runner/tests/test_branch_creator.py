"""Tests for branch_creator."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from branch_creator import create_branch, BranchCreationResult


def make_runner(responses):
    """Create a mock command runner from a list of (rc, stdout, stderr) tuples."""
    calls = []
    idx = [0]
    def run(cmd, cwd):
        i = idx[0]
        idx[0] += 1
        calls.append((cmd, cwd))
        if i < len(responses):
            return responses[i]
        return (0, "", "")
    return run, calls


# --- Success scenarios ---

def test_create_branch_success():
    runner, calls = make_runner([
        (0, "", ""),          # fetch
        (0, "", ""),          # branch --list (empty = not exists)
        (0, "", ""),          # ls-remote (empty = not exists)
        (0, "", ""),          # branch create
        (0, "", ""),          # push
    ])
    result = create_branch("/repo", "feature-x", run_command=runner)
    assert result.success is True
    assert result.branch_name == "feature-x"
    assert "created" in result.reason

def test_create_branch_no_push():
    runner, calls = make_runner([
        (0, "", ""),
        (0, "", ""),
        (0, "", ""),
        (0, "", ""),
    ])
    result = create_branch("/repo", "feature-x", push=False, run_command=runner)
    assert result.success is True
    assert len(calls) == 4  # No push call


# --- Already exists ---

def test_branch_exists_locally():
    runner, _ = make_runner([
        (0, "", ""),                    # fetch
        (0, "  feature-x\n", ""),       # branch --list shows it
    ])
    result = create_branch("/repo", "feature-x", run_command=runner)
    assert result.success is True
    assert "already exists locally" in result.reason

def test_branch_exists_on_remote():
    runner, _ = make_runner([
        (0, "", ""),
        (0, "", ""),                    # not local
        (0, "abc123 refs/heads/feature-x\n", ""),  # exists on remote
    ])
    result = create_branch("/repo", "feature-x", run_command=runner)
    assert result.success is True
    assert "already exists on remote" in result.reason


# --- Error handling ---

def test_fetch_failure():
    runner, _ = make_runner([
        (1, "", "network error"),
    ])
    result = create_branch("/repo", "feature-x", run_command=runner)
    assert result.success is False
    assert "fetch failed" in result.reason

def test_permission_denied():
    runner, _ = make_runner([
        (0, "", ""),
        (0, "", ""),
        (0, "", ""),
        (0, "", ""),          # branch create ok
        (1, "", "Permission denied"),  # push fails
    ])
    result = create_branch("/repo", "feature-x", run_command=runner)
    assert result.success is False
    assert "permission denied" in result.reason

def test_branch_creation_failure():
    runner, _ = make_runner([
        (0, "", ""),
        (0, "", ""),
        (0, "", ""),
        (1, "", "fatal: bad ref"),
    ])
    result = create_branch("/repo", "feature-x", run_command=runner)
    assert result.success is False
    assert "branch creation failed" in result.reason

def test_push_failure_generic():
    runner, _ = make_runner([
        (0, "", ""),
        (0, "", ""),
        (0, "", ""),
        (0, "", ""),
        (1, "", "remote hung up"),
    ])
    result = create_branch("/repo", "feature-x", run_command=runner)
    assert result.success is False
    assert "push failed" in result.reason


# --- Result ---

def test_result_to_dict():
    r = BranchCreationResult(True, "my-branch", "ok")
    d = r.to_dict()
    assert d == {"success": True, "branch_name": "my-branch", "reason": "ok"}

def test_custom_base_branch():
    runner, calls = make_runner([
        (0, "", ""), (0, "", ""), (0, "", ""), (0, "", ""), (0, "", ""),
    ])
    create_branch("/repo", "feat", base_branch="develop", run_command=runner)
    # The branch create command should reference origin/develop
    branch_cmd = calls[3][0]
    assert "origin/develop" in branch_cmd

def test_custom_remote():
    runner, calls = make_runner([
        (0, "", ""), (0, "", ""), (0, "", ""), (0, "", ""), (0, "", ""),
    ])
    create_branch("/repo", "feat", remote="upstream", run_command=runner)
    assert calls[0][0][2] == "upstream"  # fetch upstream
