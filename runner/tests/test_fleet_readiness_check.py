#!/usr/bin/env python3
"""The readiness check decides whether an autonomous fleet turns itself back on.

Two properties matter more than the probing itself:

  1. It fails CLOSED. Every other guard in this tree fails open, because
     blocking work on a guard's own bug is worse than the drift. Here
     "allowing" means releasing a 20-lane autonomous fleet, and the cost of a
     wrong yes is a queue full of plausible, unverifiable commits — which is
     precisely what the 2026-08-24 incident consisted of.

  2. Reachable is not capable. A weak local model answers happily and will
     produce a commit; the 2026-08-24 canary produced a syntactically perfect
     commit whose content was the prompt pasted into the README. Local models
     must not count toward readiness, because the QA and judge stages route to
     the same providers as the coder — when only weak models are up, the
     drafting and the checking are degraded together.
"""
import io
import os
import sys
import unittest
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "tools"))
sys.path.insert(0, os.path.dirname(_HERE))

import fleet_readiness_check as frc  # noqa: E402


def _probes(**states):
    """Replace the probe table. Values are (state, detail)."""
    table = {name: (lambda r=states.get(name, (None, "unset")): r)
             for name in frc.CAPABLE}
    return mock.patch.object(frc, "PROBES", table)


class CapabilityPolicyTest(unittest.TestCase):
    def test_local_is_not_a_capable_provider(self):
        # The whole point: ollama being up must not read as "fleet is ready".
        self.assertNotIn("local", frc.CAPABLE)
        self.assertNotIn("ollama", frc.CAPABLE)

    def test_the_capable_set_is_the_hosted_vendors(self):
        self.assertEqual(set(frc.CAPABLE),
                         {"claude", "openai", "google", "deepseek", "xai"})


class VerdictTest(unittest.TestCase):
    def setUp(self):
        self.out = io.StringIO()

    def test_all_dead_is_not_ready(self):
        with _probes(claude=(False, "weekly limit"), openai=(False, "no credits"),
                     google=(False, "depleted"), deepseek=(False, "balance"),
                     xai=(False, "spend limit")):
            ready, _results = frc.check(self.out)
        self.assertFalse(ready)

    def test_one_live_provider_is_enough(self):
        with _probes(claude=(False, "weekly limit"), openai=(True, "ok"),
                     google=(False, "depleted"), deepseek=(None, "no key"),
                     xai=(False, "spend")):
            ready, _results = frc.check(self.out)
        self.assertTrue(ready)

    def test_a_missing_key_is_not_a_live_provider(self):
        # SKIP must never be mistaken for LIVE — an unconfigured vendor tells us
        # nothing about whether work can be done.
        with _probes(**{n: (None, "no key") for n in frc.CAPABLE}):
            ready, _results = frc.check(self.out)
        self.assertFalse(ready)

    def test_a_probe_that_raises_is_not_a_yes(self):
        def boom():
            raise RuntimeError("network stack on fire")
        table = {n: boom for n in frc.CAPABLE}
        with mock.patch.object(frc, "PROBES", table):
            ready, results = frc.check(self.out)
        self.assertFalse(ready)
        self.assertTrue(all(s is None for s, _d in results.values()))

    def test_the_reason_reaches_the_operator(self):
        with _probes(claude=(False, 'exhausted: "weekly limit"'),
                     openai=(None, "no key"), google=(None, "no key"),
                     deepseek=(None, "no key"), xai=(None, "no key")):
            frc.check(self.out)
        self.assertIn("weekly limit", self.out.getvalue())


class ExitCodeTest(unittest.TestCase):
    """0 ready / 1 not ready / 2 undetermined — and 2 must never resume."""

    def test_ready_returns_zero(self):
        with mock.patch.object(frc, "check", lambda *a, **k: (True, {"openai": (True, "ok")})):
            self.assertEqual(frc.main([]), 0)

    def test_not_ready_returns_one(self):
        with mock.patch.object(frc, "check", lambda *a, **k: (False, {})):
            self.assertEqual(frc.main([]), 1)

    def test_a_broken_check_returns_two_and_does_not_resume(self):
        def boom(*a, **k):
            raise RuntimeError("db unreachable")
        resumed = []
        with mock.patch.object(frc, "check", boom), \
             mock.patch.object(frc, "resume", lambda *a, **k: resumed.append(1)):
            self.assertEqual(frc.main(["--resume"]), 2)
        self.assertEqual(resumed, [], "a failed check must never lift the halt")

    def test_not_ready_does_not_resume_even_when_asked(self):
        resumed = []
        with mock.patch.object(frc, "check", lambda *a, **k: (False, {})), \
             mock.patch.object(frc, "resume", lambda *a, **k: resumed.append(1)):
            frc.main(["--resume"])
        self.assertEqual(resumed, [])

    def test_ready_without_the_flag_does_not_resume(self):
        # Checking must be safe to run at any time; only --resume acts.
        resumed = []
        with mock.patch.object(frc, "check", lambda *a, **k: (True, {"openai": (True, "ok")})), \
             mock.patch.object(frc, "resume", lambda *a, **k: resumed.append(1)):
            frc.main([])
        self.assertEqual(resumed, [])

    def test_ready_with_the_flag_resumes(self):
        resumed = []

        def fake_resume(*a, **k):
            resumed.append(1)
            return 0
        with mock.patch.object(frc, "check", lambda *a, **k: (True, {"openai": (True, "ok")})), \
             mock.patch.object(frc, "_promote", lambda *a, **k: None), \
             mock.patch.object(frc, "resume", fake_resume):
            self.assertEqual(frc.main(["--resume"]), 0)
        self.assertEqual(resumed, [1])


class DeadModelIdGateTest(unittest.TestCase):
    """A funded account is not sufficient. The config has to be sound too.

    On 2026-08-24 the default agentic coder was `gemini-2.5-pro`, which Google
    had retired. Resuming on money alone would have routed straight back to a
    404 that reads like any other provider error.
    """

    def _ready(self):
        return mock.patch.object(
            frc, "check", lambda *a, **k: (True, {"openai": (True, "ok")}))

    def test_a_dead_id_blocks_the_resume(self):
        resumed = []
        with self._ready(), \
             mock.patch.object(frc, "dead_model_ids",
                               lambda *a, **k: ["gemini-2.5-pro"]), \
             mock.patch.object(frc, "resume", lambda *a, **k: resumed.append(1)):
            self.assertEqual(frc.main(["--resume"]), 1)
        self.assertEqual(resumed, [], "resumed onto a retired model id")

    def test_a_clean_config_resumes(self):
        resumed = []

        def fake_resume(*a, **k):
            resumed.append(1)
            return 0
        with self._ready(), \
             mock.patch.object(frc, "dead_model_ids", lambda *a, **k: []), \
             mock.patch.object(frc, "_promote", lambda *a, **k: None), \
             mock.patch.object(frc, "resume", fake_resume):
            self.assertEqual(frc.main(["--resume"]), 0)
        self.assertEqual(resumed, [1])

    def test_the_dead_ids_are_named(self):
        out = io.StringIO()
        with self._ready(), \
             mock.patch.object(frc, "dead_model_ids",
                               lambda *a, **k: ["gemini-4.0-flash"]), \
             mock.patch("sys.stdout", out):
            frc.main([])
        self.assertIn("gemini-4.0-flash", out.getvalue())

    def test_an_unavailable_audit_does_not_strand_the_fleet(self):
        # This gate does NOT fail closed, unlike the provider probe. A dead id
        # degrades one route; a halt that cannot lift stops everything, and the
        # audit needs a vendor catalogue it may not be able to reach.
        broken = mock.Mock()
        broken.audit = mock.Mock(side_effect=RuntimeError("catalogue down"))
        with mock.patch.dict(sys.modules, {"model_id_audit": broken}):
            self.assertEqual(frc.dead_model_ids(io.StringIO()), [])


class BannerWiringTest(unittest.TestCase):
    """The probe's verdicts come from provider_banner, so the two must agree."""

    def test_real_banners_classify_as_exhausted(self):
        import provider_banner as pb
        for blob in (
            "Error code: 429 - {'message': 'Your prepayment credits are depleted.'}",
            "Error code: 429 - {'type': 'insufficient_quota'}",
            "Error code: 403 - 'used all available credits or reached its monthly "
            "spending limit'",
            "Error code: 402 - {'message': 'Insufficient Balance'}",
            "You've hit your weekly limit - resets Aug 25 at 11pm",
        ):
            self.assertEqual(pb.classify(blob), "exhausted", blob[:60])

    def test_a_healthy_response_is_not_a_banner(self):
        import provider_banner as pb
        self.assertIsNone(pb.classify('{"choices":[{"message":{"content":"ok"}}]}'))


if __name__ == "__main__":
    unittest.main(verbosity=2)
