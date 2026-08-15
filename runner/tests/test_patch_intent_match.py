#!/usr/bin/env python3
"""Tests for patch_intent_match — intent ranking and offset-only patch adaptation.

The two named acceptance tests are first: the ranking example from the task, and a diff
applied to a tree whose hunks have all shifted down 5-10 lines.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import patch_intent_match as pim  # noqa: E402


TARGET = "MERGED-DIFF LIBRARY: adapt proven prior diffs before drafting net-new code"

CANDIDATES = [
    {"source": "prediction-markets-institute/weekly-lint-prediction-markets-institute",
     "hash": "bffd1c2752f8",
     "intent": "weekly lint pass over the prediction markets institute package"},
    {"source": "beethoven/merged-diff-library-adapter",
     "hash": "aaaa11112222",
     "intent": "adapt proven prior merged diffs before drafting net-new code for a task"},
    {"source": "pareto-2080/remove-duplicate-pricing-grid",
     "hash": "8b92d078e856",
     "intent": "remove duplicate pricing grid reconstruction to improve maintainability"},
]


class RankingAcceptanceTests(unittest.TestCase):
    """The task's named example."""

    def test_the_adapter_candidate_ranks_first(self):
        ranked = pim.rank_candidates(TARGET, CANDIDATES)
        self.assertTrue(ranked)
        self.assertEqual(ranked[0]["source"], "beethoven/merged-diff-library-adapter")

    def test_results_are_sorted_by_descending_score(self):
        scores = [r["score"] for r in pim.rank_candidates(TARGET, CANDIDATES, min_score=0)]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_every_result_keeps_its_source_hash_and_intent(self):
        for row in pim.rank_candidates(TARGET, CANDIDATES, min_score=0):
            for key in ("source", "hash", "intent", "score"):
                self.assertIn(key, row)

    def test_best_candidate_agrees_with_the_ranking(self):
        self.assertEqual(pim.best_candidate(TARGET, CANDIDATES)["hash"], "aaaa11112222")

    def test_an_unrelated_target_selects_nothing(self):
        self.assertIsNone(pim.best_candidate(
            "rotate the TLS certificate on the mail relay", CANDIDATES))


class TokenizeTests(unittest.TestCase):
    def test_unigrams_are_a_superset_of_the_merged_diff_library_tokeniser(self):
        """Documents a real quirk upstream: `_words` uses a `{4,}` regex and then filters
        `len(w) > 4`, so it silently drops every 4-letter token — `diff`, `code`, `test`,
        `hunk`. This tokeniser honours the regex and keeps them."""
        text = "Adapt proven prior diffs before drafting NET-NEW code"
        from merged_diff_library import _words
        mine, theirs = pim.tokenize(text, n=1), _words(text)
        self.assertTrue(theirs.issubset(mine))
        self.assertTrue(all(len(w) == 4 for w in mine - theirs), mine - theirs)
        self.assertIn("code", mine)

    def test_bigrams_distinguish_word_order(self):
        a, b = "pricing config loader", "loader config pricing"
        self.assertEqual(pim.tokenize(a, n=1), pim.tokenize(b, n=1))
        self.assertNotEqual(pim.tokenize(a, n=2), pim.tokenize(b, n=2))

    def test_short_words_are_dropped(self):
        self.assertNotIn("the", pim.tokenize("the pricing config"))

    def test_garbage_input_returns_an_empty_set(self):
        for bad in (None, 7, [], {}):
            self.assertEqual(pim.tokenize(bad), set())


class SimilarityTests(unittest.TestCase):
    def test_jaccard_is_symmetric_and_bounded(self):
        a, b = {"x", "y"}, {"y", "z"}
        self.assertEqual(pim.jaccard(a, b), pim.jaccard(b, a))
        self.assertEqual(pim.jaccard(a, a), 1.0)

    def test_empty_sides_score_zero(self):
        self.assertEqual(pim.jaccard(set(), {"x"}), 0.0)
        self.assertEqual(pim.overlap({"x"}, set()), 0.0)

    def test_containment_rewards_a_superset_intent_that_jaccard_punishes(self):
        short, long = {"a", "b"}, {"a", "b", "c", "d", "e", "f"}
        self.assertEqual(pim.overlap(short, long), 1.0)
        self.assertLess(pim.jaccard(short, long), 0.5)

    def test_identical_intents_score_one(self):
        self.assertEqual(pim.score_intent("adapt proven prior diffs",
                                          "adapt proven prior diffs"), 1.0)

    def test_scoring_never_raises(self):
        for bad in (None, 7, [], {}):
            self.assertIsInstance(pim.score_intent(bad, bad), float)


class RankingRobustnessTests(unittest.TestCase):
    def test_ties_break_deterministically_by_source(self):
        same = "adapt proven prior diffs before drafting net-new code"
        candidates = [{"source": "z/one", "hash": "1", "intent": same},
                      {"source": "a/two", "hash": "2", "intent": same}]
        first = [r["source"] for r in pim.rank_candidates(TARGET, candidates)]
        second = [r["source"] for r in pim.rank_candidates(TARGET, list(reversed(candidates)))]
        self.assertEqual(first, second)
        self.assertEqual(first[0], "a/two")

    def test_non_dict_candidates_are_skipped_not_fatal(self):
        ranked = pim.rank_candidates(TARGET, [None, "x", 7, CANDIDATES[1]])
        self.assertEqual(len(ranked), 1)

    def test_limit_is_honoured(self):
        self.assertEqual(len(pim.rank_candidates(TARGET, CANDIDATES, min_score=0, limit=1)), 1)

    def test_empty_inputs_return_an_empty_list(self):
        self.assertEqual(pim.rank_candidates(TARGET, []), [])
        self.assertEqual(pim.rank_candidates("", CANDIDATES), [])


# ---------------------------------------------------------------------------
# Patch adaptation
# ---------------------------------------------------------------------------

ORIGINAL_FILE = "\n".join(f"line {i}" for i in range(1, 41)) + "\n"

DIFF = """diff --git a/app/mod.py b/app/mod.py
--- a/app/mod.py
+++ b/app/mod.py
@@ -10,3 +10,4 @@ def widget():
 line 10
 line 11
+inserted by the patch
 line 12
"""


def shifted(by):
    """The same file with `by` extra lines prepended — every hunk shifts down."""
    return "\n".join(f"header {i}" for i in range(by)) + "\n" + ORIGINAL_FILE


class AdaptAcceptanceTests(unittest.TestCase):
    """The task's named example: hunks shifted down 5-10 lines must still apply."""

    def _adapt(self, shift):
        return pim.adapt_diff(DIFF, lambda path: shifted(shift))

    def test_a_five_line_shift_is_adapted(self):
        result = self._adapt(5)
        self.assertTrue(result["ok"], result["details"])
        self.assertIn("@@ -15,3 +15,4 @@", result["diff"])

    def test_a_ten_line_shift_is_adapted(self):
        result = self._adapt(10)
        self.assertTrue(result["ok"], result["details"])
        self.assertIn("@@ -20,3 +20,4 @@", result["diff"])

    def test_every_shift_in_the_range_lands_correctly(self):
        for shift in range(5, 11):
            result = self._adapt(shift)
            self.assertTrue(result["ok"], f"shift {shift}: {result['details']}")
            # Both sides shift by the same delta: the patch still inserts at the same
            # place relative to its own context.
            self.assertIn(f"@@ -{10 + shift},3 +{10 + shift},4 @@", result["diff"])

    def test_the_patch_body_is_never_altered(self):
        """Offset-only: the semantic intent of the patch cannot change."""
        result = self._adapt(7)
        body = [l for l in result["diff"].splitlines() if l[:1] in ("+", "-", " ")
                and not l.startswith(("+++", "---"))]
        original = [l for l in DIFF.splitlines() if l[:1] in ("+", "-", " ")
                    and not l.startswith(("+++", "---"))]
        self.assertEqual(body, original)

    def test_an_unshifted_file_is_reported_as_unchanged(self):
        result = pim.adapt_diff(DIFF, lambda path: ORIGINAL_FILE)
        self.assertTrue(result["ok"])
        self.assertEqual(result["unchanged"], 1)
        self.assertEqual(result["adapted"], 0)


class AdaptSafetyTests(unittest.TestCase):
    def test_a_missing_target_file_fails_rather_than_guessing(self):
        result = pim.adapt_diff(DIFF, lambda path: None)
        self.assertFalse(result["ok"])
        self.assertEqual(result["failed"], 1)
        self.assertIn("target file not found", result["details"][0])

    def test_the_original_diff_is_returned_when_nothing_could_be_placed(self):
        """Never hand back a half-adapted patch: it would apply some hunks and drop others."""
        result = pim.adapt_diff(DIFF, lambda path: "totally unrelated\ncontent\n")
        self.assertFalse(result["ok"])
        self.assertEqual(result["diff"], DIFF)

    def test_a_drift_beyond_the_limit_is_refused(self):
        result = pim.adapt_diff(DIFF, lambda path: shifted(6), max_drift=2)
        self.assertFalse(result["ok"])
        self.assertIn("no context match", result["details"][0])

    def test_a_low_context_ratio_is_refused(self):
        result = pim.adapt_diff(DIFF, lambda path: shifted(5), min_ratio=1.01)
        self.assertFalse(result["ok"])

    def test_a_reader_that_raises_is_treated_as_a_missing_file(self):
        def boom(path):
            raise RuntimeError("io error")
        result = pim.adapt_diff(DIFF, boom)
        self.assertFalse(result["ok"])
        self.assertEqual(result["failed"], 1)

    def test_empty_and_garbage_diffs_do_not_raise(self):
        for bad in (None, "", "not a diff at all", 7):
            result = pim.adapt_diff(bad, lambda path: ORIGINAL_FILE)
            self.assertFalse(result["ok"])


class ParseHunkTests(unittest.TestCase):
    def test_hunk_metadata_is_parsed(self):
        hunk = pim.parse_hunks(DIFF)[0]
        self.assertEqual(hunk["file"], "app/mod.py")
        self.assertEqual((hunk["old_start"], hunk["old_len"]), (10, 3))
        self.assertEqual((hunk["new_start"], hunk["new_len"]), (10, 4))

    def test_the_old_body_is_context_plus_removals_only(self):
        body = pim.hunk_old_body(pim.parse_hunks(DIFF)[0])
        self.assertEqual(body, ["line 10", "line 11", "line 12"])

    def test_multiple_hunks_and_files_are_kept_apart(self):
        diff = DIFF + """diff --git a/app/other.py b/app/other.py
--- a/app/other.py
+++ b/app/other.py
@@ -5,2 +5,3 @@
 line 5
+added
 line 6
"""
        hunks = pim.parse_hunks(diff)
        self.assertEqual(len(hunks), 2)
        self.assertEqual([h["file"] for h in hunks], ["app/mod.py", "app/other.py"])

    def test_a_malformed_diff_yields_what_was_parseable(self):
        self.assertEqual(pim.parse_hunks("@@ garbage @@\nnonsense"), [])


class LocateTests(unittest.TestCase):
    def test_an_exact_match_returns_ratio_one(self):
        lines = ORIGINAL_FILE.splitlines()
        pos, ratio = pim.locate_hunk(["line 10", "line 11", "line 12"], lines, 10)
        self.assertEqual((pos, ratio), (10, 1.0))

    def test_no_match_returns_none(self):
        pos, _ = pim.locate_hunk(["nowhere", "to", "be found"], ORIGINAL_FILE.splitlines(), 10)
        self.assertIsNone(pos)

    def test_empty_inputs_return_none(self):
        self.assertEqual(pim.locate_hunk([], ["a"], 1), (None, 0.0))
        self.assertEqual(pim.locate_hunk(["a"], [], 1), (None, 0.0))


if __name__ == "__main__":
    unittest.main()
