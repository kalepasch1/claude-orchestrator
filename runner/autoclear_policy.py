"""Autoclear policy execution — apply rules to clear task-related resources.

Rules format:
  - action: 'delete_volume', 'delete_logs', 'delete_artifacts'
  - target: resource identifier or pattern
  - condition: (optional) predicate on task context
  - rollback: if action fails, whether to flag error vs. continue silently

Returns True if all enabled actions succeeded (or no actions matched).
Returns False if any action failed and was not rolled back.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def apply_autoclear_rules(task_context: dict, rules: dict) -> bool:
    """Apply autoclear rules to a task context.

    Args:
        task_context: Task execution state (task_id, status, resources, etc.)
        rules: Rules dict with 'rules' key containing list of rule dicts.
               Each rule: {action, target, condition?, rollback?, enabled?}

    Returns:
        True if all enabled actions succeeded or no actions were applicable.
        False if any action failed and had rollback=True.
    """
    if not rules or not isinstance(rules, dict):
        logger.debug("no rules provided or invalid rules dict")
        return True

    rule_list = rules.get("rules", [])
    if not rule_list:
        logger.debug("no rules in autoclear policy")
        return True

    all_succeeded = True
    for rule in rule_list:
        if not isinstance(rule, dict):
            logger.warning("invalid rule, skipping: %s", rule)
            continue

        if not rule.get("enabled", True):
            continue

        action = rule.get("action")
        target = rule.get("target")
        condition = rule.get("condition")
        rollback_on_failure = rule.get("rollback", False)

        if not action or not target:
            logger.debug("rule missing action or target, skipping: %s", rule)
            continue

        # Evaluate optional condition
        if condition and not _evaluate_condition(condition, task_context):
            logger.debug("rule condition not met, skipping rule: %s", rule.get("id", "unknown"))
            continue

        # Execute the action
        try:
            success = _execute_action(action, target, task_context)
            if not success and rollback_on_failure:
                logger.error("action failed with rollback required: %s on %s", action, target)
                all_succeeded = False
            elif success:
                logger.info("autoclear action succeeded: %s on %s", action, target)
            else:
                logger.warning("action failed but rollback not required: %s on %s", action, target)
        except Exception as e:
            logger.exception("exception during autoclear action %s: %s", action, e)
            if rollback_on_failure:
                all_succeeded = False

    return all_succeeded


def _evaluate_condition(condition: str, task_context: dict) -> bool:
    """Evaluate a simple condition string against task context.

    Supports: "status==completed", "kind!=prod", "has_resources==true", etc.
    Returns True if condition is met, False otherwise.
    """
    if not condition or not isinstance(condition, str):
        return True

    parts = condition.split("==", 1)
    if len(parts) == 2:
        key, expected = parts[0].strip(), parts[1].strip()
        actual = task_context.get(key)
        return str(actual).lower() == expected.lower()

    parts = condition.split("!=", 1)
    if len(parts) == 2:
        key, expected = parts[0].strip(), parts[1].strip()
        actual = task_context.get(key)
        return str(actual).lower() != expected.lower()

    return True


def _execute_action(action: str, target: str, task_context: dict) -> bool:
    """Execute a single autoclear action.

    Minimal implementation: log the action and return success.
    Real implementation would invoke runner cleanup routines.

    Args:
        action: action name (delete_volume, delete_logs, delete_artifacts)
        target: resource identifier
        task_context: task state dict

    Returns:
        True if action succeeded, False if it failed (but not critical).
    """
    task_id = task_context.get("task_id", "unknown")

    if action == "delete_volume":
        logger.info("would delete volume %s for task %s", target, task_id)
        return True
    elif action == "delete_logs":
        logger.info("would delete logs %s for task %s", target, task_id)
        return True
    elif action == "delete_artifacts":
        logger.info("would delete artifacts %s for task %s", target, task_id)
        return True
    else:
        logger.warning("unknown autoclear action: %s", action)
        return True
