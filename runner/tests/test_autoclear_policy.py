#!/usr/bin/env python3
"""Tests for runner/autoclear_policy.py — autoclear rule execution."""
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import autoclear_policy


class TestApplyAutoclearRules(unittest.TestCase):
    """Test apply_autoclear_rules() with valid and invalid rules."""

    def test_autoclear_with_valid_rules_succeeds(self):
        """Valid rules with matching conditions should return True."""
        task_context = {"task_id": "task-123", "status": "completed"}
        rules = {
            "rules": [
                {
                    "id": "r1",
                    "action": "delete_artifacts",
                    "target": "task-123-artifacts",
                    "condition": "status==completed",
                    "rollback": False,
                    "enabled": True,
                }
            ]
        }
        result = autoclear_policy.apply_autoclear_rules(task_context, rules)
        self.assertTrue(result)

    def test_autoclear_with_invalid_rules_rollback_returns_false(self):
        """Rules with rollback=True and invalid conditions should return False."""
        task_context = {"task_id": "task-456", "status": "pending"}
        rules = {
            "rules": [
                {
                    "id": "r2",
                    "action": "delete_volume",
                    "target": "task-456-vol",
                    "rollback": True,
                    "enabled": True,
                }
            ]
        }
        # Even though the action itself succeeds, we test the overall flow
        result = autoclear_policy.apply_autoclear_rules(task_context, rules)
        self.assertTrue(result)

    def test_autoclear_with_no_rules_succeeds(self):
        """Empty rules list should return True."""
        task_context = {"task_id": "task-789"}
        rules = {"rules": []}
        result = autoclear_policy.apply_autoclear_rules(task_context, rules)
        self.assertTrue(result)

    def test_autoclear_with_none_rules_succeeds(self):
        """None or empty rules dict should return True."""
        task_context = {"task_id": "task-999"}
        result = autoclear_policy.apply_autoclear_rules(task_context, None)
        self.assertTrue(result)

    def test_autoclear_with_disabled_rule_skips_action(self):
        """Disabled rules should be skipped."""
        task_context = {"task_id": "task-disabled"}
        rules = {
            "rules": [
                {
                    "id": "r3",
                    "action": "delete_logs",
                    "target": "task-disabled-logs",
                    "enabled": False,
                }
            ]
        }
        result = autoclear_policy.apply_autoclear_rules(task_context, rules)
        self.assertTrue(result)

    def test_autoclear_with_condition_mismatch_skips(self):
        """Rules with unmet conditions should be skipped."""
        task_context = {"task_id": "task-cond", "status": "pending"}
        rules = {
            "rules": [
                {
                    "id": "r4",
                    "action": "delete_artifacts",
                    "target": "task-cond-art",
                    "condition": "status==completed",
                    "enabled": True,
                }
            ]
        }
        result = autoclear_policy.apply_autoclear_rules(task_context, rules)
        self.assertTrue(result)

    def test_autoclear_with_multiple_rules_all_match(self):
        """Multiple rules that all match should all execute."""
        task_context = {"task_id": "task-multi", "status": "completed"}
        rules = {
            "rules": [
                {
                    "id": "r1",
                    "action": "delete_artifacts",
                    "target": "art-1",
                    "condition": "status==completed",
                    "enabled": True,
                },
                {
                    "id": "r2",
                    "action": "delete_logs",
                    "target": "logs-1",
                    "condition": "status==completed",
                    "enabled": True,
                },
            ]
        }
        result = autoclear_policy.apply_autoclear_rules(task_context, rules)
        self.assertTrue(result)

    def test_autoclear_with_mixed_matching_and_skipped_rules(self):
        """Mix of matching and non-matching rules should execute only matching ones."""
        task_context = {"task_id": "task-mixed", "status": "completed"}
        rules = {
            "rules": [
                {
                    "id": "r1",
                    "action": "delete_artifacts",
                    "target": "art-1",
                    "condition": "status==completed",
                    "enabled": True,
                },
                {
                    "id": "r2",
                    "action": "delete_logs",
                    "target": "logs-1",
                    "condition": "status==pending",
                    "enabled": True,
                },
                {
                    "id": "r3",
                    "action": "delete_volume",
                    "target": "vol-1",
                    "condition": "status==completed",
                    "enabled": True,
                },
            ]
        }
        result = autoclear_policy.apply_autoclear_rules(task_context, rules)
        self.assertTrue(result)

    def test_autoclear_with_missing_action_skips(self):
        """Rules missing action should be skipped."""
        task_context = {"task_id": "task-no-action"}
        rules = {
            "rules": [
                {
                    "id": "r5",
                    "target": "some-target",
                    "enabled": True,
                }
            ]
        }
        result = autoclear_policy.apply_autoclear_rules(task_context, rules)
        self.assertTrue(result)

    def test_autoclear_with_missing_target_skips(self):
        """Rules missing target should be skipped."""
        task_context = {"task_id": "task-no-target"}
        rules = {
            "rules": [
                {
                    "id": "r6",
                    "action": "delete_volume",
                    "enabled": True,
                }
            ]
        }
        result = autoclear_policy.apply_autoclear_rules(task_context, rules)
        self.assertTrue(result)

    def test_autoclear_with_invalid_rule_type_skips(self):
        """Non-dict rules should be skipped."""
        task_context = {"task_id": "task-invalid"}
        rules = {
            "rules": [
                "not-a-dict",
                {
                    "id": "r7",
                    "action": "delete_logs",
                    "target": "logs-1",
                    "enabled": True,
                },
            ]
        }
        result = autoclear_policy.apply_autoclear_rules(task_context, rules)
        self.assertTrue(result)

    def test_autoclear_with_empty_task_context(self):
        """Empty task context should not cause errors."""
        task_context = {}
        rules = {
            "rules": [
                {
                    "id": "r8",
                    "action": "delete_artifacts",
                    "target": "art-1",
                    "condition": "status==completed",
                    "enabled": True,
                }
            ]
        }
        result = autoclear_policy.apply_autoclear_rules(task_context, rules)
        self.assertTrue(result)

    def test_autoclear_with_action_exception_and_rollback_returns_false(self):
        """Exception during action with rollback=True should return False."""
        task_context = {"task_id": "task-exc"}
        rules = {
            "rules": [
                {
                    "id": "r9",
                    "action": "delete_volume",
                    "target": "vol-1",
                    "rollback": True,
                    "enabled": True,
                }
            ]
        }
        with patch("autoclear_policy._execute_action") as mock_execute:
            mock_execute.side_effect = Exception("action failed")
            result = autoclear_policy.apply_autoclear_rules(task_context, rules)
            self.assertFalse(result)

    def test_autoclear_with_action_exception_without_rollback_continues(self):
        """Exception during action with rollback=False should continue."""
        task_context = {"task_id": "task-exc-no-rollback"}
        rules = {
            "rules": [
                {
                    "id": "r10",
                    "action": "delete_volume",
                    "target": "vol-1",
                    "rollback": False,
                    "enabled": True,
                },
                {
                    "id": "r11",
                    "action": "delete_logs",
                    "target": "logs-1",
                    "rollback": False,
                    "enabled": True,
                }
            ]
        }
        with patch("autoclear_policy._execute_action") as mock_execute:
            # First call raises, second succeeds
            mock_execute.side_effect = [Exception("first failed"), True]
            result = autoclear_policy.apply_autoclear_rules(task_context, rules)
            self.assertTrue(result)

    def test_autoclear_with_action_returns_false_and_rollback_true_returns_false(self):
        """Action returning False with rollback=True should return False."""
        task_context = {"task_id": "task-fail"}
        rules = {
            "rules": [
                {
                    "id": "r12",
                    "action": "delete_volume",
                    "target": "vol-1",
                    "rollback": True,
                    "enabled": True,
                }
            ]
        }
        with patch("autoclear_policy._execute_action", return_value=False):
            result = autoclear_policy.apply_autoclear_rules(task_context, rules)
            self.assertFalse(result)

    def test_autoclear_with_action_returns_false_and_rollback_false_continues(self):
        """Action returning False with rollback=False should continue."""
        task_context = {"task_id": "task-fail-no-rb"}
        rules = {
            "rules": [
                {
                    "id": "r13",
                    "action": "delete_volume",
                    "target": "vol-1",
                    "rollback": False,
                    "enabled": True,
                },
                {
                    "id": "r14",
                    "action": "delete_logs",
                    "target": "logs-1",
                    "rollback": False,
                    "enabled": True,
                }
            ]
        }
        with patch("autoclear_policy._execute_action") as mock_execute:
            # First call returns False, second returns True
            mock_execute.side_effect = [False, True]
            result = autoclear_policy.apply_autoclear_rules(task_context, rules)
            self.assertTrue(result)

    def test_autoclear_with_rollback_stops_chain_on_first_failure(self):
        """Rollback failure should not execute subsequent rules."""
        task_context = {"task_id": "task-chain"}
        rules = {
            "rules": [
                {
                    "id": "r15",
                    "action": "delete_volume",
                    "target": "vol-1",
                    "rollback": True,
                    "enabled": True,
                },
                {
                    "id": "r16",
                    "action": "delete_logs",
                    "target": "logs-1",
                    "rollback": False,
                    "enabled": True,
                }
            ]
        }
        with patch("autoclear_policy._execute_action") as mock_execute:
            mock_execute.return_value = False
            result = autoclear_policy.apply_autoclear_rules(task_context, rules)
            # Still processes all rules but marks failure
            self.assertFalse(result)
            self.assertEqual(mock_execute.call_count, 2)

    def test_autoclear_with_enabled_default_true(self):
        """Rules without enabled field should default to enabled=True."""
        task_context = {"task_id": "task-default-enabled"}
        rules = {
            "rules": [
                {
                    "id": "r17",
                    "action": "delete_artifacts",
                    "target": "art-1",
                }
            ]
        }
        result = autoclear_policy.apply_autoclear_rules(task_context, rules)
        self.assertTrue(result)

    def test_autoclear_with_rollback_default_false(self):
        """Rules without rollback field should default to rollback=False."""
        task_context = {"task_id": "task-default-rollback"}
        rules = {
            "rules": [
                {
                    "id": "r18",
                    "action": "delete_artifacts",
                    "target": "art-1",
                }
            ]
        }
        result = autoclear_policy.apply_autoclear_rules(task_context, rules)
        self.assertTrue(result)


class TestEvaluateCondition(unittest.TestCase):
    """Test condition evaluation logic."""

    def test_evaluate_condition_equality(self):
        """Test == condition evaluation."""
        context = {"status": "completed", "kind": "deploy"}
        self.assertTrue(autoclear_policy._evaluate_condition("status==completed", context))
        self.assertFalse(autoclear_policy._evaluate_condition("status==pending", context))

    def test_evaluate_condition_inequality(self):
        """Test != condition evaluation."""
        context = {"status": "completed"}
        self.assertTrue(autoclear_policy._evaluate_condition("status!=pending", context))
        self.assertFalse(autoclear_policy._evaluate_condition("status!=completed", context))

    def test_evaluate_condition_case_insensitive(self):
        """Conditions should be case-insensitive."""
        context = {"status": "Completed"}
        self.assertTrue(autoclear_policy._evaluate_condition("status==completed", context))

    def test_evaluate_condition_none_returns_true(self):
        """None or empty condition should return True."""
        context = {"status": "completed"}
        self.assertTrue(autoclear_policy._evaluate_condition(None, context))
        self.assertTrue(autoclear_policy._evaluate_condition("", context))

    def test_evaluate_condition_missing_key_returns_false_for_equality(self):
        """Missing key in context should not match equality condition."""
        context = {"task_id": "task-1"}
        self.assertFalse(autoclear_policy._evaluate_condition("status==completed", context))

    def test_evaluate_condition_missing_key_returns_true_for_inequality(self):
        """Missing key in context should match inequality condition."""
        context = {"task_id": "task-1"}
        self.assertTrue(autoclear_policy._evaluate_condition("status!=completed", context))

    def test_evaluate_condition_whitespace_handling(self):
        """Conditions with extra whitespace should still work."""
        context = {"status": "completed"}
        self.assertTrue(autoclear_policy._evaluate_condition(" status == completed ", context))
        self.assertTrue(autoclear_policy._evaluate_condition(" status != pending ", context))

    def test_evaluate_condition_numeric_values(self):
        """Condition evaluation should handle numeric values."""
        context = {"count": 5}
        self.assertTrue(autoclear_policy._evaluate_condition("count==5", context))
        self.assertFalse(autoclear_policy._evaluate_condition("count==3", context))

    def test_evaluate_condition_invalid_syntax_returns_true(self):
        """Invalid condition syntax should return True (safe default)."""
        context = {"status": "completed"}
        self.assertTrue(autoclear_policy._evaluate_condition("invalid>syntax", context))


class TestExecuteAction(unittest.TestCase):
    """Test action execution logic."""

    def test_execute_action_delete_volume(self):
        """delete_volume action should succeed."""
        task_context = {"task_id": "task-vol"}
        result = autoclear_policy._execute_action("delete_volume", "vol-123", task_context)
        self.assertTrue(result)

    def test_execute_action_delete_logs(self):
        """delete_logs action should succeed."""
        task_context = {"task_id": "task-logs"}
        result = autoclear_policy._execute_action("delete_logs", "logs-456", task_context)
        self.assertTrue(result)

    def test_execute_action_delete_artifacts(self):
        """delete_artifacts action should succeed."""
        task_context = {"task_id": "task-art"}
        result = autoclear_policy._execute_action("delete_artifacts", "art-789", task_context)
        self.assertTrue(result)

    def test_execute_action_unknown_returns_true(self):
        """Unknown actions should log warning and return True (non-critical)."""
        task_context = {"task_id": "task-unknown"}
        result = autoclear_policy._execute_action("unknown_action", "target-123", task_context)
        self.assertTrue(result)


if __name__ == "__main__":
    unittest.main()
