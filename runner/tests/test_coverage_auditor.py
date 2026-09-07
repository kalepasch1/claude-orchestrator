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

def _tiny_repo(tmp_path):
    """(see _clean_tmp_repo below for why pytest's tmp_path cannot be used directly)"""
    """A minimal tree with one source function and one test that calls it.

    THE TWO TESTS BELOW USED TO SCAN THE WHOLE CHECKOUT, and asserted almost nothing
    about it: `len(tests) > 0`, and that audit_coverage returns a dict with a couple of
    keys. Both walk the repo, so their cost grows with it -- measured 2026-09-07,
    test_audit_coverage 101.8s and test_find_test_files 96.0s on a QUIET box, against
    pytest.ini's 120s per-test bound.

    That is not a passing test, it is a coin flip. Under full-suite load both cross the
    bound, and one of them did: a timeout in the middle of a 19,000-test run, which
    production_push_guard sees as a red suite. Same defect class as
    branch_manager.find_stale_branches -- a test whose cost is the live repo's size, so
    it gets slower every day the fleet commits.

    A four-file tree exercises the identical code paths (walk, parse, match a test name
    to a function) and asserts the same properties in milliseconds, deterministically.
    """
    # `runner/`, not an arbitrary name: audit_coverage(repo_path, subdir="runner")
    # scans <repo>/runner and returns early with a DIFFERENT dict shape -- one with no
    # "coverage_pct" key at all -- when that directory is absent.
    (tmp_path / "runner").mkdir()
    (tmp_path / "runner" / "mod.py").write_text(
        "def covered_function():\n    return 1\n\n\ndef uncovered_function():\n    return 2\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_mod.py").write_text(
        "def test_covered_function():\n    covered_function()\n")
    return str(tmp_path)


import contextlib  # noqa: E402

#: The tiny fixture tree defines exactly these two public functions, one covered by a
#: test and one not -- which is what makes the assertions in test_audit_coverage exact.
_TINY_REPO_PUBLIC_FUNCS = 2
_NO_COVERAGE = 0
_FULL_COVERAGE_PCT = 100


@contextlib.contextmanager
def _clean_tmp_repo():
    """A tiny repo at a path that does NOT contain the substring "test".

    pytest's tmp_path is named after the test that asks for it, so it always contains
    "test" -- and audit_coverage skips any directory whose path does (`if "test" in
    root: continue`, meant to skip test directories). With tmp_path the fixture tree was
    skipped entirely and audit_coverage returned total=0, which is why the stronger
    assertions below could not be made from it. tempfile gives /tmp/tmpXXXXXXXX, which
    is clean.
    """
    import tempfile as _tf
    with _tf.TemporaryDirectory() as base:
        import pathlib
        yield _tiny_repo(pathlib.Path(base))


def test_find_test_files():
    with _clean_tmp_repo() as repo:
        tests = find_test_files(repo)
    assert len(tests) > 0
    assert any(os.path.basename(t) == "test_mod.py" for t in tests), tests


def test_find_test_files_ignores_a_tree_with_none():
    """The counterpart the old assertion could not make: > 0 must mean something."""
    import tempfile as _tempfile
    with _tempfile.TemporaryDirectory() as empty:
        assert find_test_files(empty) == []

def test_has_coverage():
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
        f.write("def test_my_function():\n    my_function()\n")
        f.flush()
        assert has_test_coverage("my_function", [f.name]) is True
    os.unlink(f.name)

def test_no_coverage():
    assert has_test_coverage("nonexistent_func_xyz", []) is False

def test_audit_coverage():
    with _clean_tmp_repo() as repo:
        result = audit_coverage(repo)
    assert "total" in result
    assert "coverage_pct" in result
    assert result["total"] >= 0
    # Stronger than the old version, and only possible because the tree is known:
    # one public function is called by a test and one is not. Named constants because
    # tools/lint_conventions.py counts a bare literal as MAGIC_NUMBERS and the ratchet
    # is a count -- a fix that raises the baseline is not a fix.
    assert result["total"] == _TINY_REPO_PUBLIC_FUNCS, result
    assert _NO_COVERAGE < result["coverage_pct"] < _FULL_COVERAGE_PCT, result

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
