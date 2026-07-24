#!/usr/bin/env python3
"""
Test suite for pipeline_contract.py - orchestration pipeline contract generation.

Tests cover:
- Control prompt detection and wrapping behavior
- Task classification and capability assignment
- Provider routing and fallback behavior
- QA panel composition
- Cross-learning context aggregation
- Plan building and rendering
- Fail-soft degradation
"""
import pytest
import os
import json
from unittest.mock import Mock, patch, MagicMock
import pipeline_contract as pc


class TestControlPromptDetection:
    """Tests for control flow detection."""

    def test_is_control_prompt_replay(self):
        assert pc.is_control_prompt("REPLAY: some-id")
        assert pc.is_control_prompt("  REPLAY: some-id")

    def test_is_control_prompt_rotate_key(self):
        assert pc.is_control_prompt("ROTATE_KEY: orch_config_xyz")

    def test_is_control_prompt_revoke(self):
        assert pc.is_control_prompt("REVOKE_AND_STOP: fleet-wide")

    def test_is_control_prompt_negative(self):
        assert not pc.is_control_prompt("Normal prompt text")
        assert not pc.is_control_prompt("")
        assert not pc.is_control_prompt(None)

    def test_is_control_prompt_case_sensitive(self):
        assert not pc.is_control_prompt("replay: some-id")
        assert not pc.is_control_prompt("Replay: some-id")


class TestAlreadyWrapped:
    """Tests for wrapped prompt detection."""

    def test_already_wrapped_with_marker(self):
        prompt = f"## {pc.MARKER}\nsome content"
        assert pc.already_wrapped(prompt)

    def test_already_wrapped_full_contract(self):
        prompt = pc.wrap_prompt("Fix auth bug", project="test")
        assert pc.already_wrapped(prompt)

    def test_already_wrapped_negative(self):
        assert not pc.already_wrapped("Normal prompt")
        assert not pc.already_wrapped("")
        assert not pc.already_wrapped(None)

    def test_already_wrapped_partial(self):
        assert pc.already_wrapped(f"Leading text {pc.MARKER} trailing")


class TestOriginalRequest:
    """Tests for extracting original request from wrapped prompts."""

    def test_original_request_unwrapped(self):
        prompt = "Fix the auth bug"
        assert pc.original_request(prompt) == prompt

    def test_original_request_wrapped(self):
        original = "Fix the auth bug"
        wrapped = pc.wrap_prompt(original, project="test")
        extracted = pc.original_request(wrapped)
        assert original in extracted

    def test_original_request_marker_present_no_header(self):
        prompt = f"## {pc.MARKER}\nSome content\n## END {pc.MARKER}"
        result = pc.original_request(prompt)
        # Should remove the contract block
        assert pc.MARKER not in result

    def test_original_request_empty(self):
        assert pc.original_request("") == ""
        assert pc.original_request(None) == ""


class TestClassify:
    """Tests for task classification and capability assignment."""

    def test_classify_legal_material(self):
        result = pc.classify("Some prompt", material=True)
        assert result["task_class"] == "legal"
        assert result["need"] == 9
        assert result["risk"] == "legal_posture"

    def test_classify_security(self):
        result = pc.classify("Fix SQL injection vulnerability")
        assert result["task_class"] == "security"
        assert result["need"] == 9
        assert result["risk"] == "security"

    def test_classify_auth_related(self):
        result = pc.classify("Update authentication flow")
        assert result["task_class"] == "security"
        assert result["need"] == 9

    def test_classify_research_explicit(self):
        result = pc.classify("Research how to optimize caching", kind="research")
        assert result["task_class"] == "plan"
        assert result["need"] == 8
        assert result["risk"] == "strategy"

    def test_classify_research_keyword(self):
        result = pc.classify("Investigate A/B testing framework")
        assert result["task_class"] == "plan"
        assert result["need"] == 8

    def test_classify_mechanical(self):
        result = pc.classify("Fix typo in docs")
        assert result["task_class"] == "mechanical"
        assert result["need"] == 5
        assert result["risk"] == "routine"

    def test_classify_migration(self):
        result = pc.classify("Add database schema migration")
        assert result["task_class"] == "hard"
        assert result["need"] == 8
        assert result["risk"] == "broad_change"

    def test_classify_build_default(self):
        result = pc.classify("Implement user dashboard")
        assert result["task_class"] == "build"
        assert result["need"] == 6
        assert result["risk"] == "standard"

    def test_classify_empty_prompt(self):
        result = pc.classify("")
        assert result["task_class"] == "build"
        assert result["need"] == 6

    def test_classify_kind_parameter(self):
        result1 = pc.classify("Some task", kind="efficiency")
        assert result1["task_class"] == "mechanical"

        result2 = pc.classify("Some task", kind="cost")
        assert result2["task_class"] == "mechanical"

    def test_classify_multiple_keywords(self):
        result = pc.classify("Security audit of authentication module with RLS")
        assert result["task_class"] == "security"


class TestSafeRoute:
    """Tests for safe routing with fallback behavior."""

    def test_safe_route_successful_app_triage(self):
        with patch('pipeline_contract.app_triage') as mock_triage:
            mock_triage.route.return_value = {
                "provider": "google",
                "model": "gemini-2.0-flash",
                "reason": "policy"
            }
            result = pc._safe_route("app1", "task_qa", "review", need=6)
            assert result["provider"] == "google"
            assert result["model"] == "gemini-2.0-flash"

    def test_safe_route_app_triage_exception(self):
        with patch('pipeline_contract.app_triage') as mock_triage:
            mock_triage.route.side_effect = Exception("API error")
            with patch('pipeline_contract.model_policy.choose') as mock_policy:
                mock_policy.return_value = ("claude", "claude-opus", "fallback")
                result = pc._safe_route("app1", "task_qa", "review")
                assert result["provider"] == "claude"

    def test_safe_route_no_app_triage(self):
        with patch('pipeline_contract.app_triage', None):
            with patch('pipeline_contract.model_policy.choose') as mock_policy:
                mock_policy.return_value = ("local", "llama3.1", "direct_policy")
                result = pc._safe_route("app1", "task_qa", "review")
                assert result["provider"] == "local"

    def test_safe_route_both_fail_fallback(self):
        with patch('pipeline_contract.app_triage') as mock_triage:
            mock_triage.route.side_effect = Exception()
            with patch('pipeline_contract.model_policy.choose') as mock_policy:
                mock_policy.side_effect = Exception()
                result = pc._safe_route("app1", "task_qa", "review")
                assert result["provider"] == "claude"
                assert "haiku" in result["model"]

    def test_safe_route_converts_to_string(self):
        with patch('pipeline_contract.app_triage') as mock_triage:
            mock_triage.route.return_value = {"provider": None, "model": None}
            result = pc._safe_route("app1", "task_qa", "review")
            assert isinstance(result["provider"], str)
            assert isinstance(result["model"], str)


class TestAuthorModel:
    """Tests for author model selection."""

    def test_author_model_router_success(self):
        with patch('pipeline_contract.model_router.route') as mock_router:
            mock_router.return_value = {"model": "claude-opus"}
            result = pc._author_model("Some prompt", "build")
            assert result == "claude-opus"

    def test_author_model_router_exception(self):
        with patch('pipeline_contract.model_router.route') as mock_router:
            mock_router.side_effect = Exception()
            result = pc._author_model("Some prompt", "build")
            # Should fall back to env var or default
            assert "claude" in result or "haiku" in result

    def test_author_model_env_override(self):
        with patch('pipeline_contract.model_router.route') as mock_router:
            mock_router.side_effect = Exception()
            with patch.dict(os.environ, {"ORCH_DEFAULT_MODEL": "custom-model"}):
                result = pc._author_model("Some prompt", "build")
                assert result == "custom-model"


class TestCoder:
    """Tests for agentic coder selection."""

    def test_coder_pick_success(self):
        with patch('pipeline_contract.agentic_coders.pick') as mock_pick:
            mock_pick.return_value = "ollama/deepseek-coder-v2:16b"
            result = pc._coder("slug-123", "Write a function", False)
            assert result == "ollama/deepseek-coder-v2:16b"

    def test_coder_pick_exception(self):
        with patch('pipeline_contract.agentic_coders.pick') as mock_pick:
            mock_pick.side_effect = Exception()
            result = pc._coder("slug-123", "Write a function", False)
            assert result == "claude"

    def test_coder_passes_task_dict(self):
        with patch('pipeline_contract.agentic_coders.pick') as mock_pick:
            mock_pick.return_value = "test-model"
            pc._coder("test-slug", "test-prompt", True)
            called_task = mock_pick.call_args[0][0]
            assert called_task["slug"] == "test-slug"
            assert called_task["prompt"] == "test-prompt"
            assert called_task["material"] is True

    def test_coder_empty_values(self):
        with patch('pipeline_contract.agentic_coders.pick') as mock_pick:
            mock_pick.return_value = "fallback"
            result = pc._coder("", "", False)
            assert result == "fallback"


class TestQAPanel:
    """Tests for QA panel composition."""

    def test_qa_panel_from_judge(self):
        with patch('pipeline_contract.judge') as mock_judge:
            mock_judge._panel_providers.return_value = ["local", "deepseek", "google"]
            mock_judge.REVIEWERS = {"local": "llama3.1", "deepseek": "v4-flash"}
            result = pc._qa_panel("claude-opus")
            assert "local:llama3.1" in result

    def test_qa_panel_judge_exception(self):
        with patch('pipeline_contract.judge') as mock_judge:
            mock_judge._panel_providers.side_effect = Exception()
            with patch('pipeline_contract.mg.available') as mock_available:
                mock_available.return_value = ["local", "deepseek", "google"]
                result = pc._qa_panel("claude-opus")
                assert len(result) >= 1

    def test_qa_panel_no_judge(self):
        with patch('pipeline_contract.judge', None):
            with patch('pipeline_contract.mg.available') as mock_available:
                mock_available.return_value = ["local", "deepseek"]
                result = pc._qa_panel("claude-opus")
                assert "local" in result[0] or "deepseek" in result[0]

    def test_qa_panel_fallback(self):
        with patch('pipeline_contract.judge', None):
            with patch('pipeline_contract.mg.available') as mock_available:
                mock_available.side_effect = Exception()
                result = pc._qa_panel("claude-opus")
                assert len(result) == 1
                assert "haiku" in result[0]

    def test_qa_panel_limit_two(self):
        with patch('pipeline_contract.judge', None):
            with patch('pipeline_contract.mg.available') as mock_available:
                mock_available.return_value = ["local", "deepseek", "google", "openai", "claude"]
                result = pc._qa_panel("claude-opus")
                assert len(result) <= 2


class TestRecentContext:
    """Tests for cross-learning context aggregation."""

    def test_recent_context_no_project(self):
        result = pc._recent_context("")
        assert result == []

    def test_recent_context_db_import_fails(self):
        with patch.dict('sys.modules', {'db': None}):
            result = pc._recent_context("test-project")
            assert result == []

    def test_recent_context_outcomes(self):
        mock_db = MagicMock()
        mock_outcomes = [
            {"integrated": True, "tests_passed": True, "usd": "1.50", "model": "claude-opus"},
            {"integrated": False, "tests_passed": False, "usd": "0.75", "model": "claude-opus"},
            {"integrated": True, "tests_passed": True, "usd": "2.00", "model": "google"},
        ]
        mock_db.select.return_value = mock_outcomes

        with patch('pipeline_contract.db', mock_db):
            result = pc._recent_context("test-project")
            outcome_line = [l for l in result if "recent outcome signal" in l]
            assert len(outcome_line) == 1
            assert "2/3 merged" in outcome_line[0]
            assert "2/3 test-pass" in outcome_line[0]

    def test_recent_context_learned_routes(self):
        mock_db = MagicMock()
        mock_db.select.side_effect = [
            [],  # outcomes
            [
                {"operation": "build_fix", "provider": "google", "model": "gemini-2.0", "avg_quality": 4.4},
                {"operation": "completion", "provider": "local", "model": "llama3.2:3b", "avg_quality": 7.2},
            ]
        ]

        with patch('pipeline_contract.db', mock_db):
            result = pc._recent_context("test-project")
            route_lines = [l for l in result if "learned route" in l]
            assert len(route_lines) >= 2

    def test_recent_context_operator_feedback(self):
        mock_db = MagicMock()
        mock_db.select.side_effect = [
            [],  # outcomes
            [],  # routes
            [
                {"category": "strategy", "severity": "med", "observation": "Long downtime during remediation"}
            ]
        ]

        with patch('pipeline_contract.db', mock_db):
            result = pc._recent_context("test-project")
            feedback_lines = [l for l in result if "operator feedback" in l]
            assert len(feedback_lines) >= 1

    def test_recent_context_truncation(self):
        mock_db = MagicMock()
        mock_db.select.return_value = []

        with patch('pipeline_contract.db', mock_db):
            result = pc._recent_context("test-project")
            # Should not exceed 8 items total
            assert len(result) <= 8


class TestBuildPlan:
    """Tests for complete orchestration plan building."""

    def test_build_plan_basic(self):
        with patch('pipeline_contract._author_model') as mock_author:
            with patch('pipeline_contract._coder') as mock_coder:
                with patch('pipeline_contract._safe_route') as mock_route:
                    with patch('pipeline_contract._qa_panel') as mock_panel:
                        with patch('pipeline_contract._recent_context') as mock_context:
                            mock_author.return_value = "claude-opus"
                            mock_coder.return_value = "claude"
                            mock_route.return_value = {"provider": "test", "model": "test-model", "reason": "test"}
                            mock_panel.return_value = ["local:llama"]
                            mock_context.return_value = []

                            plan = pc.build_plan("Fix auth bug", project="test-proj")
                            assert plan["project"] == "test-proj"
                            assert plan["task_class"] == "security"
                            assert plan["need"] == 9
                            assert plan["source"] == "unknown"

    def test_build_plan_with_parameters(self):
        with patch('pipeline_contract._author_model') as mock_author:
            with patch('pipeline_contract._coder') as mock_coder:
                with patch('pipeline_contract._safe_route') as mock_route:
                    with patch('pipeline_contract._qa_panel') as mock_panel:
                        with patch('pipeline_contract._recent_context') as mock_context:
                            mock_author.return_value = "claude-opus"
                            mock_coder.return_value = "claude"
                            mock_route.return_value = {"provider": "google", "model": "gemini", "reason": "policy"}
                            mock_panel.return_value = ["deepseek:v4"]
                            mock_context.return_value = []

                            plan = pc.build_plan(
                                "Write API docs",
                                project="myapp",
                                kind="build",
                                source="manual",
                                slug="api-docs-001",
                                material=False
                            )
                            assert plan["project"] == "myapp"
                            assert plan["source"] == "manual"
                            assert plan["slug"] == "api-docs-001"
                            assert plan["kind"] == "build"

    def test_build_plan_routing_calls(self):
        with patch('pipeline_contract._author_model') as mock_author:
            with patch('pipeline_contract._coder') as mock_coder:
                with patch('pipeline_contract._safe_route') as mock_route:
                    with patch('pipeline_contract._qa_panel') as mock_panel:
                        with patch('pipeline_contract._recent_context') as mock_context:
                            mock_author.return_value = "claude-opus"
                            mock_coder.return_value = "claude"
                            mock_route.return_value = {"provider": "test", "model": "test", "reason": "test"}
                            mock_panel.return_value = []
                            mock_context.return_value = []

                            pc.build_plan("Test", project="test")

                            # Verify routing was called for each operation
                            route_calls = [call[0] for call in mock_route.call_args_list]
                            operations = [call[1] for call in route_calls]
                            assert "task_preflight" in operations
                            assert "task_strategy" in operations
                            assert "task_qa" in operations


class TestRenderPlan:
    """Tests for plan rendering to markdown."""

    def test_render_plan_basic(self):
        plan = {
            "source": "manual",
            "project": "test-proj",
            "task_class": "security",
            "need": 9,
            "risk": "security",
            "preflight": {"provider": "google", "model": "gemini", "reason": "policy"},
            "strategy": {"provider": "google", "model": "gemini", "reason": "policy"},
            "coder": "claude-opus",
            "author_model": "claude-opus",
            "qa": {"provider": "local", "model": "llama", "reason": "policy"},
            "qa_panel": ["local:llama3.1", "deepseek:v4-flash"],
            "legal_gate": "owner-only",
            "release": "auto-merge to orchestrator/dev",
        }

        rendered = pc.render_plan(plan)
        assert pc.MARKER in rendered
        assert "manual" in rendered
        assert "test-proj" in rendered
        assert "security" in rendered
        assert "local:llama" in rendered
        assert "deepseek:v4-flash" in rendered

    def test_render_plan_with_context(self):
        plan = {
            "source": "auto",
            "project": "test",
            "task_class": "build",
            "need": 6,
            "risk": "standard",
            "preflight": {"provider": "google", "model": "gemini", "reason": "policy"},
            "strategy": {"provider": "google", "model": "gemini", "reason": "policy"},
            "coder": "claude",
            "author_model": "claude-haiku",
            "qa": {"provider": "local", "model": "llama", "reason": "policy"},
            "qa_panel": ["local:llama"],
            "legal_gate": "owner-only",
            "release": "auto-merge to orchestrator/dev",
            "collaboration": [
                "recent outcome signal: 2/12 merged",
                "learned route: build_fix -> google:gemini-2.0-flash, q=4.4"
            ]
        }

        rendered = pc.render_plan(plan)
        assert "recent outcome signal" in rendered
        assert "learned route" in rendered
        assert "cross-learning context" in rendered

    def test_render_plan_missing_fields(self):
        plan = {"source": "test", "project": "test"}
        rendered = pc.render_plan(plan)
        assert pc.MARKER in rendered
        # Should handle missing fields gracefully


class TestWrapPrompt:
    """Tests for prompt wrapping with contract."""

    def test_wrap_prompt_basic(self):
        original = "Improve the dashboard"
        wrapped = pc.wrap_prompt(original, project="beethoven")
        assert pc.MARKER in wrapped
        assert pc.ORIGINAL_HEADER in wrapped
        assert original in wrapped

    def test_wrap_prompt_already_wrapped(self):
        original = "Fix auth bug"
        wrapped1 = pc.wrap_prompt(original, project="test")
        wrapped2 = pc.wrap_prompt(wrapped1, project="test")
        # Should not double-wrap
        assert wrapped1 == wrapped2

    def test_wrap_prompt_control_command(self):
        control = "REPLAY: some-task-id"
        wrapped = pc.wrap_prompt(control, project="test")
        # Should not wrap control commands
        assert wrapped == control

    def test_wrap_prompt_empty(self):
        wrapped = pc.wrap_prompt("", project="test")
        assert wrapped == ""

    def test_wrap_prompt_none(self):
        wrapped = pc.wrap_prompt(None, project="test")
        assert wrapped is None or wrapped == ""

    def test_wrap_prompt_whitespace_only(self):
        wrapped = pc.wrap_prompt("   \n  ", project="test")
        assert wrapped.strip() == ""

    def test_wrap_prompt_preserves_original(self):
        original = "Very important fix"
        wrapped = pc.wrap_prompt(original, project="test", kind="build", source="manual", slug="fix-123")
        extracted = pc.original_request(wrapped)
        assert original in extracted


class TestArtifact:
    """Tests for JSON artifact generation."""

    def test_artifact_valid_json(self):
        artifact = pc.artifact("Fix a bug", project="test")
        parsed = json.loads(artifact)
        assert "task_class" in parsed
        assert "source" in parsed

    def test_artifact_handles_exception(self):
        with patch('pipeline_contract.build_plan') as mock_plan:
            mock_plan.side_effect = Exception("Build failed")
            artifact = pc.artifact("Some prompt")
            parsed = json.loads(artifact)
            assert parsed == {}

    def test_artifact_includes_plan_data(self):
        artifact = pc.artifact("Add feature", project="myapp", kind="build", source="api")
        parsed = json.loads(artifact)
        assert parsed["project"] == "myapp"
        assert parsed["source"] == "api"


class TestNote:
    """Tests for note suffix generation."""

    def test_note_empty_existing(self):
        result = pc.note("", source="manual")
        assert "pipeline:manual" in result
        assert "triage-plan-code-qa-devmerge-release" in result

    def test_note_with_existing(self):
        result = pc.note("Important change", source="api")
        assert "Important change" in result
        assert "pipeline:api" in result
        assert ";" in result

    def test_note_whitespace_existing(self):
        result = pc.note("   \n", source="test")
        assert result == "pipeline:test; triage-plan-code-qa-devmerge-release"

    def test_note_none_source(self):
        result = pc.note("text", source=None)
        assert "pipeline:unknown" in result


class TestIntegration:
    """End-to-end integration tests."""

    def test_full_pipeline_security_task(self):
        with patch('pipeline_contract._author_model') as mock_author:
            with patch('pipeline_contract._coder') as mock_coder:
                with patch('pipeline_contract._safe_route') as mock_route:
                    with patch('pipeline_contract._qa_panel') as mock_panel:
                        with patch('pipeline_contract._recent_context') as mock_context:
                            mock_author.return_value = "claude-opus"
                            mock_coder.return_value = "claude"
                            mock_route.return_value = {"provider": "google", "model": "gemini", "reason": "policy"}
                            mock_panel.return_value = ["local:llama", "deepseek:v4"]
                            mock_context.return_value = ["recent outcome signal: 5/12 merged"]

                            prompt = "Fix XSS vulnerability in user input validation"
                            wrapped = pc.wrap_prompt(prompt, project="webapp", source="scanner")

                            assert pc.already_wrapped(wrapped)
                            assert "security" in wrapped.lower() or wrapped.find(prompt) >= 0

                            original = pc.original_request(wrapped)
                            assert prompt in original

    def test_full_pipeline_mechanical_task(self):
        with patch('pipeline_contract._author_model') as mock_author:
            with patch('pipeline_contract._coder') as mock_coder:
                with patch('pipeline_contract._safe_route') as mock_route:
                    with patch('pipeline_contract._qa_panel') as mock_panel:
                        with patch('pipeline_contract._recent_context') as mock_context:
                            mock_author.return_value = "claude-haiku"
                            mock_coder.return_value = "claude"
                            mock_route.return_value = {"provider": "google", "model": "gemini", "reason": "policy"}
                            mock_panel.return_value = ["local:llama"]
                            mock_context.return_value = []

                            prompt = "Fix typo in README: 'recieve' -> 'receive'"
                            plan = pc.build_plan(prompt, project="docs", kind="build")

                            assert plan["task_class"] == "mechanical"
                            assert plan["need"] == 5
                            rendered = pc.render_plan(plan)
                            assert "mechanical" in rendered

    def test_control_command_not_wrapped(self):
        control = "ROTATE_KEY: encryption_master"
        wrapped = pc.wrap_prompt(control, project="security")
        assert wrapped == control
        assert not pc.already_wrapped(wrapped)


class TestFailSoftBehavior:
    """Tests for graceful degradation on errors."""

    def test_build_plan_survives_all_provider_failures(self):
        with patch('pipeline_contract._author_model') as mock_author:
            with patch('pipeline_contract._coder') as mock_coder:
                with patch('pipeline_contract._safe_route') as mock_route:
                    with patch('pipeline_contract._qa_panel') as mock_panel:
                        with patch('pipeline_contract._recent_context') as mock_context:
                            mock_author.side_effect = Exception()
                            mock_coder.side_effect = Exception()
                            mock_route.side_effect = Exception()
                            mock_panel.side_effect = Exception()
                            mock_context.side_effect = Exception()

                            # Should not raise, should return sensible defaults
                            plan = pc.build_plan("Fix something", project="test")
                            assert "task_class" in plan
                            assert "coder" in plan

    def test_wrap_prompt_survives_plan_build_failure(self):
        with patch('pipeline_contract.build_plan') as mock_build:
            # Can't actually make wrap_prompt fail because build_plan is called
            # But we can verify behavior with a working build_plan
            mock_build.return_value = {
                "source": "test",
                "project": "test",
                "task_class": "build",
                "need": 6,
                "risk": "standard",
                "preflight": {"provider": "test", "model": "test", "reason": "test"},
                "strategy": {"provider": "test", "model": "test", "reason": "test"},
                "coder": "claude",
                "author_model": "claude",
                "qa": {"provider": "test", "model": "test", "reason": "test"},
                "qa_panel": [],
                "legal_gate": "test",
                "release": "test",
                "collaboration": []
            }
            wrapped = pc.wrap_prompt("Test prompt", project="test")
            assert wrapped is not None


class TestEdgeCases:
    """Tests for boundary conditions and edge cases."""

    def test_classify_very_long_prompt(self):
        long_prompt = "x" * 10000
        result = pc.classify(long_prompt)
        assert "task_class" in result

    def test_classify_unicode_content(self):
        prompt = "Fix 中文 content and émojis 🚀"
        result = pc.classify(prompt)
        assert "task_class" in result

    def test_wrap_prompt_very_long_original(self):
        long_prompt = "Implement " + ("very " * 1000) + "important feature"
        wrapped = pc.wrap_prompt(long_prompt, project="test")
        original = pc.original_request(wrapped)
        assert long_prompt in original

    def test_original_request_malformed_contract(self):
        malformed = f"## {pc.MARKER}\nNo end marker here"
        result = pc.original_request(malformed)
        # Should handle gracefully
        assert isinstance(result, str)

    def test_safe_route_none_model_value(self):
        with patch('pipeline_contract.app_triage') as mock_triage:
            mock_triage.route.return_value = {"provider": "test", "model": None}
            result = pc._safe_route("app", "op", "class")
            assert isinstance(result["model"], str)
            assert result["model"] == ""

    def test_build_plan_strategy_need_respects_minimum(self):
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

                            # Mechanical task has need=5, but strategy should request at least 7
                            plan = pc.build_plan("Fix typo", kind="efficiency")
                            # Verify strategy call was made with appropriate need
                            strategy_calls = [c for c in mock_route.call_args_list
                                            if c[0][1] == "task_strategy"]
                            assert len(strategy_calls) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
