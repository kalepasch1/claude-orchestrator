#!/usr/bin/env python3
"""Tests for decision_confidence_autodecide.py — auto-decide high-confidence low-stakes approvals."""
import os, sys, unittest, time
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import decision_confidence_autodecide as ad


def _approval(**kw):
    base = {"id": "a1", "kind": "material", "category": "", "title": "Ship feature X",
            "why": "routine", "status": "pending", "brief_status": "ready"}
    base.update(kw)
    return base


def _brief(**kw):
    base = {"decision": "Ship feature X", "confidence": 92,
            "recommendation": "approve", "counsel_needed": False,
            "stakes": "minor UI change", "options": [
                {"label": "Ship", "reversibility": "high"},
                {"label": "Wait", "reversibility": "high"},
            ]}
    base.update(kw)
    return base


class TestCategoryDenylist(unittest.TestCase):
    def test_base_categories(self):
        dl = ad.category_denylist()
        for cat in ("legal", "financial", "security", "personnel", "compliance"):
            self.assertIn(cat, dl)

    @patch.dict(os.environ, {"ORCH_AUTODECIDE_DENYLIST_EXTRA": "hr,  procurement"})
    def test_extra_env_categories(self):
        dl = ad.category_denylist()
        self.assertIn("hr", dl)
        self.assertIn("procurement", dl)


class TestStakeLevel(unittest.TestCase):
    def test_empty_brief_medium(self):
        self.assertEqual(ad.stake_level({}), "medium")

    def test_none_brief_medium(self):
        self.assertEqual(ad.stake_level(None), "medium")

    def test_low_stakes(self):
        b = _brief(stakes="minor copy change")
        self.assertEqual(ad.stake_level(b), "low")

    def test_high_dollar_amount(self):
        b = _brief(stakes="costs $5M to revert")
        self.assertEqual(ad.stake_level(b), "high")

    def test_catastrophic_stakes(self):
        b = _brief(stakes="catastrophic data loss")
        self.assertEqual(ad.stake_level(b), "high")

    def test_irreversible_options(self):
        b = _brief(options=[
            {"label": "A", "reversibility": "low"},
            {"label": "B", "reversibility": "none"},
        ])
        self.assertEqual(ad.stake_level(b), "high")

    def test_external_parties_medium(self):
        b = _brief(stakes="notify vendor of changes")
        self.assertEqual(ad.stake_level(b), "medium")


class TestShouldAutodecide(unittest.TestCase):
    def test_high_confidence_low_stakes_yes(self):
        self.assertTrue(ad.should_autodecide(_approval(), _brief()))

    def test_low_confidence_no(self):
        self.assertFalse(ad.should_autodecide(_approval(), _brief(confidence=60)))

    def test_threshold_boundary_exact(self):
        self.assertTrue(ad.should_autodecide(_approval(), _brief(confidence=85)))

    def test_threshold_boundary_below(self):
        self.assertFalse(ad.should_autodecide(_approval(), _brief(confidence=84)))

    def test_counsel_needed_no(self):
        self.assertFalse(ad.should_autodecide(_approval(), _brief(counsel_needed=True)))

    def test_legal_category_no(self):
        self.assertFalse(ad.should_autodecide(_approval(kind="legal"), _brief()))

    def test_financial_category_no(self):
        self.assertFalse(ad.should_autodecide(_approval(category="financial"), _brief()))

    def test_security_category_no(self):
        self.assertFalse(ad.should_autodecide(_approval(kind="security"), _brief()))

    def test_high_stakes_no(self):
        b = _brief(stakes="catastrophic failure risk")
        self.assertFalse(ad.should_autodecide(_approval(), b))

    def test_all_irreversible_options_no(self):
        b = _brief(options=[
            {"label": "A", "reversibility": "irreversible"},
            {"label": "B", "reversibility": "none"},
        ])
        self.assertFalse(ad.should_autodecide(_approval(), b))

    def test_empty_brief_no(self):
        self.assertFalse(ad.should_autodecide(_approval(), {}))

    def test_none_brief_no(self):
        self.assertFalse(ad.should_autodecide(_approval(), None))

    def test_non_numeric_confidence_no(self):
        self.assertFalse(ad.should_autodecide(_approval(), _brief(confidence="unknown")))


class TestAutodecide(unittest.TestCase):
    @patch("decision_confidence_autodecide.db")
    def test_returns_record(self, mock_db):
        mock_db.update = MagicMock()
        mock_db.insert = MagicMock()
        rec = ad.autodecide(_approval(), _brief())
        self.assertEqual(rec["approval_id"], "a1")
        self.assertEqual(rec["decided_by"], "autodecide")
        self.assertEqual(rec["decision"], "approve")
        self.assertGreaterEqual(rec["confidence"], 85)
        self.assertIn("ts", rec)

    @patch("decision_confidence_autodecide.db")
    def test_updates_db(self, mock_db):
        mock_db.update = MagicMock()
        mock_db.insert = MagicMock()
        ad.autodecide(_approval(id="a99"), _brief())
        mock_db.update.assert_called_once()
        args = mock_db.update.call_args
        self.assertEqual(args[0][0], "approvals")
        self.assertEqual(args[0][1], {"id": "a99"})

    @patch("decision_confidence_autodecide.db")
    def test_db_failure_still_returns(self, mock_db):
        mock_db.update = MagicMock(side_effect=Exception("db down"))
        mock_db.insert = MagicMock(side_effect=Exception("db down"))
        rec = ad.autodecide(_approval(), _brief())
        self.assertEqual(rec["decided_by"], "autodecide")


class TestAuditTrail(unittest.TestCase):
    def test_in_memory_trail(self):
        ad._audit_log.clear()
        ad._audit_log.append({"approval_id": "trail1", "decision": "approve"})
        trail = ad.audit_trail("trail1")
        self.assertEqual(len(trail), 1)
        self.assertEqual(trail[0]["approval_id"], "trail1")

    def test_empty_trail(self):
        ad._audit_log.clear()
        self.assertEqual(ad.audit_trail("nonexistent"), [])


class TestStats(unittest.TestCase):
    def test_stats_shape(self):
        s = ad.stats()
        for key in ("evaluated", "auto_decided", "manual_required", "avg_confidence_auto"):
            self.assertIn(key, s)

    def test_avg_confidence_no_division_by_zero(self):
        saved = dict(ad._stats)
        ad._stats.update({"auto_decided": 0, "confidence_sum": 0.0})
        s = ad.stats()
        self.assertEqual(s["avg_confidence_auto"], 0.0)
        ad._stats.update(saved)


class TestRun(unittest.TestCase):
    @patch("decision_confidence_autodecide.db")
    def test_run_auto_decides_eligible(self, mock_db):
        mock_db.select = MagicMock(return_value=[
            {"id": "r1", "kind": "material", "category": "", "status": "pending",
             "brief_status": "ready", "brief_json": {
                 "confidence": 95, "recommendation": "approve",
                 "counsel_needed": False, "stakes": "trivial",
                 "options": [{"label": "go", "reversibility": "high"}],
             }},
        ])
        mock_db.update = MagicMock()
        mock_db.insert = MagicMock()
        summary = ad.run()
        self.assertEqual(summary["evaluated"], 1)
        self.assertEqual(summary["auto_decided"], 1)

    @patch("decision_confidence_autodecide.db")
    def test_run_skips_low_confidence(self, mock_db):
        mock_db.select = MagicMock(return_value=[
            {"id": "r2", "kind": "material", "category": "", "status": "pending",
             "brief_status": "ready", "brief_json": {
                 "confidence": 40, "recommendation": "deny",
                 "counsel_needed": False, "stakes": "trivial",
                 "options": [],
             }},
        ])
        summary = ad.run()
        self.assertEqual(summary["manual_required"], 1)
        self.assertEqual(summary["auto_decided"], 0)

    @patch("decision_confidence_autodecide.db")
    def test_run_handles_db_failure(self, mock_db):
        mock_db.select = MagicMock(side_effect=Exception("timeout"))
        summary = ad.run()
        self.assertTrue(len(summary["errors"]) > 0)

    @patch("decision_confidence_autodecide.db")
    def test_run_parses_json_string_brief(self, mock_db):
        import json as _json
        mock_db.select = MagicMock(return_value=[
            {"id": "r3", "kind": "material", "category": "", "status": "pending",
             "brief_status": "ready", "brief_json": _json.dumps({
                 "confidence": 90, "recommendation": "approve",
                 "counsel_needed": False, "stakes": "low",
                 "options": [{"label": "go", "reversibility": "high"}],
             })},
        ])
        mock_db.update = MagicMock()
        mock_db.insert = MagicMock()
        summary = ad.run()
        self.assertEqual(summary["auto_decided"], 1)


if __name__ == "__main__":
    unittest.main()
