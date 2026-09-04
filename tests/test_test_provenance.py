"""Tests for tools/test_provenance.py.

Provenance: 95fc17a356b7 — a regression test must name the commit whose
behavior it locks in, so the guard can be justified rather than "simplified"
away later. This suite is the executable form of that convention.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import test_provenance as TP  # noqa: E402

SHA = "95fc17a356b7"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("ORCH_PROVENANCE_LABEL", raising=False)
    monkeypatch.delenv("ORCH_PROVENANCE_MIN_SHA", raising=False)


# --- is_valid_sha ----------------------------------------------------------

@pytest.mark.parametrize(
    "given,expected",
    [
        (SHA, True),
        ("a1b2c3d", True),
        ("0" * 40, True),
        ("a1b2c3", False),          # too short
        ("0" * 41, False),          # too long
        ("A1B2C3D", False),         # uppercase is not a git short sha
        ("z1b2c3d", False),         # not hex
        ("", False),
        (None, False),
        (12345678, False),
    ],
)
def test_is_valid_sha(given, expected):
    assert TP.is_valid_sha(given) is expected


def test_min_sha_env_override(monkeypatch):
    monkeypatch.setenv("ORCH_PROVENANCE_MIN_SHA", "12")
    assert TP.is_valid_sha("a1b2c3d") is False
    assert TP.is_valid_sha(SHA) is True


def test_min_sha_env_garbage_falls_back(monkeypatch):
    monkeypatch.setenv("ORCH_PROVENANCE_MIN_SHA", "not-a-number")
    assert TP.is_valid_sha("a1b2c3d") is True


def test_min_sha_env_out_of_range_falls_back(monkeypatch):
    monkeypatch.setenv("ORCH_PROVENANCE_MIN_SHA", "3")
    assert TP.is_valid_sha("a1b") is False


# --- format_provenance -----------------------------------------------------

def test_format_provenance_basic():
    assert TP.format_provenance(SHA, "keeps the lease alive") == (
        f"Provenance: {SHA} — keeps the lease alive."
    )


def test_format_provenance_supplies_default_reason():
    assert "behavior locked in by this commit" in TP.format_provenance(SHA, "  ")


def test_format_provenance_bad_sha_is_empty():
    assert TP.format_provenance("nope", "reason") == ""
    assert TP.format_provenance(None, "reason") == ""


def test_format_provenance_label_override(monkeypatch):
    monkeypatch.setenv("ORCH_PROVENANCE_LABEL", "Locks")
    assert TP.format_provenance(SHA, "x").startswith("Locks: ")


# --- parse_provenance ------------------------------------------------------

def test_parse_from_docstring():
    got = TP.parse_provenance(f"Provenance: {SHA} — fail-soft heartbeat.")
    assert got == TP.Provenance(sha=SHA, reason="fail-soft heartbeat")


def test_parse_from_hash_comment():
    got = TP.parse_provenance(f"# provenance: {SHA} - why")
    assert got is not None and got.sha == SHA


def test_parse_finds_marker_on_a_later_line():
    text = f"Some summary line.\n\nProvenance: {SHA} — the reason.\n"
    assert TP.parse_provenance(text).sha == SHA


def test_parse_rejects_short_sha():
    assert TP.parse_provenance("Provenance: abc123 — too short") is None


@pytest.mark.parametrize("given", ["", None, "no marker here", 42])
def test_parse_returns_none_on_junk(given):
    assert TP.parse_provenance(given) is None


# --- find_provenance / missing_provenance ----------------------------------

WITH_MARKER = f'''
def test_alpha():
    """Provenance: {SHA} — alpha is guarded."""
    assert True
'''

WITHOUT_MARKER = '''
def test_beta():
    """Just a summary."""
    assert True

def helper():
    pass
'''


def test_find_provenance_hit():
    assert TP.find_provenance(WITH_MARKER, "test_alpha").sha == SHA


def test_find_provenance_unknown_function():
    assert TP.find_provenance(WITH_MARKER, "test_nope") is None


def test_find_provenance_unparsable_source_is_fail_soft():
    assert TP.find_provenance("def broken(:\n", "test_alpha") is None


@pytest.mark.parametrize("src,name", [(None, "t"), ("", "t"), ("x = 1", None)])
def test_find_provenance_bad_input(src, name):
    assert TP.find_provenance(src, name) is None


def test_missing_provenance_lists_only_unmarked_tests():
    assert TP.missing_provenance(WITHOUT_MARKER) == ["test_beta"]
    assert TP.missing_provenance(WITH_MARKER) == []


def test_missing_provenance_ignores_non_test_functions():
    assert "helper" not in TP.missing_provenance(WITHOUT_MARKER)


def test_missing_provenance_covers_async_tests():
    src = "async def test_gamma():\n    assert True\n"
    assert TP.missing_provenance(src) == ["test_gamma"]


@pytest.mark.parametrize("given", [None, "", "def broken(:\n"])
def test_missing_provenance_fail_soft(given):
    assert TP.missing_provenance(given) == []


# --- insert_provenance -----------------------------------------------------

def test_insert_creates_docstring_when_absent():
    src = "def test_delta():\n    assert True\n"
    out = TP.insert_provenance(src, "test_delta", SHA, "delta is guarded")
    assert TP.find_provenance(out, "test_delta").sha == SHA
    assert "assert True" in out


def test_insert_appends_to_existing_docstring():
    src = 'def test_eps():\n    """Existing summary."""\n    assert True\n'
    out = TP.insert_provenance(src, "test_eps", SHA, "eps is guarded")
    assert "Existing summary." in out
    assert TP.find_provenance(out, "test_eps").sha == SHA


def test_insert_is_idempotent():
    once = TP.insert_provenance(WITH_MARKER, "test_alpha", SHA, "again")
    assert once == WITH_MARKER


def test_insert_preserves_indentation_inside_a_class():
    src = "class TestX:\n    def test_zeta(self):\n        assert True\n"
    out = TP.insert_provenance(src, "test_zeta", SHA, "zeta")
    assert '        """Provenance' in out


def test_insert_bad_sha_returns_source_unchanged():
    src = "def test_eta():\n    assert True\n"
    assert TP.insert_provenance(src, "test_eta", "nope", "r") == src


def test_insert_unknown_function_returns_source_unchanged():
    src = "def test_theta():\n    assert True\n"
    assert TP.insert_provenance(src, "test_absent", SHA, "r") == src


def test_insert_unparsable_source_returns_source_unchanged():
    src = "def broken(:\n"
    assert TP.insert_provenance(src, "test_x", SHA, "r") == src


@pytest.mark.parametrize("given", [None, ""])
def test_insert_empty_source_is_fail_soft(given):
    assert TP.insert_provenance(given, "test_x", SHA, "r") == ""


def test_inserted_output_is_still_valid_python():
    import ast

    src = "def test_iota():\n    assert True\n"
    ast.parse(TP.insert_provenance(src, "test_iota", SHA, "iota"))


# --- check_file / main -----------------------------------------------------

def test_check_file_reports_unmarked(tmp_path):
    p = tmp_path / "test_sample.py"
    p.write_text(WITHOUT_MARKER, encoding="utf-8")
    assert TP.check_file(p) == ["test_beta"]


def test_check_file_missing_path_is_fail_soft(tmp_path):
    assert TP.check_file(tmp_path / "nope.py") == []


def test_check_file_none_is_fail_soft():
    assert TP.check_file(None) == []


def test_main_exits_zero_when_all_marked(tmp_path):
    p = tmp_path / "test_ok.py"
    p.write_text(WITH_MARKER, encoding="utf-8")
    assert TP.main([str(p)]) == 0


def test_main_exits_one_when_something_is_unmarked(tmp_path, capsys):
    p = tmp_path / "test_bad.py"
    p.write_text(WITHOUT_MARKER, encoding="utf-8")
    assert TP.main([str(p)]) == 1
    assert "test_beta" in capsys.readouterr().out


def test_main_without_args_is_fail_soft():
    assert TP.main([]) == 0
