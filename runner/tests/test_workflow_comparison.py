import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import workflow_comparison


class WorkflowComparisonTest(unittest.TestCase):
    def test_native_claude_is_not_mislabeled_as_cowork(self):
        self.assertEqual("orchestrator_native", workflow_comparison.workflow_for_outcome(
            {"model": "claude-sonnet-4-6"}))
        self.assertEqual("cowork", workflow_comparison.workflow_for_outcome(
            {"model": "cowork-executor"}))

    def test_cleared_cowork_account_is_recovered_from_note(self):
        self.assertEqual("cowork", workflow_comparison.workflow_for_task(
            {"account": None, "note": "cowork-executor: implemented and pushed"}))
        self.assertEqual("orchestrator_native", workflow_comparison.workflow_for_task(
            {"account": None, "note": "agentic coder: claude"}))

    def test_summarizes_delivery_stages_separately(self):
        rows = [
            {"model": "cowork-executor", "slug": "a", "tests_passed": True},
            {"model": "ollama", "slug": "b", "tests_passed": True,
             "integrated": True, "deployed": True, "wall_ms": 2000},
            {"model": "deepseek", "slug": "c", "tests_passed": False},
        ]
        result = workflow_comparison.summarize_outcomes(rows, 2)
        self.assertEqual(1, result["cowork"]["tests_passed"])
        self.assertEqual(1, result["orchestrator_native"]["integrated"])
        self.assertEqual(1, result["orchestrator_native"]["deployed"])
        self.assertEqual(0.5, result["orchestrator_native"]["pass_rate"])

    def test_time_parser_handles_postgrest_timestamps(self):
        parsed = workflow_comparison._parse_time("2026-07-15T07:06:10.037319+00:00")
        self.assertEqual(7, parsed.hour)


if __name__ == "__main__":
    unittest.main()
