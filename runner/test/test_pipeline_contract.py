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

    def test_opening_marker_alone_counts_as_wrapped(self):
        # WAS `test_partial_marker`, asserting that a prompt carrying only the opening
        # marker is NOT already wrapped. already_wrapped() is `MARKER in prompt` and has
        # never required the END marker — deliberately: original_request() carries an
        # explicit "Fallback for partially copied prompts" branch, so a truncated or
        # hand-edited contract must still be recognised. Requiring both markers would
        # make wrap_prompt() prepend a SECOND contract to a prompt that already has one,
        # which is the exact duplication this guard exists to prevent.
        partial = f"## {pc.MARKER}\n- source: manual"
        assert pc.already_wrapped(partial)
        assert pc.wrap_prompt(partial, project="app") == partial


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
        # WAS: env value "bad,ops". That is not malformed — both names satisfy
        # ^[a-z_][a-z0-9_]*$, so no ValueError was raised and the function correctly
        # DENIED "any_op" for not being on the list. The test asserted the fail-soft
        # branch while supplying input that never reaches it.
        # A name that fails the validation regex is what trips the fail-soft path.
        with patch.dict(os.environ, {"ORCH_BUILD_ALLOWED_OPERATIONS": "Bad-Op!,task_qa"}):
            assert pc._operation_authorized("any_op", "build") is True

    def test_well_formed_env_still_denies_unlisted_operations(self):
        # The half the old test actually exercised, kept and stated honestly.
        with patch.dict(os.environ, {"ORCH_BUILD_ALLOWED_OPERATIONS": "bad,ops"}):
            assert pc._operation_authorized("any_op", "build") is False
            assert pc._operation_authorized("ops", "build") is True

    def test_empty_env_denies_every_operation(self):
        # An explicitly empty allowlist means "allow nothing", not "allow everything".
        with patch.dict(os.environ, {"ORCH_BUILD_ALLOWED_OPERATIONS": ""}):
            assert pc._operation_authorized("task_qa", "build") is False

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

    # WAS (both tests): patch("pipeline_contract.model_router", side_effect=...). That
    # sets side_effect on the *module* mock, so calling the module would raise — but the
    # code calls model_router.route(), which happily returned an auto-created MagicMock.
    # The router never failed, the fallback never ran, and the assertion compared a
    # string to `<MagicMock name='model_router.route().__getitem__()'>`. The exception
    # belongs on .route.
    def test_model_router_exception_uses_env_default(self):
        mock_router = MagicMock()
        mock_router.route.side_effect = Exception("error")
        with patch("pipeline_contract.model_router", mock_router):
            with patch.dict(os.environ, {"ORCH_DEFAULT_MODEL": "claude-sonnet-5"}):
                result = pc._author_model("prompt", "build")
                assert result == "claude-sonnet-5"

    def test_model_router_exception_uses_hardcoded_default(self):
        mock_router = MagicMock()
        mock_router.route.side_effect = Exception("error")
        with patch("pipeline_contract.model_router", mock_router):
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
        # WAS: side_effect on the agentic_coders MODULE mock, so .pick() returned a
        # MagicMock and the fallback never ran; the assertion compared "claude" to
        # `<MagicMock name='agentic_coders.pick()'>`. Put the failure on .pick.
        mock_coders = MagicMock()
        mock_coders.pick.side_effect = Exception("error")
        with patch("pipeline_contract.agentic_coders", mock_coders):
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
        # WAS: side_effect on the mg MODULE mock. mg.available() then returned a
        # MagicMock which only blew up later, inside set(), so the right branch was
        # reached by accident. Fail the call that _qa_panel actually makes.
        mock_mg = MagicMock()
        mock_mg.available.side_effect = Exception("error")
        with patch("pipeline_contract.judge", None):
            with patch("pipeline_contract.mg", mock_mg):
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

    def test_reads_the_module_level_db_seam_not_a_local_reimport(self):
        # WAS `test_db_import_failure_returns_empty`: set sys.modules["db"] = None and
        # expected []. It passed only because _recent_context re-imported db into its own
        # scope, and that shadowing import is precisely what made `pipeline_contract.db`
        # unpatchable — three sibling tests in this class could never reach their
        # fixtures. The guarded local import was also dead code: `import db` at module
        # scope has already run, so it cannot fail there. It has been removed from the
        # module; this pins the seam so it does not come back.
        seam = MagicMock()
        seam.select.side_effect = [
            [{"model": "claude", "tests_passed": True, "integrated": True, "usd": 1.0}],
            [],
            [],
        ]
        decoy = MagicMock()
        decoy.select.return_value = []
        with patch("pipeline_contract.db", seam), patch.dict(sys.modules, {"db": decoy}):
            result = pc._recent_context("myapp")
        assert any("recent outcome signal" in item for item in result)
        assert decoy.select.call_count == 0, "a local `import db` has been reintroduced"

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

    # WAS (both): `assert isinstance(result, list)`. _recent_context is annotated
    # -> List[str] and every return statement is a list, so that held even when the
    # function raised nothing at all and even before the db seam was patchable. What
    # the fail-soft contract actually promises is an EMPTY bundle, with all three
    # queries attempted rather than the first failure aborting the rest.
    def test_permission_error_fails_soft(self):
        mock_db = MagicMock()
        mock_db.select.side_effect = PermissionError("denied")
        with patch("pipeline_contract.db", mock_db):
            result = pc._recent_context("myapp")
        assert result == []
        assert mock_db.select.call_count == 3, "each query is guarded independently"

    def test_generic_exception_fails_soft(self):
        mock_db = MagicMock()
        mock_db.select.side_effect = RuntimeError("crash")
        with patch("pipeline_contract.db", mock_db):
            result = pc._recent_context("myapp")
        assert result == []
        assert mock_db.select.call_count == 3


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

    def test_render_includes_all_rendered_keys(self):
        # WAS `test_render_includes_all_keys`, which also required the slug to appear.
        # render_plan() has never emitted the slug: the contract block is prepended to
        # the agent's own prompt, where the slug is already known, and build_plan's
        # default slug is the placeholder "(auto)". Assert the fields render_plan really
        # is responsible for, including the ones the old test skipped.
        plan = pc.build_plan("test", project="app", slug="slug123", source="intake")
        rendered = pc.render_plan(plan)
        assert "- project: app" in rendered
        assert "- source: intake" in rendered
        assert "preflight triage" in rendered
        assert "strategy planner" in rendered
        assert "independent QA route" in rendered
        assert f"agentic coder: {plan['coder']}" in rendered
        assert f"author model {plan['author_model']}" in rendered
        assert "- QA panel:" in rendered
        assert "- merge/release:" in rendered

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

    def test_wrap_empty_prompt_is_not_wrapped(self):
        # WAS `test_wrap_empty_prompt_unchanged`, which required wrap_prompt(None) to
        # return None. It returns "": the function normalises with `text = prompt or ""`
        # before doing anything, exactly as original_request() does, and every caller
        # concatenates the result into a prompt string. Handing None back would push a
        # None into those call sites. What matters — and what the name meant — is that an
        # empty prompt gets no contract prepended.
        assert pc.wrap_prompt("") == ""
        assert pc.wrap_prompt(None) == ""
        assert pc.wrap_prompt("   \n ") == "   \n "
        assert pc.MARKER not in pc.wrap_prompt(None)

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
        # WAS: side_effect on the model_policy MODULE mock (so .choose() returned a
        # MagicMock and only blew up later while unpacking), plus two `is not None`
        # assertions that a dict literal in build_plan satisfies unconditionally.
        # Fail model_policy.choose for real and pin the documented hardcoded fallback.
        mock_policy = MagicMock()
        mock_policy.choose.side_effect = Exception("fail")
        with patch("pipeline_contract.app_triage", None):
            with patch("pipeline_contract.model_policy", mock_policy):
                plan = pc.build_plan("test")
        for leg in ("preflight", "strategy", "qa"):
            assert plan[leg]["provider"] == "claude", leg
            assert plan[leg]["model"] == "claude-haiku-4-5-20251001", leg
            assert plan[leg]["reason"] == "fallback policy", leg

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
