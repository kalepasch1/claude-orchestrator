#!/usr/bin/env python3
"""Tests for proof_strength.py — PURE logic only (no git)."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import proof_strength


# ── classify_proof ──────────────────────────────────────────────────

def test_classify_none():
    assert proof_strength.classify_proof(None)["kind"] == "weak"

def test_classify_empty():
    assert proof_strength.classify_proof("")["kind"] == "weak"

def test_classify_non_string():
    assert proof_strength.classify_proof(42)["kind"] == "weak"

def test_classify_pytest_specific():
    r = proof_strength.classify_proof("python3 -m pytest runner/tests/test_foo.py -q")
    assert r["kind"] == "test"
    assert r["has_specific_file"] is True
    assert r["file_path"] == "runner/tests/test_foo.py"

def test_classify_pytest_bare():
    r = proof_strength.classify_proof("pytest")
    assert r["kind"] == "test"
    assert r["has_specific_file"] is False

def test_classify_vitest_specific():
    r = proof_strength.classify_proof("npx vitest run src/foo.test.ts")
    assert r["kind"] == "test"
    assert r["has_specific_file"] is True
    assert "foo.test.ts" in r["file_path"]

def test_classify_jest():
    r = proof_strength.classify_proof("jest --run src/bar.spec.js")
    assert r["kind"] == "test"
    assert r["has_specific_file"] is True

def test_classify_npm_test():
    r = proof_strength.classify_proof("npm test")
    assert r["kind"] == "test"
    assert r["has_specific_file"] is False

def test_classify_py_compile():
    r = proof_strength.classify_proof("python3 -m py_compile runner/foo.py")
    assert r["kind"] == "build"

def test_classify_tsc():
    r = proof_strength.classify_proof("npx tsc --noEmit")
    assert r["kind"] == "build"

def test_classify_nuxi_typecheck():
    r = proof_strength.classify_proof("npx nuxi typecheck")
    assert r["kind"] == "build"

def test_classify_npm_run_build():
    r = proof_strength.classify_proof("npm run build")
    assert r["kind"] == "build"

def test_classify_random_cmd():
    r = proof_strength.classify_proof("echo hello")
    assert r["kind"] == "weak"

def test_classify_compound_pytest():
    r = proof_strength.classify_proof("python3 -m pytest runner/tests/test_proof_strength.py -q AND python3 -m pytest runner/tests -q")
    assert r["kind"] == "test"
    assert r["has_specific_file"] is True


# ── should_check_red_on_base ────────────────────────────────────────

def test_should_check_none_task():
    assert proof_strength.should_check_red_on_base(None) is False

def test_should_check_empty_task():
    assert proof_strength.should_check_red_on_base({}) is False

def test_should_check_build_proof():
    task = {"proof": "python3 -m py_compile runner/foo.py"}
    assert proof_strength.should_check_red_on_base(task) is False

def test_should_check_generic_test():
    task = {"proof": "pytest"}
    assert proof_strength.should_check_red_on_base(task) is False

def test_should_check_specific_test():
    task = {"proof": "python3 -m pytest runner/tests/test_foo.py -q"}
    assert proof_strength.should_check_red_on_base(task) is True

def test_should_check_proof_cmd_key():
    task = {"proof_cmd": "python3 -m pytest runner/tests/test_bar.py"}
    assert proof_strength.should_check_red_on_base(task) is True

def test_should_check_weak():
    task = {"proof": "echo done"}
    assert proof_strength.should_check_red_on_base(task) is False

def test_should_check_non_dict():
    assert proof_strength.should_check_red_on_base("string") is False
    assert proof_strength.should_check_red_on_base(123) is False
