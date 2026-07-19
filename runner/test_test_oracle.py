"""Tests for runner/test_oracle.py"""
import sys, os, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ["ORCH_TEST_ORACLE_ENABLED"] = "true"
os.environ["ORCH_DB_URL"] = ""
os.environ["ORCH_DB_ENABLED"] = "false"

import test_oracle


def test_build_index_with_temp_dir():
    """build_index scans a temp dir and finds test files and source mappings."""
    with tempfile.TemporaryDirectory() as td:
        # Create a source file
        src = os.path.join(td, "calculator.py")
        with open(src, "w") as f:
            f.write("def add(a, b):\n    return a + b\n")

        # Create a test file that imports the source
        test_f = os.path.join(td, "test_calculator.py")
        with open(test_f, "w") as f:
            f.write("import calculator\n\ndef test_add():\n    assert calculator.add(1, 2) == 3\n")

        result = test_oracle.build_index(td)
        assert isinstance(result, dict)
        assert "files_indexed" in result
        assert "test_files" in result
        assert "mappings" in result
        assert result["test_files"] >= 1


def test_affected_tests_returns_list():
    """affected_tests returns dict with test_files list."""
    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, "utils.py")
        with open(src, "w") as f:
            f.write("def helper():\n    pass\n")

        test_f = os.path.join(td, "test_utils.py")
        with open(test_f, "w") as f:
            f.write("import utils\n\ndef test_helper():\n    pass\n")

        test_oracle.build_index(td)
        result = test_oracle.affected_tests(td, ["utils.py"])
        assert isinstance(result, dict)
        assert "test_files" in result
        assert isinstance(result["test_files"], list)
        assert "strategy" in result


def test_selective_test_cmd_returns_string():
    """selective_test_cmd returns a string command."""
    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, "app.py")
        with open(src, "w") as f:
            f.write("def run():\n    pass\n")

        test_f = os.path.join(td, "test_app.py")
        with open(test_f, "w") as f:
            f.write("import app\n\ndef test_run():\n    pass\n")

        test_oracle.build_index(td)
        cmd = test_oracle.selective_test_cmd(td, ["app.py"], "pytest -v")
        assert isinstance(cmd, str)
        assert len(cmd) > 0


def test_build_index_invalid_path():
    """build_index with invalid path returns zeros gracefully."""
    result = test_oracle.build_index("/nonexistent/path/xyz")
    assert isinstance(result, dict)
    assert result["files_indexed"] == 0
    assert result["test_files"] == 0
