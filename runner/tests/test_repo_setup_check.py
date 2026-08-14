"""Tests for repo_setup_check."""
import subprocess
import sys, os
import tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from repo_setup_check import (
    check_tools, check_repo_structure, verify_repo_setup, check_repo_ready,
    detect_default_branch, SetupCheckResult, REQUIRED_TOOLS, OPTIONAL_TOOLS,
)

GIT_ID = ["-c", "user.name=test", "-c", "user.email=test@test.local"]


def _git(args, cwd=None):
    subprocess.run(["git"] + GIT_ID + args, cwd=cwd, check=True, capture_output=True)


def _make_upstream(root, branch="main"):
    """Create a local 'remote' repo with one commit on the given branch."""
    upstream = os.path.join(root, "upstream")
    _git(["init", "-b", branch, upstream])
    with open(os.path.join(upstream, "README.md"), "w") as f:
        f.write("hello\n")
    _git(["add", "."], cwd=upstream)
    _git(["commit", "-m", "init"], cwd=upstream)
    return upstream


def _advance_upstream(upstream):
    with open(os.path.join(upstream, "more.txt"), "w") as f:
        f.write("more\n")
    _git(["add", "."], cwd=upstream)
    _git(["commit", "-m", "advance"], cwd=upstream)

def test_check_tools_finds_python():
    results = check_tools({"python3": "python3 --version"})
    assert results["python3"] is not None

def test_check_tools_missing():
    results = check_tools({"nonexistent": "nonexistent_tool_xyz --version"})
    assert results["nonexistent"] is None

def test_repo_structure_valid():
    repo = os.path.join(os.path.dirname(__file__), "..", "..")
    checks = check_repo_structure(repo)
    assert checks["has_git"] is True
    assert checks["has_runner"] is True

def test_repo_structure_invalid():
    checks = check_repo_structure("/tmp/nonexistent_repo_xyz")
    assert checks["has_git"] is False

def test_verify_repo_setup():
    repo = os.path.join(os.path.dirname(__file__), "..", "..")
    result = verify_repo_setup(repo)
    assert "python3" in result.available
    assert isinstance(result.ok, bool)

def test_setup_result_to_dict():
    r = SetupCheckResult()
    r.available = {"python3": "3.11"}
    d = r.to_dict()
    assert d["ok"] is True
    assert "python3" in d["available"]

def test_setup_result_not_ok():
    r = SetupCheckResult()
    r.missing = ["missing_tool"]
    assert r.ok is False

def test_required_tools_defined():
    assert "python3" in REQUIRED_TOOLS
    assert "git" in REQUIRED_TOOLS


def test_check_repo_ready_structure():
    result = check_repo_ready("/tmp/nonexistent_repo_xyz")
    for key in ("exists", "clean", "current", "default_branch", "ready", "error"):
        assert key in result


def test_check_repo_ready_missing_repo():
    result = check_repo_ready("/tmp/nonexistent_repo_xyz")
    assert result["exists"] is False
    assert result["ready"] is False
    assert result["error"]


def test_check_repo_ready_none_path():
    result = check_repo_ready(None)
    assert result["exists"] is False
    assert result["error"]


def test_check_repo_ready_not_a_repo():
    with tempfile.TemporaryDirectory() as d:
        result = check_repo_ready(d)
        assert result["exists"] is False
        assert "not a git repository" in result["error"]


def test_check_repo_ready_clean_current_clone():
    with tempfile.TemporaryDirectory() as root:
        upstream = _make_upstream(root)
        local = os.path.join(root, "local")
        _git(["clone", upstream, local])
        result = check_repo_ready(local)
        assert result["exists"] is True
        assert result["clean"] is True
        assert result["current"] is True
        assert result["ready"] is True
        assert result["default_branch"] == "main"
        assert result["error"] == ""


def test_check_repo_ready_dirty():
    with tempfile.TemporaryDirectory() as root:
        upstream = _make_upstream(root)
        local = os.path.join(root, "local")
        _git(["clone", upstream, local])
        with open(os.path.join(local, "dirty.txt"), "w") as f:
            f.write("dirty\n")
        result = check_repo_ready(local)
        assert result["clean"] is False
        assert result["ready"] is False


def test_check_repo_ready_behind_main():
    with tempfile.TemporaryDirectory() as root:
        upstream = _make_upstream(root)
        local = os.path.join(root, "local")
        _git(["clone", upstream, local])
        _advance_upstream(upstream)
        _git(["fetch", "origin"], cwd=local)
        result = check_repo_ready(local)
        assert result["current"] is False
        assert result["ready"] is False


def test_check_repo_ready_develop_default():
    with tempfile.TemporaryDirectory() as root:
        upstream = _make_upstream(root, branch="develop")
        local = os.path.join(root, "local")
        _git(["clone", upstream, local])
        result = check_repo_ready(local)
        assert result["default_branch"] == "develop"
        assert result["ready"] is True


def test_check_repo_ready_no_remote():
    with tempfile.TemporaryDirectory() as root:
        repo = _make_upstream(root)
        result = check_repo_ready(repo)
        assert result["exists"] is True
        assert result["current"] is True
        assert result["ready"] is True


def test_detect_default_branch_local_only():
    with tempfile.TemporaryDirectory() as root:
        repo = _make_upstream(root, branch="develop")
        assert detect_default_branch(repo) == "develop"
