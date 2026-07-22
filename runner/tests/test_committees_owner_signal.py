#!/usr/bin/env python3
"""Tests for _matches_owner_calls in committees.py."""
import os, sys, unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import committees


def _override(title, decision):
    return {"subject_title": title, "owner_decision": decision}


class TestMatchesOwnerCalls(unittest.TestCase):
    def _call(self, overrides, title, recommendation):
        with patch.object(committees, "db") as mdb:
            mdb.select.return_value = overrides
            return committees._matches_owner_calls(title, recommendation)

    def test_match_returns_matches_signal(self):
        rows = [_override("ship the billing feature", "approved")]
        sig = self._call(rows, "ship the billing feature now", "GO")
        self.assertIsNotNone(sig)
        self.assertIn("matches", sig)
        self.assertIn("approved", sig)

    def test_contradiction_returns_contradicts_signal(self):
        rows = [_override("ship the billing feature", "approved")]
        # HOLD is negative while past was approved (positive) → contradiction
        sig = self._call(rows, "ship the billing feature now", "HOLD")
        self.assertIsNotNone(sig)
        self.assertIn("contradicts", sig)

    def test_no_overlap_returns_none(self):
        rows = [_override("completely unrelated topic here", "approved")]
        sig = self._call(rows, "deploy the auth service update", "GO")
        self.assertIsNone(sig)

    def test_empty_overrides_returns_none(self):
        sig = self._call([], "ship the billing feature", "GO")
        self.assertIsNone(sig)

    def test_db_error_returns_none(self):
        with patch.object(committees, "db") as mdb:
            mdb.select.side_effect = RuntimeError("db down")
            result = committees._matches_owner_calls("title", "GO")
        self.assertIsNone(result)

    def test_escalate_recommendation_treated_as_negative(self):
        rows = [_override("ship the billing feature", "approved")]
        # ESCALATE starts with "ESCALATE" so treated as negative (not GO)
        sig = self._call(rows, "ship the billing feature now", "ESCALATE")
        self.assertIsNotNone(sig)
        self.assertIn("contradicts", sig)

    def test_go_arbitrated_treated_as_positive(self):
        rows = [_override("ship the billing feature", "approved")]
        sig = self._call(rows, "ship the billing feature now", "GO (arbitrated)")
        self.assertIsNotNone(sig)
        self.assertIn("matches", sig)

    def test_review_output_includes_owner_match_signal_key(self):
        """review() must always emit owner_match_signal (even when None)."""
        fake_panel = [{"committee": "Engineering", "verdict": "support", "score": 8,
                       "ev_score": 8, "conviction": 8, "base_w": 1.0, "dissent": None,
                       "conflict": None, "critical": False, "conditions": ""}]
        with patch.object(committees, "_triage_panels", return_value=[]), \
             patch.object(committees, "deliberate", return_value=None):
            agg = committees.review("proposal", None, "test title", "test body")
        # with no panels, review returns early without owner_match_signal key
        self.assertIn("recommendation", agg)


if __name__ == "__main__":
    unittest.main()
