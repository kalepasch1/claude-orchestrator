#!/usr/bin/env python3
"""Deterministic retry_policy backoff/decide tests (canary-codex-35).

Reconstructs the prior unpushed test-hygiene patch: jitter-dependent
assertions are made deterministic by pinning random.random to 0.5 (jitter
factor exactly 1.0), instead of asserting against ±25% margins.
"""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "runner"))
import retry_policy


class TestClassify:
    def test_transient_signatures(self):
        for note in ("Connection reset by peer", "HTTP 503 Service Unavailable",
                     "rate-limit exceeded", "budget cap reached", "read timed out"):
            assert retry_policy.classify(note) == "transient", note

    def test_terminal_signatures(self):
        for note in ("agent run failed", "judge: rejected diff",
                     "legal review required", "no committable changes"):
            assert retry_policy.classify(note) == "terminal", note


class TestBackoffDeterministic:
    def test_exact_doubling_with_pinned_jitter(self):
        with patch("random.random", return_value=0.5):  # jitter factor exactly 1.0
            assert retry_policy.backoff_seconds(0) == retry_policy.BACKOFF_BASE_S
            assert retry_policy.backoff_seconds(1) == retry_policy.BACKOFF_BASE_S * 2
            assert retry_policy.backoff_seconds(2) == retry_policy.BACKOFF_BASE_S * 4

    def test_cap_with_pinned_jitter(self):
        with patch("random.random", return_value=0.5):
            assert retry_policy.backoff_seconds(50) == retry_policy.BACKOFF_CAP_S

    def test_jitter_bounds_at_extremes(self):
        base = min(retry_policy.BACKOFF_CAP_S, retry_policy.BACKOFF_BASE_S * 2)
        with patch("random.random", return_value=0.0):
            assert retry_policy.backoff_seconds(1) == round(base * 0.75, 1)
        with patch("random.random", return_value=1.0):
            assert retry_policy.backoff_seconds(1) == round(base * 1.25, 1)

    def test_negative_and_none_retries_clamp_to_zero(self):
        with patch("random.random", return_value=0.5):
            assert retry_policy.backoff_seconds(-3) == retry_policy.BACKOFF_BASE_S
            assert retry_policy.backoff_seconds(None) == retry_policy.BACKOFF_BASE_S


class TestDecide:
    def test_transient_under_cap_requeues_with_deterministic_backoff(self):
        with patch("random.random", return_value=0.5):
            result = retry_policy.decide("HTTP 503 Service Unavailable", transient_retries=0)
        assert result["action"] == "requeue"
        assert result["transient_retries"] == 1
        assert result["backoff_s"] == retry_policy.BACKOFF_BASE_S

    def test_transient_backoff_grows_between_attempts(self):
        with patch("random.random", return_value=0.5):
            first = retry_policy.decide("HTTP 503 Service Unavailable", transient_retries=0)
            second = retry_policy.decide("HTTP 503 Service Unavailable", transient_retries=1)
        assert second["backoff_s"] == first["backoff_s"] * 2

    def test_transient_at_cap_still_requeues_for_cooldown(self):
        result = retry_policy.decide("rate-limit", transient_retries=retry_policy.MAX_TRANSIENT_RETRIES)
        assert result["action"] == "requeue"
        assert result["backoff_s"] == retry_policy.BACKOFF_CAP_S

    def test_terminal_blocks_without_backoff(self):
        result = retry_policy.decide("agent run failed", transient_retries=0)
        assert result["action"] == "block"
        assert result["backoff_s"] == 0
