"""Tests for ai_error_handler — error classification and remediation."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ai_error_handler import (
    classify_error,
    suggest_remediation,
    is_transient,
    extract_error_context,
    prioritize_errors,
)

# ── classify_error ──────────────────────────────────────────────────────

def test_classify_dependency_module_not_found():
    r = classify_error("ModuleNotFoundError: No module named 'foo'")
    assert r["category"] == "dependency"
    assert r["confidence"] >= 0.9

def test_classify_dependency_import_error():
    r = classify_error("ImportError: cannot import name 'bar' from 'baz'")
    assert r["category"] == "dependency"

def test_classify_auth_401():
    r = classify_error("HTTP 401 Unauthorized")
    assert r["category"] == "auth"
    assert r["confidence"] >= 0.8

def test_classify_auth_token_expired():
    r = classify_error("token expired, please re-authenticate")
    assert r["category"] == "auth"

def test_classify_timeout():
    r = classify_error("TimeoutError: operation timed out after 30s")
    assert r["category"] == "timeout"
    assert r["confidence"] >= 0.9

def test_classify_syntax():
    r = classify_error("SyntaxError: invalid syntax (foo.py, line 42)")
    assert r["category"] == "syntax"

def test_classify_resource_oom():
    r = classify_error("MemoryError: Cannot allocate 2GB")
    assert r["category"] == "resource"

def test_classify_runtime_type_error():
    r = classify_error("TypeError: unsupported operand type(s)")
    assert r["category"] == "runtime"

def test_classify_unknown():
    r = classify_error("something completely unrecognizable xyz 123")
    assert r["category"] == "unknown"
    assert r["confidence"] == 0.0

def test_classify_none_input():
    r = classify_error(None)
    assert r["category"] == "unknown"
    assert r["confidence"] == 0.0

def test_classify_empty_string():
    r = classify_error("")
    assert r["category"] == "unknown"

# ── suggest_remediation ─────────────────────────────────────────────────

def test_remediation_returns_list_for_known():
    cls = classify_error("ModuleNotFoundError: No module named 'x'")
    rems = suggest_remediation(cls)
    assert isinstance(rems, list)
    assert len(rems) >= 2

def test_remediation_bad_input():
    rems = suggest_remediation(None)
    assert isinstance(rems, list)
    assert len(rems) >= 1

def test_remediation_unknown_category():
    rems = suggest_remediation({"category": "never_heard_of_this"})
    assert isinstance(rems, list)  # falls back to "unknown"

# ── is_transient ────────────────────────────────────────────────────────

def test_transient_timeout():
    cls = classify_error("TimeoutError: read timed out")
    assert is_transient(cls) is True

def test_transient_syntax_is_not():
    cls = classify_error("SyntaxError: invalid syntax")
    assert is_transient(cls) is False

def test_transient_bad_input():
    assert is_transient(None) is False

def test_transient_resource():
    cls = classify_error("MemoryError: Cannot allocate memory")
    assert is_transient(cls) is True

# ── extract_error_context ───────────────────────────────────────────────

def test_extract_context_python_traceback():
    tb = '''Traceback (most recent call last):
  File "/app/runner/main.py", line 42, in run
    do_thing()
  File "/app/runner/utils.py", line 10, in do_thing
    raise ValueError("bad")
ValueError: bad'''
    ctx = extract_error_context(tb)
    assert ctx["file"] == "/app/runner/main.py"
    assert ctx["line"] == 42
    assert "ValueError" in ctx["snippet"]

def test_extract_context_module():
    ctx = extract_error_context("ModuleNotFoundError: No module named 'requests'")
    assert ctx["module"] == "requests"

def test_extract_context_none():
    ctx = extract_error_context(None)
    assert ctx["file"] is None
    assert ctx["snippet"] == ""

def test_extract_context_max_lines():
    long_err = "\n".join(f"line {i}" for i in range(50))
    ctx = extract_error_context(long_err, max_lines=5)
    assert ctx["snippet"].count("\n") == 4  # 5 lines = 4 newlines

# ── prioritize_errors ───────────────────────────────────────────────────

def test_prioritize_severity_order():
    errs = [
        classify_error("TimeoutError: timed out"),
        classify_error("MemoryError: OOM"),
        classify_error("SyntaxError: bad"),
    ]
    ordered = prioritize_errors(errs)
    cats = [e["category"] for e in ordered]
    assert cats.index("resource") < cats.index("timeout")
    assert cats.index("syntax") < cats.index("timeout")

def test_prioritize_empty():
    assert prioritize_errors([]) == []

def test_prioritize_none():
    assert prioritize_errors(None) == []

def test_prioritize_malformed_items():
    result = prioritize_errors([None, "bad", {"category": "auth", "confidence": 0.9}])
    assert isinstance(result, list)
    assert len(result) == 3
    # The dict item should come first (has a real category)
    assert result[0] == {"category": "auth", "confidence": 0.9}
