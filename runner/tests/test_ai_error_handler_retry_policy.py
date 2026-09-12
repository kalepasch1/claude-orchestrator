#!/usr/bin/env python3
"""Which failures are worth retrying, and which three digits are not evidence.

Two defects in the same decision path, both of which spend the retry budget on
failures that cannot benefit:

1. `auth` was on the automatic-retry list. An expired token does not un-expire
   because you asked again — clearing it takes a credential change, which is an
   action, not a wait. Against a real service, retrying walks into lockouts and
   rate limits, turning a fixable credential problem into a throttled one.

2. The auth pattern was a bare `401|403`, which under re.I matches those digits
   ANYWHERE: "line 401", "took 1403ms", a port, a byte count, the leading digits
   of a SHA. Any build log containing one was classified auth at 0.90
   confidence — and auth was retryable, so a syntax error on line 401 was
   retried as an expired token.

The second is the third appearance of one shape in this repo: the bare `OOM` in
quarantine_triage matched "groomed" and requeued every groomed duplicate, and
the secret linter flagged its own detector. A digit alternation with no boundary
is not a pattern, it is a substring search.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai_error_handler import (  # noqa: E402
    NON_RETRYABLE_REASONS,
    classify_error,
    is_transient,
    suggest_remediation,
)


class TestAuthIsNotRetried:
    def test_an_expired_token_is_not_transient(self):
        assert is_transient(classify_error("Error: token expired")) is False

    def test_a_401_response_is_not_transient(self):
        assert is_transient(classify_error("HTTP 401 Unauthorized")) is False

    def test_a_403_response_is_not_transient(self):
        assert is_transient(classify_error("HTTP 403 Forbidden")) is False

    def test_it_is_still_classified_as_auth(self):
        # Not retrying is not the same as not understanding. The classification
        # is what makes the remediation useful.
        assert classify_error("HTTP 401 Unauthorized")["category"] == "auth"

    def test_the_remedy_is_still_offered(self):
        remedies = suggest_remediation(classify_error("token expired"))
        assert any("rotate" in text.lower() or "refresh" in text.lower()
                   for text in remedies)

    def test_the_reason_travels_with_the_decision(self):
        # An absence explains nothing; the reason is written down.
        assert "auth" in NON_RETRYABLE_REASONS
        assert "lockout" in NON_RETRYABLE_REASONS["auth"]


class TestThreeDigitsAreNotEvidence:
    def test_a_line_number_is_not_an_auth_failure(self):
        classified = classify_error(
            'File "runner/db.py", line 401\n    SyntaxError: invalid syntax')
        assert classified["category"] != "auth"
        assert classified["category"] == "syntax"

    def test_a_duration_is_not_an_auth_failure(self):
        classified = classify_error("TypeError: bad operand (took 1403ms)")
        assert classified["category"] != "auth"

    def test_a_byte_count_is_not_an_auth_failure(self):
        classified = classify_error("AssertionError: expected 403 bytes, got 12")
        assert classified["category"] != "auth"

    def test_a_sha_prefix_is_not_an_auth_failure(self):
        classified = classify_error("KeyError: commit 4013ab9f not in index")
        assert classified["category"] != "auth"

    def test_a_port_is_not_an_auth_failure(self):
        classified = classify_error("ValueError: cannot bind port 4030")
        assert classified["category"] != "auth"

    def test_the_misclassified_syntax_error_is_no_longer_retried(self):
        # The whole cost of the bug in one assertion: a deterministic source
        # error was being retried as a transient credential problem.
        classified = classify_error(
            'File "app.py", line 401\n    SyntaxError: invalid syntax')
        assert is_transient(classified) is False


class TestRealAuthFailuresStillMatch:
    def test_status_code_forms(self):
        for text in ("HTTP 401 Unauthorized",
                     "HTTP/1.1 403 Forbidden",
                     "response status 401",
                     "server returned code 403",
                     "401 Client Error: Unauthorized for url"):
            assert classify_error(text)["category"] == "auth", text

    def test_worded_forms(self):
        for text in ("AuthenticationError: bad key",
                     "Unauthorized",
                     "403 Forbidden",
                     "invalid token"):
            assert classify_error(text)["category"] == "auth", text


class TestTheRestOfThePolicyIsUnchanged:
    def test_a_timeout_is_still_retried(self):
        assert is_transient(classify_error("TimeoutError: read timed out")) is True

    def test_a_resource_exhaustion_is_still_retried(self):
        # A full disk or an OOM can genuinely clear, and the retry may land on
        # a host with room.
        assert is_transient(
            classify_error("MemoryError: Cannot allocate memory")) is True

    def test_a_syntax_error_is_still_not_retried(self):
        assert is_transient(classify_error("SyntaxError: invalid syntax")) is False

    def test_bad_input_is_still_not_retried(self):
        assert is_transient(None) is False
        assert is_transient({}) is False
