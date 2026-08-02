import unittest
from unittest.mock import patch, MagicMock
import math
import logging
from prompt_evolver import PromptEvolver, TEMPLATE_IDS


class TestPromptEvolver(unittest.TestCase):

    def setUp(self):
        self.evolver = PromptEvolver()
        self.base_prompt = "Generate a summary"

    @patch("prompt_evolver.db")
    def test_cold_start_returns_base(self, mock_db):
        """When DB has no templates for a kind, return base prompt"""
        mock_db.query.return_value = []

        prompt, template_id = self.evolver.select_template("code_gen", self.base_prompt)

        self.assertEqual(prompt, self.base_prompt)
        self.assertEqual(template_id, "base")

    @patch("prompt_evolver.db")
    def test_ucb_prefers_untried_arm(self, mock_db):
        """UCB1 prefers untried arms (n_trials=0) over tried arms"""
        mock_db.query.return_value = [
            {"kind": "code_gen", "template_id": "chain_of_thought", "total_reward": 4.0, "n_trials": 5},
            {"kind": "code_gen", "template_id": "edit_first", "total_reward": 0.0, "n_trials": 0},
        ]

        prompt, template_id = self.evolver.select_template("code_gen", self.base_prompt)

        self.assertEqual(template_id, "edit_first")
        self.assertTrue(prompt.startswith("[template:edit_first]\n"))

    @patch("prompt_evolver.db")
    def test_ucb_calculation_for_tried_arms(self, mock_db):
        """When all arms are tried, selects highest UCB1 score"""
        # N=10 total, arm1: mean=0.8, n=5, ucb = 0.8 + sqrt(2*ln(10)/5) ≈ 1.55
        # arm2: mean=0.6, n=5, ucb = 0.6 + sqrt(2*ln(10)/5) ≈ 1.35
        mock_db.query.return_value = [
            {"kind": "code_gen", "template_id": "chain_of_thought", "total_reward": 4.0, "n_trials": 5},
            {"kind": "code_gen", "template_id": "edit_first", "total_reward": 3.0, "n_trials": 5},
        ]

        prompt, template_id = self.evolver.select_template("code_gen", self.base_prompt)

        self.assertEqual(template_id, "chain_of_thought")

    @patch("prompt_evolver.db")
    def test_template_tag_prepending(self, mock_db):
        """Non-base templates should have tag prepended; base returns unmodified"""
        mock_db.query.return_value = [
            {"kind": "code_gen", "template_id": "base", "total_reward": 1.0, "n_trials": 1},
        ]

        prompt, template_id = self.evolver.select_template("code_gen", self.base_prompt)

        self.assertEqual(template_id, "base")
        self.assertEqual(prompt, self.base_prompt)

    @patch("prompt_evolver.db")
    def test_record_outcome_success(self, mock_db):
        """record_outcome inserts with merge-duplicates resolution"""
        self.evolver.record_outcome("code_gen", "chain_of_thought", merged_first_try=True)

        mock_db.insert.assert_called_once()
        call_args = mock_db.insert.call_args
        self.assertEqual(call_args[0][0], "prompt_templates")
        self.assertEqual(call_args[1]["resolution"], "merge-duplicates")
        self.assertEqual(call_args[0][1]["total_reward"], 1.0)
        self.assertEqual(call_args[0][1]["kind"], "code_gen")
        self.assertEqual(call_args[0][1]["template_id"], "chain_of_thought")

    @patch("prompt_evolver.db")
    def test_record_outcome_failure(self, mock_db):
        """record_outcome with merged_first_try=False has reward 0.0"""
        self.evolver.record_outcome("code_gen", "edit_first", merged_first_try=False)

        call_args = mock_db.insert.call_args
        self.assertEqual(call_args[0][1]["total_reward"], 0.0)

    @patch("prompt_evolver.db")
    def test_record_outcome_swallows_exceptions(self, mock_db):
        """record_outcome logs but doesn't raise on DB error"""
        mock_db.insert.side_effect = Exception("DB connection failed")

        # Should not raise
        try:
            self.evolver.record_outcome("code_gen", "chain_of_thought", merged_first_try=True)
        except Exception:
            self.fail("record_outcome raised exception instead of swallowing it")

    @patch("prompt_evolver.db")
    def test_select_template_db_error(self, mock_db):
        """select_template returns base on DB error"""
        mock_db.query.side_effect = Exception("DB connection failed")

        prompt, template_id = self.evolver.select_template("code_gen", self.base_prompt)

        self.assertEqual(prompt, self.base_prompt)
        self.assertEqual(template_id, "base")


if __name__ == "__main__":
    unittest.main()
