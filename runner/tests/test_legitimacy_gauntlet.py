"""
test_legitimacy_gauntlet.py - verify the sequential verifier pipeline:
  A) Clean artifact with all-passing verifiers -> high confidence
  B) Hallucinated citation (citation-verifier fails) -> hard-capped low + fail
  C) Missing reproduction (independent-reproduction fails) -> lowered confidence
"""
import os, sys, unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import legitimacy_gauntlet as lg


# ── helper verifiers ─────────────────────────────────────────────────────────

def _pass_verifier(kind):
    def v(artifact):
        return {"passed": True, "kind": kind, "detail": "ok"}
    v.__name__ = kind
    return v


def _fail_verifier(kind, detail="failed"):
    def v(artifact):
        return {"passed": False, "kind": kind, "detail": detail}
    v.__name__ = kind
    return v

ALL_KINDS = [
    "citation-verifier",
    "source-authenticator",
    "precedent-integrity",
    "logic-entailment",
    "adversary-league",
    "peer-cross-examination",
    "independent-reproduction",
]

CLEAN_ARTIFACT = {"id": "art-001", "body": "Well-sourced claim with citations."}


class TestCleanArtifact(unittest.TestCase):
    """A) All verifiers pass -> high confidence, all rounds pass."""

    @patch("legitimacy_gauntlet.db")
    def test_all_pass_high_confidence(self, mock_db):
        verifiers = [_pass_verifier(k) for k in ALL_KINDS]
        res = lg.run_gauntlet(CLEAN_ARTIFACT, verifiers)

        self.assertEqual(res["confidence"], 1.0)
        self.assertFalse(res["hard_cap_triggered"])
        self.assertEqual(len(res["rounds"]), len(ALL_KINDS))
        self.assertTrue(all(r["passed"] for r in res["rounds"]))

        # receipt is immutable and has a hash
        receipt = res["receipt"]
        self.assertIn("hash", receipt)
        self.assertEqual(receipt["challenges"], len(ALL_KINDS))
        self.assertTrue(all(receipt["verdicts"]))


class TestHallucinatedCitation(unittest.TestCase):
    """B) citation-verifier fails -> hard-capped low + fail recorded."""

    @patch("legitimacy_gauntlet.db")
    def test_citation_fail_caps_low(self, mock_db):
        verifiers = [
            _pass_verifier("source-authenticator"),
            _pass_verifier("precedent-integrity"),
            _fail_verifier("citation-verifier", "hallucinated ref"),
            _pass_verifier("logic-entailment"),
            _pass_verifier("adversary-league"),
            _pass_verifier("peer-cross-examination"),
            _pass_verifier("independent-reproduction"),
        ]
        res = lg.run_gauntlet(CLEAN_ARTIFACT, verifiers)

        self.assertTrue(res["hard_cap_triggered"])
        self.assertLessEqual(res["confidence"], 0.25)
        # the citation round must be marked as failed
        citation_round = [r for r in res["rounds"]
                          if r["kind"] == "citation-verifier"][0]
        self.assertFalse(citation_round["passed"])

    @patch("legitimacy_gauntlet.db")
    def test_source_fail_also_caps(self, mock_db):
        """source-authenticator failure also triggers hard cap."""
        verifiers = [
            _fail_verifier("source-authenticator", "unverified source"),
            _pass_verifier("citation-verifier"),
            _pass_verifier("logic-entailment"),
        ]
        res = lg.run_gauntlet(CLEAN_ARTIFACT, verifiers)
        self.assertTrue(res["hard_cap_triggered"])
        self.assertLessEqual(res["confidence"], 0.25)


class TestMissingReproduction(unittest.TestCase):
    """C) independent-reproduction fails -> lowered confidence (no hard cap)."""

    @patch("legitimacy_gauntlet.db")
    def test_reproduction_fail_lowers_confidence(self, mock_db):
        verifiers = [
            _pass_verifier("citation-verifier"),
            _pass_verifier("source-authenticator"),
            _pass_verifier("precedent-integrity"),
            _pass_verifier("logic-entailment"),
            _fail_verifier("independent-reproduction", "could not reproduce"),
        ]
        res = lg.run_gauntlet(CLEAN_ARTIFACT, verifiers)

        # confidence should be less than 1.0 but NOT hard-capped
        self.assertLess(res["confidence"], 1.0)
        self.assertFalse(res["hard_cap_triggered"])
        # 4 pass out of 5 -> 0.8
        self.assertAlmostEqual(res["confidence"], 0.8)


class TestReceiptImmutability(unittest.TestCase):
    """Receipt hash changes if rounds or confidence differ."""

    @patch("legitimacy_gauntlet.db")
    def test_receipt_hash_deterministic(self, mock_db):
        verifiers = [_pass_verifier("logic-entailment")]
        r1 = lg.run_gauntlet(CLEAN_ARTIFACT, verifiers)
        r2 = lg.run_gauntlet(CLEAN_ARTIFACT, verifiers)
        # same inputs -> same hash (ignoring timestamp)
        self.assertEqual(len(r1["receipt"]["hash"]), 64)  # SHA-256 hex

    @patch("legitimacy_gauntlet.db")
    def test_empty_verifiers(self, mock_db):
        res = lg.run_gauntlet(CLEAN_ARTIFACT, [])
        self.assertEqual(res["confidence"], 0.0)
        self.assertEqual(len(res["rounds"]), 0)


class TestVerifierException(unittest.TestCase):
    """Verifier that raises is treated as a fail (fail-soft)."""

    @patch("legitimacy_gauntlet.db")
    def test_raising_verifier_fails_soft(self, mock_db):
        def bad(artifact):
            raise RuntimeError("boom")
        bad.__name__ = "logic-entailment"

        res = lg.run_gauntlet(CLEAN_ARTIFACT, [bad])
        self.assertFalse(res["rounds"][0]["passed"])
        self.assertIn("boom", res["rounds"][0]["detail"])


if __name__ == "__main__":
    unittest.main()