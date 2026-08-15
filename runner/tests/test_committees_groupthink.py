#!/usr/bin/env python3
"""Unit tests for the CADE groupthink guard and idea-tournament bracket in committees.py.

These cover the SEATING DECISION, not the model calls: the whole point of the guard is that extra
adversary/exploration seats are expensive, so the rule deciding when to buy them has to be exact and
must not fire on ordinary low-stakes issues. Everything under test is deterministic and offline.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import committees


class IssueMaterialityTest(unittest.TestCase):
    """Pre-panel stakes estimate stays in range and responds to real risk markers."""

    def test_bare_issue_is_low_materiality(self):
        m = committees.issue_materiality("rename a local variable")
        self.assertLess(m, committees.GROUPTHINK_MATERIALITY)

    def test_risk_markers_raise_materiality(self):
        low = committees.issue_materiality("tweak copy on the about page")
        high = committees.issue_materiality(
            "irreversible production migration touching customer billing and PII")
        self.assertGreater(high, low)

    def test_stays_within_unit_interval(self):
        m = committees.issue_materiality(
            "irreversible production customer revenue payment billing credential secret security "
            "privacy pii delete migration licensing regulatory compliance custody legal contract",
            blast_radius=1.0)
        self.assertGreaterEqual(m, 0.0)
        self.assertLessEqual(m, 1.0)

    def test_handles_none_and_bad_blast_radius(self):
        self.assertIsInstance(committees.issue_materiality(None, None), float)
        self.assertIsInstance(committees.issue_materiality("x", "y", blast_radius="not-a-number"), float)


class ConvergedFastTest(unittest.TestCase):
    """Premature consensus = every opening verdict identical, across enough seats to mean something."""

    def test_unanimous_panel_is_premature(self):
        self.assertTrue(committees.converged_fast(
            [{"verdict": "support"}, {"verdict": "support"}, {"verdict": "support"}]))

    def test_split_panel_is_not_premature(self):
        self.assertFalse(committees.converged_fast(
            [{"verdict": "support"}, {"verdict": "oppose"}, {"verdict": "support"}]))

    def test_two_seats_are_too_thin_to_call_groupthink(self):
        self.assertFalse(committees.converged_fast([{"verdict": "support"}, {"verdict": "support"}]))

    def test_empty_panel_is_not_premature(self):
        self.assertFalse(committees.converged_fast([]))
        self.assertFalse(committees.converged_fast(None))


class GroupthinkSeatsTest(unittest.TestCase):
    """The guard must stay shut on ordinary issues and open on the two conditions that justify it."""

    def test_does_not_fire_on_low_stakes_split_panel(self):
        self.assertEqual(committees.groupthink_seats(0.3, False), [])

    def test_fires_on_high_materiality_alone(self):
        self.assertTrue(committees.groupthink_seats(0.9, False))

    def test_fires_on_premature_consensus_alone(self):
        # Low materiality, but the room agreed before cross-examination — that is the case the guard exists for.
        self.assertTrue(committees.groupthink_seats(0.1, True))

    def test_seats_an_exploration_quota_not_just_adversaries(self):
        seats = committees.groupthink_seats(0.9, True)
        self.assertTrue(any(committees.HERETIC_SEAT in s for s in seats))

    def test_exploration_quota_scales_with_materiality(self):
        modest = committees.groupthink_seats(0.7, False)
        extreme = committees.groupthink_seats(0.95, False)
        self.assertGreater(sum(committees.HERETIC_SEAT in s for s in extreme),
                           sum(committees.HERETIC_SEAT in s for s in modest))

    def test_is_idempotent_against_already_seated(self):
        first = committees.groupthink_seats(0.9, True)
        again = committees.groupthink_seats(0.9, True, seated=first)
        self.assertEqual(again, [])

    def test_never_duplicates_the_standing_red_seat(self):
        seats = committees.groupthink_seats(0.9, True)
        self.assertNotIn(committees.RED_SEAT, seats)

    def test_bad_materiality_does_not_raise(self):
        self.assertEqual(committees.groupthink_seats(None, False), [])
        self.assertEqual(committees.groupthink_seats("nonsense", False), [])


class TournamentBracketTest(unittest.TestCase):
    """Idea tournament: competing proposals, weaker half eliminated, strongest survives."""

    def test_eliminates_the_weaker_half(self):
        proposals = [{"id": "a", "score": 9}, {"id": "b", "score": 2},
                     {"id": "c", "score": 7}, {"id": "d", "score": 1}]
        survivors = committees.tournament_bracket(proposals)
        self.assertEqual([p["id"] for p in survivors], ["a", "c"])

    def test_conviction_modulates_but_score_dominates(self):
        proposals = [{"id": "low-score-high-conviction", "score": 4, "conviction": 10},
                     {"id": "high-score-low-conviction", "score": 9, "conviction": 1}]
        self.assertEqual(committees.tournament_bracket(proposals, keep=1)[0]["id"],
                         "high-score-low-conviction")

    def test_keep_is_honoured_and_clamped(self):
        proposals = [{"id": "a", "score": 9}, {"id": "b", "score": 8}, {"id": "c", "score": 7}]
        self.assertEqual(len(committees.tournament_bracket(proposals, keep=1)), 1)
        self.assertEqual(len(committees.tournament_bracket(proposals, keep=99)), 3)
        self.assertEqual(len(committees.tournament_bracket(proposals, keep=0)), 1)

    def test_ties_break_on_original_order_so_the_bracket_is_stable(self):
        proposals = [{"id": "first", "score": 5}, {"id": "second", "score": 5}]
        self.assertEqual(committees.tournament_bracket(proposals, keep=1)[0]["id"], "first")

    def test_single_proposal_survives(self):
        self.assertEqual(len(committees.tournament_bracket([{"id": "only", "score": 3}])), 1)

    def test_empty_and_malformed_input(self):
        self.assertEqual(committees.tournament_bracket([]), [])
        self.assertEqual(committees.tournament_bracket(None), [])
        self.assertEqual(committees.tournament_bracket(["not-a-dict", 42]), [])


class ExistingContractsPreservedTest(unittest.TestCase):
    """The guard is additive: nothing the rest of the engine depends on may have moved."""

    def test_core_entrypoints_still_exist(self):
        for fn in ("deliberate", "review", "locate_owner", "active_committees", "build_kg",
                   "verify_determination", "tune_budget"):
            self.assertTrue(callable(getattr(committees, fn, None)), f"{fn} missing or not callable")

    def test_red_seat_is_still_a_standing_seat(self):
        self.assertTrue(committees.RED_SEAT)
        self.assertTrue(committees.DEFAULT_SEATS)


if __name__ == "__main__":
    unittest.main()
