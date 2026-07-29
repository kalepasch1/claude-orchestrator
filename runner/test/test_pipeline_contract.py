#!/usr/bin/env python3
"""
test_pipeline_contract.py - comprehensive tests for pipeline_contract module.

Covers: classification, permission handling, routing fallbacks, wrapping, and fail-soft behavior.
"""
import os
import sys
import json
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pipeline_contract as pc


class TestControlPrompt:
    """Tests for is_control_prompt()."""

    def test_replay_control_prompt(self):
        assert pc.is_control_prompt("REPLAY: some-slug-123")

    def test_rotate_key_control_prompt(self):
        assert pc.is_control_prompt("ROTATE_KEY: prod/database")

    def test_revoke_and_stop_control_prompt(self):
        assert pc.is_control_prompt("REVOKE_AND_STOP: team-x")

    def test_whitespace_before_control(self):
        assert pc.is_control_prompt("  REPLAY: test")
        assert pc.is_control_prompt("\t\nROTATE_KEY: test")

    def test_non_control_prompt(self):
        assert not pc.is_control_prompt("Fix the database migration")

    def test_control_in_middle_is_not_control(self):
        assert not pc.is_control_prompt("Please REPLAY: test")

    def test_empty_and_none(self):
        assert not pc.is_control_prompt("")
        assert not pc.is_control_prompt(None)


class TestAlreadyWrapped:
    """Tests for already_wrapped()."""

    def test_wrapped_prompt(self):
        wrapped = f"## {pc.MARKER}\nsome content\n## END {pc.MARKER}"
        assert pc.already_wrapped(wrapped)

    def test_unwrapped_prompt(self):
        assert not pc.already_wrapped("This is a normal prompt")

    def test_empty_and_none(self):
        assert not pc.already_wrapped("")
        assert not pc.already_wrapped(None)

    def test_partial_marker(self):
        assert not pc.already_wrapped(f"## {pc.MARKER}")  # Missing END marker


class TestOriginalRequest:
    """Tests for original_request()."""

    def test_unwrapped_returns_as_is(self):
        prompt = "Fix the bug"
        assert pc.original_request(prompt) == prompt

    def test_extract_from_wrapped(self):
        original = "Fix the database migration"
        wrapped = f"## {pc.MARKER}\n...\n## {pc.ORIGINAL_HEADER}\n{original}\n## END"
        result = pc.original_request(wrapped)
        assert original in result

    def test_fallback_removal(self):
        prompt = "## ORCHESTRATION PIPELINE CONTRACT\ncontract\n## END ORCHESTRATION PIPELINE CONTRACT\nOriginal request"
        result = pc.original_request(prompt)
        assert "Original request" in result
        assert "ORCHESTRATION PIPELINE CONTRACT" not in result

    def test_empty_and_none(self):
        assert pc.original_request("") == ""
        assert pc.original_request(None) == ""


class TestClassify:
    """Tests for classify()."""

    def test_security_classification(self):
        result = pc.classify("Add OAuth authentication to the API")
        assert result["task_class"] == "security"
        assert result["need"] >= 9
        assert result["risk"] == "security"

    def test_legal_classification(self):
        result = pc.classify("Add GDPR compliance to the system")
        assert result["task_class"] == "legal"
        assert result["need"] >= 9
        assert result["risk"] == "legal_posture"

    def test_research_classification(self):
        result = pc.classify("Research payment strategies", kind="research")
        assert result["task_class"] == "plan"
        assert result["need"] >= 8
        assert result["risk"] == "strategy"

    def test_mechanical_classification(self):
        result = pc.classify("Fix typo in documentation")
        assert result["task_class"] == "mechanical"
        assert result["need"] <= 5
        assert result["risk"] == "routine"

    def test_migration_classification(self):
        result = pc.classify("Backfill user data for schema change")
        assert result["task_class"] == "hard"
        assert result["need"] >= 8
        assert result["risk"] == "broad_change"

    def test_default_build_classification(self):
        result = pc.classify("Implement new feature")
        assert result["task_class"] == "build"
        assert result["need"] == 6
        assert result["risk"] == "standard"

    def test_security_keywords_case_insensitive(self):
        for keyword in ["OAUTH", "oauth", "OaUth"]:
            result = pc.classify(f"Add {keyword}")
            assert result["task_class"] == "security"

    def test_kind_parameter_overrides(self):
        result = pc.classify("Something", kind="efficiency")
        assert result["task_class"] == "mechanical"

    def test_material_flag(self):
        result = pc.classify("Fix a small bug", material=True)
        # material=True should trigger legal check first
        assert "task_class" in result

    def test_empty_prompt(self):
        result = pc.classify("")
        assert result["task_class"] == "build"
        assert result["need"] == 6


class TestCredentialAllows:
    """Tests for _credential_allows()."""

    def test_no_allowlist_allows_all(self):
        with patch.dict(os.environ, {}, clear=False):
            assert pc._credential_allows("legal", "build", "test")
            assert pc._credential_allows("security", "research", "test")

    @patch.dict(os.environ, {"ORCH_LEGAL_TASK_ALLOWLIST": "build,research"})
    def test_legal_allowlist_blocks_unlisted(self):
        assert pc._credential_allows("legal", "build", "test")
        assert not pc._credential_allows("legal", "deployment", "test")

    @patch.dict(os.environ, {"ORCH_SECURITY_TASK_ALLOWLIST": "build"})
    def test_security_allowlist_blocks_unlisted(self):
        assert pc._credential_allows("security", "build", "test")
        assert not pc._credential_allows("security", "research", "test")

    def test_non_gated_tasks_always_allowed(self):
        with patch.dict(os.environ, {"ORCH_LEGAL_TASK_ALLOWLIST": ""}):
            assert pc._credential_allows("research", "build", "test")


class TestOperationAuthorized:
    """Tests for _operation_authorized()."""

    def test_no_env_allows_all(self):
        with patch.dict(os.environ, {}, clear=False):
            assert pc._operation_authorized("any_op", "build")

    @patch.dict(os.environ, {"ORCH_BUILD_ALLOWED_OPERATIONS": "task_preflight,task_qa"})
    def test_env_allows_listed_operations(self):
        assert pc._operation_authorized("task_preflight", "build")
        assert not pc._operation_authorized("task_strategy", "build")

    def test_malformed_env_fails_soft(self):
        with patch.dict(os.environ, {"ORCH_BUILD_ALLOWED_OPERATIONS": "bad,ops"}):
            # Should fail-soft and allow
            assert pc._operation_authorized("any_op", "build") is True

    def test_exception_fails_soft(self):
        with patch("os.environ.get", side_effect=Exception("test error")):
            assert pc._operation_authorized("op", "task") is True


class TestSafeRoute:
    """Tests for _safe_route()."""

    def test_restricted_operation_denied(self):
        with patch.dict(os.environ, {"ORCH_SECURITY_ALLOWED_OPERATIONS": ""}):
            result = pc._safe_route("app", "task_security_gate", "security")
            assert result["provider"] == "claude"
            assert "unauthorized" in result["reason"]

    def test_app_triage_success(self):
        mock_triage = MagicMock()
        mock_triage.route.return_value = {
            "provider": "google",
            "model": "gemini-2.5-flash",
            "reason": "high-capacity"
        }
        with patch("pipeline_contract.app_triage", mock_triage):
            result = pc._safe_route("myapp", "task_qa", "build")
            assert result["provider"] == "google"
            assert result["model"] == "gemini-2.5-flash"

    def test_app_triage_permission_error_fallback(self):
        mock_triage = MagicMock()
        mock_triage.route.side_effect = PermissionError("denied")
        with patch("pipeline_contract.app_triage", mock_triage):
            with patch("pipeline_contract.model_policy") as mock_policy:
                mock_policy.choose.return_value = ("deepseek", "deepseek-v4", "fallback")
                result = pc._safe_route("app", "task_strategy", "plan")
                assert result["provider"] == "deepseek"

    def test_all_routes_fail_hardcoded_default(self):
        with patch("pipeline_contract.app_triage", None):
            with patch("pipeline_contract.model_policy") as mock_policy:
                mock_policy.choose.side_effect = PermissionError("denied")
                result = pc._safe_route("app", "task_qa", "build")
                assert result["provider"] == "claude"
                assert "haiku" in result["model"]
                assert "fallback" in result["reason"].lower()

    def test_generic_exception_uses_fallback(self):
        with patch("pipeline_contract.app_triage", None):
            with patch("pipeline_contract.model_policy", side_effect=RuntimeError("crash")):
                result = pc._safe_route("app", "task_strategy", "build")
                assert result["provider"] == "claude"


class TestAuthorModel:
    """Tests for _author_model()."""

    def test_model_router_success(self):
        with patch("pipeline_contract.model_router") as mock_router:
            mock_router.route.return_value = {"model": "claude-opus-5"}
            result = pc._author_model("write code", "build")
            assert result == "claude-opus-5"

    def test_model_router_exception_uses_env_default(self):
        with patch("pipeline_contract.model_router", side_effect=Exception("error")):
            with patch.dict(os.environ, {"ORCH_DEFAULT_MODEL": "claude-sonnet-5"}):
                result = pc._author_model("prompt", "build")
                assert result == "claude-sonnet-5"

    def test_model_router_exception_uses_hardcoded_default(self):
        with patch("pipeline_contract.model_router", side_effect=Exception("error")):
            with patch.dict(os.environ, {}, clear=True):
                result = pc._author_model("prompt", "build")
                assert "haiku" in result


class TestCoder:
    """Tests for _coder()."""

    def test_coder_selection_success(self):
        with patch("pipeline_contract.agentic_coders") as mock_coders:
            mock_coders.pick.return_value = "anthropic"
            result = pc._coder("slug-123", "build the feature", False)
            assert result == "anthropic"

    def test_coder_selection_exception_defaults_to_claude(self):
        with patch("pipeline_contract.agentic_coders", side_effect=Exception("error")):
            result = pc._coder("slug", "prompt", False)
            assert result == "claude"


class TestQaPanel:
    """Tests for _qa_panel()."""

    def test_judge_panel_providers(self):
        mock_judge = MagicMock()
        mock_judge._panel_providers.return_value = ["claude", "deepseek"]
        mock_judge.REVIEWERS = {"claude": "claude-opus", "deepseek": "deepseek-v4"}
        with patch("pipeline_contract.judge", mock_judge):
            result = pc._qa_panel("claude-sonnet", "build")
            assert "claude:claude-opus" in result

    def test_legal_task_special_handling(self):
        with patch("pipeline_contract.judge", None):
            with patch("pipeline_contract.mg") as mock_mg:
                mock_mg.available.return_value = ["local", "deepseek"]
                result = pc._qa_panel("claude", "legal")
                assert any("local" in p for p in result)

    def test_fallback_to_available_providers(self):
        with patch("pipeline_contract.judge", None):
            with patch("pipeline_contract.mg") as mock_mg:
                mock_mg.available.return_value = ["google", "openai"]
                result = pc._qa_panel("claude", "build")
                assert len(result) >= 1

    def test_all_failures_hardcoded_default(self):
        with patch("pipeline_contract.judge", None):
            with patch("pipeline_contract.mg", side_effect=Exception("error")):
                result = pc._qa_panel("claude", "build")
                assert result == ["claude:claude-haiku-4-5-20251001"]


class TestRecentContext:
    """Tests for _recent_context()."""

    def test_empty_project_returns_empty_list(self):
        result = pc._recent_context("")
        assert result == []

    def test_none_project_returns_empty_list(self):
        result = pc._recent_context(None)
        assert result == []

    def test_db_import_failure_returns_empty(self):
        with patch.dict(sys.modules, {"db": None}):
            result = pc._recent_context("myapp")
            assert result == []

    def test_outcomes_query_success(self):
        mock_db = MagicMock()
        mock_db.select.side_effect = [
            [
                {"model": "claude", "tests_passed": True, "integrated": True, "usd": 10.5},
                {"model": "deepseek", "tests_passed": False, "integrated": False, "usd": 5.2},
            ],
            [],  # routes query
            []   # feedback query
        ]
        with patch("pipeline_contract.db", mock_db):
            result = pc._recent_context("myapp")
            assert any("merged" in item for item in result)

    def test_permission_error_fails_soft(self):
        mock_db = MagicMock()
        mock_db.select.side_effect = PermissionError("denied")
        with patch("pipeline_contract.db", mock_db):
            result = pc._recent_context("myapp")
            assert isinstance(result, list)

    def test_generic_exception_fails_soft(self):
        mock_db = MagicMock()
        mock_db.select.side_effect = RuntimeError("crash")
        with patch("pipeline_contract.db", mock_db):
            result = pc._recent_context("myapp")
            assert isinstance(result, list)


class TestBuildPlan:
    """Tests for build_plan()."""

    def test_basic_plan_structure(self):
        result = pc.build_plan("Fix a bug", project="myapp")
        assert "source" in result
        assert "task_class" in result
        assert "need" in result
        assert "preflight" in result
        assert "strategy" in result
        assert "coder" in result
        assert "qa" in result
        assert "qa_panel" in result

    def test_security_plan_elevated_need(self):
        result = pc.build_plan("Add OAuth", project="app", material=False)
        assert result["need"] >= 9

    def test_plan_with_slug(self):
        result = pc.build_plan("test", slug="my-task-id")
        assert result["slug"] == "my-task-id"

    def test_plan_with_source(self):
        result = pc.build_plan("test", source="loop-worker")
        assert result["source"] == "loop-worker"

    def test_plan_default_values(self):
        result = pc.build_plan("test")
        assert result["project"] == "selected app"
        assert result["source"] == "unknown"
        assert result["slug"] == "(auto)"


class TestRenderPlan:
    """Tests for render_plan()."""

    def test_render_includes_marker(self):
        plan = pc.build_plan("test")
        rendered = pc.render_plan(plan)
        assert f"## {pc.MARKER}" in rendered
        assert f"## END {pc.MARKER}" in rendered

    def test_render_includes_all_keys(self):
        plan = pc.build_plan("test", project="app", slug="slug123")
        rendered = pc.render_plan(plan)
        assert "app" in rendered
        assert "slug123" in rendered
        assert "preflight triage" in rendered
        assert "strategy planner" in rendered

    def test_render_with_collaboration_context(self):
        plan = pc.build_plan("test", project="app")
        rendered = pc.render_plan(plan)
        assert "coordination rule" in rendered


class TestWrapPrompt:
    """Tests for wrap_prompt()."""

    def test_wrap_normal_prompt(self):
        prompt = "Fix the issue"
        wrapped = pc.wrap_prompt(prompt, project="app")
        assert pc.MARKER in wrapped
        assert pc.ORIGINAL_HEADER in wrapped
        assert prompt in wrapped

    def test_wrap_already_wrapped_unchanged(self):
        wrapped_input = f"## {pc.MARKER}\ntest\n## END {pc.MARKER}"
        result = pc.wrap_prompt(wrapped_input)
        assert result == wrapped_input

    def test_wrap_control_prompt_unchanged(self):
        control = "REPLAY: test-slug"
        result = pc.wrap_prompt(control)
        assert result == control

    def test_wrap_empty_prompt_unchanged(self):
        result = pc.wrap_prompt("")
        assert result == ""
        result = pc.wrap_prompt(None)
        assert result == None

    def test_wrap_includes_contract_before_original(self):
        prompt = "Build something"
        wrapped = pc.wrap_prompt(prompt)
        marker_idx = wrapped.find(pc.MARKER)
        original_idx = wrapped.find(pc.ORIGINAL_HEADER)
        assert marker_idx < original_idx


class TestArtifact:
    """Tests for artifact()."""

    def test_artifact_returns_json(self):
        result = pc.artifact("test prompt", project="app")
        parsed = json.loads(result)
        assert isinstance(parsed, dict)
        assert "task_class" in parsed

    def test_artifact_contains_plan_data(self):
        result = pc.artifact("fix bug", project="myapp")
        parsed = json.loads(result)
        assert parsed["project"] == "myapp"
        assert "need" in parsed

    def test_artifact_exception_returns_empty_json(self):
        with patch("pipeline_contract.build_plan", side_effect=Exception("crash")):
            result = pc.artifact("test")
            assert result == "{}"


class TestNote:
    """Tests for note()."""

    def test_note_with_existing(self):
        result = pc.note("existing note", "manual")
        assert "existing note" in result
        assert "pipeline:manual" in result

    def test_note_without_existing(self):
        result = pc.note(source="worker")
        assert result == "pipeline:worker; triage-plan-code-qa-devmerge-release"

    def test_note_default_source(self):
        result = pc.note("")
        assert "pipeline:unknown" in result


class TestIntegration:
    """End-to-end integration tests."""

    def test_full_pipeline_security_task(self):
        prompt = "Implement JWT authentication"
        plan = pc.build_plan(prompt, project="api", kind="build")
        rendered = pc.render_plan(plan)
        wrapped = pc.wrap_prompt(prompt, project="api")

        assert plan["task_class"] == "security"
        assert pc.MARKER in rendered
        assert prompt in wrapped

    def test_full_pipeline_mechanical_task(self):
        prompt = "Fix typo in README"
        plan = pc.build_plan(prompt, project="docs")
        assert plan["task_class"] == "mechanical"
        assert plan["need"] <= 5

    def test_routing_fallback_chain(self):
        # Simulate all routing layers failing
        with patch("pipeline_contract.app_triage", None):
            with patch("pipeline_contract.model_policy", side_effect=Exception("fail")):
                plan = pc.build_plan("test")
                assert plan["preflight"]["model"] is not None
                assert plan["strategy"]["provider"] is not None

    def test_permission_denied_at_each_layer(self):
        # Ensure each layer fails soft on PermissionError
        mock_triage = MagicMock()
        mock_triage.route.side_effect = PermissionError("denied")
        mock_policy = MagicMock()
        mock_policy.choose.side_effect = PermissionError("denied")

        with patch("pipeline_contract.app_triage", mock_triage):
            with patch("pipeline_contract.model_policy", mock_policy):
                plan = pc.build_plan("test")
                # Should reach the hardcoded default
                assert plan["strategy"]["provider"] == "claude"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
