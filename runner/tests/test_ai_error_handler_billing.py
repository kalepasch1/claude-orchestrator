#!/usr/bin/env python3
"""Billing/quota errors must never be retried.

THE FAILURE THIS PINS
---------------------
improve-distribute-test-runners-across-fleet-8-slice-3 exhausted its retries against
this, four times over, each attempt sleeping longer than the last:

    litellm.APIError: XaiException - Error code: 403 - {'code': 'permission-denied',
    'error': 'Your team ... has either used all available credits or reached its
    monthly spending limit.'}
    Retrying in 4.0 seconds... 8.0 ... 16.0 ... 32.0

The 403 matched the auth pattern at 0.90 confidence, auth was a transient category, so
the runner retried. Sixty seconds of backoff per task to reach a conclusion that was
available immediately — and identically for every other task routed to that provider,
because waiting does not add credits to an account.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ai_error_handler as aeh  # noqa: E402

# The message verbatim from the failing run.
XAI_403 = (
    "litellm.APIError: APIError: XaiException - Error code: 403 - {'code': "
    "'permission-denied', 'error': 'Your team b4fa25c7-b07a-4087-99ea-53375a0cecde "
    "has either used all available credits or reached its monthly spending limit. To "
    "continue making API requests, please purchase more credits or raise your "
    "spending limit.'}"
)


# ── the exact regression ────────────────────────────────────────────────────

def test_the_xai_credit_exhaustion_is_classified_as_billing():
    assert aeh.classify_error(XAI_403)["category"] == "billing"


def test_the_xai_credit_exhaustion_is_never_retried():
    """The whole point: this is what cost 4 backoff sleeps per task."""
    assert aeh.is_transient(aeh.classify_error(XAI_403)) is False


def test_the_xai_credit_exhaustion_is_permanent():
    assert aeh.is_permanent(aeh.classify_error(XAI_403)) is True


def test_billing_beats_auth_despite_the_403():
    """Ordering is load-bearing — classify_error returns the FIRST match."""
    result = aeh.classify_error(XAI_403)
    assert result["category"] != "auth"
    assert result["confidence"] >= aeh.HIGH_CONFIDENCE_THRESHOLD


def test_billing_remediation_says_stop_retrying():
    steps = aeh.suggest_remediation(aeh.classify_error(XAI_403))
    assert any("STOP RETRYING" in s for s in steps)


# ── the billing family generally ────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "Your team has used all available credits",
    "please purchase more credits",
    "reached its monthly spending limit",
    "insufficient credit balance",
    "insufficient funds for this request",
    "You exceeded your current quota, please check your plan and billing details",
    "Error 402: Payment Required",
    "credits exhausted",
    "out of credits",
    "billing hard limit reached",
])
def test_billing_shapes_are_all_permanent(text):
    classification = aeh.classify_error(text)
    assert classification["category"] == "billing", text
    assert aeh.is_transient(classification) is False
    assert aeh.is_permanent(classification) is True


def test_billing_outranks_resource_for_quota_wording():
    """'quota exceeded' used to land in resource, which was transient."""
    classification = aeh.classify_error("You exceeded your current quota")
    assert classification["category"] == "billing"
    assert aeh.is_transient(classification) is False


# ── auth: expiry retried, permission denial not ─────────────────────────────

@pytest.mark.parametrize("text", [
    "token expired",
    "Error 401: token has expired",
    "session expired, please log in again",
    "credentials expired",
])
def test_an_expired_credential_is_still_retried(text):
    """Narrowing auth must not throw away the case that genuinely IS transient."""
    classification = aeh.classify_error(text)
    assert classification["category"] == "auth", text
    assert aeh.is_transient(classification) is True, text


@pytest.mark.parametrize("text", [
    "403 Forbidden",
    "401 Unauthorized",
    "permission denied",
    "AuthenticationError: invalid API key",
    "Access Denied",
])
def test_a_hard_authorization_failure_is_not_retried(text):
    classification = aeh.classify_error(text)
    assert classification["category"] == "auth", text
    assert aeh.is_transient(classification) is False, text


# ── nothing else changed ────────────────────────────────────────────────────

@pytest.mark.parametrize("text,category", [
    ("TimeoutError: read timed out", "timeout"),
    ("MemoryError", "resource"),
    ("No space left on device", "resource"),
    ("SyntaxError: invalid syntax", "syntax"),
    ("ModuleNotFoundError: No module named 'x'", "dependency"),
])
def test_other_categories_are_unaffected(text, category):
    assert aeh.classify_error(text)["category"] == category


def test_timeouts_are_still_retried():
    assert aeh.is_transient(aeh.classify_error("TimeoutError: read timed out")) is True


def test_resource_exhaustion_is_still_retried():
    assert aeh.is_transient(aeh.classify_error("MemoryError")) is True


def test_billing_is_the_most_severe_category():
    """An exhausted provider fails every task routed to it, not just one."""
    assert aeh._SEVERITY_ORDER[0] == "billing"


# ── fail-soft ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("value", [None, "", 42, [], {}])
def test_is_permanent_is_fail_soft(value):
    assert aeh.is_permanent(value) is False


@pytest.mark.parametrize("value", [None, "", 42, [], {}])
def test_is_transient_is_fail_soft(value):
    assert aeh.is_transient(value) is False


def test_unknown_text_is_neither_transient_nor_permanent():
    classification = aeh.classify_error("something entirely unfamiliar")
    assert aeh.is_transient(classification) is False
    assert aeh.is_permanent(classification) is False


# ── the same defect in auto_error_categorizer ───────────────────────────────

import auto_error_categorizer as aec  # noqa: E402


def test_categorizer_marks_the_xai_message_permanent():
    result = aec.categorize(XAI_403)
    assert result["category"] == aec.PERMANENT
    assert result["retryable"] is False


def test_categorizer_matches_hyphenated_permission_denied():
    """`permission\\s*denied` never matched the literal providers actually send."""
    assert aec._PERMANENT_PATTERNS.search("'code': 'permission-denied'")


def test_categorizer_does_not_retry_an_openai_style_quota_message():
    """'quota exceeded' is in _TRANSIENT_PATTERNS — billing must win."""
    result = aec.categorize(
        "You exceeded your current quota, please check your plan and billing details")
    assert result["category"] == aec.PERMANENT
    assert result["retryable"] is False


def test_categorizer_still_retries_a_real_rate_limit():
    """429 throttling IS transient — the narrowing must not swallow it."""
    result = aec.categorize("429 Too Many Requests: rate limit exceeded, try again")
    assert result["category"] == aec.TRANSIENT
    assert result["retryable"] is True


def test_categorizer_still_retries_a_timeout():
    assert aec.categorize("connection timeout")["retryable"] is True
