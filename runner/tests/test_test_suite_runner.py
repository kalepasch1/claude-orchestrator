"""Tests for test_suite_runner module — discovery, filtering, subdirectory scan."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import test_suite_runner as tsr


def test_discover_root_only():
    """Default discovery finds root-level test modules."""
    mods = tsr.discover_test_modules(include_subdir=False)
    names = [m[0] for m in mods]
    # Should find at least one test_*.py in runner root
    assert len(names) > 0, "Expected at least one root test module"
    # Should not include test_suite_runner itself
    assert "test_suite_runner" not in names


def test_discover_with_subdir():
    """--subdir flag discovers tests in tests/ subdirectory."""
    mods_root = tsr.discover_test_modules(include_subdir=False)
    mods_all = tsr.discover_test_modules(include_subdir=True)
    assert len(mods_all) > len(mods_root), (
        f"Subdir discovery should find more modules: root={len(mods_root)}, all={len(mods_all)}"
    )
    labels = [m[1] for m in mods_all]
    has_subdir = any(l.startswith("tests/") for l in labels)
    assert has_subdir, "Expected at least one tests/ prefixed label"


def test_pattern_filter():
    """Pattern filter restricts discovered modules."""
    all_mods = tsr.discover_test_modules(include_subdir=False)
    filtered = tsr.discover_test_modules(include_subdir=False, pattern="test_branch*")
    assert len(filtered) < len(all_mods), "Pattern should reduce module count"
    for mod_name, _ in filtered:
        assert mod_name.startswith("test_branch"), f"Unexpected module: {mod_name}"


def test_pattern_no_match():
    """Pattern that matches nothing returns empty list."""
    mods = tsr.discover_test_modules(pattern="test_zzz_nonexistent_xyz*")
    assert mods == []


def test_run_module_passing():
    """run_module_tests works on a module with passing tests."""
    # Create a temporary test module
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", dir=tempfile.gettempdir(),
                                     prefix="test_tmp_pass_", delete=False) as f:
        f.write("def test_one(): assert 1 + 1 == 2\n")
        f.write("def test_two(): assert True\n")
        tmp_path = f.name
    try:
        mod_name = os.path.basename(tmp_path)[:-3]
        sys.path.insert(0, os.path.dirname(tmp_path))
        r = tsr.run_module_tests(mod_name)
        assert r["passed"] == 2
        assert r["failed"] == 0
        assert r["errors"] == []
    finally:
        os.unlink(tmp_path)


def test_run_module_failing():
    """run_module_tests captures failures without crashing."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", dir=tempfile.gettempdir(),
                                     prefix="test_tmp_fail_", delete=False) as f:
        f.write("def test_boom(): raise ValueError('kaboom')\n")
        tmp_path = f.name
    try:
        mod_name = os.path.basename(tmp_path)[:-3]
        sys.path.insert(0, os.path.dirname(tmp_path))
        r = tsr.run_module_tests(mod_name)
        assert r["failed"] == 1
        assert any("kaboom" in e for e in r["errors"])
    finally:
        os.unlink(tmp_path)


def test_run_module_import_error():
    """run_module_tests handles import errors gracefully."""
    r = tsr.run_module_tests("nonexistent_module_xyz_123")
    assert r["failed"] == 1
    assert any("IMPORT ERROR" in e for e in r["errors"])


def test_run_module_no_test_fns():
    """Module with no test_ functions reports as skipped."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", dir=tempfile.gettempdir(),
                                     prefix="test_tmp_empty_", delete=False) as f:
        f.write("# no test functions here\nVALUE = 42\n")
        tmp_path = f.name
    try:
        mod_name = os.path.basename(tmp_path)[:-3]
        sys.path.insert(0, os.path.dirname(tmp_path))
        r = tsr.run_module_tests(mod_name)
        assert r["skipped"] == 1
        assert r["passed"] == 0
        assert r["failed"] == 0
    finally:
        os.unlink(tmp_path)


def test_discover_returns_tuples():
    """Discovery returns (module_name, label) tuples."""
    mods = tsr.discover_test_modules()
    assert len(mods) > 0
    for item in mods:
        assert isinstance(item, tuple) and len(item) == 2
        mod_name, label = item
        assert isinstance(mod_name, str)
        assert isinstance(label, str)
