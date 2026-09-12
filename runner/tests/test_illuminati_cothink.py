#!/usr/bin/env python3
"""Illuminati co-think at ALL four build phases.

The proof line asks for mocked Illuminati responses attached at every phase, and
for an escalate verdict at any phase to create the RIGHT gate. Both are here,
plus the two failure modes that matter more than the happy path:

  - an OUTAGE must not halt the fleet, and must not pretend review happened;
  - an UNREADABLE verdict must not be treated as permission.
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import illuminati_cothink as ic  # noqa: E402


def fake_verdict(verdict, rationale="because", dimensions=None):
    return {"verdict": verdict, "rationale": rationale, "dimensions": dimensions or []}


class ReviewAtEveryPhaseTest(unittest.TestCase):
    """One integration, consumed at four points."""

    def test_all_four_phases_are_supported(self):
        self.assertEqual(ic.PHASES, ("intake", "planning", "build", "premerge"))

    def test_each_phase_attaches_a_verdict(self):
        for phase in ic.PHASES:
            with self.subTest(phase=phase), \
                 mock.patch.object(ic, "ILLUMINATI_URL", "http://illuminati.test"), \
                 mock.patch.object(ic, "_post", return_value=fake_verdict("proceed")) as post:
                v = ic.review(phase, {"objective": "ship a thing"})
                self.assertEqual(v["phase"], phase)
                self.assertEqual(v["verdict"], "proceed")
                self.assertFalse(v["degraded"])
                # the phase travels to Illuminati, not just back to us
                self.assertEqual(post.call_args[0][1]["phase"], phase)

    def test_unknown_phase_is_review_not_proceed(self):
        v = ic.review("deployment", {})
        self.assertEqual(v["verdict"], "review")


class VerdictParsingTest(unittest.TestCase):
    """An answer we cannot read is not permission."""

    def setUp(self):
        self.url = mock.patch.object(ic, "ILLUMINATI_URL", "http://illuminati.test")
        self.url.start()
        self.addCleanup(self.url.stop)

    def test_known_verdicts_pass_through(self):
        for verdict in ("proceed", "review", "escalate"):
            with self.subTest(verdict=verdict), \
                 mock.patch.object(ic, "_post", return_value=fake_verdict(verdict)):
                self.assertEqual(ic.review("planning", {})["verdict"], verdict)

    def test_casing_and_whitespace_tolerated(self):
        with mock.patch.object(ic, "_post", return_value={"verdict": "  ESCALATE "}):
            self.assertEqual(ic.review("planning", {})["verdict"], "escalate")

    def test_unknown_verdict_becomes_review(self):
        for junk in ("approved", "", None, 42):
            with self.subTest(junk=junk), \
                 mock.patch.object(ic, "_post", return_value={"verdict": junk}):
                self.assertEqual(ic.review("planning", {})["verdict"], "review")

    def test_non_dict_response_becomes_review(self):
        for junk in ("yes", [1, 2], None):
            with self.subTest(junk=junk), \
                 mock.patch.object(ic, "_post", return_value=junk):
                self.assertEqual(ic.review("build", {})["verdict"], "review")


class OutageTest(unittest.TestCase):
    """An outage degrades; it does not halt, and it does not hide."""

    def test_transport_error_proceeds_but_flags_degraded(self):
        with mock.patch.object(ic, "ILLUMINATI_URL", "http://illuminati.test"), \
             mock.patch.object(ic, "_post", side_effect=OSError("connection refused")):
            v = ic.review("build", {})
        self.assertEqual(v["verdict"], "proceed", "an outage must not halt every build")
        self.assertTrue(v["degraded"], "an outage must not look like a clean pass")
        self.assertIn("connection refused", v["rationale"])

    def test_unconfigured_url_degrades(self):
        with mock.patch.object(ic, "ILLUMINATI_URL", ""):
            v = ic.review("intake", {})
        self.assertTrue(v["degraded"])

    def test_disabled_flag_degrades(self):
        with mock.patch.object(ic, "ENABLED", False):
            v = ic.review("intake", {})
        self.assertTrue(v["degraded"])
        self.assertIn("disabled", v["rationale"])


class GateCreationTest(unittest.TestCase):
    """Escalate at any phase creates the RIGHT gate."""

    def setUp(self):
        self.url = mock.patch.object(ic, "ILLUMINATI_URL", "http://illuminati.test")
        self.url.start()
        self.addCleanup(self.url.stop)
        self.steer = mock.patch.object(ic, "_record_steering", return_value=True)
        self.steer.start()
        self.addCleanup(self.steer.stop)

    def test_clean_proceed_creates_nothing(self):
        with mock.patch.object(ic, "_post", return_value=fake_verdict("proceed")):
            out = ic.cothink("planning", {}, project="beethoven")
        self.assertFalse(out["gate"]["created"])
        self.assertEqual(out["gate"]["kind"], "none")

    def test_review_records_but_does_not_block(self):
        with mock.patch.object(ic, "_post", return_value=fake_verdict("review")):
            out = ic.cothink("build", {}, project="beethoven")
        self.assertEqual(out["gate"]["kind"], "review_notice")
        self.assertTrue(out["gate"]["created"])
        self.assertIsNone(out["gate"]["approval_id"])

    def test_escalate_pre_merge_opens_a_blocking_card(self):
        with mock.patch.object(ic, "_post", return_value=fake_verdict("escalate")), \
             mock.patch.object(ic, "_open_premerge_card", return_value="appr-1") as card:
            out = ic.cothink("premerge", {}, project="beethoven", task_id="t-9")
        self.assertEqual(out["gate"]["kind"], "blocking_card")
        self.assertEqual(out["gate"]["approval_id"], "appr-1")
        self.assertTrue(out["gate"]["created"])
        card.assert_called_once()

    def test_escalate_earlier_phases_notify_without_blocking_the_loop(self):
        for phase in ("intake", "planning", "build"):
            with self.subTest(phase=phase), \
                 mock.patch.object(ic, "_post", return_value=fake_verdict("escalate")), \
                 mock.patch.object(ic, "_open_premerge_card") as card:
                out = ic.cothink(phase, {}, project="beethoven")
            self.assertEqual(out["gate"]["kind"], "escalation_notice")
            self.assertTrue(out["gate"]["created"])
            card.assert_not_called()

    def test_degraded_proceed_still_leaves_a_trace(self):
        # The gap in legal coverage must be visible afterwards.
        with mock.patch.object(ic, "_post", side_effect=OSError("down")):
            out = ic.cothink("premerge", {}, project="beethoven")
        self.assertEqual(out["gate"]["kind"], "degraded_notice")
        self.assertTrue(out["gate"]["created"])

    def test_escalate_survives_a_failed_card_write(self):
        # The verdict is real even if the follow-up write fails; report it.
        with mock.patch.object(ic, "_post", return_value=fake_verdict("escalate")), \
             mock.patch.object(ic, "_open_premerge_card", return_value=None):
            out = ic.cothink("premerge", {}, project="beethoven")
        self.assertEqual(out["verdict"], "escalate")
        self.assertFalse(out["gate"]["created"])
        self.assertEqual(out["gate"]["kind"], "blocking_card")


class HumanSteeringTest(unittest.TestCase):
    """Non-engineers steering in their own vocabulary is first-class."""

    def test_lawyer_redirect_is_recorded_with_attribution(self):
        with mock.patch.dict(sys.modules, {"steering": mock.MagicMock()}) as mods:
            mods["steering"].record.return_value = {"id": 1}
            ok = ic.record_human_input(
                "redirect", actor_id="counsel-1", actor_label="Counsel (external)",
                rationale="Reframe as attachable credit, not insurance.",
                project="tomorrow", discipline="legal")
            self.assertTrue(ok)
            kwargs = mods["steering"].record.call_args.kwargs
            self.assertEqual(kwargs["actor_id"], "counsel-1")
            self.assertEqual(kwargs["payload"]["discipline"], "legal")
            self.assertEqual(kwargs["payload"]["source"], "human")

    def test_all_three_human_event_types_are_accepted(self):
        with mock.patch.dict(sys.modules, {"steering": mock.MagicMock()}) as mods:
            mods["steering"].record.return_value = {"id": 1}
            for et in ic.HUMAN_EVENT_TYPES:
                with self.subTest(event_type=et):
                    self.assertTrue(ic.record_human_input(
                        et, "a-1", "Analyst", "rationale", discipline="finance"))

    def test_unknown_event_type_is_refused(self):
        self.assertFalse(ic.record_human_input("gossip", "a-1", "A", "text"))

    def test_missing_actor_or_rationale_is_refused(self):
        self.assertFalse(ic.record_human_input("redirect", "", "A", "text"))
        self.assertFalse(ic.record_human_input("redirect", "a-1", "A", ""))

    def test_steering_failure_is_reported_not_raised(self):
        with mock.patch.dict(sys.modules, {"steering": mock.MagicMock()}) as mods:
            mods["steering"].record.side_effect = RuntimeError("db down")
            self.assertFalse(ic.record_human_input("redirect", "a-1", "A", "text"))


class StatsTest(unittest.TestCase):
    def test_stats_shape(self):
        s = ic.stats()
        self.assertIn("enabled", s)
        self.assertEqual(s["phases"], list(ic.PHASES))
        self.assertEqual(s["verdicts"], list(ic.VERDICTS))


if __name__ == "__main__":
    unittest.main()
