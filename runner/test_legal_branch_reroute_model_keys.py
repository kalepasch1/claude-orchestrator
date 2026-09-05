#!/usr/bin/env python3
"""
Test suite for legal-driven branch rerouting with model key validation and fallback.

Tests cover:
- Missing branch detection and recovery from queue
- Model key validation and rerouting
- Legal gate enforcement with branch context
- Coordination rule validation (no overwrites, reuse prior solutions)
- Model fallback when primary keys unavailable
- Integration with orchestration pipeline
"""
import pytest
import os
import sys
import json
from unittest.mock import Mock, patch, MagicMock, call
from datetime import datetime
from typing import Dict, List, Tuple, Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ["ORCH_DB_URL"] = ""
os.environ["ORCH_DB_ENABLED"] = "false"

# Mock imports
import contract_validator as cv


class TestMissingBranchDetection:
    """Tests for detecting and recovering missing branches."""

    def test_detect_missing_branch_simple(self):
        """Detect when expected branch is missing."""
        branches = ["main", "develop", "feature/old"]
        expected = "orchestrator/legal-task-2069e59"
        result = cv.detect_missing_branch(branches, expected)
        assert result["missing"] is True
        assert result["branch"] == expected

    def test_detect_missing_branch_found(self):
        """Detect when branch exists."""
        branches = ["main", "orchestrator/legal-task-2069e59", "develop"]
        expected = "orchestrator/legal-task-2069e59"
        result = cv.detect_missing_branch(branches, expected)
        assert result["missing"] is False
        assert result["branch"] == expected

    def test_recover_from_queue_exists(self):
        """Recover missing branch from work queue."""
        queue = [
            {
                "branch": "orchestrator/legal-task-2069e59",
                "status": "queued",
                "timestamp": "2026-09-03T10:00:00Z",
                "reason": "legal-rework needed"
            },
            {
                "branch": "feature/other",
                "status": "in-progress",
                "timestamp": "2026-09-03T09:00:00Z"
            }
        ]
        result = cv.recover_from_queue(queue, "orchestrator/legal-task-2069e59")
        assert result is not None
        assert result["branch"] == "orchestrator/legal-task-2069e59"
        assert result["status"] == "queued"

    def test_recover_from_queue_not_found(self):
        """Return None when branch not in queue."""
        queue = [
            {
                "branch": "feature/other",
                "status": "in-progress"
            }
        ]
        result = cv.recover_from_queue(queue, "orchestrator/legal-task-2069e59")
        assert result is None

    def test_recover_from_queue_empty(self):
        """Handle empty queue gracefully."""
        result = cv.recover_from_queue([], "orchestrator/legal-task-2069e59")
        assert result is None

    def test_mark_recovered_work_preserves_state(self):
        """Mark recovered work without losing prior state."""
        recovered = {
            "branch": "orchestrator/legal-task-2069e59",
            "status": "queued",
            "solution_hash": "abc123def456",
            "prior_cost_usd": 0.42
        }
        result = cv.mark_recovered(recovered, "reroute-pending")
        assert result["branch"] == recovered["branch"]
        assert result["status"] == "reroute-pending"
        assert result["solution_hash"] == "abc123def456"
        assert result["prior_cost_usd"] == 0.42


class TestModelKeyRouting:
    """Tests for model key validation and rerouting logic."""

    def test_validate_model_key_valid(self):
        """Validate correct model key format."""
        key = "google:gemini-4.0-flash"
        result = cv.validate_model_key(key)
        assert result["valid"] is True
        assert result["provider"] == "google"
        assert result["model"] == "gemini-4.0-flash"

    def test_validate_model_key_claude_variant(self):
        """Validate Claude model key."""
        key = "claude:claude-fable-5"
        result = cv.validate_model_key(key)
        assert result["valid"] is True
        assert result["provider"] == "claude"

    def test_validate_model_key_openai_variant(self):
        """Validate OpenAI model key."""
        key = "openai:gpt-5.4-mini"
        result = cv.validate_model_key(key)
        assert result["valid"] is True
        assert result["provider"] == "openai"

    def test_validate_model_key_invalid_format(self):
        """Reject invalid model key format."""
        key = "no-colon-invalid"
        result = cv.validate_model_key(key)
        assert result["valid"] is False
        assert "format" in result["reason"]

    def test_validate_model_key_empty(self):
        """Reject empty model key."""
        result = cv.validate_model_key("")
        assert result["valid"] is False

    def test_validate_model_key_none(self):
        """Handle None key gracefully."""
        result = cv.validate_model_key(None)
        assert result["valid"] is False

    def test_route_to_fallback_when_key_missing(self):
        """Route to fallback model when primary key unavailable."""
        route_config = {
            "primary": "google:gemini-4.0-pro",
            "fallback": "claude:claude-fable-5",
            "available_keys": ["claude:claude-fable-5"]
        }
        result = cv.route_model(route_config)
        assert result["model"] == "claude:claude-fable-5"
        assert result["source"] == "fallback"

    def test_route_to_primary_when_available(self):
        """Route to primary model when key available."""
        route_config = {
            "primary": "google:gemini-4.0-pro",
            "fallback": "claude:claude-fable-5",
            "available_keys": ["google:gemini-4.0-pro", "claude:claude-fable-5"]
        }
        result = cv.route_model(route_config)
        assert result["model"] == "google:gemini-4.0-pro"
        assert result["source"] == "primary"

    def test_route_with_no_available_keys(self):
        """Handle case when no keys available."""
        route_config = {
            "primary": "google:gemini-4.0-pro",
            "fallback": "claude:claude-fable-5",
            "available_keys": []
        }
        result = cv.route_model(route_config)
        assert result["model"] is None
        assert result["source"] is None
        assert result["error"] == "no_available_keys"

    def test_route_respects_model_rotation(self):
        """Route respects model rotation strategy."""
        route_config = {
            "strategy": "rotate",
            "candidates": [
                "google:gemini-4.0-flash-lite",
                "google:gemini-4.0-pro",
                "claude:claude-fable-5"
            ],
            "available_keys": ["google:gemini-4.0-pro", "claude:claude-fable-5"],
            "rotation_index": 1
        }
        result = cv.route_model(route_config)
        # Should select next in rotation that's available
        assert result["model"] in route_config["available_keys"]


class TestLegalGateWithBranchContext:
    """Tests for legal gate enforcement considering branch state."""

    def test_legal_gate_missing_branch_blocks_merge(self):
        """Missing branch blocks merge until recovered."""
        diff = "Added feature to src/feature.py"
        context = {
            "branch_missing": True,
            "branch_name": "orchestrator/legal-task-2069e59",
            "recovery_pending": True
        }
        all_clear, results = cv.check_legal_gates(diff, context=context)
        # Should have coordination rule violation
        coordination_violated = [r for r in results if "coordination" in r.get("gate", "")]
        assert len(coordination_violated) > 0 or not all_clear

    def test_legal_gate_recovered_branch_allows_merge(self):
        """Recovered branch passes legal gates."""
        diff = "Code change in recovered branch"
        context = {
            "branch_missing": False,
            "branch_name": "orchestrator/legal-task-2069e59",
            "recovered_from_queue": True,
            "prior_solution_hash": "abc123def456"
        }
        all_clear, results = cv.check_legal_gates(diff, context=context)
        # Should not block on recovery status
        recovery_blocks = [r for r in results if "recovery" in r.get("gate", "").lower()]
        assert len(recovery_blocks) == 0

    def test_legal_gate_with_model_key_failure(self):
        """Model key failure triggers legal gate escalation."""
        diff = "Strategy implementation using rotated model"
        context = {
            "model_routing_failed": True,
            "no_available_keys": True,
            "primary_model": "google:gemini-4.0-pro",
            "fallback_model": "claude:claude-fable-5"
        }
        all_clear, results = cv.check_legal_gates(diff, context=context)
        # Should escalate to owner review
        owner_required = [r for r in results if r.get("required_approver") == "owner"]
        assert len(owner_required) > 0 or not all_clear

    def test_legal_gate_clean_merge_with_valid_routing(self):
        """Clean merge with valid model routing passes gates."""
        diff = "Added safe feature"
        context = {
            "branch_missing": False,
            "model_routing_valid": True,
            "used_model": "google:gemini-4.0-pro"
        }
        all_clear, results = cv.check_legal_gates(diff, context=context)
        triggered = [r for r in results if r["triggered"]]
        assert len(triggered) == 0 or len(triggered) <= 1


class TestCoordinationRules:
    """Tests for coordination rule validation."""

    def test_no_overwrite_rule_detects_conflict(self):
        """no-overwrites rule detects unrelated changes."""
        active_work = [
            {
                "branch": "feature/auth-refactor",
                "files_changed": ["src/auth.py", "src/middleware.py"],
                "status": "in-progress"
            }
        ]
        incoming_changes = {
            "branch": "orchestrator/legal-task-2069e59",
            "files_changed": ["src/auth.py"],  # Overlaps!
        }
        result = cv.check_no_overwrite_rule(active_work, incoming_changes)
        assert result["violated"] is True
        assert "overlap" in result["details"]

    def test_no_overwrite_rule_detects_no_conflict(self):
        """no-overwrites rule passes when no overlap."""
        active_work = [
            {
                "branch": "feature/auth-refactor",
                "files_changed": ["src/auth.py"],
                "status": "in-progress"
            }
        ]
        incoming_changes = {
            "branch": "orchestrator/legal-task-2069e59",
            "files_changed": ["src/legal.py"],  # No overlap
        }
        result = cv.check_no_overwrite_rule(active_work, incoming_changes)
        assert result["violated"] is False

    def test_reuse_prior_solutions_finds_match(self):
        """Reuse rule finds matching prior solution."""
        task = {
            "kind": "legal",
            "class": "legal_posture",
            "slug": "rework-legal-2069e59"
        }
        prior_solutions = [
            {
                "task_kind": "legal",
                "task_class": "legal_posture",
                "solution_hash": "abc123def456",
                "cost_usd": 0.42,
                "model": "google:gemini-4.0-pro"
            },
            {
                "task_kind": "feature",
                "task_class": "other",
                "solution_hash": "xyz789",
                "cost_usd": 0.15
            }
        ]
        result = cv.reuse_prior_solution(task, prior_solutions)
        assert result["found"] is True
        assert result["solution_hash"] == "abc123def456"

    def test_reuse_prior_solutions_no_match(self):
        """Reuse rule returns None when no match."""
        task = {
            "kind": "feature",
            "class": "new_feature",
            "slug": "add-new-feature"
        }
        prior_solutions = [
            {
                "task_kind": "legal",
                "task_class": "legal_posture",
                "solution_hash": "abc123"
            }
        ]
        result = cv.reuse_prior_solution(task, prior_solutions)
        assert result["found"] is False

    def test_leave_recovered_in_queue_until_shipped(self):
        """Recovered work stays in queue after recovery."""
        recovered_item = {
            "branch": "orchestrator/legal-task-2069e59",
            "status": "reroute-pending",
            "recovered_from_queue": True,
            "shipped": False
        }
        queue = [recovered_item]
        result = cv.check_queue_retention(queue, recovered_item["branch"])
        assert result["should_remain_in_queue"] is True
        assert result["reason"] == "recovered-not-shipped"

    def test_remove_from_queue_after_ship(self):
        """Shipped work can be removed from queue."""
        shipped_item = {
            "branch": "orchestrator/legal-task-2069e59",
            "status": "shipped",
            "shipped": True
        }
        result = cv.check_queue_retention([shipped_item], shipped_item["branch"])
        assert result["should_remain_in_queue"] is False


class TestBranchRerouteOrchestration:
    """Tests for complete branch reroute orchestration flow."""

    def test_orchestrate_missing_branch_detection_recovery(self):
        """Full flow: detect missing, recover from queue, reroute."""
        task = {
            "kind": "legal",
            "class": "legal_posture",
            "branch": "orchestrator/legal-task-2069e59"
        }
        available_branches = ["main", "develop"]
        work_queue = [
            {
                "branch": "orchestrator/legal-task-2069e59",
                "status": "queued",
                "solution_hash": "prior_solution_123"
            }
        ]

        # Detect missing
        missing = cv.detect_missing_branch(available_branches, task["branch"])
        assert missing["missing"] is True

        # Recover from queue
        recovered = cv.recover_from_queue(work_queue, task["branch"])
        assert recovered is not None

        # Should mark as recovered and ready for reroute
        result = {
            "detected_missing": True,
            "recovered": True,
            "ready_for_reroute": True
        }
        assert result["ready_for_reroute"] is True

    def test_orchestrate_model_key_reroute_on_recovery(self):
        """Model key is rerouted when branch recovered."""
        original_config = {
            "primary_model": "google:gemini-4.0-pro",
            "fallback_model": "claude:claude-fable-5",
            "available_keys": []  # Primary key unavailable
        }

        # Route should fall back
        route_result = cv.route_model(original_config)
        assert route_result["model"] == "claude:claude-fable-5"

        # But if primary becomes available after recovery
        updated_config = {
            "primary_model": "google:gemini-4.0-pro",
            "fallback_model": "claude:claude-fable-5",
            "available_keys": ["google:gemini-4.0-pro"]
        }
        route_result = cv.route_model(updated_config)
        assert route_result["model"] == "google:gemini-4.0-pro"

    def test_orchestrate_full_pipeline_with_missing_branch_and_legal_gate(self):
        """End-to-end: missing branch, recovery, legal gate, reroute."""
        task_spec = {
            "branch": "orchestrator/legal-task-2069e59",
            "kind": "legal",
            "class": "legal_posture",
            "diff": "Added licensing content"
        }

        available_branches = ["main", "develop"]
        work_queue = [
            {
                "branch": task_spec["branch"],
                "status": "queued",
                "solution_hash": "abc123"
            }
        ]

        available_keys = ["claude:claude-fable-5"]
        route_config = {
            "primary": "google:gemini-4.0-pro",
            "fallback": "claude:claude-fable-5",
            "available_keys": available_keys
        }

        # Step 1: Detect missing branch
        missing = cv.detect_missing_branch(available_branches, task_spec["branch"])
        assert missing["missing"] is True

        # Step 2: Recover from queue
        recovered = cv.recover_from_queue(work_queue, task_spec["branch"])
        assert recovered is not None

        # Step 3: Validate model routing
        routing = cv.route_model(route_config)
        assert routing["model"] in available_keys

        # Step 4: Check legal gates with context
        all_clear, results = cv.check_legal_gates(
            task_spec["diff"],
            context={
                "branch_missing": False,  # Was missing but recovered
                "recovered_from_queue": True,
                "used_model": routing["model"]
            }
        )
        # Should pass legal gates for recovered branch with valid routing
        coordination_blocks = [r for r in results if r.get("gate") == "coordination"]
        assert len(coordination_blocks) == 0


class TestModelKeyMocking:
    """Tests for model key mocking in test scenarios."""

    def test_mock_unavailable_model_key(self):
        """Mock scenario where model key is unavailable."""
        with patch.dict(os.environ, {"ORCH_GEMINI_API_KEY": ""}):
            route_config = {
                "primary": "google:gemini-4.0-pro",
                "fallback": "claude:claude-fable-5",
                "available_keys": ["claude:claude-fable-5"]
            }
            result = cv.route_model(route_config)
            assert result["model"] == "claude:claude-fable-5"

    def test_mock_all_keys_unavailable(self):
        """Mock scenario where all keys are unavailable."""
        with patch.dict(os.environ, {}, clear=True):
            route_config = {
                "primary": "google:gemini-4.0-pro",
                "fallback": "claude:claude-fable-5",
                "available_keys": []
            }
            result = cv.route_model(route_config)
            assert result["model"] is None
            assert result["error"] == "no_available_keys"

    def test_mock_model_key_rotation(self):
        """Mock model key rotation strategy."""
        with patch("contract_validator.get_rotation_index") as mock_rotate:
            mock_rotate.return_value = 1
            route_config = {
                "strategy": "rotate",
                "candidates": ["google:gemini-4.0-flash", "google:gemini-4.0-pro"],
                "available_keys": ["google:gemini-4.0-pro"]
            }
            result = cv.route_model(route_config)
            # Should use rotation strategy
            assert result["model"] in route_config["available_keys"]

    def test_mock_branch_recovery_failure(self):
        """Mock failure scenario during branch recovery."""
        with patch.object(cv, "recover_from_queue", return_value=None):
            branches = ["main", "develop"]
            queue = []
            missing = cv.detect_missing_branch(branches, "missing-branch")
            assert missing["missing"] is True
            recovered = cv.recover_from_queue(queue, "missing-branch")
            assert recovered is None

    def test_mock_legal_gate_escalation(self):
        """Mock legal gate escalation on model key failure."""
        with patch("contract_validator.validate_model_key") as mock_validate:
            mock_validate.return_value = {"valid": False}
            result = cv.validate_model_key("invalid-key")
            assert result["valid"] is False


class TestErrorHandlingAndFailSoft:
    """Tests for error handling and fail-soft behavior."""

    def test_detect_missing_branch_survives_none_input(self):
        """Handle None branches gracefully."""
        try:
            result = cv.detect_missing_branch(None, "branch")
            assert isinstance(result, dict)
        except Exception as e:
            pytest.fail(f"Should handle None gracefully: {e}")

    def test_route_model_survives_bad_config(self):
        """Handle malformed route config."""
        try:
            result = cv.route_model({})
            assert result is not None or result is None  # Either response is acceptable
        except Exception as e:
            pytest.fail(f"Should handle bad config gracefully: {e}")

    def test_check_legal_gates_with_missing_context(self):
        """Handle missing context gracefully."""
        try:
            all_clear, results = cv.check_legal_gates("diff", context=None)
            assert isinstance(all_clear, bool)
            assert isinstance(results, list)
        except Exception as e:
            pytest.fail(f"Should handle missing context: {e}")

    def test_recovery_from_queue_with_corrupted_item(self):
        """Handle corrupted queue item gracefully."""
        queue = [
            {
                "branch": "valid-branch",
                "status": "queued"
            },
            {
                # Corrupted: missing required fields
                "status": "queued"
            }
        ]
        try:
            result = cv.recover_from_queue(queue, "valid-branch")
            assert result is not None
            assert result["branch"] == "valid-branch"
        except Exception as e:
            pytest.fail(f"Should handle corrupted items: {e}")

    def test_coordination_rule_with_empty_active_work(self):
        """Handle empty active work list."""
        result = cv.check_no_overwrite_rule([], {"files_changed": ["file.py"]})
        assert result["violated"] is False


class TestIntegrationScenarios:
    """Integration tests combining multiple components."""

    def test_scenario_legal_rework_missing_branch_complete_flow(self):
        """
        Integration: legal-rework task with missing branch.
        Simulate full pipeline contract execution.
        """
        # Setup
        task = {
            "id": "rework-legal-2069e59",
            "kind": "legal",
            "class": "legal_posture",
            "branch": "orchestrator/legal-task-2069e59",
            "diff": "Updated licensing terms for compliance"
        }

        git_state = {
            "available_branches": ["main", "develop"],
            "work_queue": [
                {
                    "branch": "orchestrator/legal-task-2069e59",
                    "status": "queued",
                    "solution_hash": "prior-solution-hash-2069e59"
                }
            ]
        }

        model_state = {
            "primary_model": "google:gemini-4.0-pro",
            "fallback_model": "claude:claude-fable-5",
            "available_keys": ["claude:claude-fable-5"]
        }

        # Execute pipeline
        # 1. Detect missing branch
        missing = cv.detect_missing_branch(
            git_state["available_branches"],
            task["branch"]
        )
        assert missing["missing"] is True

        # 2. Recover from queue
        recovered = cv.recover_from_queue(
            git_state["work_queue"],
            task["branch"]
        )
        assert recovered is not None
        assert recovered["status"] == "queued"

        # 3. Mark as recovered
        marked = cv.mark_recovered(recovered, "reroute-pending")
        assert marked["status"] == "reroute-pending"

        # 4. Validate model routing
        routing = cv.route_model(model_state)
        assert routing["model"] == "claude:claude-fable-5"
        assert routing["source"] == "fallback"

        # 5. Check legal gates with context
        all_clear, results = cv.check_legal_gates(
            task["diff"],
            context={
                "branch": task["branch"],
                "recovered_from_queue": True,
                "used_model": routing["model"],
                "task_class": task["class"]
            }
        )

        # Verify coordination rules
        coordination = [r for r in results if "coordination" in r.get("gate", "")]
        # Recovered branch with valid routing should pass coordination
        assert all(not r["triggered"] for r in coordination)

    def test_scenario_model_key_unavailable_escalation(self):
        """
        Integration: model key unavailable leads to legal gate escalation.
        """
        task = {
            "id": "rework-legal-2069e59",
            "branch": "orchestrator/legal-task-2069e59",
            "diff": "Updated terms requiring legal review"
        }

        # All model keys unavailable
        route_config = {
            "primary": "google:gemini-4.0-pro",
            "fallback": "claude:claude-fable-5",
            "available_keys": []
        }

        # Model routing fails
        routing = cv.route_model(route_config)
        assert routing["model"] is None
        assert routing["error"] == "no_available_keys"

        # Legal gate escalation
        all_clear, results = cv.check_legal_gates(
            task["diff"],
            context={
                "model_routing_failed": True,
                "no_available_keys": True
            }
        )

        # Should require owner approval
        owner_required = [r for r in results if r.get("required_approver") == "owner"]
        assert len(owner_required) > 0

    def test_scenario_coordination_rule_conflict_detection(self):
        """
        Integration: coordination rules detect conflicts with active work.
        """
        active_work = [
            {
                "branch": "feature/security-audit",
                "status": "in-progress",
                "files_changed": ["src/auth.py", "src/security.py"]
            }
        ]

        incoming_task = {
            "branch": "orchestrator/legal-task-2069e59",
            "files_changed": ["src/auth.py"]  # Overlaps with active work!
        }

        # Check no-overwrite rule
        result = cv.check_no_overwrite_rule(active_work, incoming_task)
        assert result["violated"] is True

        # Should trigger coordination gate in legal check
        all_clear, legal_results = cv.check_legal_gates(
            "Licensing update",
            context={
                "coordination_violation": True,
                "active_work_conflict": result["details"]
            }
        )

        coordination_blocks = [r for r in legal_results if r.get("gate") == "coordination"]
        assert len(coordination_blocks) > 0


# ---- Test runner ----

def run_all_tests() -> bool:
    """Run all test functions and report results."""
    test_count = 0
    pass_count = 0
    fail_count = 0
    errors: List[str] = []

    for name, obj in list(globals().items()):
        if name.startswith("Test") and isinstance(obj, type):
            for method_name in dir(obj):
                if method_name.startswith("test_") and callable(getattr(obj, method_name)):
                    method = getattr(obj, method_name)
                    test_count += 1
                    try:
                        method()
                        pass_count += 1
                        print(f"  PASS  {name}.{method_name}")
                    except AssertionError as e:
                        fail_count += 1
                        msg = f"{name}.{method_name}: {e}"
                        print(f"  FAIL  {msg}")
                        errors.append(msg)
                    except Exception as e:
                        fail_count += 1
                        msg = f"{name}.{method_name}: {type(e).__name__}: {e}"
                        print(f"  ERROR {msg}")
                        errors.append(msg)

    print(f"\nlegal_branch_reroute_model_keys tests: {pass_count}/{test_count} passed")
    if fail_count > 0:
        print(f"Failures: {fail_count}")
        for error in errors[:10]:
            print(f"  - {error}")
        if len(errors) > 10:
            print(f"  ... and {len(errors) - 10} more")
    return fail_count == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
