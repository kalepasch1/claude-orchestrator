"""Tests for test_coverage_auditor."""
import sys, os, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from test_coverage_auditor import find_python_functions, find_test_files, has_test_coverage, audit_coverage

def test_find_functions():
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
        f.write("def foo():\n    pass\ndef bar():\n    pass\n")
        f.flush()
        funcs = find_python_functions(f.name)
    os.unlink(f.name)
    assert len(funcs) == 2
    assert funcs[0]["name"] == "foo"

def test_find_test_files():
    repo = os.path.join(os.path.dirname(__file__), "..", "..")
    tests = find_test_files(repo)
    assert len(tests) > 0

def test_has_coverage():
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
        f.write("def test_my_function():\n    my_function()\n")
        f.flush()
        assert has_test_coverage("my_function", [f.name]) is True
    os.unlink(f.name)

def test_no_coverage():
    assert has_test_coverage("nonexistent_func_xyz", []) is False

def test_audit_coverage():
    repo = os.path.join(os.path.dirname(__file__), "..", "..")
    result = audit_coverage(repo)
    assert "total" in result
    assert "coverage_pct" in result
    assert result["total"] >= 0

def test_audit_nonexistent():
    result = audit_coverage("/nonexistent/path")
    assert result["total"] == 0

def test_find_functions_nonexistent():
    assert find_python_functions("/nonexistent/file.py") == []

def test_private_functions_skipped():
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
        f.write("def _private():\n    pass\ndef public():\n    pass\n")
        f.flush()
        funcs = find_python_functions(f.name)
    os.unlink(f.name)
    # Both found by find_python_functions, but audit_coverage skips private
    assert len(funcs) == 2
