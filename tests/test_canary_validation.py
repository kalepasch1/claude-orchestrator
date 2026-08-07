#!/usr/bin/env python3
"""Test script for validate_canary (canary-gemini-25).

Asserts the three specified cases, logging each, and exercises edge cases.
Runnable directly (python tests/test_canary_validation.py) or via pytest.
"""
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "runner"))
from canary_validation import validate_canary

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("test_canary_validation")


def test_exact_word_returns_true():
    log.info("case: validate_canary('canary') should be True")
    assert validate_canary("canary") is True


def test_phrase_containing_word_returns_true():
    log.info("case: validate_canary('Canary bird') should be True")
    assert validate_canary("Canary bird") is True


def test_unrelated_text_returns_false():
    log.info("case: validate_canary('nothing') should be False")
    assert validate_canary("nothing") is False


def test_substring_without_word_boundary_is_false():
    log.info("case: embedded substring 'canaryish' should be False")
    assert validate_canary("canaryish token") is False


def test_non_string_input_is_false():
    log.info("case: non-string input should be False")
    assert validate_canary(None) is False
    assert validate_canary(42) is False


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"ok   {name}")
            except AssertionError:
                failures += 1
                print(f"FAIL {name}")
    print(f"\n{failures} failure(s)")
    sys.exit(1 if failures else 0)
