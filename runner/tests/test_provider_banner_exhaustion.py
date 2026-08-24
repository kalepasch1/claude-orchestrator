#!/usr/bin/env python3
"""Real provider banners captured live on 2026-08-24, when the fleet was
producing empty commits and nobody could see why.

Every string below was returned by the vendor's own API during that outage.
They are verbatim, not paraphrased, and that is the whole point of the file:
a paraphrase would have passed the OLD code too. The failure only reproduces
with the exact shape litellm wraps around the message.

What was broken
---------------
litellm names its exception classes after the HTTP status it wrapped. Google
returns 429 when an account is out of prepaid credit, so a terminal
"your balance is zero" arrived as:

    litellm.RateLimitError: VertexAIException - Error code: 429 - ... your
    prepayment credits are depleted ...

`provider_banner.classify` lowercased that whole string and looked for
"ratelimit" — which is present, in the WRAPPER, not the message. Verdict:
transient. So the provider was never demoted, stayed selectable forever, and
every routed task spent ~60s in aider's retry loop before returning no edits.
The runner then committed aider's own scratch files as the work product.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import provider_banner as pb  # noqa: E402
import error_taxonomy as et   # noqa: E402

# --- captured verbatim, 2026-08-24 -----------------------------------------
GEMINI_CREDITS = (
    "litellm.RateLimitError: VertexAIException - Error code: 429 - {'error': "
    "{'code': 429, 'message': 'Your prepayment credits are depleted. Please go "
    "to AI Studio at https://ai.studio/projects to top up.', "
    "'status': 'RESOURCE_EXHAUSTED'}}")
OPENAI_CREDITS = (
    "litellm.RateLimitError: OpenAIException - Error code: 429 - {'error': "
    "{'message': 'You have no credits remaining. Add credits to continue using "
    "the API at https://platform.openai.com/settings/organization/billing/.', "
    "'type': 'insufficient_quota', 'code': 'credit_balance_exhausted'}}")
XAI_CREDITS = (
    "litellm.APIError: XaiException - Error code: 403 - {'code': "
    "'permission-denied', 'error': 'Your team has either used all available "
    "credits or reached its monthly spending limit.'}")
GEMINI_MODEL_GONE = (
    "litellm.NotFoundError: VertexAIException - Error code: 404 - {'error': "
    "{'code': 404, 'message': 'This model models/gemini-2.5-pro is no longer "
    "available to new users. Please update your code to use "
    "models/gemini-3.1-pro-preview for the latest features and "
    "improvements.', 'status': 'NOT_FOUND'}}")
GEMINI_MODEL_MISSING = (
    "litellm.NotFoundError: Error code: 404 - models/gemini-4.0-flash is not "
    "found for API version v1beta, or is not supported for generateContent.")
CLAUDE_WEEKLY = (
    "You've hit your weekly limit · resets Aug 25 at 11pm "
    "(America/New_York)")
DEEPSEEK_BALANCE = (
    "Error code: 402 - {'error': {'message': 'Insufficient Balance', "
    "'type': 'unknown_error'}}")

# A genuine transient throttle. This must NOT read as terminal: demoting a
# vendor that is merely busy costs the fleet a working provider, which is a
# worse outage than the one this file exists to prevent.
TRUE_RATE_LIMIT = (
    "litellm.RateLimitError: Error code: 429 - rate limit exceeded, please "
    "retry after 20s")
NORMAL_OUTPUT = "Applied edit to README.md. Tokens: 2.0k sent, 23 received."


class TestTerminalVersusTransient(unittest.TestCase):
    """The distinction the whole outage turned on."""

    def test_gemini_credit_depletion_is_terminal(self):
        # THE REGRESSION: wrapped in RateLimitError, but no amount of waiting
        # puts money back in the account.
        self.assertEqual(pb.classify(GEMINI_CREDITS), "exhausted")

    def test_openai_credit_depletion_is_terminal(self):
        self.assertEqual(pb.classify(OPENAI_CREDITS), "exhausted")

    def test_xai_credit_depletion_is_terminal(self):
        self.assertEqual(pb.classify(XAI_CREDITS), "exhausted")

    def test_deepseek_insufficient_balance_is_terminal(self):
        self.assertEqual(pb.classify(DEEPSEEK_BALANCE), "exhausted")

    def test_claude_weekly_limit_is_terminal(self):
        self.assertEqual(pb.classify(CLAUDE_WEEKLY), "exhausted")

    def test_true_rate_limit_stays_transient(self):
        self.assertEqual(pb.classify(TRUE_RATE_LIMIT), "rate_limited")

    def test_normal_output_is_not_a_banner(self):
        self.assertIsNone(pb.classify(NORMAL_OUTPUT))


class TestRetiredModelIsItsOwnClass(unittest.TestCase):
    """A 404'd model id is neither a capacity problem nor a billing problem."""

    def test_retired_model_id(self):
        self.assertEqual(pb.classify(GEMINI_MODEL_GONE), "model_gone")

    def test_unknown_model_id(self):
        self.assertEqual(pb.classify(GEMINI_MODEL_MISSING), "model_gone")

    def test_not_reported_as_exhaustion(self):
        # Reporting this as exhaustion sends the operator to the billing page
        # to fix a config typo. The two need different answers.
        self.assertNotEqual(pb.classify(GEMINI_MODEL_GONE), "exhausted")


class TestRemediationActuallyChanges(unittest.TestCase):
    """A verdict only matters if it changes what the fleet does next."""

    def test_gemini_credits_rotate_rather_than_wait(self):
        got = et.classify(GEMINI_CREDITS)
        self.assertEqual(got["error_class"], "exhaustion")
        self.assertEqual(got["remediation"], "rotate_account")

    def test_openai_credits_rotate_rather_than_wait(self):
        self.assertEqual(
            et.classify(OPENAI_CREDITS)["remediation"], "rotate_account")

    def test_retired_model_repins(self):
        got = et.classify(GEMINI_MODEL_GONE)
        self.assertEqual(got["error_class"], "model_gone")
        self.assertEqual(got["remediation"], "repin_model")

    def test_true_rate_limit_still_waits(self):
        got = et.classify(TRUE_RATE_LIMIT)
        self.assertEqual(got["error_class"], "rate_limit")
        self.assertEqual(got["remediation"], "wait_and_retry")


class TestUnrelatedErrorsStillClassify(unittest.TestCase):
    """Guard against the new early-return swallowing everything else.

    The banner check runs before the local pattern list now, so a bug there
    would silently reclassify ordinary build and test failures.
    """

    def test_test_failure(self):
        self.assertEqual(
            et.classify("FAILED: test_thing assertion error")["error_class"],
            "test_failure")

    def test_merge_conflict(self):
        self.assertEqual(
            et.classify("CONFLICT (content): merge conflict in a.py")["error_class"],
            "merge_conflict")

    def test_import_error(self):
        self.assertEqual(
            et.classify("ModuleNotFoundError: No module named 'foo'")["error_class"],
            "import_error")


class TestWrapperStripping(unittest.TestCase):
    """The mechanism of the fix."""

    def test_wrapper_alone_is_not_evidence(self):
        # An exception class name with no corroborating message says nothing
        # about what the provider actually reported.
        self.assertIsNone(pb.classify("litellm.RateLimitError"))

    def test_status_code_survives_stripping(self):
        # "Error code: 429" is the provider speaking, and must still count.
        self.assertEqual(pb.classify("Error code: 429 - server busy"),
                         "rate_limited")

    def test_reason_names_the_matched_phrase(self):
        # An operator reading the log needs the phrase, not a regex.
        why = pb.reason(GEMINI_CREDITS)
        self.assertTrue(why and why.startswith("exhausted:"), why)


if __name__ == "__main__":
    unittest.main(verbosity=2)
