"""Anti-groupthink contrarian pull + the causal layer over the knowledge graph.

Both units under test are deliberately PURE (no db, no network), because the value of
each is a policy decision, and a policy you can only observe through a database round
trip is a policy nobody re-tests once it is written.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import committees  # noqa: E402


class ContrarianScheduleTest(unittest.TestCase):
    def test_fires_on_the_interval_and_not_between(self):
        self.assertTrue(committees.contrarian_due(5, every=5))
        self.assertTrue(committees.contrarian_due(10, every=5))
        for n in (1, 2, 3, 4, 6, 9):
            self.assertFalse(committees.contrarian_due(n, every=5), n)

    def test_zero_disables_it_entirely(self):
        """0 must mean pure UCB1, not 'every pull' — a modulo bug here funds the worst arm forever."""
        for n in (1, 5, 50):
            self.assertFalse(committees.contrarian_due(n, every=0))

    def test_never_fires_before_the_first_pull(self):
        self.assertFalse(committees.contrarian_due(0, every=5))

    def test_fail_soft_on_garbage(self):
        """Bad config must degrade to the default, never raise into the board loop."""
        self.assertTrue(committees.contrarian_due(5, every="not-a-number"))
        self.assertFalse(committees.contrarian_due("not-a-number", every=5))
        self.assertFalse(committees.contrarian_due(None, every=5))


class SelectBoardArmTest(unittest.TestCase):
    # (ucb, name, id, reward), pre-sorted descending as board_bandit sorts them
    SCORED = [(9.0, "best", 1, 9.0), (5.0, "mid", 2, 5.0), (0.1, "worst", 3, 0.1)]

    def test_normal_pull_takes_the_ucb_winner(self):
        arm, contrarian = committees.select_board_arm(self.SCORED, total_pulls=3, every=5)
        self.assertEqual(arm[1], "best")
        self.assertFalse(contrarian)

    def test_contrarian_pull_force_funds_the_least_favored_arm(self):
        arm, contrarian = committees.select_board_arm(self.SCORED, total_pulls=5, every=5)
        self.assertEqual(arm[1], "worst")
        self.assertTrue(contrarian)

    def test_single_arm_has_no_dissent_to_fund(self):
        one = [(9.0, "only", 1, 9.0)]
        arm, contrarian = committees.select_board_arm(one, total_pulls=5, every=5)
        self.assertEqual(arm[1], "only")
        self.assertFalse(contrarian)

    def test_empty_scoreboard_is_not_an_exception(self):
        self.assertEqual(committees.select_board_arm([], total_pulls=5, every=5), (None, False))


class CausalLinksTest(unittest.TestCase):
    OPS = [{"app": "alpha", "consensus_verdict": "ship", "created_at": "2026-01-01T00:00:00Z"}]

    def test_only_outcomes_after_the_determination_count(self):
        """The whole point of the causal layer: an outcome that PRECEDES a verdict is not its effect."""
        outcomes = [
            {"app": "alpha", "lift": 10.0, "concluded_at": "2026-02-01T00:00:00Z"},
            {"app": "alpha", "lift": 20.0, "concluded_at": "2026-03-01T00:00:00Z"},
            {"app": "alpha", "lift": -99.0, "concluded_at": "2025-12-01T00:00:00Z"},  # before
        ]
        links = committees.causal_links(self.OPS, outcomes)
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0]["n"], 2)
        self.assertEqual(links[0]["effect"], 15.0)

    def test_a_single_observation_is_an_anecdote_not_a_link(self):
        outcomes = [{"app": "alpha", "lift": 10.0, "concluded_at": "2026-02-01T00:00:00Z"}]
        self.assertEqual(committees.causal_links(self.OPS, outcomes), [])

    def test_outcomes_do_not_leak_across_apps(self):
        outcomes = [
            {"app": "beta", "lift": 10.0, "concluded_at": "2026-02-01T00:00:00Z"},
            {"app": "beta", "lift": 10.0, "concluded_at": "2026-03-01T00:00:00Z"},
        ]
        self.assertEqual(committees.causal_links(self.OPS, outcomes), [])

    def test_malformed_rows_are_skipped_not_raised_on(self):
        outcomes = [
            {"app": "alpha", "lift": "not-a-number", "concluded_at": "2026-02-01T00:00:00Z"},
            {"app": "alpha", "lift": 4.0, "concluded_at": "2026-02-02T00:00:00Z"},
            {"app": "alpha", "lift": 6.0, "concluded_at": "2026-02-03T00:00:00Z"},
        ]
        links = committees.causal_links(self.OPS, outcomes)
        self.assertEqual(links[0]["n"], 2)
        self.assertEqual(links[0]["effect"], 5.0)

    def test_empty_input_is_empty_output(self):
        self.assertEqual(committees.causal_links([], []), [])
        self.assertEqual(committees.causal_links(None, None), [])

    def test_strongest_absolute_effect_ranks_first(self):
        """A large NEGATIVE effect is as informative as a large positive one."""
        ops = self.OPS + [{"app": "alpha", "consensus_verdict": "hold",
                           "created_at": "2026-01-01T00:00:00Z"}]
        outcomes = [
            {"app": "alpha", "lift": -50.0, "concluded_at": "2026-02-01T00:00:00Z"},
            {"app": "alpha", "lift": -50.0, "concluded_at": "2026-02-02T00:00:00Z"},
        ]
        links = committees.causal_links(ops, outcomes)
        self.assertEqual(links[0]["effect"], -50.0)


class FormatCausalContextTest(unittest.TestCase):
    def test_says_nothing_when_there_is_nothing_to_say(self):
        self.assertEqual(committees.format_causal_context([]), "")

    def test_renders_and_marks_itself_uncontrolled(self):
        out = committees.format_causal_context(
            [{"verdict": "ship", "app": "alpha", "n": 3, "effect": 12.5}])
        self.assertIn("ship", out)
        self.assertIn("alpha", out)
        self.assertIn("not controlled", out)


class PublicSurfacePreservedTest(unittest.TestCase):
    """The guardrail: extending this module must not remove or rename what already exists."""

    def test_existing_entry_points_still_exist(self):
        for name in ("board_bandit", "board_review", "build_kg", "kg_context",
                     "deliberate", "review", "_triage_panels"):
            self.assertTrue(callable(getattr(committees, name, None)), name)


if __name__ == "__main__":
    unittest.main()
