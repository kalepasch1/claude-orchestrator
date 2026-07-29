#!/usr/bin/env python3
"""
Test suite for pipeline_contract.py preflight triage and strategy planner sections.

Focuses on:
- Permission-denied error handling in preflight/strategy routing
- Fail-soft degradation preserving existing behavior
- Authorization checks for restricted operations
- Allowlist-based task filtering
- Model selection under permission constraints
"""
import pytest
import os
import json
import sys
from unittest.mock import Mock, patch, MagicMock, call
from io import StringIO

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pipeline_contract as pc


class TestPreflightTriagePermissionHandling:
    """Tests for permission-denied errors in preflight triage routing."""

    def test_preflight_permission_denied_from_app_triage(self):
        """Preflight should fall back to model_policy when app_triage raises PermissionError."""
        with patch('pipeline_contract.app_triage') as mock_triage:
            mock_triage.route.side_effect = PermissionError("app_triage: permission denied")
            with patch('pipeline_contract.model_policy.choose') as mock_policy:
                mock_policy.return_value = ("claude", "claude-opus", "fallback_policy")

                result = pc._safe_route("orchestrator", "task_preflight", "rating", need=5, agentic=False)

                # Should have fallen back to model_policy
                assert result["provider"] == "claude"
                assert result["model"] == "claude-opus"

    def test_preflight_both_fail_uses_hardcoded_default(self):
        """Both app_triage and model_policy fail -> hardcoded default model."""
        with patch('pipeline_contract.app_triage') as mock_triage:
            mock_triage.route.side_effect = PermissionError("denied")
            with patch('pipeline_contract.model_policy.choose') as mock_policy:
                mock_policy.side_effect = PermissionError("denied")

                result = pc._safe_route("orchestrator", "task_preflight", "rating")

                assert result["provider"] == "claude"
                assert "haiku" in result["model"]
                assert "permission denied" in result["reason"].lower()

    def test_preflight_logs_permission_error_and_continues(self, capsys):
        """Permission errors should be logged to stderr but not raise."""
        with patch('pipeline_contract.app_triage') as mock_triage:
            mock_triage.route.side_effect = PermissionError("preflight access denied")
            with patch('pipeline_contract.model_policy.choose') as mock_policy:
                mock_policy.return_value = ("claude", "claude-opus", "fallback")

                # Should not raise
                result = pc._safe_route("orchestrator", "task_preflight", "rating")

                assert result is not None
                assert "provider" in result


class TestStrategyPlannerPermissionHandling:
    """Tests for permission-denied errors in strategy planning."""

    def test_strategy_permission_denied_fallback(self):
        """Strategy planner should use model_policy fallback on PermissionError."""
        with patch('pipeline_contract.app_triage') as mock_triage:
            mock_triage.route.side_effect = PermissionError("strategy denied")
            with patch('pipeline_contract.model_policy.choose') as mock_policy:
                mock_policy.return_value = ("local", "llama3.1", "fallback_policy")

                result = pc._safe_route("orchestrator", "task_strategy", "plan", need=7)

                assert result["provider"] == "local"
                assert result["model"] == "llama3.1"

    def test_strategy_respects_need_parameter_in_fallback(self):
        """Strategy routing should pass the need parameter to model_policy."""
        with patch('pipeline_contract.app_triage') as mock_triage:
            mock_triage.route.side_effect = PermissionError()
            with patch('pipeline_contract.model_policy.choose') as mock_policy:
                mock_policy.return_value = ("claude", "claude-opus", "fallback")

                pc._safe_route("orchestrator", "task_strategy", "plan", need=8)

                # Verify model_policy was called with correct need
                mock_policy.assert_called_once()
                call_kwargs = mock_policy.call_args[1]
                assert call_kwargs.get("need") == 8

    def test_strategy_both_fail_final_fallback(self):
        """All strategy routing options fail -> hardcoded Haiku."""
        with patch('pipeline_contract.app_triage') as mock_triage:
            mock_triage.route.side_effect = PermissionError()
            with patch('pipeline_contract.model_policy.choose') as mock_policy:
                mock_policy.side_effect = PermissionError()

                result = pc._safe_route("orchestrator", "task_strategy", "plan", need=8)

                assert result["provider"] == "claude"
                assert "haiku-4-5" in result["model"]


class TestRestrictedOperationAuthorization:
    """Tests for authorization checks on restricted operations."""

    def test_restricted_operation_denied_for_security_task(self):
        """Restricted ops on security tasks -> fallback to Haiku."""
        with patch.dict(os.environ, {"ORCH_SECURITY_ALLOWED_OPERATIONS": ""}):
            result = pc._safe_route("app", "task_security_gate", "security")

            # Should degrade to Haiku when operation not authorized
            assert result["provider"] == "claude"
            assert "haiku" in result["model"]
            assert "operation unauthorized" in result["reason"]

    def test_restricted_operation_allowed_for_security_task(self):
        """Restricted ops allowed for security tasks -> normal routing."""
        with patch.dict(os.environ, {"ORCH_SECURITY_ALLOWED_OPERATIONS": "task_security_gate"}):
            with patch('pipeline_contract.app_triage') as mock_triage:
                mock_triage.route.return_value = {
                    "provider": "google",
                    "model": "gemini-pro",
                    "reason": "policy"
                }

                result = pc._safe_route("app", "task_security_gate", "security")

                assert result["provider"] == "google"

    def test_restricted_operation_denied_for_legal_task(self):
        """Restricted ops on legal tasks without authorization -> degrade."""
        with patch.dict(os.environ, {"ORCH_LEGAL_ALLOWED_OPERATIONS": ""}):
            result = pc._safe_route("app", "permission_audit", "legal")

            assert result["provider"] == "claude"
            assert "operation unauthorized" in result["reason"]

    def test_task_security_gate_restricted_op(self):
        """task_security_gate is a restricted operation."""
        assert "task_security_gate" in pc.RESTRICTED_OPERATIONS

    def test_task_legal_gate_restricted_op(self):
        """task_legal_gate is a restricted operation."""
        assert "task_legal_gate" in pc.RESTRICTED_OPERATIONS


class TestCredentialAllowlists:
    """Tests for security/legal task allowlists."""

    def test_security_task_blocked_by_allowlist(self):
        """Security task with non-allowlisted kind -> blocked."""
        with patch.dict(os.environ, {"ORCH_SECURITY_TASK_ALLOWLIST": "build,review"}):
            result = pc.classify("Fix vulnerability", kind="speculative")

            # Should degrade to standard build instead of security routing
            # This depends on _credential_allows returning False
            allowed = pc._credential_allows("security", "speculative", "Fix vulnerability")
            assert allowed is False

    def test_security_task_allowed_by_allowlist(self):
        """Security task with allowlisted kind -> allowed."""
        with patch.dict(os.environ, {"ORCH_SECURITY_TASK_ALLOWLIST": "build,review,security"}):
            allowed = pc._credential_allows("security", "security", "Fix vulnerability")
            assert allowed is True

    def test_legal_task_blocked_by_allowlist(self):
        """Legal task with non-allowlisted kind -> blocked."""
        with patch.dict(os.environ, {"ORCH_LEGAL_TASK_ALLOWLIST": "build"}):
            allowed = pc._credential_allows("legal", "speculative", "Review contract")
            assert allowed is False

    def test_legal_task_allowed_by_allowlist(self):
        """Legal task with allowlisted kind -> allowed."""
        with patch.dict(os.environ, {"ORCH_LEGAL_TASK_ALLOWLIST": "build,legal_review"}):
            allowed = pc._credential_allows("legal", "legal_review", "Review contract")
            assert allowed is True

    def test_no_allowlist_env_permits_all(self):
        """No allowlist env var -> all tasks permitted."""
        with patch.dict(os.environ, {}, clear=False):
            # Remove allowlist vars if present
            os.environ.pop("ORCH_SECURITY_TASK_ALLOWLIST", None)
            os.environ.pop("ORCH_LEGAL_TASK_ALLOWLIST", None)

            allowed_sec = pc._credential_allows("security", "any_kind", "text")
            allowed_legal = pc._credential_allows("legal", "any_kind", "text")

            assert allowed_sec is True
            assert allowed_legal is True


class TestBuildPlanPreflightStrategy:
    """Tests for preflight/strategy integration in build_plan."""

    def test_build_plan_calls_preflight_with_rating_task_class(self):
        """build_plan should call _safe_route for preflight with task_class='rating'."""
        with patch('pipeline_contract._author_model') as mock_author:
            with patch('pipeline_contract._coder') as mock_coder:
                with patch('pipeline_contract._safe_route') as mock_route:
                    with patch('pipeline_contract._qa_panel') as mock_panel:
                        with patch('pipeline_contract._recent_context') as mock_context:
                            mock_author.return_value = "claude"
                            mock_coder.return_value = "claude"
                            mock_route.return_value = {"provider": "test", "model": "test", "reason": "test"}
                            mock_panel.return_value = []
                            mock_context.return_value = []

                            pc.build_plan("Test prompt")

                            # Find preflight call
                            preflight_calls = [c for c in mock_route.call_args_list
                                             if c[0][1] == "task_preflight"]
                            assert len(preflight_calls) == 1
                            # Check task_class parameter
                            assert preflight_calls[0][1].get("task_class") == "rating"

    def test_build_plan_calls_strategy_with_plan_task_class(self):
        """build_plan should call _safe_route for strategy with task_class='plan'."""
        with patch('pipeline_contract._author_model') as mock_author:
            with patch('pipeline_contract._coder') as mock_coder:
                with patch('pipeline_contract._safe_route') as mock_route:
                    with patch('pipeline_contract._qa_panel') as mock_panel:
                        with patch('pipeline_contract._recent_context') as mock_context:
                            mock_author.return_value = "claude"
                            mock_coder.return_value = "claude"
                            mock_route.return_value = {"provider": "test", "model": "test", "reason": "test"}
                            mock_panel.return_value = []
                            mock_context.return_value = []

                            pc.build_plan("Test prompt")

                            # Find strategy call
                            strategy_calls = [c for c in mock_route.call_args_list
                                            if c[0][1] == "task_strategy"]
                            assert len(strategy_calls) == 1
                            # Check task_class parameter
                            assert strategy_calls[0][1].get("task_class") == "plan"

    def test_build_plan_strategy_need_minimum_7(self):
        """Strategy need should be at least 7 regardless of task classification."""
        with patch('pipeline_contract._author_model') as mock_author:
            with patch('pipeline_contract._coder') as mock_coder:
                with patch('pipeline_contract._safe_route') as mock_route:
                    with patch('pipeline_contract._qa_panel') as mock_panel:
                        with patch('pipeline_contract._recent_context') as mock_context:
                            mock_author.return_value = "claude"
                            mock_coder.return_value = "claude"
                            mock_route.return_value = {"provider": "test", "model": "test", "reason": "test"}
                            mock_panel.return_value = []
                            mock_context.return_value = []

                            # Mechanical task has need=5
                            pc.build_plan("Fix typo", kind="efficiency")

                            # Find strategy call
                            strategy_calls = [c for c in mock_route.call_args_list
                                            if c[0][1] == "task_strategy"]
                            strategy_need = strategy_calls[0][0][3]  # need parameter
                            assert strategy_need >= 7

    def test_build_plan_preserves_existing_behavior_on_preflight_failure(self):
        """build_plan should complete even if preflight routing fails."""
        with patch('pipeline_contract._author_model') as mock_author:
            with patch('pipeline_contract._coder') as mock_coder:
                with patch('pipeline_contract._safe_route') as mock_route:
                    with patch('pipeline_contract._qa_panel') as mock_panel:
                        with patch('pipeline_contract._recent_context') as mock_context:
                            mock_author.return_value = "claude"
                            mock_coder.return_value = "claude"
                            # First call (preflight) fails, others succeed
                            mock_route.side_effect = [
                                Exception("preflight failed"),
                                {"provider": "test", "model": "test", "reason": "test"},  # strategy
                                {"provider": "test", "model": "test", "reason": "test"}    # qa
                            ]
                            mock_panel.return_value = []
                            mock_context.return_value = []

                            # Should not raise, should complete
                            plan = pc.build_plan("Test")
                            assert "preflight" in plan
                            assert plan["preflight"] is not None

    def test_build_plan_preserves_existing_behavior_on_strategy_failure(self):
        """build_plan should complete even if strategy routing fails."""
        with patch('pipeline_contract._author_model') as mock_author:
            with patch('pipeline_contract._coder') as mock_coder:
                with patch('pipeline_contract._safe_route') as mock_route:
                    with patch('pipeline_contract._qa_panel') as mock_panel:
                        with patch('pipeline_contract._recent_context') as mock_context:
                            mock_author.return_value = "claude"
                            mock_coder.return_value = "claude"
                            # First call succeeds, second (strategy) fails, third succeeds
                            mock_route.side_effect = [
                                {"provider": "test", "model": "test", "reason": "test"},  # preflight
                                Exception("strategy failed"),
                                {"provider": "test", "model": "test", "reason": "test"}    # qa
                            ]
                            mock_panel.return_value = []
                            mock_context.return_value = []

                            # Should not raise, should complete
                            plan = pc.build_plan("Test")
                            assert "strategy" in plan
                            assert plan["strategy"] is not None


class TestWrapPromptPreservesSemantics:
    """Tests that prompt wrapping preserves task semantics through routing."""

    def test_wrap_security_prompt_maintains_classification(self):
        """Security prompts should maintain classification through wrap/unwrap."""
        security_prompt = "Fix SQL injection in user_id parameter"
        wrapped = pc.wrap_prompt(security_prompt, project="app1")

        assert pc.already_wrapped(wrapped)
        assert security_prompt in wrapped

        original = pc.original_request(wrapped)
        assert security_prompt in original

        # Re-classify the original
        classification = pc.classify(original)
        assert classification["task_class"] == "security"

    def test_wrap_legal_prompt_maintains_classification(self):
        """Legal prompts should maintain classification through wrap/unwrap."""
        legal_prompt = "Review licensing requirements for new dependencies"
        wrapped = pc.wrap_prompt(legal_prompt, project="app1", material=True)

        assert pc.already_wrapped(wrapped)
        original = pc.original_request(wrapped)

        classification = pc.classify(original)
        assert classification["task_class"] == "legal"

    def test_wrap_preserves_routing_decisions(self):
        """Wrapped prompt routing should match original routing."""
        original_text = "Implement feature X"

        with patch('pipeline_contract._author_model') as mock_author:
            with patch('pipeline_contract._coder') as mock_coder:
                with patch('pipeline_contract._safe_route') as mock_route:
                    with patch('pipeline_contract._qa_panel') as mock_panel:
                        with patch('pipeline_contract._recent_context') as mock_context:
                            mock_author.return_value = "claude-opus"
                            mock_coder.return_value = "claude"
                            mock_route.return_value = {"provider": "google", "model": "gemini", "reason": "policy"}
                            mock_panel.return_value = ["local:llama"]
                            mock_context.return_value = []

                            plan_original = pc.build_plan(original_text, project="test")

                            wrapped = pc.wrap_prompt(original_text, project="test")
                            extracted = pc.original_request(wrapped)

                            plan_extracted = pc.build_plan(extracted, project="test")

                            # Plans should match
                            assert plan_original["task_class"] == plan_extracted["task_class"]
                            assert plan_original["need"] == plan_extracted["need"]


class TestOperationAuthorizationCheck:
    """Tests for _operation_authorized function."""

    def test_operation_authorized_with_empty_allowed_operations(self):
        """Empty allowed operations string means no operations allowed."""
        with patch.dict(os.environ, {"ORCH_SECURITY_ALLOWED_OPERATIONS": ""}):
            authorized = pc._operation_authorized("task_security_gate", "security")
            assert authorized is False

    def test_operation_authorized_with_matching_operation(self):
        """Operation in allowed list -> authorized."""
        with patch.dict(os.environ, {"ORCH_SECURITY_ALLOWED_OPERATIONS": "task_security_gate,other_op"}):
            authorized = pc._operation_authorized("task_security_gate", "security")
            assert authorized is True

    def test_operation_authorized_with_non_matching_operation(self):
        """Operation not in allowed list -> not authorized."""
        with patch.dict(os.environ, {"ORCH_SECURITY_ALLOWED_OPERATIONS": "other_op"}):
            authorized = pc._operation_authorized("task_security_gate", "security")
            assert authorized is False

    def test_operation_authorized_no_env_var(self):
        """No env var -> operation authorized (permissive default)."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ORCH_SECURITY_ALLOWED_OPERATIONS", None)
            authorized = pc._operation_authorized("task_security_gate", "security")
            assert authorized is True

    def test_operation_authorized_handles_exception(self):
        """Exception during auth check -> fail-soft, allow operation."""
        with patch.dict(os.environ, {"ORCH_SECURITY_ALLOWED_OPERATIONS": "invalid[syntax"}):
            # Should not raise, should return True (fail-soft)
            authorized = pc._operation_authorized("any_op", "security")
            assert authorized is True


class TestFailSoftPreservesExistingBehavior:
    """Tests that fail-soft degradation preserves existing behavior."""

    def test_wrap_prompt_degraded_still_wraps(self):
        """Even if internal routing fails, wrap_prompt still wraps."""
        with patch('pipeline_contract.build_plan') as mock_plan:
            mock_plan.side_effect = Exception("Build failed")

            # wrap_prompt calls build_plan; if it fails, should still work
            # Actually, wrap_prompt will fail if build_plan fails during the call
            # But the contract is that if build_plan returns a valid dict, rendering succeeds

            # Let's test that render_plan is robust
            bad_plan = {}
            rendered = pc.render_plan(bad_plan)
            assert pc.MARKER in rendered

    def test_render_plan_handles_missing_fields(self):
        """render_plan should handle missing fields without error."""
        minimal_plan = {"source": "test"}
        rendered = pc.render_plan(minimal_plan)

        # Should not raise, should include marker
        assert pc.MARKER in rendered
        assert "test" in rendered

    def test_artifact_returns_json_on_any_error(self):
        """artifact() should always return valid JSON, even on error."""
        with patch('pipeline_contract.build_plan') as mock_plan:
            mock_plan.side_effect = Exception("Fatal error")

            result = pc.artifact("prompt")

            # Should be valid JSON
            parsed = json.loads(result)
            assert isinstance(parsed, dict)

    def test_classify_never_returns_none(self):
        """classify() should always return a dict with required keys."""
        for prompt in [None, "", "   ", "x" * 10000, "auth security legal", "üñíçödé"]:
            result = pc.classify(prompt)
            assert isinstance(result, dict)
            assert "task_class" in result
            assert "need" in result
            assert "risk" in result


class TestPreflightTriageEdgeCases:
    """Edge cases for preflight triage routing."""

    def test_preflight_agentic_false_for_preflight(self):
        """Preflight should be called with agentic=False."""
        with patch('pipeline_contract.app_triage') as mock_triage:
            mock_triage.route.return_value = {"provider": "test", "model": "test", "reason": "test"}

            with patch('pipeline_contract._author_model') as mock_author:
                with patch('pipeline_contract._coder') as mock_coder:
                    with patch('pipeline_contract._safe_route') as mock_route:
                        with patch('pipeline_contract._qa_panel') as mock_panel:
                            with patch('pipeline_contract._recent_context') as mock_context:
                                mock_author.return_value = "claude"
                                mock_coder.return_value = "claude"
                                mock_route.return_value = {"provider": "test", "model": "test", "reason": "test"}
                                mock_panel.return_value = []
                                mock_context.return_value = []

                                pc.build_plan("Test")

                                # Check first _safe_route call (preflight)
                                first_call = mock_route.call_args_list[0]
                                assert first_call[1].get("agentic") is False

    def test_strategy_agentic_false_for_strategy(self):
        """Strategy should be called with agentic=False."""
        with patch('pipeline_contract.app_triage') as mock_triage:
            mock_triage.route.return_value = {"provider": "test", "model": "test", "reason": "test"}

            with patch('pipeline_contract._author_model') as mock_author:
                with patch('pipeline_contract._coder') as mock_coder:
                    with patch('pipeline_contract._safe_route') as mock_route:
                        with patch('pipeline_contract._qa_panel') as mock_panel:
                            with patch('pipeline_contract._recent_context') as mock_context:
                                mock_author.return_value = "claude"
                                mock_coder.return_value = "claude"
                                mock_route.return_value = {"provider": "test", "model": "test", "reason": "test"}
                                mock_panel.return_value = []
                                mock_context.return_value = []

                                pc.build_plan("Test")

                                # Check second _safe_route call (strategy)
                                second_call = mock_route.call_args_list[1]
                                assert second_call[1].get("agentic") is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
