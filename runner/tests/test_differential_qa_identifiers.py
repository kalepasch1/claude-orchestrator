#!/usr/bin/env python3
"""Tests for order-independent, truncation-safe differential QA comparison.

Acceptance criteria from the original task:
1. Two shuffled orderings of the same failure set → compare returns the same verdict.
2. A failure appearing beyond the 6000-char boundary is still recognised.
"""
import random
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import differential_qa


def _tap_line(n, name):
    return f"not ok {n} - {name}"


def _vitest_line(name):
    return f"  × {name} (12ms)"


def _pytest_line(path, name):
    return f"FAILED {path}::{name}"


def test_test_identifiers_tap():
    log = "not ok 1 - should add numbers\nnot ok 2 - should subtract\nok 3 - should multiply"
    ids = differential_qa.test_identifiers(log)
    assert ids == ["should add numbers", "should subtract"]


def test_test_identifiers_vitest():
    log = "  × handles null input (5ms)\n  × validates schema (12ms)\n  ✓ passes basic check"
    ids = differential_qa.test_identifiers(log)
    assert "handles null input" in ids
    assert "validates schema" in ids
    assert len(ids) == 2


def test_test_identifiers_pytest():
    log = "FAILED tests/test_auth.py::test_login_redirect\nFAILED tests/test_auth.py::test_logout"
    ids = differential_qa.test_identifiers(log)
    assert ids == ["tests/test_auth.py::test_login_redirect", "tests/test_auth.py::test_logout"]


def test_test_identifiers_empty_for_build_output():
    log = "error TS2304: Cannot find name 'foo'.\nsrc/bar.ts(12,5): error TS2339: ..."
    ids = differential_qa.test_identifiers(log)
    assert ids == []



def test_shuffled_orderings_same_verdict():
    """Two shuffled orderings of the same failure set must produce the same verdict."""
    names = [f"test_case_{i}" for i in range(37)]
    # Build two logs with the same failures in different order
    order_a = list(names)
    order_b = list(names)
    random.seed(42)
    random.shuffle(order_a)
    random.seed(99)
    random.shuffle(order_b)
    log_a = "\n".join(_tap_line(i + 1, n) for i, n in enumerate(order_a))
    log_b = "\n".join(_tap_line(i + 1, n) for i, n in enumerate(order_b))
    # Both used as candidate against the same baseline (order_a)
    result_a = differential_qa.compare(log_a, log_b)
    result_b = differential_qa.compare(log_b, log_a)
    assert result_a["allowed"] == result_b["allowed"], (
        f"Different orderings gave different verdicts: {result_a} vs {result_b}")
    assert result_a["allowed"] is True
    # Signature-based comparison must also be deterministic now that sort is applied
    sigs_a = differential_qa.signatures(log_a)
    sigs_b = differential_qa.signatures(log_b)
    assert sigs_a == sigs_b, "Sorted signatures should be identical for identical content"


def test_failure_beyond_6000_char_boundary():
    """A failure appearing beyond the 6000-char boundary must still be recognised."""
    # Build a baseline log where one failure is beyond the 6000-char mark
    padding = "ok 1 - passing test " + ("x" * 200) + "\n"
    padding_block = padding * 40  # ~9600 chars of padding
    early_fail = _tap_line(100, "early-failure-within-window")
    late_fail = _tap_line(200, "late-failure-beyond-truncation")
    # The late failure appears BEFORE the padding, so it's >6000 chars from the end
    full_log = late_fail + "\n" + padding_block + early_fail + "\n"
    assert len(full_log) > 6000
    # The late failure should be in the test_identifiers parsed from the full log
    ids = differential_qa.test_identifiers(full_log)
    assert "late-failure-beyond-truncation" in ids
    assert "early-failure-within-window" in ids
    # When comparing candidate (same set) against baseline (same set), should waive
    result = differential_qa.compare(full_log, full_log)
    assert result["allowed"] is True, f"Should waive identical failure set: {result}"



def test_new_failure_detected_via_identifiers():
    """A candidate with an extra failure should NOT be waived."""
    baseline = "\n".join(_tap_line(i, f"test_{i}") for i in range(1, 6))
    candidate = baseline + "\n" + _tap_line(6, "new_regression_test")
    result = differential_qa.compare(candidate, baseline)
    assert result["allowed"] is False
    assert "new_regression_test" in result["new"]


def test_signatures_sort_determinism():
    """signatures() must sort before capping, making the result order-independent."""
    lines = [f"error: assertion failed in test_{i}" for i in range(250)]
    log_forward = "\n".join(lines)
    log_reverse = "\n".join(reversed(lines))
    sigs_f = differential_qa.signatures(log_forward)
    sigs_r = differential_qa.signatures(log_reverse)
    assert sigs_f == sigs_r, "Sorted+capped signatures must match regardless of input order"
    assert len(sigs_f) == differential_qa._SIGNATURE_CAP


if __name__ == "__main__":
    test_test_identifiers_tap()
    test_test_identifiers_vitest()
    test_test_identifiers_pytest()
    test_test_identifiers_empty_for_build_output()
    test_shuffled_orderings_same_verdict()
    test_failure_beyond_6000_char_boundary()
    test_new_failure_detected_via_identifiers()
    test_signatures_sort_determinism()
    print("All tests passed.")
