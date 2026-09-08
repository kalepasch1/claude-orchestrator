"""error_classifier.py — classify task errors for autonomous retry decisions.

When a task fails, the error message determines whether to retry (transient),
escalate model tier (capacity), quarantine (persistent), or supersede
(infrastructure). This module provides a pure-function classifier so the
decision logic is testable and consistent across runner, cowork executor,
and agentic_repair.

Fail-soft: returns UNKNOWN on any parsing failure.
"""
from __future__ import annotations

import re
from enum import Enum
from typing import NamedTuple


class ErrorClass(str, Enum):
    TRANSIENT = "transient"       # network timeout, rate limit — retry same tier
    CAPACITY = "capacity"         # context overflow, OOM — escalate model
    BUILD_FAIL = "build_fail"     # compilation/syntax error — fix code
    TEST_FAIL = "test_fail"       # tests red — fix code
    INFRA = "infra"               # missing binary, permission — supersede
    CONFLICT = "conflict"         # git merge conflict — needs resolution
    UNKNOWN = "unknown"           # unclassifiable


class Classification(NamedTuple):
    error_class: ErrorClass
    confidence: float  # 0.0–1.0
    detail: str


_PATTERNS = [
    (ErrorClass.TRANSIENT, 0.9, [
        re.compile(r"(timeout|timed out|rate.limit|429|503|502|ECONNRESET|ETIMEDOUT)", re.I),
    ]),
    (ErrorClass.CAPACITY, 0.85, [
        re.compile(r"(context.window|max.tokens|output.limit|token.limit|OOM|out.of.memory)", re.I),
    ]),
    (ErrorClass.INFRA, 0.9, [
        re.compile(r"(No such file or directory|command not found|ENOENT|permission denied|EACCES)", re.I),
    ]),
    (ErrorClass.CONFLICT, 0.9, [
        re.compile(r"(merge conflict|CONFLICT|non-fast-forward|diverged)", re.I),
    ]),
    (ErrorClass.BUILD_FAIL, 0.8, [
        re.compile(r"(SyntaxError|build failed|compilation error|Cannot find module|TypeError.*undefined)", re.I),
    ]),
    (ErrorClass.TEST_FAIL, 0.8, [
        re.compile(r"(FAILED|AssertionError|test.fail|tests? red|\d+ fail)", re.I),
    ]),
]


def classify(error_text: str) -> Classification:
    """Classify an error message. Returns UNKNOWN if no pattern matches."""
    if not error_text:
        return Classification(ErrorClass.UNKNOWN, 0.0, "empty error text")
    try:
        for cls, confidence, patterns in _PATTERNS:
            for pat in patterns:
                m = pat.search(error_text)
                if m:
                    return Classification(cls, confidence, m.group(0))
    except Exception:
        pass
    return Classification(ErrorClass.UNKNOWN, 0.3, "no pattern matched")


def should_retry(classification: Classification) -> bool:
    """Whether the error class warrants an automatic retry."""
    return classification.error_class in (
        ErrorClass.TRANSIENT,
        ErrorClass.CAPACITY,
    )


def should_escalate(classification: Classification) -> bool:
    """Whether the error class warrants model tier escalation."""
    return classification.error_class == ErrorClass.CAPACITY


def should_supersede(classification: Classification) -> bool:
    """Whether the error is an infrastructure blocker (not fixable by code)."""
    return classification.error_class == ErrorClass.INFRA
