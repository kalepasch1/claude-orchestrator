"""Tests for the smoke-failure collector.

The acceptance criterion is that smoke-failures.json contains an array of objects
with keys testName/file/error, so the parser contract is what gets pinned here.
"""
import importlib.util
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_spec = importlib.util.spec_from_file_location(
    "collect_smoke_failures", REPO_ROOT / "runner" / "tools" / "collect_smoke_failures.py"
)
csf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(csf)


SUMMARY = """\
...F..F                                                        [100%]
=========================== short test summary info ============================
FAILED runner/tests/test_a.py::TestX::test_one - AssertionError: 1 != 2
FAILED tests/test_b.py::test_two - TypeError: unsupported operand
ERROR tests/test_c.py
======================== 2 failed, 5 passed in 1.23s ===========================
"""


def test_parses_failed_lines():
    out = csf.parse_summary(SUMMARY)
    assert len(out) == 3
    assert out[0] == {
        "testName": "TestX::test_one",
        "file": "runner/tests/test_a.py",
        "error": "AssertionError: 1 != 2",
    }


def test_every_row_has_the_required_keys():
    for row in csf.parse_summary(SUMMARY):
        assert set(row) == {"testName", "file", "error"}
        assert all(isinstance(v, str) for v in row.values())


def test_collection_error_is_recorded_without_a_test_name():
    """A collection abort reports zero test results; it must still be inventoried."""
    row = [r for r in csf.parse_summary(SUMMARY) if r["file"] == "tests/test_c.py"][0]
    assert row["testName"] == "<collection>"
    assert row["error"] == "ERROR"


def test_ignores_lines_outside_the_summary_block():
    noisy = "FAILED not/in/summary.py::test_x - nope\n" + SUMMARY
    out = csf.parse_summary(noisy)
    assert not any(r["file"] == "not/in/summary.py" for r in out)


def test_duplicate_entries_are_collapsed():
    doubled = SUMMARY.replace(
        "FAILED tests/test_b.py::test_two - TypeError: unsupported operand",
        "FAILED tests/test_b.py::test_two - TypeError: unsupported operand\n"
        "FAILED tests/test_b.py::test_two - TypeError: unsupported operand",
    )
    assert len(csf.parse_summary(doubled)) == 3


def test_empty_run_yields_empty_list():
    assert csf.parse_summary("5 passed in 0.1s\n") == []


def test_output_is_json_serialisable_as_an_array(tmp_path):
    path = tmp_path / "smoke-failures.json"
    path.write_text(json.dumps(csf.parse_summary(SUMMARY), indent=2))
    loaded = json.loads(path.read_text())
    assert isinstance(loaded, list)
    assert loaded[1]["file"] == "tests/test_b.py"
