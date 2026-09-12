"""No model, network, or production database calls."""
import importlib.util
import json
import hashlib
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch


class ReviewIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.db = types.SimpleNamespace(select=Mock(return_value=[]), insert=Mock(return_value={"id": "saved"}), update=Mock(return_value=[{"id": "card"}]))
        self.frontier = types.SimpleNamespace(
            codex_available=lambda: False, WEB_TOOLS=["WebFetch"],
            complete=Mock(return_value={"json": {"score": .8, "rationale": "checked"}}),
            local_complete=Mock(side_effect=AssertionError("no local fallback")))
        self.modules = patch.dict(sys.modules, {"db": self.db, "frontier": self.frontier})
        self.modules.start()
        self.addCleanup(self.modules.stop)
        spec = importlib.util.spec_from_file_location("review_integrity", Path(__file__).resolve().parents[1] / "publication_commission.py")
        self.pc = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.pc)

    def test_evidence_is_valid_complete_json_not_cut_at_9000(self):
        art = {"content": "x" * 12000, "citations": [{"url": "https://example.test/authority", "quote": "q" * 9000}]}
        self.assertEqual(self.pc._score_one("evidence", "check", art)["score"], .8)
        sent = self.frontier.complete.call_args.args[0].removeprefix("ARTIFACT:\n")
        payload = json.loads(sent)
        self.assertEqual(payload["citations"], art["citations"])
        self.assertEqual(payload["content"], art["content"])

    def test_oversized_evidence_defers_without_model(self):
        result = self.pc.review_artifact({"content": "x" * 96001})
        self.assertEqual(result["decision"], "deferred")
        self.frontier.complete.assert_not_called()

    def test_invalid_scores_never_become_merits_rejections_or_passes(self):
        for score in [float("nan"), float("inf"), True, -.1, 1.1, "0.9", None]:
            with self.subTest(score=score):
                self.frontier.complete.return_value = {"json": {"score": score}}
                self.assertEqual(self.pc.review_artifact({})["decision"], "deferred")
        self.frontier.local_complete.assert_not_called()

    def test_unavailable_review_does_not_persist_or_mutate_card(self):
        self.frontier.complete.return_value = {"error": "budget unavailable"}
        self.pc._candidates = lambda _: [{"id": "card", "type": "verdict_card"}]
        result = self.pc.run(1)
        self.assertEqual(result["deferred"], 1)
        self.assertEqual(result["reviewed"], 0)
        self.db.insert.assert_not_called()
        self.db.update.assert_not_called()

    def test_unconfirmed_review_write_never_advances_card(self):
        self.db.insert.return_value = None
        self.pc._candidates = lambda _: [{"id": "card", "type": "verdict_card"}]
        result = self.pc.run(1)
        self.assertEqual(result["persist_failed"], 1)
        self.assertEqual(result["reviewed"], 0)
        self.db.update.assert_not_called()

    def test_state_map_matches_live_schema_and_never_self_publishes(self):
        states = {"internal", "commission_review", "attorney_review", "published", "withdrawn"}
        self.assertTrue(set(self.pc.CARD_STATE.values()) <= states)
        self.assertNotIn("published", self.pc.CARD_STATE.values())
        self.pc._candidates = lambda _: [{"id": "card", "type": "verdict_card"}]
        result = self.pc.run(1)
        self.assertEqual(result["reviewed"], 1)
        self.assertEqual(self.db.update.call_args.args[2], {"publication_state": "attorney_review"})

    def test_repair_receipt_binds_rereview_to_exact_citations(self):
        cites = [{"url": "https://example.test/rule", "quote": "source"}]
        digest = hashlib.sha256(json.dumps(cites, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        prior = {"id": "review", "artifact_id": "card", "artifact_type": "verdict_card", "decision": "reject",
                 "created_at": "2026-09-12T00:00:00Z", "detail": {"requires_rereview": True, "repaired_citations_sha256": digest}}
        def select(table, params):
            return [prior] if table == "publication_reviews" else ([{"id": "card", "process": "consilium_v2", "citations": cites}] if table == "verdict_cards" else [])
        self.db.select.side_effect = select
        self.assertEqual(self.pc._candidates(1)[0]["prior_review"], prior)
        prior["detail"]["repaired_citations_sha256"] = "mismatch"
        self.assertEqual(self.pc._candidates(1), [])

    def test_rereview_keeps_old_rejection_in_history(self):
        prior = {"id": "review", "artifact_id": "card", "artifact_type": "verdict_card", "decision": "reject",
                 "created_at": "2026-09-12T00:00:00Z", "detail": {"requires_rereview": True, "veto": "evidence floor"}}
        self.pc._candidates = lambda _: [{"id": "card", "type": "verdict_card", "prior_review": prior}]
        result = self.pc.run(1)
        self.assertEqual(result["reviewed"], 1)
        row = self.db.update.call_args_list[0].args[2]
        self.assertEqual(row["detail"]["previous_review"], prior)
        self.assertNotIn("requires_rereview", row["detail"])
        self.db.insert.assert_not_called()


if __name__ == "__main__":
    unittest.main()
