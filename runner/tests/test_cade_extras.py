"""Tests for cade_extras harness."""
import os, sys, types, importlib, tempfile, textwrap
import pytest

# Ensure runner/ is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_discovers_and_runs_cx_module(tmp_path, monkeypatch):
    """A dummy cx_hello.py is discovered and its run() is called."""
    # Write a dummy cx_ module into tmp_path
    cx_file = tmp_path / "cx_hello.py"
    cx_file.write_text(textwrap.dedent("""\
        _called = False
        def run():
            global _called
            _called = True
    """))

    # Patch _RUNNER_DIR so discovery looks in tmp_path
    import cade_extras
    monkeypatch.setattr(cade_extras, "_RUNNER_DIR", str(tmp_path))
    # Clear module cache
    cade_extras._loaded_modules.clear()

    # Also ensure tmp_path is importable
    monkeypatch.syspath_prepend(str(tmp_path))

    result = cade_extras.run()
    assert result["ran"] == 1
    assert result["failed"] == 0

    # Verify the module's run() was actually invoked
    mod = cade_extras._loaded_modules["cx_hello"]
    assert mod._called is True


def test_bad_module_does_not_break_loop(tmp_path, monkeypatch):
    """A failing cx_ module is logged but doesn't stop others."""
    (tmp_path / "cx_bad.py").write_text("def run(): raise RuntimeError('boom')\n")
    (tmp_path / "cx_good.py").write_text(textwrap.dedent("""\
        _called = False
        def run():
            global _called
            _called = True
    """))

    import cade_extras
    monkeypatch.setattr(cade_extras, "_RUNNER_DIR", str(tmp_path))
    cade_extras._loaded_modules.clear()
    monkeypatch.syspath_prepend(str(tmp_path))

    result = cade_extras.run()
    # cx_bad fails, cx_good succeeds (sorted order: bad < good)
    assert result["ran"] == 1
    assert result["failed"] == 1


def test_no_cx_modules(tmp_path, monkeypatch):
    """When no cx_* modules exist, run() returns zeros."""
    import cade_extras
    monkeypatch.setattr(cade_extras, "_RUNNER_DIR", str(tmp_path))
    cade_extras._loaded_modules.clear()

    result = cade_extras.run()
    assert result["ran"] == 0
    assert result["failed"] == 0
