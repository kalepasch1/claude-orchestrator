"""
test_intake_dedup.py - Tests for intake semantic deduplication.
Covers candidate_matches on synthetic fixtures: near-dup scores high,
unrelated task scores low. No network required (Jaccard fallback).
"""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.pop("EMBED_PROVIDER", None)
import intake_dedup


class TestTokenize(unittest.TestCase):
    def test_basic(self):
        tokens = intake_dedup._tokenize("Add a login page with OAuth support")
        self.assertIn("login", tokens)
        self.assertIn("page", tokens)
        self.assertIn("oauth", tokens)
        self.assertIn("support", tokens)
        self.assertNotIn("a", tokens)  # single-char excluded
    def test_empty(self):
        self.assertEqual(intake_dedup._tokenize(""), set())
        self.assertEqual(intake_dedup._tokenize(None), set())


class TestJaccard(unittest.TestCase):
    def test_identical(self):
        t = {"aaa", "bbb", "ccc"}
        self.assertAlmostEqual(intake_dedup._jaccard(t, t), 1.0)
    def test_disjoint(self):
        self.assertAlmostEqual(intake_dedup._jaccard({"aaa", "bbb"}, {"ccc", "ddd"}), 0.0)
    def test_partial(self):
        score = intake_dedup._jaccard({"aaa", "bbb", "ccc"}, {"bbb", "ccc", "ddd"})
        self.assertAlmostEqual(score, 2 / 4)
    def test_empty(self):
        self.assertEqual(intake_dedup._jaccard(set(), {"aaa"}), 0.0)


class TestCandidateMatches(unittest.TestCase):
    def test_near_dup_scores_high(self):
        existing = [
            {"ref": "task:add-login", "text": "Add a login page with OAuth support and session management"},
            {"ref": "task:fix-css", "text": "Fix the CSS alignment on the footer navigation bar"},
        ]
        matches = intake_dedup.candidate_matches(
            "Add a login page with OAuth support and user sessions", existing)
        self.assertTrue(len(matches) > 0)
        self.assertEqual(matches[0][0], "task:add-login")
        login_score = dict(matches).get("task:add-login", 0)
        css_score = dict(matches).get("task:fix-css", 0)
        self.assertGreater(login_score, css_score)
    def test_unrelated_scores_low(self):
        existing = [
            {"ref": "task:deploy-k8s", "text": "Deploy kubernetes cluster with helm charts and monitoring"},
        ]
        matches = intake_dedup.candidate_matches(
            "Write unit tests for the billing calculator module", existing)
        if matches:
            self.assertLess(matches[0][1], 0.3)
    def test_empty_prompt(self):
        self.assertEqual(intake_dedup.candidate_matches("", [{"ref": "x", "text": "foo"}]), [])
    def test_empty_existing(self):
        self.assertEqual(intake_dedup.candidate_matches("some prompt", []), [])
    def test_none_existing(self):
        self.assertEqual(intake_dedup.candidate_matches("test", []), [])
    def test_exact_dup_high_score(self):
        text = "Implement a webhook handler for Stripe payment events with retry logic"
        existing = [{"ref": "task:stripe-webhook", "text": text}]
        matches = intake_dedup.candidate_matches(text, existing)
        self.assertEqual(matches[0][0], "task:stripe-webhook")
        self.assertAlmostEqual(matches[0][1], 1.0)
    def test_sorted_descending(self):
        existing = [
            {"ref": "a", "text": "completely different topic about marine biology research"},
            {"ref": "b", "text": "add authentication with login page oauth support sessions"},
            {"ref": "c", "text": "add login page authentication oauth"},
        ]
        matches = intake_dedup.candidate_matches(
            "add login page with oauth authentication support", existing)
        scores = [s for _, s in matches]
        self.assertEqual(scores, sorted(scores, reverse=True))


if __name__ == "__main__":
    unittest.main()
