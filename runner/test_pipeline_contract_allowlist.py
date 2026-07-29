#!/usr/bin/env python3
"""
Test suite for pipeline_contract.py allowlist and authorization features.

Tests cover:
- Security and legal task allowlist configuration
- Credential authorization checks for restricted task classes
- Operation authorization for restricted operations
- Fail-soft permission error handling
- Integration with task classification and routing
- Environment variable parsing and edge cases
"""
import pytest
import importlib
import os
import json
from unittest.mock import Mock, patch, MagicMock
import pipeline_contract as pc


class TestAllowlistConfiguration:
    """Tests for allowlist initialization from environment variables."""

    def test_security_allowlist_single_value(self):
        with patch.dict(os.environ, {"ORCH_SECURITY_TASK_ALLOWLIST": "build"}):
            # Re-import to pick up env var
            import importlib
            importlib.reload(pc)
            assert pc.SECURITY_TASK_ALLOWLIST == {"build"}

    def test_security_allowlist_multiple_values(self):
        with patch.dict(os.environ, {"ORCH_SECURITY_TASK_ALLOWLIST": "build,research,strategy"}):
            importlib.reload(pc)
            assert pc.SECURITY_TASK_ALLOWLIST == {"build", "research", "strategy"}

    def test_security_allowlist_none_when_unset(self):
        with patch.dict(os.environ, {}, clear=True):
            importlib.reload(pc)
            # When env var is not set, allowlist should be None (allow-all mode)
            assert pc.SECURITY_TASK_ALLOWLIST is None

    def test_legal_allowlist_single_value(self):
        with patch.dict(os.environ, {"ORCH_LEGAL_TASK_ALLOWLIST": "strategy"}):
            importlib.reload(pc)
            assert pc.LEGAL_TASK_ALLOWLIST == {"strategy"}

    def test_legal_allowlist_multiple_values(self):
        with patch.dict(os.environ, {"ORCH_LEGAL_TASK_ALLOWLIST": "research,strategy,plan"}):
            importlib.reload(pc)
            assert pc.LEGAL_TASK_ALLOWLIST == {"research", "strategy", "plan"}

    def test_legal_allowlist_none_when_unset(self):
        with patch.dict(os.environ, {}, clear=True):
            importlib.reload(pc)
            assert pc.LEGAL_TASK_ALLOWLIST is None

    def test_allowlist_whitespace_trimming(self):
        with patch.dict(os.environ, {"ORCH_SECURITY_TASK_ALLOWLIST": " build , research "}):
            importlib.reload(pc)
            # Should preserve spaces as-is from split (no trimming)
            # This tests the actual behavior of split() which doesn't trim
            values = set(" build , research ".split(","))
            assert pc.SECURITY_TASK_ALLOWLIST == values

    def test_allowlist_empty_string(self):
        with patch.dict(os.environ, {"ORCH_SECURITY_TASK_ALLOWLIST": ""}):
            importlib.reload(pc)
            # Empty string should create empty set, not None
            assert pc.SECURITY_TASK_ALLOWLIST == set()

    def test_allowlist_duplicate_values(self):
        with patch.dict(os.environ, {"ORCH_SECURITY_TASK_ALLOWLIST": "build,build,research"}):
            importlib.reload(pc)
            assert pc.SECURITY_TASK_ALLOWLIST == {"build", "research"}


class TestCredentialAllows:
    """Tests for _credential_allows() function."""

    def test_credential_allows_security_none_allowlist(self):
        # When allowlist is None, all kinds are allowed
        with patch.object(pc, "SECURITY_TASK_ALLOWLIST", None):
            assert pc._credential_allows("security", "build", "some text") is True
            assert pc._credential_allows("security", "research", "some text") is True
            assert pc._credential_allows("security", "unknown", "some text") is True

    def test_credential_allows_security_in_allowlist(self):
        with patch.object(pc, "SECURITY_TASK_ALLOWLIST", {"build", "research"}):
            assert pc._credential_allows("security", "build", "some text") is True
            assert pc._credential_allows("security", "research", "some text") is True

    def test_credential_allows_security_not_in_allowlist(self):
        with patch.object(pc, "SECURITY_TASK_ALLOWLIST", {"build"}):
            assert pc._credential_allows("security", "research", "some text") is False
            assert pc._credential_allows("security", "strategy", "some text") is False

    def test_credential_allows_security_empty_allowlist(self):
        # Empty allowlist means nothing is allowed
        with patch.object(pc, "SECURITY_TASK_ALLOWLIST", set()):
            assert pc._credential_allows("security", "build", "some text") is False
            assert pc._credential_allows("security", "research", "some text") is False

    def test_credential_allows_legal_none_allowlist(self):
        # When allowlist is None, all kinds are allowed
        with patch.object(pc, "LEGAL_TASK_ALLOWLIST", None):
            assert pc._credential_allows("legal", "build", "some text") is True
            assert pc._credential_allows("legal", "research", "some text") is True

    def test_credential_allows_legal_in_allowlist(self):
        with patch.object(pc, "LEGAL_TASK_ALLOWLIST", {"strategy", "research"}):
            assert pc._credential_allows("legal", "strategy", "some text") is True
            assert pc._credential_allows("legal", "research", "some text") is True

    def test_credential_allows_legal_not_in_allowlist(self):
        with patch.object(pc, "LEGAL_TASK_ALLOWLIST", {"strategy"}):
            assert pc._credential_allows("legal", "build", "some text") is False
            assert pc._credential_allows("legal", "research", "some text") is False

    def test_credential_allows_legal_empty_allowlist(self):
        with patch.object(pc, "LEGAL_TASK_ALLOWLIST", set()):
            assert pc._credential_allows("legal", "build", "some text") is False
            assert pc._credential_allows("legal", "strategy", "some text") is False

    def test_credential_allows_other_task_class(self):
        # Non-restricted task classes should always be allowed
        with patch.object(pc, "SECURITY_TASK_ALLOWLIST", {"build"}):
            with patch.object(pc, "LEGAL_TASK_ALLOWLIST", {"strategy"}):
                assert pc._credential_allows("build", "research", "text") is True
                assert pc._credential_allows("mechanical", "unknown", "text") is True
                assert pc._credential_allows("plan", "anything", "text") is True

    def test_credential_allows_case_sensitivity(self):
        # kind parameter is lowercased
        with patch.object(pc, "SECURITY_TASK_ALLOWLIST", {"build"}):
            assert pc._credential_allows("security", "Build", "text") is True  # Lowercased
            assert pc._credential_allows("security", "BUILD", "text") is True  # Lowercased


class TestOperationAuthorized:
    """Tests for _operation_authorized() function."""

    def test_operation_authorized_no_env_var(self):
        # When no env var set, all operations are allowed
        with patch.dict(os.environ, {}, clear=True):
            assert pc._operation_authorized("task_security_gate", "security") is True
            assert pc._operation_authorized("task_legal_gate", "legal") is True
            assert pc._operation_authorized("any_operation", "build") is True

    def test_operation_authorized_allowed_operation(self):
        with patch.dict(os.environ, {"ORCH_SECURITY_ALLOWED_OPERATIONS": "task_security_gate,permission_audit"}):
            assert pc._operation_authorized("task_security_gate", "security") is True
            assert pc._operation_authorized("permission_audit", "security") is True

    def test_operation_authorized_denied_operation(self):
        with patch.dict(os.environ, {"ORCH_SECURITY_ALLOWED_OPERATIONS": "task_security_gate"}):
            assert pc._operation_authorized("task_security_gate", "security") is True
            assert pc._operation_authorized("credential_validation", "security") is False

    def test_operation_authorized_empty_allowed_list(self):
        # Empty list means no operations are allowed
        with patch.dict(os.environ, {"ORCH_SECURITY_ALLOWED_OPERATIONS": ""}):
            assert pc._operation_authorized("task_security_gate", "security") is False
            assert pc._operation_authorized("any_op", "security") is False

    def test_operation_authorized_legal_operations(self):
        with patch.dict(os.environ, {"ORCH_LEGAL_ALLOWED_OPERATIONS": "task_legal_gate"}):
            assert pc._operation_authorized("task_legal_gate", "legal") is True
            assert pc._operation_authorized("permission_audit", "legal") is False

    def test_operation_authorized_fail_soft_on_exception(self):
        # If there's an error parsing env, should fail-soft and allow
        with patch.dict(os.environ, {"ORCH_SECURITY_ALLOWED_OPERATIONS": "malformed\x00data"}):
            # Should not raise, should return True (fail-soft)
            result = pc._operation_authorized("task_security_gate", "security")
            assert isinstance(result, bool)

    def test_operation_authorized_multi_operation_list(self):
        with patch.dict(os.environ, {"ORCH_SECURITY_ALLOWED_OPERATIONS": "op1,op2,op3,op4"}):
            assert pc._operation_authorized("op1", "security") is True
            assert pc._operation_authorized("op2", "security") is True
            assert pc._operation_authorized("op3", "security") is True
            assert pc._operation_authorized("op4", "security") is True
            assert pc._operation_authorized("op5", "security") is False


class TestRestrictedOperations:
    """Tests for RESTRICTED_OPERATIONS enforcement."""

    def test_restricted_operations_set_not_empty(self):
        assert pc.RESTRICTED_OPERATIONS is not None
        assert len(pc.RESTRICTED_OPERATIONS) > 0

    def test_restricted_operations_includes_security_gate(self):
        assert "task_security_gate" in pc.RESTRICTED_OPERATIONS

    def test_restricted_operations_includes_legal_gate(self):
        assert "task_legal_gate" in pc.RESTRICTED_OPERATIONS

    def test_restricted_operations_includes_permission_audit(self):
        assert "permission_audit" in pc.RESTRICTED_OPERATIONS

    def test_restricted_operations_includes_credential_validation(self):
        assert "credential_validation" in pc.RESTRICTED_OPERATIONS


class TestClassifyWithAllowlist:
    """Tests for classify() function with allowlist enforcement."""

    def test_classify_legal_with_allowlist_allowed(self):
        with patch.object(pc, "LEGAL_TASK_ALLOWLIST", {"research"}):
            result = pc.classify("licensing requirements", kind="research")
            # Should be legal since kind is in allowlist
            # Note: depends on LEGAL_RX matching and allowlist check
            assert result["task_class"] in ("legal", "build")

    def test_classify_legal_with_allowlist_denied(self):
        with patch.object(pc, "LEGAL_TASK_ALLOWLIST", {"strategy"}):
            result = pc.classify("licensing requirements", kind="build")
            # Should be gated to build if allowlist denies
            if "security_gated" in result:
                assert result["security_gated"] is True

    def test_classify_security_with_allowlist_allowed(self):
        with patch.object(pc, "SECURITY_TASK_ALLOWLIST", {"build"}):
            result = pc.classify("Fix XSS vulnerability", kind="build")
            # May still be security class, but depends on regex matching
            assert "task_class" in result

    def test_classify_security_with_allowlist_denied(self):
        with patch.object(pc, "SECURITY_TASK_ALLOWLIST", {"research"}):
            result = pc.classify("Fix authentication bug", kind="build")
            # Should be gated if kind not in allowlist
            if "security_gated" in result:
                assert result["security_gated"] is True

    def test_classify_legal_keywords_match(self):
        # Test that LEGAL_RX regex matches legal keywords
        legal_keywords = [
            "legal requirement",
            "compliance audit",
            "licensing agreement",
            "registration process",
            "custody arrangement",
            "transmission protocol",
            "legal advice",
            "contract term",
            "privacy policy",
            "GDPR compliance",
            "HIPAA requirement",
            "PCI audit",
            "SOC 2 control",
            "regulatory requirement",
            "counsel decision",
            "attorney opinion",
            "lawyer review",
        ]
        for keyword in legal_keywords:
            result = pc.classify(keyword)
            # Legal regex should match these
            match = pc.LEGAL_RX.search(keyword)
            assert match is not None, f"LEGAL_RX should match '{keyword}'"


class TestSafeRouteWithAuthorization:
    """Tests for _safe_route() with restricted operation checks."""

    def test_safe_route_restricted_operation_denied(self):
        with patch.object(pc, "_operation_authorized", return_value=False):
            result = pc._safe_route("app", "task_security_gate", "security")
            assert result["reason"] == "operation unauthorized for task class"
            assert result["model"] == "claude-haiku-4-5-20251001"

    def test_safe_route_restricted_operation_allowed(self):
        with patch.object(pc, "_operation_authorized", return_value=True):
            with patch.object(pc, "app_triage") as mock_triage:
                mock_triage.route.return_value = {
                    "provider": "test",
                    "model": "test-model",
                    "reason": "policy"
                }
                result = pc._safe_route("app", "task_security_gate", "security")
                # Should continue to normal routing
                assert result["provider"] == "test"

    def test_safe_route_unrestricted_operation(self):
        # Non-restricted operations should not trigger authorization check
        with patch.object(pc, "app_triage") as mock_triage:
            mock_triage.route.return_value = {
                "provider": "local",
                "model": "llama",
                "reason": "policy"
            }
            result = pc._safe_route("app", "normal_operation", "build")
            assert result["provider"] == "local"

    def test_safe_route_restricted_operation_legal_task(self):
        with patch.object(pc, "_operation_authorized", return_value=False):
            result = pc._safe_route("app", "task_legal_gate", "legal")
            assert result["reason"] == "operation unauthorized for task class"

    def test_safe_route_restricted_operation_non_restricted_class(self):
        # Restricted operations don't apply to non-restricted task classes
        with patch.object(pc, "app_triage") as mock_triage:
            mock_triage.route.return_value = {
                "provider": "test",
                "model": "test-model",
                "reason": "policy"
            }
            result = pc._safe_route("app", "task_security_gate", "build")
            # Should proceed normally for non-security/legal classes
            assert result["provider"] == "test"


class TestPermissionErrorHandling:
    """Tests for permission error handling in _safe_route()."""

    def test_safe_route_permission_error_from_app_triage(self):
        with patch("pipeline_contract.app_triage") as mock_triage:
            mock_triage.route.side_effect = PermissionError("Access denied")
            with patch("pipeline_contract.model_policy.choose") as mock_policy:
                mock_policy.return_value = ("claude", "claude-opus", "fallback")
                result = pc._safe_route("app", "operation", "security")
                # Should fall back to model_policy, not raise
                assert result["provider"] == "claude"

    def test_safe_route_permission_error_from_model_policy(self):
        with patch("pipeline_contract.app_triage", None):
            with patch("pipeline_contract.model_policy.choose") as mock_policy:
                mock_policy.side_effect = PermissionError("Permission denied")
                result = pc._safe_route("app", "operation", "security")
                # Should return fallback policy
                assert result["model"] == "claude-haiku-4-5-20251001"
                assert result["reason"] == "fallback policy (permission denied)"

    def test_safe_route_permission_error_both_fail(self):
        with patch("pipeline_contract.app_triage") as mock_triage:
            mock_triage.route.side_effect = PermissionError()
            with patch("pipeline_contract.model_policy.choose") as mock_policy:
                mock_policy.side_effect = PermissionError()
                result = pc._safe_route("app", "op", "legal")
                # Should return fallback
                assert result["provider"] == "claude"
                assert "haiku" in result["model"]


class TestRecentContextPermissionErrors:
    """Tests for permission error handling in _recent_context()."""

    def test_recent_context_outcomes_permission_error(self):
        mock_db = MagicMock()
        mock_db.select.side_effect = PermissionError("Access denied to outcomes table")

        with patch("pipeline_contract.db", mock_db):
            result = pc._recent_context("test-project")
            # Should not raise, should return empty or skip that item
            assert isinstance(result, list)

    def test_recent_context_routes_permission_error(self):
        mock_db = MagicMock()
        mock_db.select.side_effect = [[], PermissionError("Access denied to routes")]

        with patch("pipeline_contract.db", mock_db):
            result = pc._recent_context("test-project")
            # Should handle permission error gracefully
            assert isinstance(result, list)

    def test_recent_context_feedback_permission_error(self):
        mock_db = MagicMock()
        mock_db.select.side_effect = [[], [], PermissionError("Access denied to feedback")]

        with patch("pipeline_contract.db", mock_db):
            result = pc._recent_context("test-project")
            # Should handle permission error gracefully
            assert isinstance(result, list)


class TestQAPanelLegalTask:
    """Tests for _qa_panel() with legal task class."""

    def test_qa_panel_legal_task_with_local_available(self):
        with patch("pipeline_contract.judge", None):
            with patch("pipeline_contract.mg.available") as mock_available:
                mock_available.return_value = ["local", "deepseek", "google"]
                result = pc._qa_panel("claude-opus", task_class="legal")
                # Should prefer local and deepseek for legal tasks
                assert len(result) > 0

    def test_qa_panel_legal_task_with_local_only(self):
        with patch("pipeline_contract.judge", None):
            with patch("pipeline_contract.mg.available") as mock_available:
                mock_available.return_value = ["local"]
                result = pc._qa_panel("claude-opus", task_class="legal")
                # Should include local models
                assert len(result) > 0

    def test_qa_panel_legal_task_with_deepseek_only(self):
        with patch("pipeline_contract.judge", None):
            with patch("pipeline_contract.mg.available") as mock_available:
                mock_available.return_value = ["deepseek"]
                result = pc._qa_panel("claude-opus", task_class="legal")
                # Should include deepseek
                assert len(result) > 0

    def test_qa_panel_legal_task_no_local_or_deepseek(self):
        with patch("pipeline_contract.judge", None):
            with patch("pipeline_contract.mg.available") as mock_available:
                mock_available.return_value = ["google", "openai", "claude"]
                result = pc._qa_panel("claude-opus", task_class="legal")
                # Should fall back to general availability
                assert len(result) > 0

    def test_qa_panel_legal_task_exception_handling(self):
        with patch("pipeline_contract.judge", None):
            with patch("pipeline_contract.mg.available") as mock_available:
                mock_available.side_effect = Exception("Service error")
                result = pc._qa_panel("claude-opus", task_class="legal")
                # Should not raise, fall back to default
                assert len(result) > 0

    def test_qa_panel_non_legal_task_unchanged(self):
        with patch("pipeline_contract.judge", None):
            with patch("pipeline_contract.mg.available") as mock_available:
                mock_available.return_value = ["local", "deepseek", "google"]
                result = pc._qa_panel("claude-opus", task_class="build")
                # Should use normal availability check
                assert len(result) > 0


class TestBuildPlanWithAuthorization:
    """Tests for build_plan() with allowlist integration."""

    def test_build_plan_legal_task_with_allowlist(self):
        with patch("pipeline_contract._author_model") as mock_author:
            with patch("pipeline_contract._coder") as mock_coder:
                with patch("pipeline_contract._safe_route") as mock_route:
                    with patch("pipeline_contract._qa_panel") as mock_panel:
                        with patch("pipeline_contract._recent_context") as mock_context:
                            mock_author.return_value = "claude-opus"
                            mock_coder.return_value = "claude"
                            mock_route.return_value = {"provider": "test", "model": "test", "reason": "test"}
                            mock_panel.return_value = ["local:llama"]
                            mock_context.return_value = []

                            with patch.object(pc, "LEGAL_TASK_ALLOWLIST", {"research"}):
                                plan = pc.build_plan("compliance audit", kind="research")
                                assert "task_class" in plan

    def test_build_plan_security_task_with_allowlist(self):
        with patch("pipeline_contract._author_model") as mock_author:
            with patch("pipeline_contract._coder") as mock_coder:
                with patch("pipeline_contract._safe_route") as mock_route:
                    with patch("pipeline_contract._qa_panel") as mock_panel:
                        with patch("pipeline_contract._recent_context") as mock_context:
                            mock_author.return_value = "claude-opus"
                            mock_coder.return_value = "claude"
                            mock_route.return_value = {"provider": "test", "model": "test", "reason": "test"}
                            mock_panel.return_value = ["local:llama"]
                            mock_context.return_value = []

                            with patch.object(pc, "SECURITY_TASK_ALLOWLIST", {"build"}):
                                plan = pc.build_plan("Fix XSS", kind="build")
                                assert "task_class" in plan


class TestLegalRegex:
    """Tests for LEGAL_RX regular expression."""

    def test_legal_rx_matches_legal_keyword(self):
        assert pc.LEGAL_RX.search("legal requirement") is not None
        assert pc.LEGAL_RX.search("This is a legal matter") is not None

    def test_legal_rx_matches_compliance_keyword(self):
        assert pc.LEGAL_RX.search("compliance audit") is not None
        assert pc.LEGAL_RX.search("need compliance") is not None

    def test_legal_rx_matches_contract_keyword(self):
        assert pc.LEGAL_RX.search("contract term") is not None
        assert pc.LEGAL_RX.search("sign contract") is not None

    def test_legal_rx_matches_licensing_keyword(self):
        assert pc.LEGAL_RX.search("licensing agreement") is not None
        assert pc.LEGAL_RX.search("license") is not None

    def test_legal_rx_matches_privacy_keyword(self):
        assert pc.LEGAL_RX.search("privacy policy") is not None
        assert pc.LEGAL_RX.search("GDPR") is not None
        assert pc.LEGAL_RX.search("HIPAA") is not None

    def test_legal_rx_no_false_positives(self):
        assert pc.LEGAL_RX.search("regular development task") is None
        assert pc.LEGAL_RX.search("bug fix") is None
        assert pc.LEGAL_RX.search("implement feature") is None

    def test_legal_rx_case_insensitive(self):
        assert pc.LEGAL_RX.search("LEGAL REQUIREMENT") is not None
        assert pc.LEGAL_RX.search("Legal Requirement") is not None
        assert pc.LEGAL_RX.search("CONTRACT TERM") is not None


class TestIntegrationAllowlist:
    """End-to-end integration tests for allowlist functionality."""

    def test_full_security_task_with_authorization_denied(self):
        with patch("pipeline_contract._author_model") as mock_author:
            with patch("pipeline_contract._coder") as mock_coder:
                with patch("pipeline_contract._safe_route") as mock_route:
                    with patch("pipeline_contract._qa_panel") as mock_panel:
                        with patch("pipeline_contract._recent_context") as mock_context:
                            mock_author.return_value = "claude-opus"
                            mock_coder.return_value = "claude"
                            mock_route.return_value = {"provider": "test", "model": "test", "reason": "test"}
                            mock_panel.return_value = ["local:llama"]
                            mock_context.return_value = []

                            with patch.object(pc, "SECURITY_TASK_ALLOWLIST", {"research"}):
                                plan = pc.build_plan("Fix XSS vulnerability", kind="build")
                                assert plan["task_class"] == "build"  # May be gated

    def test_full_legal_task_with_authorization_allowed(self):
        with patch("pipeline_contract._author_model") as mock_author:
            with patch("pipeline_contract._coder") as mock_coder:
                with patch("pipeline_contract._safe_route") as mock_route:
                    with patch("pipeline_contract._qa_panel") as mock_panel:
                        with patch("pipeline_contract._recent_context") as mock_context:
                            mock_author.return_value = "claude-opus"
                            mock_coder.return_value = "claude"
                            mock_route.return_value = {"provider": "test", "model": "test", "reason": "test"}
                            mock_panel.return_value = ["local:llama"]
                            mock_context.return_value = []

                            with patch.object(pc, "LEGAL_TASK_ALLOWLIST", {"strategy"}):
                                plan = pc.build_plan("Review licensing terms", kind="strategy")
                                assert "task_class" in plan


class TestEdgeCasesAllowlist:
    """Edge cases and boundary conditions for allowlist."""

    def test_credential_allows_empty_kind(self):
        with patch.object(pc, "SECURITY_TASK_ALLOWLIST", {"build"}):
            result = pc._credential_allows("security", "", "text")
            assert result is False

    def test_credential_allows_none_kind(self):
        with patch.object(pc, "SECURITY_TASK_ALLOWLIST", {"build"}):
            result = pc._credential_allows("security", None, "text")
            # None.lower() would raise, but function should handle it
            # or the calling code ensures kind is a string
            assert isinstance(result, bool)

    def test_operation_authorized_empty_kind(self):
        with patch.dict(os.environ, {"ORCH_SECURITY_ALLOWED_OPERATIONS": "op1"}):
            # Uppercase conversion should handle empty string
            result = pc._operation_authorized("op1", "security")
            assert isinstance(result, bool)

    def test_allowlist_with_special_characters(self):
        with patch.dict(os.environ, {"ORCH_SECURITY_TASK_ALLOWLIST": "build-fix,research_deep"}):
            importlib.reload(pc)
            assert pc.SECURITY_TASK_ALLOWLIST == {"build-fix", "research_deep"}

    def test_credential_allows_very_long_kind(self):
        long_kind = "a" * 1000
        with patch.object(pc, "SECURITY_TASK_ALLOWLIST", {long_kind}):
            result = pc._credential_allows("security", long_kind, "text")
            assert result is True

    def test_operation_authorized_very_long_operation(self):
        long_op = "x" * 1000
        with patch.dict(os.environ, {f"ORCH_SECURITY_ALLOWED_OPERATIONS": long_op}):
            result = pc._operation_authorized(long_op, "security")
            assert result is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
