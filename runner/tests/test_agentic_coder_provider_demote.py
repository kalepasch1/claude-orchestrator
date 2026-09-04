"""agentic_coders.record_run_failure — a dead account must demote its provider.

The failure this pins down: `_provider_healthy()` gates coder SELECTION on the
provider_failover_sla demote registry, but nothing on the agentic-coder path ever
WROTE to that registry. aider/codex/gemini talk to the provider themselves, so the
403 never reaches model_gateway (the only writer), the gate re-checks an un-updated
registry, picks the same dead provider, and pays aider's ~60s retry window again.
improve-competitive-scanner-slice-5 burned four attempts on byte-identical output.
"""
import unittest
from unittest import mock

import agentic_coders

_XAI_403 = (
    "litellm.APIError: APIError: XaiException - Error code: 403 - {'code': "
    "'permission-denied', 'error': 'Your team b4fa25c7 has either used all available "
    "credits or reached its monthly spending limit. To continue making API requests, "
    "please purchase more credits or raise your spending limit.'}\n"
    "Retrying in 4.0 seconds...\nRetrying in 8.0 seconds...\nexhausted retries"
)


class RecordRunFailureTest(unittest.TestCase):
    def setUp(self):
        self.demote = mock.Mock()
        patcher = mock.patch.dict(
            "sys.modules",
            {"provider_failover_sla": mock.Mock(demote=self.demote, is_demoted=lambda p: False)},
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_credit_exhaustion_run_demotes_the_provider(self):
        coder = {"name": "aider-xai", "cmd": "aider --model xai/grok-3-mini-fast"}
        reason = agentic_coders.record_run_failure(coder, _XAI_403, "", returncode=1)
        assert reason, "credit exhaustion must produce a demote reason"
        self.demote.assert_called_once()
        assert self.demote.call_args[0][0] == "xai"

    def test_a_successful_run_never_demotes(self):
        # rc=0 with the banner still on stdout (aider recovered) is not a dead account
        coder = {"name": "aider-xai", "cmd": "aider --model xai/grok-3-mini-fast"}
        assert agentic_coders.record_run_failure(coder, _XAI_403, "", returncode=0) == ""
        self.demote.assert_not_called()

    def test_an_ordinary_work_failure_never_demotes(self):
        # demoting on test failures would empty the coder pool over normal red builds
        coder = {"name": "aider-xai", "cmd": "aider --model xai/grok-3-mini-fast"}
        for blob in ("FAILED tests/test_thing.py::test_x - AssertionError",
                     "aider: no changes made to the repository",
                     "ModuleNotFoundError: No module named 'foo'"):
            with self.subTest(blob=blob):
                assert agentic_coders.record_run_failure(coder, blob, "", returncode=1) == ""
        self.demote.assert_not_called()

    def test_an_undeterminable_provider_never_demotes(self):
        # coder_provider() fails open; a guess here would remove a working coder
        coder = {"name": "mystery", "cmd": "some-tool --go"}
        assert agentic_coders.record_run_failure(coder, _XAI_403, "", returncode=1) == ""
        self.demote.assert_not_called()

    def test_empty_output_never_demotes(self):
        coder = {"name": "aider-xai", "cmd": "aider --model xai/grok-3-mini-fast"}
        assert agentic_coders.record_run_failure(coder, "", "", returncode=1) == ""
        self.demote.assert_not_called()

    def test_it_reads_stderr_too(self):
        coder = {"name": "aider-xai", "cmd": "aider --model xai/grok-3-mini-fast"}
        assert agentic_coders.record_run_failure(coder, "", _XAI_403, returncode=1)

    def test_it_is_fail_soft(self):
        # a demote registry that raises must not wedge the lane's return path
        coder = {"name": "aider-xai", "cmd": "aider --model xai/grok-3-mini-fast"}
        with mock.patch.dict("sys.modules",
                             {"provider_failover_sla": mock.Mock(
                                 demote=mock.Mock(side_effect=RuntimeError("registry down")))}):
            assert agentic_coders.record_run_failure(coder, _XAI_403, "", returncode=1) == ""

    def test_bad_inputs_never_raise(self):
        for args in ((None, None, None, None), ({}, 5, object(), "x"), ("", "", "", 1)):
            with self.subTest(args=args):
                assert isinstance(agentic_coders.record_run_failure(*args), str)


if __name__ == "__main__":
    unittest.main()
