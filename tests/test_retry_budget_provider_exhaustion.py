#!/usr/bin/env python3
"""retry_budget provider-exhaustion regressions (canary-gemini-25).

Why this file exists: three canary tasks died BLOCKED with
`retry-budget: skipping retry (reached budget cap (4))` without a single coder
having run.  Every one of their four "attempts" was an xai 403
permission-denied "used all available credits / reached its monthly spending
limit" — a billing condition at the API boundary.  retry_budget classified it as
"other", charged it to the budget, and the fourth one tripped the cap.

retry_policy already treats that string family as transient
(tests/test_retry_policy_spend_limit.py).  retry_budget must agree.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "runner"))
import retry_budget

XAI_403 = ("litellm.APIError: APIError: XaiException - Error code: 403 - "
           "{'code': 'permission-denied', 'error': 'Your team b4fa25c7 has either "
           "used all available credits or reached its monthly spending limit.'}")

TASK = {"slug": "canary-gemini-25-debug-and-resolve-retry-budget-issue",
        "id": "74c23abb", "force_coder": "xai:xai/grok-3-mini-fast"}


def test_credit_exhaustion_classifies_as_provider_exhausted():
    assert retry_budget._classify_error(XAI_403) == "provider_exhausted"


def test_spend_limit_variants_classify_as_provider_exhausted():
    for note in ("monthly spending limit reached", "out of credits",
                 "insufficient credits for request", "quota exceeded for model",
                 "402 Payment Required", "billing account disabled"):
        assert retry_budget._classify_error(note) == "provider_exhausted", note


def test_genuine_transients_keep_their_own_class():
    assert retry_budget._classify_error("429 too many requests") == "rate_limit"
    assert retry_budget._classify_error("deadline exceeded") == "timeout"
    assert retry_budget._classify_error("AssertionError: expected 3") == "assertion"


def test_exhaustion_does_not_consume_the_budget_at_the_cap():
    """The regression itself: at attempt >= cap, exhaustion still retries."""
    out = retry_budget.should_retry(TASK, attempt=4, last_error=XAI_403)
    assert out["retry"] is True
    assert "budget cap" not in out["reason"]
    assert "exhausted" in out["reason"]


def test_exhaustion_recommends_a_different_provider():
    out = retry_budget.should_retry(TASK, attempt=4, last_error=XAI_403)
    rec = out["recommended_model"]
    assert rec, "expected a rotation target"
    assert not rec.lower().startswith("xai"), rec


def test_real_failures_still_hit_the_cap():
    """The cap must keep working for errors that did reach the coder."""
    out = retry_budget.should_retry(
        {"slug": "some-real-task", "id": "x"}, attempt=99,
        last_error="agent run failed: syntax error in module")
    assert out["retry"] is False
    assert "budget cap" in out["reason"]


def test_rotation_target_is_none_when_chain_matches_current_provider(monkeypatch):
    monkeypatch.setenv("ORCH_PROVIDER_ROTATION", "xai:xai/grok-3-mini-fast")
    assert retry_budget._rotation_target(TASK) is None


def test_rotation_target_is_fail_soft_on_garbage():
    assert retry_budget._rotation_target(None) is None
    assert retry_budget._rotation_target({}) is not None  # no current provider -> first


def test_record_attempt_does_not_charge_provider_exhaustion():
    slug = "budgettest-prefix-a"
    before = dict(retry_budget._instance._inmemory)
    retry_budget.record_attempt(slug, 1, "xai", False, "provider_exhausted")
    prefix = retry_budget._slug_prefix(slug)
    assert prefix not in retry_budget._instance._inmemory or \
        retry_budget._instance._inmemory[prefix] == before.get(prefix, {})


def test_record_attempt_still_charges_real_failures():
    slug = "budgettest-prefix-b"
    retry_budget.record_attempt(slug, 1, "claude", False, "assertion")
    prefix = retry_budget._slug_prefix(slug)
    assert retry_budget._instance._inmemory[prefix][1]["total"] == 1
    assert retry_budget._instance._inmemory[prefix][1]["success"] == 0
