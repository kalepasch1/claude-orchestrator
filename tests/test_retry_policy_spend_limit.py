#!/usr/bin/env python3
"""Provider spend-limit classification regressions (canary-codex-4).

The original canary died BLOCKED on an xai 403 permission-denied
"used all available credits / monthly spending limit" — a provider-level
condition recoverable via rotation or the monthly reset, which must classify
as transient (like "budget cap reached"), not terminal.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "runner"))
import retry_policy

XAI_403 = ("litellm.APIError: XaiException - Error code: 403 - {'code': "
           "'permission-denied', 'error': 'Your team has either used all available "
           "credits or reached its monthly spending limit.'}")


def test_xai_credit_exhaustion_is_transient():
    assert retry_policy.classify(XAI_403) == "transient"


def test_spend_limit_variants_are_transient():
    for note in ("monthly spending limit reached", "out of credits",
                 "insufficient credits for request", "quota exceeded for model"):
        assert retry_policy.classify(note) == "transient", note


def test_spend_limit_decision_requeues():
    result = retry_policy.decide(XAI_403, transient_retries=0)
    assert result["action"] == "requeue"
    assert result["transient_retries"] == 1


def test_genuine_work_failures_stay_terminal():
    for note in ("agent run failed", "judge: rejected", "legal review required"):
        assert retry_policy.classify(note) == "terminal", note
