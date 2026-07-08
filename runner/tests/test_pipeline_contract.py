import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pipeline_contract


class PipelineContractTest(unittest.TestCase):

    def _route(self, app, operation, task_class="qa", agentic=False, need=None):
        return {
            "provider": "deepseek" if task_class != "plan" else "google",
            "model": "deepseek-chat" if task_class != "plan" else "gemini-2.0-flash",
            "reason": f"test {operation}",
            "source": "test",
        }

    def test_wrap_prompt_adds_shared_contract(self):
        with patch.object(pipeline_contract.app_triage, "route", side_effect=self._route), \
             patch.object(pipeline_contract.agentic_coders, "pick", return_value="claude"), \
             patch.object(pipeline_contract, "_recent_context", return_value=["recent outcome signal: ok"]), \
             patch.object(pipeline_contract, "_qa_panel", return_value=["openai:gpt-4o-mini"]):
            wrapped = pipeline_contract.wrap_prompt(
                "Build a faster queue dashboard.",
                project="beethoven",
                kind="build",
                source="dashboard-user-driven",
                slug="queue-dashboard",
            )

        self.assertIn(pipeline_contract.MARKER, wrapped)
        self.assertIn("dashboard-user-driven", wrapped)
        self.assertIn("preflight triage", wrapped)
        self.assertIn("strategy planner", wrapped)
        self.assertIn("auto-merge", wrapped.lower())
        self.assertEqual(pipeline_contract.original_request(wrapped), "Build a faster queue dashboard.")

    def test_wrap_prompt_is_idempotent_for_existing_contract(self):
        text = f"## {pipeline_contract.MARKER}\n- x\n## END {pipeline_contract.MARKER}\n\nbody"
        self.assertEqual(pipeline_contract.wrap_prompt(text, project="x"), text)

    def test_control_prompts_are_not_wrapped(self):
        text = "ROTATE_KEY:openai:primary"
        self.assertEqual(pipeline_contract.wrap_prompt(text, project="x"), text)

    def test_legal_posture_changes_are_classified_as_legal(self):
        cls = pipeline_contract.classify(
            "Change the product so we custody customer funds and become a money transmitter.",
            kind="build",
        )
        self.assertEqual(cls["task_class"], "legal")
        self.assertEqual(cls["need"], 9)


if __name__ == "__main__":
    unittest.main()
