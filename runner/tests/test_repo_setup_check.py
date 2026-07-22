"""Tests for repo_setup_check."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from repo_setup_check import (
    check_tools, check_repo_structure, verify_repo_setup,
    SetupCheckResult, REQUIRED_TOOLS, OPTIONAL_TOOLS,
)

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
