#!/usr/bin/env python3
"""Tests for approval_policy.py - the narrow legal-only owner gate."""
import os, sys, unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import approval_policy as ap


def card(**kw):
    base = {"id": "c1", "kind": "material", "title": "Approve merge of foo",
            "why": "routine build", "detail": "", "prebrief": "", "status": "pending",
            "radar_tag": None, "legal_risk_level": None, "alternatives": None, "project": "x"}
    base.update(kw)
    return base


class TestClassification(unittest.TestCase):
    def test_plain_merge_auto_approves(self):
        self.assertTrue(ap.is_auto_approvable(card()))
        self.assertFalse(ap.is_legal_gated(card()))

    def test_novel_legal_gated(self):
        c = card(kind="legal", legal_risk_level="novel")
        self.assertTrue(ap.is_legal_gated(c))
        self.assertFalse(ap.is_auto_approvable(c))

    def test_routine_legal_not_gated_here(self):
        # legal_triage owns routine-legal clearing; policy must not gate it
        self.assertFalse(ap.is_legal_gated(card(kind="legal", legal_risk_level="routine")))

    def test_regulatory_radar_gated(self):
        self.assertTrue(ap.is_legal_gated(card(radar_tag="regulatory")))

    def test_exemption_language_gated(self):
        c = card(why="public recruit page may be general solicitation breaking the lending exemption")
        self.assertTrue(ap.is_legal_gated(c))

    def test_licensing_language_gated(self):
        c = card(detail="issues signed license attestations third parties rely on")
        self.assertTrue(ap.is_legal_gated(c))

    def test_secret_never_auto(self):
        self.assertFalse(ap.is_auto_approvable(card(kind="secret", title="Provide STRIPE_KEY")))

    def test_billing_alarm_never_auto(self):
        self.assertFalse(ap.is_auto_approvable(card(kind="self", title="Billing firewall stripped an API key at startup")))

    def test_pricing_data_use_auto(self):
        self.assertTrue(ap.is_auto_approvable(card(radar_tag="pricing", why="update pricing xlsx")))
        self.assertTrue(ap.is_auto_approvable(card(radar_tag="data_use", why="cross-app signal between our own apps")))


class TestEnrichment(unittest.TestCase):
    def test_gated_card_gets_options_and_narrow_framing(self):
        c = card(radar_tag="regulatory", why="may break exemption")
        patch_ = ap._enrich_gated(c)
        self.assertIn("NARROW LEGAL QUESTION", patch_["why"])
        self.assertGreaterEqual(len(patch_["alternatives"]), 3)
        self.assertEqual(patch_["legal_risk_level"], "novel")

    def test_already_narrowed_not_reframed(self):
        c = card(radar_tag="regulatory", why="NARROW LEGAL QUESTION: x",
                 alternatives=[{"label": "a"}], legal_risk_level="novel")
        self.assertEqual(ap._enrich_gated(c), {})


class TestSweep(unittest.TestCase):
    def test_sweep_approves_auto_and_keeps_legal(self):
        cards = [card(id="a"), card(id="b", radar_tag="regulatory", why="exemption risk")]
        with patch.object(ap, "db") as mdb:
            mdb.select.return_value = cards
            approved, gated = ap.sweep()
        self.assertEqual((approved, gated), (1, 1))
        statuses = [c.args[2] for c in mdb.update.call_args_list if "status" in c.args[2]]
        self.assertTrue(all(p.get("decided_by") == ap.POLICY_MARK for p in statuses))

    def test_sweep_disabled_env(self):
        with patch.object(ap, "ENABLED", False):
            self.assertEqual(ap.sweep(), (0, 0))


if __name__ == "__main__":
    unittest.main()
