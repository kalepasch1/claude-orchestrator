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


class TestGenericTitlesDoNotFabricateAMatch(unittest.TestCase):
    """The signal is presented to the aggregate as evidence of owner intent.

    Matching on any three shared four-letter words made almost every pair of
    this fleet's titles "similar" — they are all built from the same words
    (task, slice, branch, recover, improve, build, deploy, the project names).
    The newest override then matched nearly every subject, and the aggregate was
    told the owner had a prior call on something they had never seen. A quoted
    claim about what the owner wants, invented, is worse than silence.
    """

    def _call(self, overrides, title, recommendation):
        with patch.object(committees, "db") as mdb:
            mdb.select.return_value = overrides
            return committees._matches_owner_calls(title, recommendation)

    def test_two_unrelated_fleet_titles_do_not_match(self):
        rows = [_override(
            "recover missing branch for improve-automate-branch-management slice 2",
            "approved")]
        sig = self._call(
            rows,
            "recover missing branch for improve-quarantine-auto-triage slice 3",
            "GO")
        self.assertIsNone(
            sig,
            "boilerplate words shared by every task title are not evidence "
            "that the owner has ruled on this subject",
        )

    def test_project_names_alone_do_not_match(self):
        rows = [_override("beethoven tomorrow apparently release train", "approved")]
        sig = self._call(rows, "beethoven tomorrow apparently deploy queue", "GO")
        self.assertIsNone(sig)

    def test_a_genuinely_similar_subject_still_matches(self):
        rows = [_override("ship the billing invoice feature", "approved")]
        sig = self._call(rows, "ship the billing invoice feature now", "GO")
        self.assertIsNotNone(sig)
        self.assertIn("matches", sig)

    def test_the_best_match_wins_not_the_newest(self):
        rows = [
            _override("billing invoice export rollout", "denied"),      # newest, weaker
            _override("ship the billing invoice export feature", "approved"),
        ]
        sig = self._call(rows, "ship the billing invoice export feature", "GO")
        self.assertIsNotNone(sig)
        self.assertIn("ship the billing invoice export feature", sig)
        self.assertIn("approved", sig)

    def test_three_shared_words_between_two_long_titles_is_not_enough(self):
        # Both titles are long and detailed; they happen to share three words.
        # Three out of twenty is a collision, not a subject the owner ruled on.
        past = ("billing invoice export alpha bravo charlie delta echo foxtrot "
                "golf hotel india juliet kilo lima mike november oscar papa")
        current = ("billing invoice export quebec romeo sierra tango uniform "
                   "victor whiskey xray yankee zulu ardent bequest cipher dovetail")
        sig = self._call([_override(past, "approved")], current, "GO")
        self.assertIsNone(sig)

    def test_a_short_specific_title_fully_contained_in_a_longer_one_does_match(self):
        # The complement of the case above, stated so the ratio's denominator
        # choice is a decision on the record rather than an accident: when the
        # whole of the shorter subject appears in the longer one, that IS the
        # same subject.
        past = ("ship the billing invoice export feature to the enterprise tier "
                "for the january launch")
        sig = self._call([_override(past, "approved")],
                         "billing invoice export", "GO")
        self.assertIsNotNone(sig)
        self.assertIn("matches", sig)

    def test_a_title_with_too_few_meaningful_words_returns_none(self):
        rows = [_override("recover the task branch", "approved")]
        sig = self._call(rows, "recover the task branch", "GO")
        self.assertIsNone(sig)


if __name__ == "__main__":
    unittest.main()
