"""Tests for adversarial_regulator bot spec and safe_read_file."""
import os
import tempfile
import pytest

# Ensure runner/ is importable
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bots"))


def test_spec_loads():
    from bots.adversarial_regulator import SPEC
    assert SPEC.id == "adversarial-regulator"
    assert SPEC.role == "reviewer"
    assert SPEC.authority == 0.80
    assert SPEC.reliability == 0.85
    assert len(SPEC.eval_set) >= 5


def test_spec_competence_keys():
    from bots.adversarial_regulator import SPEC
    expected_keys = {
        "regulatory_gap_detection",
        "disclosure_adequacy",
        "fiduciary_compliance",
        "enforcement_pattern_recognition",
        "safe_harbor_validation",
    }
    assert set(SPEC.competence.keys()) == expected_keys


def test_safe_read_file_normal():
    from bots.adversarial_regulator import safe_read_file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
        f.write("hello world\n")
        path = f.name
    try:
        result = safe_read_file(path)
        assert result == "hello world\n"
    finally:
        os.unlink(path)


def test_safe_read_file_binary_bytes():
    """Verify utf-8 errors='replace' handles non-utf8 bytes without raising."""
    from bots.adversarial_regulator import safe_read_file
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        f.write(b"\x8d\xe2\x80\x99test\xff\xfe")
        path = f.name
    try:
        result = safe_read_file(path)
        assert "test" in result
        # Should contain replacement characters, not raise
        assert "�" in result or len(result) > 0
    finally:
        os.unlink(path)


def test_safe_read_file_missing():
    from bots.adversarial_regulator import safe_read_file
    result = safe_read_file("/nonexistent/path/file.txt")
    assert result == ""


def test_safe_read_file_empty():
    from bots.adversarial_regulator import safe_read_file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        path = f.name
    try:
        result = safe_read_file(path)
        assert result == ""
    finally:
        os.unlink(path)
