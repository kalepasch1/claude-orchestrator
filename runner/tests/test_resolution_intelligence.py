#!/usr/bin/env python3
import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import resolution_intelligence as ri

class TestResolutionIntelligence(unittest.TestCase):
    def test_tomorrow_payment_default_routing(self): self.assertEqual(ri.route({"product": "tomorrow", "summary": "Payment obligation may default"})["mode"], "payment_default_war_room")
    def test_unknown_licensing_event_routes_to_apparently(self): self.assertEqual(ri.route({"product": "unknown", "summary": "Regulator deficiency cure deadline"})["product"], "apparently")
    def test_envelope_is_minimal_and_non_executing(self):
        envelope = ri.build_envelope({"product": "smarter", "subjectId": "matter-1", "summary": "Settlement"})
        self.assertFalse(envelope["privatePreferencesIncluded"]); self.assertFalse(envelope["privilegedEvidenceIncluded"])
        self.assertFalse(envelope["authority"]["externalExecution"]); self.assertTrue(envelope["authority"]["humanApprovalRequired"])
        self.assertFalse(envelope["jurisdictionGuard"]["winningOutcomeTransfers"]); self.assertEqual(envelope["jurisdictionGuard"]["parallelRuleValidations"], 3)
        self.assertTrue(envelope["jurisdictionGuard"]["choiceOfLawPreflight"]); self.assertFalse(envelope["jurisdictionGuard"]["consolidatedMeritsAnswerAllowed"])
        self.assertTrue(envelope["jurisdictionGuard"]["invariantProofCertificateRequired"]); self.assertTrue(envelope["jurisdictionGuard"]["jurisdictionDriftBlocksAutonomy"])
        self.assertTrue(envelope["jurisdictionGuard"]["continuousJurisdictionGraph"]); self.assertTrue(envelope["jurisdictionGuard"]["proofCarryingDrafts"])
        self.assertTrue(envelope["jurisdictionGuard"]["bitemporalReconstruction"]); self.assertTrue(envelope["jurisdictionGuard"]["selfHealingWorkProduct"]); self.assertFalse(envelope["jurisdictionGuard"]["silentFinalizedAdviceMutation"])
        self.assertTrue(envelope["jurisdictionGuard"]["causalWorldModel"]); self.assertTrue(envelope["jurisdictionGuard"]["jurisdictionCanaries"]); self.assertFalse(envelope["jurisdictionGuard"]["automaticPromotion"])
    def test_trigger_and_prompt_guidance(self):
        event = {"title": "Counterparty default risk"}; self.assertTrue(ri.should_consider(event)); self.assertIn("human approval", ri.prompt_guidance(event))
    def test_agent_market_is_internal_and_has_dissent(self):
        task=ri.build_agent_market_task({"product":"smarter","summary":"Settlement"})
        self.assertEqual(task["marketType"],"internal_agent_tournament"); self.assertFalse(task["humanProviderMarketplace"]); self.assertFalse(task["externalEngagement"]); self.assertIn("novelty-agent",task["agentRoles"]); self.assertEqual(task["promotionScope"],"jurisdiction_local"); self.assertFalse(task["globalPromotionAllowed"]); self.assertTrue(task["poisoningDefenseRequired"]); self.assertTrue(task["computationReceiptRequired"]); self.assertTrue(task["canaryBeforePromotion"])
    def test_ambient_agent_is_not_a_human_coach_and_cannot_send(self):
        task=ri.build_ambient_agent_task({"product":"tomorrow","summary":"Payment default"},"teams")
        self.assertFalse(task["humanCoach"]); self.assertTrue(task["draftOnly"]); self.assertFalse(task["externalMessageSent"]); self.assertFalse(task["rawContentIncluded"])
    def test_cade_routing_preserves_jurisdiction_and_blocks_winner_transfer(self):
        task=ri.build_agent_market_task({"product":"smarter","summary":"CADE argument","jurisdiction":"US:CFTC"})
        self.assertEqual(task["jurisdiction"],"US:CFTC"); self.assertTrue(task["jurisdictionExplicit"]); self.assertFalse(task["jurisdictionGuard"]["winningOutcomeTransfers"])

if __name__ == "__main__": unittest.main()
