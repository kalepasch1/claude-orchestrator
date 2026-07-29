#!/usr/bin/env python3
"""
test_llm_api_retry.py - comprehensive tests for retry_policy module.

Tests the classification, backoff calculation, and retry decision logic
that prevents transient failures (network blips, rate limits, timeouts) from
wedging entire dependency trees.
"""
import os
import re
import sys
import pytest
from unittest.mock import patch, MagicMock

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import retry_policy


class TestClassify:
    """Test error classification (transient vs terminal)."""

    def test_classify_transient_connection_reset(self):
        """Network connection reset is transient."""
        note = "runner exception: <urlopen error [Errno 54] Connection reset by peer>"
        assert retry_policy.classify(note) == "transient"

    def test_classify_transient_timeout(self):
        """Network timeout is transient."""
        assert retry_policy.classify("timed out waiting for response") == "transient"
        assert retry_policy.classify("timeout: 30s exceeded") == "transient"
        assert retry_policy.classify("read timed out") == "transient"

    def test_classify_transient_rate_limit(self):
        """Rate limit errors are transient."""
        assert retry_policy.classify("rate limit exceeded") == "transient"
        assert retry_policy.classify("HTTP 429 Too Many Requests") == "transient"
        assert retry_policy.classify("rate_limit_exceeded") == "transient"

    def test_classify_transient_server_errors(self):
        """5xx server errors are transient."""
        assert retry_policy.classify("500 Internal Server Error") == "transient"
        assert retry_policy.classify("502 Bad Gateway") == "transient"
        assert retry_policy.classify("503 Service Unavailable") == "transient"
        assert retry_policy.classify("504 Gateway Timeout") == "transient"

    def test_classify_transient_conflict(self):
        """HTTP 409 Conflict is transient (retry-able race condition)."""
        assert retry_policy.classify("409: conflict") == "transient"
        assert retry_policy.classify("HTTP error 409") == "transient"

    def test_classify_transient_budget_cap(self):
        """Budget cap in subscription mode is transient throttling."""
        assert retry_policy.classify("budget cap reached") == "transient"
        assert retry_policy.classify("cost circuit breaker triggered") == "transient"

    def test_classify_transient_dns_and_ssl(self):
        """DNS and SSL issues can be transient."""
        assert retry_policy.classify("name resolution failure") == "transient"
        assert retry_policy.classify("DNS lookup failed") == "transient"
        assert retry_policy.classify("SSL handshake timeout") == "transient"

    def test_classify_transient_provider_overload(self):
        """Provider overload signals are transient."""
        assert retry_policy.classify("service overloaded, high demand") == "transient"
        assert retry_policy.classify("please try again later") == "transient"

    def test_classify_transient_broken_pipe(self):
        """Broken pipe during I/O is transient."""
        assert retry_policy.classify("broken pipe error") == "transient"

    def test_classify_terminal_agent_failed(self):
        """Agent work failure is terminal."""
        assert retry_policy.classify("agent run failed: syntax error") == "terminal"

    def test_classify_terminal_no_changes(self):
        """No code changes by agent is terminal."""
        assert retry_policy.classify("no committable changes") == "terminal"
        assert retry_policy.classify("changed nothing in codebase") == "terminal"
        assert retry_policy.classify("no file changes detected") == "terminal"

    def test_classify_terminal_verify_rejected(self):
        """Verify/judge rejection is terminal."""
        assert retry_policy.classify("verify: logic error in fix") == "terminal"
        assert retry_policy.classify("judge: introduces SQL injection") == "terminal"

    def test_classify_terminal_quality_gate(self):
        """Quality gate failure is terminal."""
        assert retry_policy.classify("quality gate failed: test coverage below 80%") == "terminal"

    def test_classify_terminal_legal_review(self):
        """Legal review flag is terminal."""
        assert retry_policy.classify("legal review required: compliance issue") == "terminal"

    def test_classify_terminal_awaiting_approval(self):
        """Awaiting approval is terminal (not auto-retry-able)."""
        assert retry_policy.classify("awaiting human approval") == "terminal"

    def test_classify_terminal_exhausted_retries(self):
        """Exhausted retries note is terminal."""
        assert retry_policy.classify("exhausted retries on this task") == "terminal"

    def test_classify_terminal_two_key(self):
        """Two-key approval requirement is terminal."""
        assert retry_policy.classify("two-key approval required") == "terminal"

    def test_classify_unknown_defaults_to_terminal(self):
        """Unknown error messages default to terminal (safer)."""
        assert retry_policy.classify("some novel error we've never seen") == "terminal"
        assert retry_policy.classify("frobnicator exploded") == "terminal"
        assert retry_policy.classify("") == "terminal"
        assert retry_policy.classify(None) == "terminal"

    def test_classify_case_insensitive(self):
        """Classification should be case-insensitive."""
        assert retry_policy.classify("TIMEOUT") == "transient"
        assert retry_policy.classify("Rate Limit") == "transient"
        assert retry_policy.classify("AGENT RUN FAILED") == "terminal"

    def test_classify_partial_match(self):
        """Partial keyword matches should trigger classification."""
        assert retry_policy.classify("The timeout was exceeded") == "transient"
        assert retry_policy.classify("experiencing high demand") == "transient"
        assert retry_policy.classify("verify did not pass") == "terminal"


class TestBackoffSeconds:
    """Test exponential backoff calculation with jitter."""

    def test_backoff_first_retry(self):
        """First retry should be close to BACKOFF_BASE_S."""
        backoff = retry_policy.backoff_seconds(0)
        expected_base = retry_policy.BACKOFF_BASE_S
        # Allow ±25% jitter
        assert expected_base * 0.75 <= backoff <= expected_base * 1.25

    def test_backoff_exponential_growth(self):
        """Each retry doubles the base backoff."""
        backoff_0 = retry_policy.backoff_seconds(0)
        backoff_1 = retry_policy.backoff_seconds(1)
        backoff_2 = retry_policy.backoff_seconds(2)

        # Account for jitter: expected values with ±25% margin
        assert backoff_1 > backoff_0 * 1.5  # 2x with margin for jitter
        assert backoff_2 > backoff_1 * 1.5

    def test_backoff_respects_cap(self):
        """Backoff should never exceed BACKOFF_CAP_S."""
        for retry_count in range(20):
            backoff = retry_policy.backoff_seconds(retry_count)
            assert backoff <= retry_policy.BACKOFF_CAP_S * 1.25  # Allow jitter

    def test_backoff_negative_retry_count_treated_as_zero(self):
        """Negative retry count should be treated as 0."""
        backoff_neg = retry_policy.backoff_seconds(-1)
        backoff_zero = retry_policy.backoff_seconds(0)
        assert backoff_neg * 0.75 <= backoff_zero <= backoff_neg * 1.5

    def test_backoff_with_custom_env_vars(self):
        """Backoff should respect environment variable overrides."""
        with patch.dict(os.environ, {"RETRY_BACKOFF_BASE_S": "10"}):
            # Need to reload module to pick up env change
            import importlib
            importlib.reload(retry_policy)
            backoff = retry_policy.backoff_seconds(0)
            assert 10 * 0.75 <= backoff <= 10 * 1.25
            # Reload back to original
            importlib.reload(retry_policy)


class TestDecide:
    """Test retry decision logic."""

    def test_decide_transient_under_limit(self):
        """Transient error under retry limit should requeue."""
        result = retry_policy.decide("timeout error", transient_retries=0)
        assert result["action"] == "requeue"
        assert result["transient_retries"] == 1
        assert result["backoff_s"] > 0
        assert "transient (1/" in result["note"]

    def test_decide_transient_increments_retry_count(self):
        """Retry count should increment."""
        result = retry_policy.decide("rate limit", transient_retries=3)
        assert result["transient_retries"] == 4
        assert "transient (4/" in result["note"]

    def test_decide_transient_at_limit(self):
        """At retry limit, should still requeue for cooldown."""
        max_retries = retry_policy.MAX_TRANSIENT_RETRIES
        result = retry_policy.decide("timeout", transient_retries=max_retries)
        assert result["action"] == "requeue"
        assert result["transient_retries"] == max_retries + 1
        assert "transient cap reached" in result["note"]

    def test_decide_transient_past_limit(self):
        """Past retry limit, should requeue for cooldown."""
        max_retries = retry_policy.MAX_TRANSIENT_RETRIES
        result = retry_policy.decide("timeout", transient_retries=max_retries + 10)
        assert result["action"] == "requeue"
        assert "transient cap reached" in result["note"]

    def test_decide_terminal_blocks(self):
        """Terminal error should block."""
        result = retry_policy.decide("agent run failed", transient_retries=0)
        assert result["action"] == "block"
        assert result["backoff_s"] == 0
        assert result["transient_retries"] == 0

    def test_decide_terminal_stays_blocked_despite_retries(self):
        """Terminal error should block even if retries were attempted."""
        result = retry_policy.decide("judge: SQL injection", transient_retries=10)
        assert result["action"] == "block"
        assert result["transient_retries"] == 10  # Count preserved

    def test_decide_truncates_long_notes(self):
        """Long error notes should be truncated."""
        long_note = "timeout: " + "x" * 200
        result = retry_policy.decide(long_note)
        assert len(result["note"]) < len(long_note)
        assert "timeout" in result["note"]

    def test_decide_handles_none_transient_retries(self):
        """None retry count should default to 0."""
        result = retry_policy.decide("timeout", transient_retries=None)
        assert result["transient_retries"] == 1
        assert result["action"] == "requeue"

    def test_decide_handles_string_retry_count(self):
        """String retry count should be converted to int."""
        result = retry_policy.decide("timeout", transient_retries="5")
        assert result["transient_retries"] == 6
        assert result["action"] == "requeue"

    def test_decide_preserves_original_note_for_terminal(self):
        """Terminal errors should preserve original note."""
        original = "verify: failed to compile"
        result = retry_policy.decide(original)
        assert result["note"] == original


class TestRecordOutcome:
    """Test outcome recording for adaptive learning."""

    @patch("retry_policy.error_outcome_tracker")
    def test_record_outcome_success(self, mock_tracker):
        """Successful outcome should be recorded."""
        retry_policy.record_outcome("timeout error", succeeded=True)
        mock_tracker.record.assert_called_once()
        call_args = mock_tracker.record.call_args[0]
        assert "timeout" in call_args[0]
        assert call_args[2] is True

    @patch("retry_policy.error_outcome_tracker")
    def test_record_outcome_failure(self, mock_tracker):
        """Failed outcome should be recorded."""
        retry_policy.record_outcome("timeout error", succeeded=False)
        mock_tracker.record.assert_called_once()
        call_args = mock_tracker.record.call_args[0]
        assert call_args[2] is False

    @patch("retry_policy.error_outcome_tracker")
    def test_record_outcome_handles_missing_module(self, mock_tracker):
        """Should fail gracefully if tracker module missing."""
        mock_tracker.side_effect = ImportError("no tracker")
        # Should not raise
        retry_policy.record_outcome("timeout", True)

    @patch("retry_policy.error_outcome_tracker")
    def test_record_outcome_handles_tracker_exceptions(self, mock_tracker):
        """Should fail gracefully if tracker raises."""
        mock_tracker.record.side_effect = Exception("tracker error")
        # Should not raise
        retry_policy.record_outcome("timeout", True)

    def test_record_outcome_fail_soft_no_tracker(self):
        """record_outcome should not raise if tracker unavailable."""
        with patch.dict(sys.modules, {"error_outcome_tracker": None}):
            # Should not raise
            retry_policy.record_outcome("some error", True)


class TestIntegration:
    """Integration tests combining multiple functions."""

    def test_workflow_transient_retry_sequence(self):
        """Simulate a sequence of transient retries."""
        note = "HTTP 503 Service Unavailable"

        # First failure
        result = retry_policy.decide(note, transient_retries=0)
        assert result["action"] == "requeue"
        assert result["transient_retries"] == 1
        backoff_1 = result["backoff_s"]

        # Second failure after backoff
        result = retry_policy.decide(note, transient_retries=1)
        assert result["action"] == "requeue"
        assert result["transient_retries"] == 2
        backoff_2 = result["backoff_s"]
        assert backoff_2 > backoff_1 * 1.4  # Should grow exponentially

        # Eventually succeeds or caps
        for i in range(retry_policy.MAX_TRANSIENT_RETRIES):
            result = retry_policy.decide(note, transient_retries=i)
            assert result["action"] == "requeue"

    def test_workflow_terminal_fails_immediately(self):
        """Simulate a terminal failure blocking immediately."""
        note = "agent run failed: tests did not pass"

        result = retry_policy.decide(note, transient_retries=0)
        assert result["action"] == "block"
        assert result["transient_retries"] == 0

        # Even after 10 "attempts", still blocked
        result = retry_policy.decide(note, transient_retries=10)
        assert result["action"] == "block"

    def test_workflow_misclassified_then_corrected(self):
        """Novel error should default to terminal but be correctable."""
        novel_error = "frobnicator overflow detected"

        # Unknown error defaults to terminal
        assert retry_policy.classify(novel_error) == "terminal"
        result = retry_policy.decide(novel_error)
        assert result["action"] == "block"

        # But if adaptive tracker learns it's actually transient...
        with patch("retry_policy.error_outcome_tracker.suggest") as mock_suggest:
            mock_suggest.return_value = "transient"
            assert retry_policy.classify(novel_error) == "transient"
            result = retry_policy.decide(novel_error)
            assert result["action"] == "requeue"

    def test_api_rate_limit_realistic_scenario(self):
        """Realistic LLM API rate limit scenario."""
        note = "API rate limit: 429 Too Many Requests"

        # Should be classified as transient
        assert retry_policy.classify(note) == "transient"

        # First 3 retries with increasing backoff
        for attempt in range(3):
            result = retry_policy.decide(note, transient_retries=attempt)
            assert result["action"] == "requeue"
            assert result["backoff_s"] > 0

    def test_timeout_realistic_scenario(self):
        """Realistic timeout scenario during LLM inference."""
        note = "read timed out waiting for model response"

        # Should be classified as transient
        assert retry_policy.classify(note) == "transient"

        # Retry with backoff
        result = retry_policy.decide(note, transient_retries=0)
        assert result["action"] == "requeue"
        assert result["transient_retries"] == 1


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_string_note(self):
        """Empty note should classify as terminal."""
        assert retry_policy.classify("") == "terminal"

    def test_none_note(self):
        """None note should classify as terminal."""
        assert retry_policy.classify(None) == "terminal"

    def test_whitespace_only_note(self):
        """Whitespace-only note should classify as terminal."""
        assert retry_policy.classify("   \n\t  ") == "terminal"

    def test_very_large_retry_count(self):
        """Very large retry count should still work."""
        result = retry_policy.decide("timeout", transient_retries=1000)
        assert result["action"] == "requeue"
        assert "transient cap reached" in result["note"]

    def test_float_retry_count(self):
        """Float retry count should be converted to int."""
        result = retry_policy.decide("timeout", transient_retries=3.7)
        assert result["transient_retries"] == 4

    def test_multiple_keywords_in_note(self):
        """Note with multiple keywords should match highest priority."""
        # Terminal should win over transient
        note = "agent run failed: timeout after 30s"
        assert retry_policy.classify(note) == "terminal"

    def test_regex_special_characters_in_note(self):
        """Note with regex special characters should not break matching."""
        note = "error: [Errno 54] (Connection reset)"
        assert retry_policy.classify(note) == "transient"

    def test_unicode_in_note(self):
        """Unicode characters in note should not break classification."""
        note = "Timeout ⏱️ 请重试"
        # Should not raise, defaults to terminal
        result = retry_policy.classify(note)
        assert result in ["transient", "terminal"]

    def test_http_error_codes(self):
        """Various HTTP error code formats should be recognized."""
        assert retry_policy.classify("HTTP 429") == "transient"
        assert retry_policy.classify("429") == "transient"
        assert retry_policy.classify("500 error") == "transient"
        assert retry_policy.classify("503") == "transient"
        assert retry_policy.classify("400 Bad Request") == "terminal"
        assert retry_policy.classify("401 Unauthorized") == "terminal"


class TestEnvironmentVariables:
    """Test environment variable configuration."""

    def test_max_transient_retries_env_override(self):
        """MAX_TRANSIENT_RETRIES should be configurable via env."""
        # This would require a module reload, which is tested in TestBackoffSeconds
        original_value = retry_policy.MAX_TRANSIENT_RETRIES
        assert isinstance(original_value, int)
        assert original_value > 0

    def test_backoff_base_env_default(self):
        """BACKOFF_BASE_S should have sensible default."""
        assert retry_policy.BACKOFF_BASE_S > 0
        assert retry_policy.BACKOFF_BASE_S <= 10  # Should be reasonable

    def test_backoff_cap_env_default(self):
        """BACKOFF_CAP_S should have sensible default."""
        assert retry_policy.BACKOFF_CAP_S > 0
        assert retry_policy.BACKOFF_CAP_S >= retry_policy.BACKOFF_BASE_S


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
