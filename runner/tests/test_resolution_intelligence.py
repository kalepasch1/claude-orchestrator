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
    def test_trigger_and_prompt_guidance(self):
        event = {"title": "Counterparty default risk"}; self.assertTrue(ri.should_consider(event)); self.assertIn("human approval", ri.prompt_guidance(event))

if __name__ == "__main__": unittest.main()
