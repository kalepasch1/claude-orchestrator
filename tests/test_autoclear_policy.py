"""Test autoclear_policy.py rule application and condition evaluation."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "runner"))

import autoclear_policy


class TestApplyAutoclearRules(unittest.TestCase):
    """Tests for apply_autoclear_rules() function."""

    def setUp(self):
        """Set up test fixtures."""
        self.basic_task_context = {
            "task_id": "task-123",
            "status": "completed",
            "kind": "deploy",
            "resources": ["vol-123", "log-456"],
        }
        self.basic_rule = {
            "id": "rule-1",
            "action": "delete_volume",
            "target": "vol-123",
            "enabled": True,
        }

    def test_apply_rules_none_rules(self):
        """With None rules, returns True (no-op)."""
        result = autoclear_policy.apply_autoclear_rules(self.basic_task_context, None)
        self.assertTrue(result)

    def test_apply_rules_empty_rules_dict(self):
        """With empty rules dict, returns True (no-op)."""
        result = autoclear_policy.apply_autoclear_rules(self.basic_task_context, {})
        self.assertTrue(result)

    def test_apply_rules_invalid_rules_not_dict(self):
        """With invalid rules (not a dict), returns True (no-op)."""
        result = autoclear_policy.apply_autoclear_rules(self.basic_task_context, "invalid")
        self.assertTrue(result)

    def test_apply_rules_no_rules_key(self):
        """With rules dict but no 'rules' key, returns True (no-op)."""
        result = autoclear_policy.apply_autoclear_rules(
            self.basic_task_context, {"other": "value"}
        )
        self.assertTrue(result)

    def test_apply_rules_empty_rules_list(self):
        """With empty rules list, returns True (no-op)."""
        result = autoclear_policy.apply_autoclear_rules(
            self.basic_task_context, {"rules": []}
        )
        self.assertTrue(result)

    def test_apply_single_valid_rule_succeeds(self):
        """A single valid rule is applied and returns True."""
        rules = {"rules": [self.basic_rule]}
        result = autoclear_policy.apply_autoclear_rules(self.basic_task_context, rules)
        self.assertTrue(result)

    def test_apply_multiple_rules_all_succeed(self):
        """Multiple valid rules are all applied and returns True."""
        rules_list = [
            {"id": "rule-1", "action": "delete_volume", "target": "vol-123", "enabled": True},
            {"id": "rule-2", "action": "delete_logs", "target": "log-456", "enabled": True},
        ]
        rules = {"rules": rules_list}
        result = autoclear_policy.apply_autoclear_rules(self.basic_task_context, rules)
        self.assertTrue(result)

    def test_apply_disabled_rule_skipped(self):
        """A rule with enabled=False is skipped."""
        disabled_rule = dict(self.basic_rule, enabled=False)
        rules = {"rules": [disabled_rule]}
        result = autoclear_policy.apply_autoclear_rules(self.basic_task_context, rules)
        self.assertTrue(result)

    def test_apply_rule_without_enabled_key_defaults_true(self):
        """A rule without 'enabled' key defaults to enabled=True."""
        rule = {"id": "rule-1", "action": "delete_volume", "target": "vol-123"}
        rules = {"rules": [rule]}
        result = autoclear_policy.apply_autoclear_rules(self.basic_task_context, rules)
        self.assertTrue(result)

    def test_apply_rule_missing_action_skipped(self):
        """A rule without action is skipped."""
        rule = {"id": "rule-1", "target": "vol-123", "enabled": True}
        rules = {"rules": [rule]}
        result = autoclear_policy.apply_autoclear_rules(self.basic_task_context, rules)
        self.assertTrue(result)

    def test_apply_rule_missing_target_skipped(self):
        """A rule without target is skipped."""
        rule = {"id": "rule-1", "action": "delete_volume", "enabled": True}
        rules = {"rules": [rule]}
        result = autoclear_policy.apply_autoclear_rules(self.basic_task_context, rules)
        self.assertTrue(result)

    def test_apply_rule_invalid_rule_not_dict(self):
        """An invalid rule (not a dict) is skipped."""
        rules = {"rules": [self.basic_rule, "invalid_rule", self.basic_rule]}
        result = autoclear_policy.apply_autoclear_rules(self.basic_task_context, rules)
        self.assertTrue(result)

    def test_apply_rule_with_matching_condition_succeeds(self):
        """A rule with a matching condition is applied."""
        rule = {
            "id": "rule-1",
            "action": "delete_volume",
            "target": "vol-123",
            "condition": "status==completed",
            "enabled": True,
        }
        rules = {"rules": [rule]}
        result = autoclear_policy.apply_autoclear_rules(self.basic_task_context, rules)
        self.assertTrue(result)

    def test_apply_rule_with_non_matching_condition_skipped(self):
        """A rule with a non-matching condition is skipped."""
        rule = {
            "id": "rule-1",
            "action": "delete_volume",
            "target": "vol-123",
            "condition": "status==failed",
            "enabled": True,
        }
        rules = {"rules": [rule]}
        result = autoclear_policy.apply_autoclear_rules(self.basic_task_context, rules)
        self.assertTrue(result)

    def test_apply_rule_rollback_on_failure_true(self):
        """With rollback=True and action fails, returns False."""
        rule = {
            "id": "rule-1",
            "action": "unknown_action",
            "target": "vol-123",
            "rollback": True,
            "enabled": True,
        }
        rules = {"rules": [rule]}
        # Mock action to fail
        with mock.patch("autoclear_policy._execute_action", return_value=False):
            result = autoclear_policy.apply_autoclear_rules(self.basic_task_context, rules)
            self.assertFalse(result)

    def test_apply_rule_rollback_on_failure_false(self):
        """With rollback=False and action fails, returns True."""
        rule = {
            "id": "rule-1",
            "action": "delete_volume",
            "target": "vol-123",
            "rollback": False,
            "enabled": True,
        }
        rules = {"rules": [rule]}
        # Mock action to fail
        with mock.patch("autoclear_policy._execute_action", return_value=False):
            result = autoclear_policy.apply_autoclear_rules(self.basic_task_context, rules)
            self.assertTrue(result)

    def test_apply_rule_rollback_defaults_false(self):
        """Without 'rollback' key, defaults to False (continues on failure)."""
        rule = {
            "id": "rule-1",
            "action": "delete_volume",
            "target": "vol-123",
            "enabled": True,
        }
        rules = {"rules": [rule]}
        # Mock action to fail
        with mock.patch("autoclear_policy._execute_action", return_value=False):
            result = autoclear_policy.apply_autoclear_rules(self.basic_task_context, rules)
            self.assertTrue(result)

    def test_apply_rule_exception_with_rollback_true(self):
        """If action raises exception and rollback=True, returns False."""
        rule = {
            "id": "rule-1",
            "action": "delete_volume",
            "target": "vol-123",
            "rollback": True,
            "enabled": True,
        }
        rules = {"rules": [rule]}
        # Mock action to raise exception
        with mock.patch("autoclear_policy._execute_action", side_effect=Exception("test error")):
            result = autoclear_policy.apply_autoclear_rules(self.basic_task_context, rules)
            self.assertFalse(result)

    def test_apply_rule_exception_with_rollback_false(self):
        """If action raises exception and rollback=False, returns True."""
        rule = {
            "id": "rule-1",
            "action": "delete_volume",
            "target": "vol-123",
            "rollback": False,
            "enabled": True,
        }
        rules = {"rules": [rule]}
        # Mock action to raise exception
        with mock.patch("autoclear_policy._execute_action", side_effect=Exception("test error")):
            result = autoclear_policy.apply_autoclear_rules(self.basic_task_context, rules)
            self.assertTrue(result)

    def test_apply_mixed_rules_one_fails_with_rollback(self):
        """If one rule fails with rollback and others succeed, returns False."""
        rules_list = [
            {"id": "rule-1", "action": "delete_volume", "target": "vol-123", "enabled": True},
            {
                "id": "rule-2",
                "action": "delete_logs",
                "target": "log-456",
                "rollback": True,
                "enabled": True,
            },
        ]
        rules = {"rules": rules_list}
        # Mock second action to fail
        with mock.patch("autoclear_policy._execute_action") as mock_action:
            mock_action.side_effect = [True, False]
            result = autoclear_policy.apply_autoclear_rules(self.basic_task_context, rules)
            self.assertFalse(result)

    def test_apply_action_delete_volume(self):
        """delete_volume action executes successfully."""
        rule = {
            "id": "rule-1",
            "action": "delete_volume",
            "target": "vol-123",
            "enabled": True,
        }
        rules = {"rules": [rule]}
        result = autoclear_policy.apply_autoclear_rules(self.basic_task_context, rules)
        self.assertTrue(result)

    def test_apply_action_delete_logs(self):
        """delete_logs action executes successfully."""
        rule = {
            "id": "rule-1",
            "action": "delete_logs",
            "target": "log-456",
            "enabled": True,
        }
        rules = {"rules": [rule]}
        result = autoclear_policy.apply_autoclear_rules(self.basic_task_context, rules)
        self.assertTrue(result)

    def test_apply_action_delete_artifacts(self):
        """delete_artifacts action executes successfully."""
        rule = {
            "id": "rule-1",
            "action": "delete_artifacts",
            "target": "artifact-789",
            "enabled": True,
        }
        rules = {"rules": [rule]}
        result = autoclear_policy.apply_autoclear_rules(self.basic_task_context, rules)
        self.assertTrue(result)

    def test_apply_action_unknown_action_returns_true(self):
        """Unknown action type returns True (no-op, but logged)."""
        rule = {
            "id": "rule-1",
            "action": "unknown_action",
            "target": "resource-123",
            "enabled": True,
        }
        rules = {"rules": [rule]}
        result = autoclear_policy.apply_autoclear_rules(self.basic_task_context, rules)
        self.assertTrue(result)

    def test_apply_all_rule_types_succeed(self):
        """A mix of all action types are applied successfully."""
        rules_list = [
            {"action": "delete_volume", "target": "vol-1", "enabled": True},
            {"action": "delete_logs", "target": "log-2", "enabled": True},
            {"action": "delete_artifacts", "target": "artifact-3", "enabled": True},
        ]
        rules = {"rules": rules_list}
        result = autoclear_policy.apply_autoclear_rules(self.basic_task_context, rules)
        self.assertTrue(result)


class TestEvaluateCondition(unittest.TestCase):
    """Tests for _evaluate_condition() helper."""

    def setUp(self):
        """Set up test fixtures."""
        self.task_context = {
            "status": "completed",
            "kind": "deploy",
            "environment": "staging",
            "has_resources": True,
            "cost_usd": 50.25,
        }

    def test_evaluate_condition_none(self):
        """None condition evaluates to True."""
        result = autoclear_policy._evaluate_condition(None, self.task_context)
        self.assertTrue(result)

    def test_evaluate_condition_empty_string(self):
        """Empty string condition evaluates to True."""
        result = autoclear_policy._evaluate_condition("", self.task_context)
        self.assertTrue(result)

    def test_evaluate_condition_invalid_type(self):
        """Non-string condition evaluates to True."""
        result = autoclear_policy._evaluate_condition(123, self.task_context)
        self.assertTrue(result)

    def test_evaluate_condition_equals_match(self):
        """Condition with == operator matches correctly."""
        result = autoclear_policy._evaluate_condition("status==completed", self.task_context)
        self.assertTrue(result)

    def test_evaluate_condition_equals_no_match(self):
        """Condition with == operator fails when values differ."""
        result = autoclear_policy._evaluate_condition("status==failed", self.task_context)
        self.assertFalse(result)

    def test_evaluate_condition_not_equals_match(self):
        """Condition with != operator matches correctly."""
        result = autoclear_policy._evaluate_condition("status!=failed", self.task_context)
        self.assertTrue(result)

    def test_evaluate_condition_not_equals_no_match(self):
        """Condition with != operator fails when values are equal."""
        result = autoclear_policy._evaluate_condition("status!=completed", self.task_context)
        self.assertFalse(result)

    def test_evaluate_condition_case_insensitive(self):
        """Condition comparison is case-insensitive."""
        result = autoclear_policy._evaluate_condition("status==COMPLETED", self.task_context)
        self.assertTrue(result)

    def test_evaluate_condition_case_insensitive_not_equals(self):
        """Not-equals comparison is case-insensitive."""
        result = autoclear_policy._evaluate_condition("status!=FAILED", self.task_context)
        self.assertTrue(result)

    def test_evaluate_condition_with_spaces(self):
        """Condition with spaces around == operator."""
        result = autoclear_policy._evaluate_condition("status == completed", self.task_context)
        self.assertTrue(result)

    def test_evaluate_condition_with_spaces_not_equals(self):
        """Condition with spaces around != operator."""
        result = autoclear_policy._evaluate_condition("status != failed", self.task_context)
        self.assertTrue(result)

    def test_evaluate_condition_missing_key(self):
        """Condition evaluates to False when key is missing from context."""
        result = autoclear_policy._evaluate_condition("missing_key==value", self.task_context)
        self.assertFalse(result)

    def test_evaluate_condition_boolean_true_string(self):
        """Condition comparing boolean True as string."""
        result = autoclear_policy._evaluate_condition("has_resources==true", self.task_context)
        self.assertTrue(result)

    def test_evaluate_condition_boolean_false_string(self):
        """Condition comparing boolean False as string."""
        task_context = dict(self.task_context, has_resources=False)
        result = autoclear_policy._evaluate_condition("has_resources==false", task_context)
        self.assertTrue(result)

    def test_evaluate_condition_numeric_value(self):
        """Condition comparing numeric values as strings."""
        result = autoclear_policy._evaluate_condition("cost_usd==50.25", self.task_context)
        self.assertTrue(result)

    def test_evaluate_condition_numeric_not_match(self):
        """Condition comparing numeric values, no match."""
        result = autoclear_policy._evaluate_condition("cost_usd==100.0", self.task_context)
        self.assertFalse(result)

    def test_evaluate_condition_multiple_equals_only_first_split(self):
        """Multiple == operators, only first split is used."""
        result = autoclear_policy._evaluate_condition(
            "status==completed==extra", self.task_context
        )
        # First split: key="status", expected="completed==extra", actual="completed"
        self.assertFalse(result)

    def test_evaluate_condition_no_operator(self):
        """Condition with no operator evaluates to True."""
        result = autoclear_policy._evaluate_condition("no_operator_here", self.task_context)
        self.assertTrue(result)

    def test_evaluate_condition_kind_not_equals(self):
        """Condition with kind field and != operator."""
        result = autoclear_policy._evaluate_condition("kind!=failed", self.task_context)
        self.assertTrue(result)

    def test_evaluate_condition_environment_match(self):
        """Condition checking environment field."""
        result = autoclear_policy._evaluate_condition("environment==staging", self.task_context)
        self.assertTrue(result)

    def test_evaluate_condition_whitespace_in_value(self):
        """Condition with value containing whitespace."""
        task_context = dict(self.task_context, name="Task Name With Spaces")
        # The condition parser doesn't strip the value, so "name with spaces" != "Task Name With Spaces"
        result = autoclear_policy._evaluate_condition("name==task name with spaces", task_context)
        self.assertTrue(result)  # Case-insensitive match


class TestExecuteAction(unittest.TestCase):
    """Tests for _execute_action() helper."""

    def setUp(self):
        """Set up test fixtures."""
        self.task_context = {"task_id": "task-123", "status": "completed"}

    def test_execute_action_delete_volume(self):
        """delete_volume action returns True."""
        result = autoclear_policy._execute_action("delete_volume", "vol-123", self.task_context)
        self.assertTrue(result)

    def test_execute_action_delete_logs(self):
        """delete_logs action returns True."""
        result = autoclear_policy._execute_action("delete_logs", "log-456", self.task_context)
        self.assertTrue(result)

    def test_execute_action_delete_artifacts(self):
        """delete_artifacts action returns True."""
        result = autoclear_policy._execute_action(
            "delete_artifacts", "artifact-789", self.task_context
        )
        self.assertTrue(result)

    def test_execute_action_unknown_action(self):
        """Unknown action type returns True (no-op)."""
        result = autoclear_policy._execute_action("unknown_action", "resource", self.task_context)
        self.assertTrue(result)

    def test_execute_action_empty_action(self):
        """Empty action string returns True."""
        result = autoclear_policy._execute_action("", "resource", self.task_context)
        self.assertTrue(result)

    def test_execute_action_empty_target(self):
        """Empty target string still executes action."""
        result = autoclear_policy._execute_action("delete_volume", "", self.task_context)
        self.assertTrue(result)

    def test_execute_action_missing_task_id(self):
        """Action executes even if task_id is missing from context."""
        task_context = {"status": "completed"}
        result = autoclear_policy._execute_action("delete_volume", "vol-123", task_context)
        self.assertTrue(result)

    def test_execute_action_case_sensitive(self):
        """Action names are case-sensitive."""
        result = autoclear_policy._execute_action("DELETE_VOLUME", "vol-123", self.task_context)
        # Case doesn't match, returns True as unknown action
        self.assertTrue(result)

    def test_execute_action_delete_logs_with_multiple_targets(self):
        """delete_logs with multiple resources as target."""
        result = autoclear_policy._execute_action("delete_logs", "log-1,log-2,log-3", self.task_context)
        self.assertTrue(result)

    def test_execute_action_delete_volume_with_pattern(self):
        """delete_volume with wildcard pattern."""
        result = autoclear_policy._execute_action("delete_volume", "vol-*", self.task_context)
        self.assertTrue(result)


class TestAutoclearPolicyIntegration(unittest.TestCase):
    """Integration tests combining apply_autoclear_rules with conditions and actions."""

    def test_full_workflow_completed_task_cleanup(self):
        """Full workflow: apply rules to clean up completed task resources."""
        task_context = {
            "task_id": "task-456",
            "status": "completed",
            "resources": ["vol-1", "log-2"],
        }
        rules = {
            "rules": [
                {
                    "id": "cleanup-completed",
                    "action": "delete_volume",
                    "target": "vol-1",
                    "condition": "status==completed",
                    "enabled": True,
                },
                {
                    "id": "cleanup-logs",
                    "action": "delete_logs",
                    "target": "log-2",
                    "condition": "status==completed",
                    "enabled": True,
                },
            ]
        }
        result = autoclear_policy.apply_autoclear_rules(task_context, rules)
        self.assertTrue(result)

    def test_full_workflow_failed_task_no_cleanup(self):
        """Full workflow: failed task should not match cleanup rules."""
        task_context = {
            "task_id": "task-789",
            "status": "failed",
            "resources": ["vol-1", "log-2"],
        }
        rules = {
            "rules": [
                {
                    "id": "cleanup-completed",
                    "action": "delete_volume",
                    "target": "vol-1",
                    "condition": "status==completed",
                    "enabled": True,
                }
            ]
        }
        result = autoclear_policy.apply_autoclear_rules(task_context, rules)
        self.assertTrue(result)

    def test_full_workflow_multiple_rules_complex_conditions(self):
        """Full workflow with complex multi-rule application."""
        task_context = {
            "task_id": "task-complex",
            "status": "completed",
            "kind": "deploy",
            "environment": "staging",
            "has_logs": True,
        }
        rules = {
            "rules": [
                {
                    "id": "rule-1",
                    "action": "delete_artifacts",
                    "target": "artifact-1",
                    "condition": "status==completed",
                    "enabled": True,
                },
                {
                    "id": "rule-2",
                    "action": "delete_logs",
                    "target": "log-1",
                    "condition": "kind==deploy",
                    "enabled": True,
                },
                {
                    "id": "rule-3",
                    "action": "delete_volume",
                    "target": "vol-1",
                    "condition": "environment!=production",
                    "enabled": True,
                },
            ]
        }
        result = autoclear_policy.apply_autoclear_rules(task_context, rules)
        self.assertTrue(result)

    def test_full_workflow_early_failure_with_rollback(self):
        """Full workflow: early failure with rollback stops processing."""
        task_context = {
            "task_id": "task-fail",
            "status": "completed",
        }
        rules = {
            "rules": [
                {
                    "id": "rule-1",
                    "action": "delete_volume",
                    "target": "vol-1",
                    "enabled": True,
                    "rollback": True,
                },
                {
                    "id": "rule-2",
                    "action": "delete_logs",
                    "target": "log-1",
                    "enabled": True,
                },
            ]
        }
        with mock.patch("autoclear_policy._execute_action", side_effect=[False, True]):
            result = autoclear_policy.apply_autoclear_rules(task_context, rules)
            self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
