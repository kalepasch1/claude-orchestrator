"""A provider that is out of credits must leave the rotation, whatever SDK reported it.

OBSERVED FAILURE. A canary task died on:

    litellm.APIError: APIError: XaiException - Error code: 403 -
    {'code': 'permission-denied', 'error': 'Your team … has either used all available
     credits or reached its monthly spending limit.'}
    Retrying in 4.0 seconds...   Retrying in 8.0 seconds...

model_gateway demoted a provider only when the exception was a urllib.error.HTTPError
with code 401/403. litellm.APIError is not an HTTPError, so isinstance() was False, xai
stayed in the rotation, and every later task routed to it again — paying litellm's own
internal backoff each time for a condition that cannot resolve until someone buys credits.

Being out of credits is a terminal fact about the ACCOUNT, not a flaky call. The fix
classifies the error TEXT (error_taxonomy already gets this right) instead of the
exception class, so it covers every SDK the fleet routes through.
"""
import os
import sys
import types
import unittest
import urllib.error
from unittest import mock

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DIR)

import error_taxonomy  # noqa: E402
import model_gateway as mg  # noqa: E402

XAI_CREDITS = (
    "litellm.APIError: APIError: XaiException - Error code: 403 - {'code': "
    "'permission-denied', 'error': 'Your team b4fa25c7-b07a-4087-99ea-53375a0cecde has "
    "either used all available credits or reached its monthly spending limit. To continue "
    "making API requests, please purchase more credits or raise your spending limit.'}"
)


class LiteLLMAPIError(Exception):
    """Stand-in for litellm.APIError — deliberately NOT an HTTPError."""


class TaxonomyAgreesTest(unittest.TestCase):
    """The classifier was always right; the gateway just never asked it."""

    def test_credit_exhaustion_is_classified_as_exhaustion(self):
        self.assertEqual(error_taxonomy.classify(XAI_CREDITS)["error_class"], "exhaustion")

    def test_remediation_is_to_rotate(self):
        self.assertEqual(error_taxonomy.classify(XAI_CREDITS)["remediation"],
                         "rotate_account")

    def test_a_plain_403_is_a_permission_error(self):
        self.assertEqual(
            error_taxonomy.classify("Error code: 403 - forbidden")["error_class"],
            "permission_error")

    def test_an_ordinary_failure_is_neither(self):
        cls = error_taxonomy.classify("ConnectionResetError: [Errno 54] reset by peer")
        self.assertNotIn(cls["error_class"], ("exhaustion", "permission_error"))


class DemoteTest(unittest.TestCase):
    """complete() must demote on the classified condition, then fall through."""

    def _complete(self, raised):
        sla = types.SimpleNamespace(demote=mock.MagicMock(),
                                    record_probe_success=mock.MagicMock())

        def _boom(provider, model, prompt, **kw):
            raise raised

        with mock.patch.dict(sys.modules, {"provider_failover_sla": sla}), \
             mock.patch.object(mg, "_call_provider", side_effect=_boom), \
             mock.patch.object(mg, "_fallbacks", return_value=[]), \
             mock.patch.object(mg, "_provider_allowed", return_value=True), \
             mock.patch.object(mg, "_record_operation"), \
             mock.patch.object(mg, "_learned_route", return_value=None):
            res = mg.complete("xai", "grok-3-mini-fast", "hello", fallback=False,
                              record_op=False)
        return res, sla

    def test_litellm_credit_exhaustion_demotes_the_provider(self):
        _, sla = self._complete(LiteLLMAPIError(XAI_CREDITS))
        sla.demote.assert_called_once()
        self.assertEqual(sla.demote.call_args[0][0], "xai")

    def test_the_demote_reason_names_the_condition(self):
        _, sla = self._complete(LiteLLMAPIError(XAI_CREDITS))
        self.assertIn("exhaustion", sla.demote.call_args[0][1])

    def test_urllib_403_still_demotes_as_before(self):
        err = urllib.error.HTTPError("http://x", 403, "Forbidden", {}, None)
        _, sla = self._complete(err)
        sla.demote.assert_called_once()
        self.assertEqual(sla.demote.call_args[0][1], "auth-403")

    def test_urllib_401_still_demotes_as_before(self):
        err = urllib.error.HTTPError("http://x", 401, "Unauthorized", {}, None)
        _, sla = self._complete(err)
        self.assertEqual(sla.demote.call_args[0][1], "auth-401")

    def test_an_ordinary_error_does_not_demote(self):
        # a flaky call must not evict a healthy provider from the rotation
        _, sla = self._complete(ConnectionResetError(54, "reset by peer"))
        sla.demote.assert_not_called()

    def test_a_timeout_does_not_demote(self):
        _, sla = self._complete(TimeoutError("timed out"))
        sla.demote.assert_not_called()

    def test_the_call_still_returns_an_error_result_rather_than_raising(self):
        res, _ = self._complete(LiteLLMAPIError(XAI_CREDITS))
        self.assertIn("error", res)
        self.assertEqual(res["text"], "")

    def test_an_unavailable_sla_module_does_not_break_the_call(self):
        def _boom(provider, model, prompt, **kw):
            raise LiteLLMAPIError(XAI_CREDITS)

        with mock.patch.dict(sys.modules, {"provider_failover_sla": None}), \
             mock.patch.object(mg, "_call_provider", side_effect=_boom), \
             mock.patch.object(mg, "_fallbacks", return_value=[]), \
             mock.patch.object(mg, "_provider_allowed", return_value=True), \
             mock.patch.object(mg, "_record_operation"), \
             mock.patch.object(mg, "_learned_route", return_value=None):
            res = mg.complete("xai", "grok", "hi", fallback=False, record_op=False)
        self.assertIn("error", res)

    def test_a_broken_taxonomy_does_not_break_the_call(self):
        sla = types.SimpleNamespace(demote=mock.MagicMock(),
                                    record_probe_success=mock.MagicMock())

        def _boom(provider, model, prompt, **kw):
            raise LiteLLMAPIError(XAI_CREDITS)

        broken = types.SimpleNamespace(classify=mock.MagicMock(side_effect=RuntimeError))
        with mock.patch.dict(sys.modules, {"provider_failover_sla": sla,
                                           "error_taxonomy": broken}), \
             mock.patch.object(mg, "_call_provider", side_effect=_boom), \
             mock.patch.object(mg, "_fallbacks", return_value=[]), \
             mock.patch.object(mg, "_provider_allowed", return_value=True), \
             mock.patch.object(mg, "_record_operation"), \
             mock.patch.object(mg, "_learned_route", return_value=None):
            res = mg.complete("xai", "grok", "hi", fallback=False, record_op=False)
        self.assertIn("error", res)
        sla.demote.assert_not_called()


if __name__ == "__main__":
    unittest.main()
