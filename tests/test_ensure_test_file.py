"""Tests for scripts/ensure_test_file.py.

Covers the happy path, idempotency, directory selection, env-var overrides, and
every fail-soft branch (missing file, bad JSON, wrong JSON shape, None input).
"""

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import ensure_test_file as ETF  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("ORCH_TEST_INFO_FILE", raising=False)
    monkeypatch.delenv("ORCH_TEST_DIRS", raising=False)


def _write_info(root: Path, payload, name="test-module-info.json"):
    (root / name).write_text(
        payload if isinstance(payload, str) else json.dumps(payload),
        encoding="utf-8",
    )


# --- module_name_from_path -------------------------------------------------

@pytest.mark.parametrize(
    "given,expected",
    [
        ("src/utils.py", "utils"),
        ("utils.py", "utils"),
        ("a/b/c/deep_module.py", "deep_module"),
        ("  src/spaced.py  ", "spaced"),
        ("src/no_extension", "no_extension"),
        ("", ""),
        (None, ""),
        (".", ""),
        ("..", ""),
        (123, ""),
    ],
)
def test_module_name_from_path(given, expected):
    assert ETF.module_name_from_path(given) == expected


# --- read_module_path ------------------------------------------------------

def test_read_module_path_happy(tmp_path):
    _write_info(tmp_path, {"module_path": "src/utils.py"})
    assert ETF.read_module_path(tmp_path) == "src/utils.py"


def test_read_module_path_missing_file(tmp_path):
    assert ETF.read_module_path(tmp_path) == ""


def test_read_module_path_none_root():
    assert ETF.read_module_path(None) == ""


def test_read_module_path_bad_json(tmp_path):
    _write_info(tmp_path, "{not json at all")
    assert ETF.read_module_path(tmp_path) == ""


def test_read_module_path_json_is_a_list(tmp_path):
    _write_info(tmp_path, ["src/utils.py"])
    assert ETF.read_module_path(tmp_path) == ""


def test_read_module_path_key_absent(tmp_path):
    _write_info(tmp_path, {"other": "src/utils.py"})
    assert ETF.read_module_path(tmp_path) == ""


def test_read_module_path_key_wrong_type(tmp_path):
    _write_info(tmp_path, {"module_path": 42})
    assert ETF.read_module_path(tmp_path) == ""


def test_read_module_path_honours_env_override(tmp_path, monkeypatch):
    _write_info(tmp_path, {"module_path": "src/other.py"}, name="alt-info.json")
    monkeypatch.setenv("ORCH_TEST_INFO_FILE", "alt-info.json")
    assert ETF.read_module_path(tmp_path) == "src/other.py"


# --- resolve_test_dir ------------------------------------------------------

def test_resolve_test_dir_prefers_existing_tests(tmp_path):
    (tmp_path / "tests").mkdir()
    assert ETF.resolve_test_dir(tmp_path) == "tests"


def test_resolve_test_dir_falls_back_to_test(tmp_path):
    (tmp_path / "test").mkdir()
    assert ETF.resolve_test_dir(tmp_path) == "test"


def test_resolve_test_dir_default_when_none_exist(tmp_path):
    assert ETF.resolve_test_dir(tmp_path) == "tests"


def test_resolve_test_dir_none_root():
    assert ETF.resolve_test_dir(None) == "tests"


def test_resolve_test_dir_env_override(tmp_path, monkeypatch):
    (tmp_path / "spec").mkdir()
    monkeypatch.setenv("ORCH_TEST_DIRS", "spec:tests")
    assert ETF.resolve_test_dir(tmp_path) == "spec"


def test_resolve_test_dir_empty_env_falls_back(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCH_TEST_DIRS", "   ")
    assert ETF.resolve_test_dir(tmp_path) == "tests"


# --- ensure_test_file ------------------------------------------------------

def test_ensure_creates_file(tmp_path):
    (tmp_path / "tests").mkdir()
    _write_info(tmp_path, {"module_path": "src/utils.py"})
    rel = ETF.ensure_test_file(tmp_path)
    assert rel == os.path.join("tests", "test_utils.py")
    assert (tmp_path / rel).is_file()


def test_ensure_creates_missing_test_dir(tmp_path):
    _write_info(tmp_path, {"module_path": "src/utils.py"})
    rel = ETF.ensure_test_file(tmp_path)
    assert (tmp_path / rel).is_file()


def test_ensure_is_idempotent_and_non_destructive(tmp_path):
    (tmp_path / "tests").mkdir()
    existing = tmp_path / "tests" / "test_utils.py"
    existing.write_text("def test_already_here():\n    assert True\n", encoding="utf-8")
    _write_info(tmp_path, {"module_path": "src/utils.py"})

    first = ETF.ensure_test_file(tmp_path)
    second = ETF.ensure_test_file(tmp_path)

    assert first == second
    assert "test_already_here" in existing.read_text(encoding="utf-8")


def test_ensure_no_info_file_is_fail_soft(tmp_path):
    assert ETF.ensure_test_file(tmp_path) == ""


def test_ensure_none_root_is_fail_soft():
    assert ETF.ensure_test_file(None) == ""


def test_ensure_unusable_module_path_is_fail_soft(tmp_path):
    _write_info(tmp_path, {"module_path": "  "})
    assert ETF.ensure_test_file(tmp_path) == ""


# --- main ------------------------------------------------------------------

def test_main_returns_zero_on_success(tmp_path, capsys):
    (tmp_path / "tests").mkdir()
    _write_info(tmp_path, {"module_path": "src/utils.py"})
    assert ETF.main([str(tmp_path)]) == 0
    assert "test_utils.py" in capsys.readouterr().out


def test_main_returns_zero_when_nothing_resolves(tmp_path, capsys):
    assert ETF.main([str(tmp_path)]) == 0
    assert "fail-soft" in capsys.readouterr().err
