#!/usr/bin/env python3
"""
test_breach_remediation.py - Comprehensive test suite for breach_remediation module.
25+ test cases covering breach detection, self-healing, replacement sourcing,
remediation matter creation, credit penalty application, and end-to-end flow.
"""
import unittest
from unittest.mock import patch, MagicMock, call
import threading
import uuid
from datetime import datetime, timedelta
from runner import breach_remediation


class TestBreachRemediation(unittest.TestCase):
    """Test suite for breach_remediation module."""

    def setUp(self):
        """Reset singleton and clear state before each test."""
        breach_remediation.invalidate()

    def tearDown(self):
        """Clean up after each test."""
        breach_remediation.invalidate()

    # === Happy Path: Breach Detection and Ring Activation ===

    def test_detect_breach_triggers_self_healing_ring(self):
        """detect_breach activates selfHealingRing on valid breach."""
        breach_id = str(uuid.uuid4())
        with patch("runner.breach_remediation.ring.activate") as mock_activate:
            result = breach_remediation.detect_breach(
                breach_id=breach_id,
                contract_id="contract_123",
                affected_parties=["party_a", "party_b"]
            )
            mock_activate.assert_called_once()
            self.assertTrue(result["ring_activated"])

    def test_detect_breach_stores_breach_metadata(self):
        """detect_breach persists breach details to store."""
        breach_id = str(uuid.uuid4())
        with patch("runner.breach_remediation.store.save") as mock_save:
            with patch("runner.breach_remediation.ring.activate"):
                breach_remediation.detect_breach(
                    breach_id=breach_id,
                    contract_id="contract_xyz",
                    affected_parties=["p1", "p2"]
                )
                mock_save.assert_called_once()
                saved_data = mock_save.call_args[0][0]
                self.assertEqual(saved_data["breach_id"], breach_id)
                self.assertEqual(saved_data["contract_id"], "contract_xyz")

    def test_detect_breach_returns_status_dict(self):
        """detect_breach returns status dict with ring_activated and timestamp."""
        with patch("runner.breach_remediation.ring.activate"):
            with patch("runner.breach_remediation.store.save"):
                result = breach_remediation.detect_breach(
                    breach_id="b1",
                    contract_id="c1",
                    affected_parties=["p1"]
                )
                self.assertIn("ring_activated", result)
                self.assertIn("timestamp", result)
                self.assertIn("breach_id", result)

    # === Discovery and Replacement Sourcing ===

    def test_discover_pairings_finds_replacement_parties(self):
        """discover_pairings locates suitable replacement party/parcels."""
        with patch("runner.breach_remediation.discovery.find_candidates") as mock_find:
            mock_find.return_value = ["replacement_party_1", "replacement_party_2"]
            result = breach_remediation.discover_pairings(
                affected_party="party_a",
                parcel_type="data_stream"
            )
            self.assertEqual(len(result["candidates"]), 2)
            self.assertIn("replacement_party_1", result["candidates"])

    def test_discover_pairings_selects_best_candidate(self):
        """discover_pairings scores and selects best candidate."""
        candidates = [
            {"id": "p1", "reliability_score": 0.85},
            {"id": "p2", "reliability_score": 0.95},
            {"id": "p3", "reliability_score": 0.75},
        ]
        with patch("runner.breach_remediation.discovery.find_candidates", return_value=candidates):
            result = breach_remediation.discover_pairings(
                affected_party="party_a",
                parcel_type="data_stream"
            )
            self.assertEqual(result["selected_candidate"]["id"], "p2")
            self.assertGreater(result["selected_candidate"]["reliability_score"], 0.9)

    def test_discover_pairings_empty_candidates_returns_fallback(self):
        """discover_pairings returns fallback when no candidates found."""
        with patch("runner.breach_remediation.discovery.find_candidates", return_value=[]):
            result = breach_remediation.discover_pairings(
                affected_party="party_b",
                parcel_type="backup"
            )
            self.assertIn("fallback_mode", result)
            self.assertTrue(result["fallback_mode"])
            self.assertIn("escalation_required", result)

    # === Honest Party Resumption ===

    def test_resume_honest_parties_initiates_recovery(self):
        """resume_honest_parties notifies affected parties to resume operations."""
        affected = ["party_a", "party_c"]
        with patch("runner.breach_remediation.notifier.send_resume_signal") as mock_notify:
            result = breach_remediation.resume_honest_parties(
                affected_parties=affected,
                replacement_party="replacement_1"
            )
            self.assertEqual(mock_notify.call_count, len(affected))
            self.assertTrue(result["resumed"])

    def test_resume_honest_parties_sets_recovery_timestamp(self):
        """resume_honest_parties records recovery initiation time."""
        with patch("runner.breach_remediation.notifier.send_resume_signal"):
            with patch("runner.breach_remediation.store.save"):
                result = breach_remediation.resume_honest_parties(
                    affected_parties=["p1", "p2"],
                    replacement_party="r1"
                )
                self.assertIn("recovery_timestamp", result)
                self.assertIsInstance(result["recovery_timestamp"], str)

    def test_resume_honest_parties_handles_notification_errors(self):
        """resume_honest_parties continues despite notification failures."""
        with patch("runner.breach_remediation.notifier.send_resume_signal", side_effect=Exception("timeout")):
            result = breach_remediation.resume_honest_parties(
                affected_parties=["p1"],
                replacement_party="r1"
            )
            # Should not raise and should indicate partial success
            self.assertIn("notification_errors", result)

    # === Remediation Matter and Smarter Bridge ===

    def test_open_remediation_matter_creates_warroom(self):
        """open_remediation_matter opens pre-agreed shared-cost matter via warRoomSync."""
        with patch("runner.breach_remediation.smarter.activate_warroom") as mock_warroom:
            mock_warroom.return_value = {"warroom_id": "wr_123", "status": "active"}
            result = breach_remediation.open_remediation_matter(
                breach_id="b1",
                affected_parties=["p1", "p2"],
                cost_share_agreement="pre_agreed_v1"
            )
            mock_warroom.assert_called_once()
            self.assertEqual(result["warroom_id"], "wr_123")
            self.assertEqual(result["status"], "active")

    def test_open_remediation_matter_includes_cost_split(self):
        """open_remediation_matter splits remediation costs per agreement."""
        with patch("runner.breach_remediation.smarter.activate_warroom") as mock_warroom:
            with patch("runner.breach_remediation.cost_calculator.calculate_split") as mock_calc:
                mock_calc.return_value = {"party_a": 50, "party_b": 50}
                result = breach_remediation.open_remediation_matter(
                    breach_id="b1",
                    affected_parties=["party_a", "party_b"],
                    cost_share_agreement="50/50"
                )
                mock_calc.assert_called_once()
                self.assertIn("cost_split", result)

    def test_open_remediation_matter_payload_format(self):
        """open_remediation_matter sends correctly formatted remediation payload."""
        with patch("runner.breach_remediation.smarter.activate_warroom"):
            with patch("runner.breach_remediation.payload.serialize") as mock_serialize:
                breach_remediation.open_remediation_matter(
                    breach_id="b1",
                    affected_parties=["p1"],
                    cost_share_agreement="agreed"
                )
                mock_serialize.assert_called_once()
                payload = mock_serialize.call_args[0][0]
                self.assertIn("breach_details", payload)
                self.assertIn("remediation_scope", payload)

    def test_open_remediation_matter_warroom_activation_fails(self):
        """open_remediation_matter escalates when warRoom activation fails."""
        with patch("runner.breach_remediation.smarter.activate_warroom", side_effect=Exception("service unavailable")):
            result = breach_remediation.open_remediation_matter(
                breach_id="b1",
                affected_parties=["p1"],
                cost_share_agreement="agreed"
            )
            self.assertIn("escalation_triggered", result)
            self.assertTrue(result["escalation_triggered"])

    # === Credit Penalty Application ===

    def test_apply_credit_penalty_on_reveal(self):
        """apply_credit_penalty deducts credits when breach is revealed."""
        affected_party = "party_x"
        penalty_amount = 100
        with patch("runner.breach_remediation.ledger.deduct") as mock_deduct:
            mock_deduct.return_value = {"new_balance": 900, "transaction_id": "tx_abc"}
            result = breach_remediation.apply_credit_penalty(
                party=affected_party,
                penalty_amount=penalty_amount,
                reason="contract_breach_reveal"
            )
            mock_deduct.assert_called_once_with(affected_party, penalty_amount)
            self.assertEqual(result["new_balance"], 900)

    def test_apply_credit_penalty_records_transaction(self):
        """apply_credit_penalty logs penalty transaction for audit trail."""
        with patch("runner.breach_remediation.ledger.deduct"):
            with patch("runner.breach_remediation.audit_log.record") as mock_audit:
                breach_remediation.apply_credit_penalty(
                    party="party_p",
                    penalty_amount=50,
                    reason="breach_remediation"
                )
                mock_audit.assert_called_once()
                audit_record = mock_audit.call_args[0][0]
                self.assertIn("party", audit_record)
                self.assertIn("penalty_amount", audit_record)
                self.assertEqual(audit_record["reason"], "breach_remediation")

    def test_apply_credit_penalty_insufficient_balance(self):
        """apply_credit_penalty returns partial credit when balance insufficient."""
        with patch("runner.breach_remediation.ledger.deduct", return_value={"available": 30, "requested": 100, "partial": True}):
            result = breach_remediation.apply_credit_penalty(
                party="poor_party",
                penalty_amount=100,
                reason="breach"
            )
            self.assertTrue(result.get("partial", False))
            self.assertIn("available", result)

    def test_apply_credit_penalty_ledger_error_propagates(self):
        """apply_credit_penalty returns error status on ledger failure."""
        with patch("runner.breach_remediation.ledger.deduct", side_effect=Exception("ledger timeout")):
            result = breach_remediation.apply_credit_penalty(
                party="party",
                penalty_amount=50,
                reason="breach"
            )
            self.assertIn("error", result)

    # === Contract Resumption ===

    def test_resume_contract_after_remediation(self):
        """resume_contract reactivates contract after remediation complete."""
        contract_id = "contract_123"
        with patch("runner.breach_remediation.contract_engine.reactivate") as mock_reactivate:
            mock_reactivate.return_value = {"status": "active", "resumed_at": datetime.now().isoformat()}
            result = breach_remediation.resume_contract(
                contract_id=contract_id,
                remediation_id="rem_456"
            )
            mock_reactivate.assert_called_once_with(contract_id)
            self.assertEqual(result["status"], "active")

    def test_resume_contract_verifies_replacement_party_integration(self):
        """resume_contract ensures replacement party is integrated into contract."""
        with patch("runner.breach_remediation.contract_engine.reactivate"):
            with patch("runner.breach_remediation.contract_engine.integrate_party") as mock_integrate:
                breach_remediation.resume_contract(
                    contract_id="c1",
                    remediation_id="r1",
                    replacement_party="rep_p1"
                )
                mock_integrate.assert_called_once_with("c1", "rep_p1")

    def test_resume_contract_idempotent(self):
        """resume_contract can be called multiple times safely."""
        with patch("runner.breach_remediation.contract_engine.reactivate") as mock_reactivate:
            mock_reactivate.return_value = {"status": "active"}
            result1 = breach_remediation.resume_contract("c1", "r1")
            result2 = breach_remediation.resume_contract("c1", "r1")
            self.assertEqual(result1["status"], result2["status"])

    # === End-to-End Breach Remediation Flow ===

    def test_orchestrate_breach_remediation_full_flow(self):
        """orchestrate_breach_remediation executes complete remediation pipeline."""
        breach_id = str(uuid.uuid4())
        with patch("runner.breach_remediation.detect_breach") as mock_detect:
            with patch("runner.breach_remediation.discover_pairings") as mock_discover:
                with patch("runner.breach_remediation.resume_honest_parties") as mock_resume:
                    with patch("runner.breach_remediation.open_remediation_matter") as mock_matter:
                        with patch("runner.breach_remediation.apply_credit_penalty") as mock_penalty:
                            with patch("runner.breach_remediation.resume_contract") as mock_contract:
                                mock_detect.return_value = {"ring_activated": True}
                                mock_discover.return_value = {"selected_candidate": {"id": "r1"}}
                                mock_resume.return_value = {"resumed": True}
                                mock_matter.return_value = {"warroom_id": "wr1"}
                                mock_penalty.return_value = {"new_balance": 900}
                                mock_contract.return_value = {"status": "active"}

                                result = breach_remediation.orchestrate_breach_remediation(
                                    breach_id=breach_id,
                                    contract_id="c1",
                                    affected_parties=["p1", "p2"],
                                    parcel_type="data"
                                )

                                self.assertTrue(result["success"])
                                self.assertEqual(result["warroom_id"], "wr1")
                                self.assertEqual(result["contract_status"], "active")

    def test_orchestrate_breach_remediation_returns_complete_payload(self):
        """orchestrate_breach_remediation returns payload with all remediation details."""
        with patch("runner.breach_remediation.detect_breach") as md:
            with patch("runner.breach_remediation.discover_pairings") as mdp:
                with patch("runner.breach_remediation.resume_honest_parties") as mrh:
                    with patch("runner.breach_remediation.open_remediation_matter") as mrm:
                        with patch("runner.breach_remediation.apply_credit_penalty") as macp:
                            with patch("runner.breach_remediation.resume_contract") as mrc:
                                md.return_value = {"ring_activated": True, "timestamp": "2026-08-03T10:00:00"}
                                mdp.return_value = {"selected_candidate": {"id": "repl_1"}}
                                mrh.return_value = {"resumed": True}
                                mrm.return_value = {"warroom_id": "wr_final"}
                                macp.return_value = {"new_balance": 850}
                                mrc.return_value = {"status": "active"}

                                result = breach_remediation.orchestrate_breach_remediation(
                                    breach_id="b1",
                                    contract_id="c1",
                                    affected_parties=["p1"],
                                    parcel_type="stream"
                                )

                                self.assertIn("breach_id", result)
                                self.assertIn("replacement_party", result)
                                self.assertIn("remediation_payload", result)
                                self.assertIn("credit_penalty_applied", result)
                                self.assertIn("contract_status", result)

    def test_orchestrate_breach_remediation_partial_failure_continues(self):
        """orchestrate_breach_remediation continues despite individual step failures."""
        with patch("runner.breach_remediation.detect_breach") as md:
            with patch("runner.breach_remediation.discover_pairings") as mdp:
                with patch("runner.breach_remediation.resume_honest_parties") as mrh:
                    with patch("runner.breach_remediation.open_remediation_matter") as mrm:
                        with patch("runner.breach_remediation.apply_credit_penalty") as macp:
                            with patch("runner.breach_remediation.resume_contract") as mrc:
                                md.return_value = {"ring_activated": True}
                                mdp.return_value = {"selected_candidate": {"id": "r1"}}
                                mrh.side_effect = Exception("notification timeout")
                                mrm.return_value = {"warroom_id": "wr1"}
                                macp.return_value = {"new_balance": 850}
                                mrc.return_value = {"status": "active"}

                                result = breach_remediation.orchestrate_breach_remediation(
                                    breach_id="b1",
                                    contract_id="c1",
                                    affected_parties=["p1"],
                                    parcel_type="stream"
                                )

                                # Should continue despite notification error
                                self.assertIn("warroom_id", result)
                                self.assertIn("partial_failure", result)

    def test_orchestrate_breach_remediation_rollback_on_critical_failure(self):
        """orchestrate_breach_remediation rolls back on critical failures."""
        with patch("runner.breach_remediation.detect_breach", side_effect=Exception("ring activation failed")):
            with patch("runner.breach_remediation.store.cleanup") as mock_cleanup:
                result = breach_remediation.orchestrate_breach_remediation(
                    breach_id="b1",
                    contract_id="c1",
                    affected_parties=["p1"],
                    parcel_type="data"
                )

                self.assertFalse(result["success"])
                mock_cleanup.assert_called_once()

    # === Error Handling and Edge Cases ===

    def test_detect_breach_empty_parties_list(self):
        """detect_breach handles empty affected_parties list."""
        with patch("runner.breach_remediation.ring.activate"):
            with patch("runner.breach_remediation.store.save"):
                result = breach_remediation.detect_breach(
                    breach_id="b1",
                    contract_id="c1",
                    affected_parties=[]
                )
                self.assertIn("warning", result)

    def test_detect_breach_duplicate_party_names(self):
        """detect_breach deduplicates affected_parties."""
        with patch("runner.breach_remediation.store.save") as mock_save:
            with patch("runner.breach_remediation.ring.activate"):
                breach_remediation.detect_breach(
                    breach_id="b1",
                    contract_id="c1",
                    affected_parties=["p1", "p1", "p2", "p1"]
                )
                saved = mock_save.call_args[0][0]
                unique_parties = set(saved["affected_parties"])
                self.assertEqual(len(unique_parties), 2)

    def test_apply_credit_penalty_zero_amount(self):
        """apply_credit_penalty handles zero penalty amount gracefully."""
        with patch("runner.breach_remediation.ledger.deduct"):
            result = breach_remediation.apply_credit_penalty(
                party="p1",
                penalty_amount=0,
                reason="test"
            )
            self.assertIn("amount_validation", result)

    def test_apply_credit_penalty_negative_amount_rejected(self):
        """apply_credit_penalty rejects negative penalty amounts."""
        result = breach_remediation.apply_credit_penalty(
            party="p1",
            penalty_amount=-50,
            reason="test"
        )
        self.assertIn("error", result)
        self.assertIn("negative", result["error"])

    def test_discover_pairings_parcel_type_normalization(self):
        """discover_pairings normalizes parcel_type parameter."""
        with patch("runner.breach_remediation.discovery.find_candidates") as mock_find:
            mock_find.return_value = ["r1"]
            breach_remediation.discover_pairings(
                affected_party="p1",
                parcel_type="DATA_STREAM"
            )
            called_type = mock_find.call_args[1].get("parcel_type")
            self.assertEqual(called_type.lower(), "data_stream")

    # === Concurrency and Thread Safety ===

    def test_concurrent_breach_detection_thread_safe(self):
        """Multiple concurrent breach detections are thread-safe."""
        results = []
        errors = []

        def detect():
            try:
                with patch("runner.breach_remediation.ring.activate"):
                    with patch("runner.breach_remediation.store.save"):
                        r = breach_remediation.detect_breach(
                            breach_id=str(uuid.uuid4()),
                            contract_id="c1",
                            affected_parties=["p1"]
                        )
                        results.append(r)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=detect) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0)
        self.assertEqual(len(results), 5)

    def test_concurrent_remediation_orchestration_no_state_corruption(self):
        """Concurrent orchestrations do not corrupt shared state."""
        results = []
        errors = []

        def orchestrate(breach_id):
            try:
                with patch("runner.breach_remediation.detect_breach") as md:
                    with patch("runner.breach_remediation.discover_pairings") as mdp:
                        with patch("runner.breach_remediation.resume_honest_parties") as mrh:
                            with patch("runner.breach_remediation.open_remediation_matter") as mrm:
                                with patch("runner.breach_remediation.apply_credit_penalty") as macp:
                                    with patch("runner.breach_remediation.resume_contract") as mrc:
                                        md.return_value = {"ring_activated": True}
                                        mdp.return_value = {"selected_candidate": {"id": f"r_{breach_id}"}}
                                        mrh.return_value = {"resumed": True}
                                        mrm.return_value = {"warroom_id": f"wr_{breach_id}"}
                                        macp.return_value = {"new_balance": 800}
                                        mrc.return_value = {"status": "active"}

                                        r = breach_remediation.orchestrate_breach_remediation(
                                            breach_id=breach_id,
                                            contract_id="c1",
                                            affected_parties=["p1"],
                                            parcel_type="data"
                                        )
                                        results.append(r)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=orchestrate, args=(f"b_{i}",)) for i in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0)
        self.assertEqual(len(results), 3)
        # Verify each result has unique identifiers
        breach_ids = [r.get("breach_id") for r in results]
        self.assertEqual(len(set(breach_ids)), 3)

    # === Singleton and Lifecycle ===

    def test_singleton_created_on_first_operation(self):
        """RemediationOrchestrator singleton created on first operation."""
        with patch("runner.breach_remediation.ring.activate"):
            with patch("runner.breach_remediation.store.save"):
                self.assertIsNone(breach_remediation._orchestrator)
                breach_remediation.detect_breach("b1", "c1", ["p1"])
                self.assertIsNotNone(breach_remediation._orchestrator)

    def test_invalidate_clears_singleton(self):
        """invalidate() clears the singleton."""
        with patch("runner.breach_remediation.ring.activate"):
            with patch("runner.breach_remediation.store.save"):
                breach_remediation.detect_breach("b1", "c1", ["p1"])
                self.assertIsNotNone(breach_remediation._orchestrator)
                breach_remediation.invalidate()
                self.assertIsNone(breach_remediation._orchestrator)

    def test_invalidate_creates_fresh_singleton_on_next_call(self):
        """After invalidate(), next call creates fresh singleton."""
        with patch("runner.breach_remediation.ring.activate"):
            with patch("runner.breach_remediation.store.save"):
                breach_remediation.detect_breach("b1", "c1", ["p1"])
                first = breach_remediation._orchestrator
                breach_remediation.invalidate()
                breach_remediation.detect_breach("b2", "c2", ["p2"])
                second = breach_remediation._orchestrator
                self.assertIsNotNone(first)
                self.assertIsNotNone(second)
                self.assertIsNot(first, second)

    # === Integration and State Verification ===

    def test_remediation_state_persisted_end_to_end(self):
        """Remediation state is correctly persisted throughout flow."""
        with patch("runner.breach_remediation.detect_breach") as md:
            with patch("runner.breach_remediation.discover_pairings") as mdp:
                with patch("runner.breach_remediation.resume_honest_parties") as mrh:
                    with patch("runner.breach_remediation.open_remediation_matter") as mrm:
                        with patch("runner.breach_remediation.apply_credit_penalty") as macp:
                            with patch("runner.breach_remediation.resume_contract") as mrc:
                                with patch("runner.breach_remediation.store.save") as mock_store:
                                    md.return_value = {"ring_activated": True}
                                    mdp.return_value = {"selected_candidate": {"id": "r1"}}
                                    mrh.return_value = {"resumed": True}
                                    mrm.return_value = {"warroom_id": "wr1"}
                                    macp.return_value = {"new_balance": 850}
                                    mrc.return_value = {"status": "active"}

                                    breach_remediation.orchestrate_breach_remediation(
                                        breach_id="b_persist",
                                        contract_id="c1",
                                        affected_parties=["p1"],
                                        parcel_type="data"
                                    )

                                    # Verify state was persisted
                                    self.assertGreater(mock_store.call_count, 0)


if __name__ == "__main__":
    unittest.main()
