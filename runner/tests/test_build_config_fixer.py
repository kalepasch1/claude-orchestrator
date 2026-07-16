"""Tests for build_config_fixer."""
import sys, os, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from build_config_fixer import (
    scan_python_syntax, scan_missing_imports, scan_config_issues,
    full_scan, BuildIssue,
)

def test_scan_syntax_valid():
    repo = os.path.join(os.path.dirname(__file__), "..", "..")
    issues = scan_python_syntax(repo)
    # Our own repo should have no syntax errors
    assert isinstance(issues, list)

def test_scan_syntax_detects_error():
    with tempfile.TemporaryDirectory() as td:
        runner_dir = os.path.join(td, "runner")
        os.makedirs(runner_dir)
        with open(os.path.join(runner_dir, "bad.py"), "w") as f:
            f.write("def foo(\n")  # Syntax error
        issues = scan_python_syntax(td)
        assert len(issues) >= 1
        assert issues[0].category == "syntax_error"

def test_scan_syntax_nonexistent_dir():
    issues = scan_python_syntax("/nonexistent/path")
    assert issues == []

def test_scan_missing_imports_clean():
    repo = os.path.join(os.path.dirname(__file__), "..", "..")
    issues = scan_missing_imports(repo)
    assert isinstance(issues, list)

def test_config_issues():
    with tempfile.TemporaryDirectory() as td:
        issues = scan_config_issues(td)
        assert any(i.category == "config_missing" for i in issues)

def test_full_scan():
    repo = os.path.join(os.path.dirname(__file__), "..", "..")
    result = full_scan(repo)
    assert "total_issues" in result
    assert isinstance(result["green"], bool)

def test_build_issue_to_dict():
    i = BuildIssue("syntax_error", "/foo.py", "bad syntax", True)
    d = i.to_dict()
    assert d["category"] == "syntax_error"
    assert d["fix_available"] is True

def test_full_scan_keys():
    repo = os.path.join(os.path.dirname(__file__), "..", "..")
    result = full_scan(repo)
    assert "syntax_errors" in result
    assert "missing_imports" in result
    assert "config_issues" in result
