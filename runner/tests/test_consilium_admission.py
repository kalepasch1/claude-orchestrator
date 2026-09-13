"""Synthetic contract fixtures only. No fixture represents a real accepted card."""
import copy
import datetime as dt
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("admission_contract", Path(__file__).resolve().parents[1] / "consilium_admission.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class AdmissionContractTest(unittest.TestCase):
    def setUp(self):
        self.now = dt.datetime(2026, 9, 13, 19, tzinfo=dt.timezone.utc)
        self.card = {key: None for key in m.FIELDS}
        self.card.update(id="00000000-0000-4000-8000-000000000001", vertical="synthetic",
                         question="Synthetic contract fixture?", position="Synthetic position — not legal advice.",
                         verdict="conditional", confidence=.8, citations=[{"source": "synthetic authority"}],
                         assumptions=["synthetic assumption"], dissent="Synthetic dissent", authority_chain=[],
                         minted_at="2026-09-12T19:00:00Z", status="fresh", publication_state="published",
                         unsettled=False, process={"private": "must not export"})
        self.review = {"id": "00000000-0000-4000-8000-000000000002", "artifact_id": self.card["id"],
                       "artifact_type": "verdict_card", "decision": "publish", "composite": .8,
                       "detail": {"scores": {key: .8 for key in m.WEIGHTS}, "veto": None,
                                  "requires_rereview": False, "reviewed_at": "2026-09-13T17:00:00Z"}}
        self.authorization = {"id": "00000000-0000-4000-8000-000000000003",
                              "reviewer_id": "00000000-0000-4000-8000-000000000004",
                              "schema": "consilium-counsel-authorization/v1", "decision": "approved",
                              "destination": m.DESTINATION, "purpose": "internal_steering",
                              "approved_at": "2026-09-13T18:00:00Z", "expires_at": "2026-09-14T18:00:00Z"}
        self.revocations = {"schema": "consilium-revocations/v1", "destination": m.DESTINATION,
                            "complete": True, "checked_at": "2026-09-13T18:59:00Z",
                            "expires_at": "2026-09-13T19:04:00Z",
                            "artifact_ids": [], "review_ids": [], "authorization_ids": []}
        self.bind()
        self.calls = []

    def bind(self):
        artifact_hash = m.digest(m.artifact_payload(self.card))
        evidence_hash = m.digest(self.card["citations"])
        self.review["detail"].update(artifact_sha256=artifact_hash, evidence_sha256=evidence_hash)
        self.authorization.update(artifact_id=self.card["id"], artifact_sha256=artifact_hash,
                                  evidence_sha256=evidence_hash, review_id=self.review["id"],
                                  review_sha256=m.digest(self.review))

    def verify(self, kind, obj):
        self.calls.append(kind)
        return True  # synthetic fixture verifier, NOT a production verifier

    def admit(self, **kwargs):
        return m.admit(self.card, self.review, self.authorization, self.revocations,
                       now=kwargs.get("now", self.now), purpose=kwargs.get("purpose", "internal_steering"),
                       verify_receipt=kwargs.get("verify_receipt", self.verify))

    def denied(self, result, reason=None):
        self.assertFalse(result["admitted"])
        self.assertIsNone(result["card"])
        if reason:
            self.assertEqual(result["reason"], reason)

    def test_synthetic_admission_has_complete_exact_evidence_not_claimed_uptake(self):
        result = self.admit()
        self.assertTrue(result["admitted"])
        self.assertFalse(result["exported"])
        self.assertFalse(result["absorbed"])
        self.assertEqual(result["value"], "unverified")
        self.assertEqual(result["expires_at"], "2026-09-13T19:04:00+00:00")
        self.assertEqual(result["artifact_sha256"], m.digest(result["card"]))
        self.assertEqual(result["evidence_sha256"], m.digest(result["card"]["citations"]))
        self.assertNotIn("process", result["card"])
        self.assertEqual(self.calls, ["commission_review", "counsel_authorization", "revocation_snapshot"])
        self.card["citations"][0]["source"] = "changed"
        self.assertEqual(result["card"]["citations"][0]["source"], "synthetic authority")

    def test_internal_rejected_and_repair_pending_cards_fail_closed(self):
        for state in ("internal", "commission_review", "attorney_review", "withdrawn", None):
            self.card["publication_state"] = state
            self.denied(self.admit(), "artifact_not_admitted")
        self.card["publication_state"] = "published"
        self.review["decision"] = "reject"
        self.denied(self.admit(), "review_not_accepted")
        self.review["decision"] = "publish"
        self.review["detail"]["requires_rereview"] = True
        self.denied(self.admit(), "review_unsettled")

    def test_state_transition_does_not_change_reviewed_content_hash(self):
        before = m.digest(m.artifact_payload(self.card))
        self.card["publication_state"] = "attorney_review"
        self.assertEqual(before, m.digest(m.artifact_payload(self.card)))
        self.denied(self.admit(), "artifact_not_admitted")

    def test_content_changes_cannot_reuse_review(self):
        original = copy.deepcopy(self.card)
        for field in ("position", "question", "dissent", "conditions", "flips_if"):
            self.card = copy.deepcopy(original)
            self.card[field] = "modified"
            self.denied(self.admit(), "review_content_unbound")
        self.card = copy.deepcopy(original)
        self.card["citations"].append({"source": "changed evidence"})
        self.denied(self.admit(), "review_content_unbound")

    def test_review_change_cannot_reuse_human_authorization(self):
        self.review["detail"]["rationales"] = {"rigor": "changed rationale"}
        self.denied(self.admit(), "authorization_unbound")

    def test_missing_unverified_or_throwing_verifier_cannot_admit(self):
        self.denied(self.admit(verify_receipt=None), "verifier_missing")
        for bad_kind in ("commission_review", "counsel_authorization", "revocation_snapshot"):
            self.denied(self.admit(verify_receipt=lambda kind, obj: kind != bad_kind), "provenance_unverified")
        self.denied(self.admit(verify_receipt=lambda *args: 1), "provenance_unverified")
        def throws(*args):
            raise ValueError("secret")
        result = self.admit(verify_receipt=throws)
        self.denied(result, "admission_verification_failed")
        self.assertNotIn("secret", str(result))

    def test_revocation_of_any_bound_record_prevents_export(self):
        for key, record in (("artifact_ids", self.card), ("review_ids", self.review), ("authorization_ids", self.authorization)):
            self.revocations[key] = [record["id"]]
            self.denied(self.admit(), "revoked")
            self.revocations[key] = []

    def test_unknown_expired_or_incomplete_revocation_state_prevents_export(self):
        original = copy.deepcopy(self.revocations)
        for patch in ({"complete": False}, {"artifact_ids": None}, {"destination": "apparently-law-copy"}):
            self.revocations = {**original, **patch}
            self.denied(self.admit(), "revocation_state_unknown")
        self.revocations = {**original, "checked_at": "2026-09-13T18:55:00Z"}
        self.denied(self.admit(), "revocation_state_stale")
        self.revocations = {**original, "expires_at": "2026-09-13T19:00:00Z"}
        self.denied(self.admit(), "revocation_state_stale")

    def test_timezone_future_and_expiry_boundaries_fail_closed(self):
        self.denied(self.admit(now=self.now.replace(tzinfo=None)), "clock_invalid")
        self.card["minted_at"] = "2026-09-13T20:00:00Z"
        self.denied(self.admit(), "artifact_expired")
        self.card["minted_at"] = "2026-08-14T19:00:00Z"
        self.denied(self.admit(), "artifact_expired")
        self.card["minted_at"] = "2026-09-12T19:00:00"
        self.denied(self.admit(), "timestamp_invalid")

    def test_reviews_and_human_authorization_expire_independently(self):
        self.review["detail"]["reviewed_at"] = "2026-09-01T17:00:00Z"
        self.denied(self.admit(), "review_expired")
        self.review["detail"]["reviewed_at"] = "2026-09-13T17:00:00Z"
        self.bind()
        self.authorization["expires_at"] = "2026-09-13T19:00:00Z"
        self.denied(self.admit(), "authorization_expired")

    def test_cross_destination_or_purpose_authorization_cannot_be_reused(self):
        self.denied(self.admit(purpose="publication"), "authorization_unbound")
        self.authorization["destination"] = "apparently-law-copy"
        self.denied(self.admit(), "authorization_unbound")
        self.denied(self.admit(purpose="anything"), "scope_invalid")

    def test_steering_only_review_cannot_authorize_publication(self):
        self.review["decision"] = "steer_only"
        self.bind()
        self.assertTrue(self.admit()["admitted"])
        self.authorization["purpose"] = "publication"
        self.denied(self.admit(purpose="publication"), "review_not_accepted")

    def test_scores_are_complete_finite_and_consistent_with_current_commission(self):
        original = copy.deepcopy(self.review)
        for value in (float("nan"), float("inf"), True, -.1, 1.1, None):
            self.review = copy.deepcopy(original)
            self.review["detail"]["scores"]["evidence"] = value
            self.denied(self.admit())
        self.review = original
        self.review["composite"] = .99
        self.denied(self.admit(), "review_scores_invalid")

    def test_missing_huge_malformed_and_recursive_evidence_is_not_truncated(self):
        for value in ([], "[]", ["source"], [{}]):
            self.card["citations"] = value
            self.denied(self.admit(), "evidence_invalid")
        self.card["citations"] = [{"source": "x" * 140000}]
        self.denied(self.admit(), "receipt_bounds")
        self.card["citations"] = []
        self.card["citations"].append(self.card["citations"])
        self.denied(self.admit(), "receipt_bounds")

    def test_verifier_cannot_mutate_receipts_or_input_by_reference(self):
        def verifier(kind, obj):
            obj.clear()
            return True
        self.assertTrue(self.admit(verify_receipt=verifier)["admitted"])
        self.assertEqual(self.review["decision"], "publish")


if __name__ == "__main__":
    unittest.main()
