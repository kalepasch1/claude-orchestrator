"""Tests for cade_extras harness — auto-discovers and runs cx_* modules."""
import importlib
import os
import sys
import types
import pytest

# Ensure runner/ is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import cade_extras


def test_dummy_cx_module_run_is_invoked(tmp_path, monkeypatch):
    """A dummy cx_ module's run() is discovered and invoked by the harness."""
    # Create a dummy cx_dummy_test.py in a temp dir
    dummy = tmp_path / "cx_dummy_test.py"
    dummy.write_text("invoked = False\ndef run():\n    global invoked\n    invoked = True\n")

    # Point the harness at the temp dir
    monkeypatch.setattr(cade_extras, "_RUNNER_DIR", str(tmp_path))

    # Ensure the temp dir is importable
    monkeypatch.syspath_prepend(str(tmp_path))

    success, failure = cade_extras.run()
    assert success == 1
    assert failure == 0

    # Verify run() was actually called
    mod = importlib.import_module("cx_dummy_test")
    assert mod.invoked is True


def test_bad_module_does_not_break_loop(tmp_path, monkeypatch):
    """One failing cx_ module must not prevent others from running."""
    good = tmp_path / "cx_aaa_good.py"
    good.write_text("invoked = False\ndef run():\n    global invoked\n    invoked = True\n")

    bad = tmp_path / "cx_bbb_bad.py"
    bad.write_text("def run():\n    raise RuntimeError('intentional')\n")

    good2 = tmp_path / "cx_ccc_good2.py"
    good2.write_text("invoked = False\ndef run():\n    global invoked\n    invoked = True\n")

    monkeypatch.setattr(cade_extras, "_RUNNER_DIR", str(tmp_path))
    monkeypatch.syspath_prepend(str(tmp_path))

    success, failure = cade_extras.run()
    assert success == 2
    assert failure == 1


def test_no_modules_returns_zero(tmp_path, monkeypatch):
    """Empty directory returns (0, 0) without error."""
    monkeypatch.setattr(cade_extras, "_RUNNER_DIR", str(tmp_path))
    success, failure = cade_extras.run()
    assert success == 0
    assert failure == 0


def test_module_without_run_is_skipped(tmp_path, monkeypatch):
    """A cx_ module that lacks run() is skipped (not counted as failure)."""
    no_run = tmp_path / "cx_no_run.py"
    no_run.write_text("x = 42\n")

    monkeypatch.setattr(cade_extras, "_RUNNER_DIR", str(tmp_path))
    monkeypatch.syspath_prepend(str(tmp_path))

    success, failure = cade_extras.run()
    assert success == 0
    assert failure == 0
