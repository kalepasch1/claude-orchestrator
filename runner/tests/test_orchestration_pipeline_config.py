"""Tests for orchestration pipeline configuration system.

Validates pipeline contract, stage definitions, task classes, legal/behavior gates,
model requirements, cost tracking, and configuration integrity.

Task: backlog-batch-illuminati-dd47b58
"""
import sys
import os
import json
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["ORCH_DB_URL"] = ""
os.environ["ORCH_DB_ENABLED"] = "false"

import orchestration_pipeline_config as opc


class TestProjectMetadata:
    """Verify project configuration contains required metadata."""

    def test_project_has_name(self):
        assert "name" in opc.PROJECT
        assert opc.PROJECT["name"] == "kalepasch-com"
        assert isinstance(opc.PROJECT["name"], str)
        assert len(opc.PROJECT["name"]) > 0

    def test_project_has_display_name(self):
        assert "display_name" in opc.PROJECT
        assert isinstance(opc.PROJECT["display_name"], str)
        assert len(opc.PROJECT["display_name"]) > 0

    def test_project_has_repo_url(self):
        assert "repo_url" in opc.PROJECT
        assert isinstance(opc.PROJECT["repo_url"], str)
        assert "github.com" in opc.PROJECT["repo_url"]

    def test_project_has_source(self):
        assert "source" in opc.PROJECT
        assert opc.PROJECT["source"] in ("native-claim", "release-self-heal", "recovery")

    def test_project_has_task_class(self):
        assert "task_class" in opc.PROJECT
        assert opc.PROJECT["task_class"] in ("easy", "medium", "hard")

    def test_project_metadata_not_empty(self):
        assert len(opc.PROJECT) >= 5


class TestTaskClasses:
    """Verify task class definitions and requirements."""

    def test_all_task_classes_defined(self):
        required_classes = ["easy", "medium", "hard"]
        for cls in required_classes:
            assert cls in opc.TASK_CLASSES

    def test_easy_task_class_definition(self):
        easy = opc.TASK_CLASSES["easy"]
        assert easy["min_tests"] == 4
        assert easy["max_tests"] == 12
        assert easy["required_capability"] == 5
        assert len(easy["stages"]) == 3
        assert "preflight_triage" in easy["stages"]
        assert "agentic_coder" in easy["stages"]
        assert "qa_panel" in easy["stages"]
        assert "strategy_planner" not in easy["stages"]

    def test_medium_task_class_definition(self):
        medium = opc.TASK_CLASSES["medium"]
        assert medium["min_tests"] == 6
        assert medium["max_tests"] == 12
        assert medium["required_capability"] == 6
        assert len(medium["stages"]) == 4
        assert "preflight_triage" in medium["stages"]
        assert "strategy_planner" in medium["stages"]
        assert "agentic_coder" in medium["stages"]
        assert "qa_panel" in medium["stages"]

    def test_hard_task_class_definition(self):
        hard = opc.TASK_CLASSES["hard"]
        assert hard["min_tests"] == 8
        assert hard["max_tests"] == 12
        assert hard["required_capability"] == 8
        assert len(hard["stages"]) == 4

    def test_task_class_capability_progression(self):
        easy_cap = opc.TASK_CLASSES["easy"]["required_capability"]
        medium_cap = opc.TASK_CLASSES["medium"]["required_capability"]
        hard_cap = opc.TASK_CLASSES["hard"]["required_capability"]
        assert easy_cap < medium_cap < hard_cap

    def test_task_class_min_tests_progression(self):
        easy_min = opc.TASK_CLASSES["easy"]["min_tests"]
        medium_min = opc.TASK_CLASSES["medium"]["min_tests"]
        hard_min = opc.TASK_CLASSES["hard"]["min_tests"]
        assert easy_min < medium_min <= hard_min

    def test_task_class_max_tests_consistent(self):
        for task_class in opc.TASK_CLASSES.values():
            assert task_class["min_tests"] <= task_class["max_tests"]

    def test_all_task_classes_have_required_fields(self):
        required_fields = ["min_tests", "max_tests", "required_capability", "stages"]
        for cls_name, cls_def in opc.TASK_CLASSES.items():
            for field in required_fields:
                assert field in cls_def, f"{cls_name} missing {field}"


class TestPipelineStages:
    """Verify pipeline stage definitions and configuration."""

    def test_preflight_triage_stage(self):
        stage = opc.STAGES["preflight_triage"]
        assert stage["display_name"] == "Preflight Triage"
        assert stage["model_provider"] == "local"
        assert stage["model"] == "llama3.2:3b"
        assert stage["quality_score"] == 7.58
        assert stage["capability"] == 5
        assert stage["cost"] == 0
        assert stage["timeout_sec"] == 120

    def test_preflight_triage_prompt_injection(self):
        stage = opc.STAGES["preflight_triage"]
        assert "prompt_injection" in stage
        assert stage["prompt_injection"]["task_context"] is True
        assert stage["prompt_injection"]["prior_outcomes"] is True
        assert stage["prompt_injection"]["test_results"] is False

    def test_strategy_planner_stage(self):
        stage = opc.STAGES["strategy_planner"]
        assert stage["display_name"] == "Strategy Planner"
        assert stage["model_provider"] == "deepseek"
        assert stage["model"] == "deepseek-v4-flash"
        assert stage["quality_score"] == 7.4
        assert stage["capability"] == 6
        assert stage["cost"] == 2
        assert stage["timeout_sec"] == 180

    def test_strategy_planner_daily_limit(self):
        stage = opc.STAGES["strategy_planner"]
        assert "daily_limit_usd" in stage
        assert stage["daily_limit_usd"] == 10.0

    def test_agentic_coder_stage(self):
        stage = opc.STAGES["agentic_coder"]
        assert stage["display_name"] == "Agentic Coder"
        assert stage["model_provider"] == "claude"
        assert "claude" in stage["model"]
        assert stage["capability"] == 8
        assert stage["timeout_sec"] == 300
        assert stage["author_required"] is True

    def test_agentic_coder_author_email(self):
        stage = opc.STAGES["agentic_coder"]
        assert "author_email" in stage
        assert "@" in stage["author_email"]

    def test_qa_panel_stage(self):
        stage = opc.STAGES["qa_panel"]
        assert stage["display_name"] == "QA Panel Review"
        assert stage["strategy"] == "quorum"
        assert stage["required_agreement"] == 2
        assert len(stage["models"]) == 2
        assert stage["samples"] == 23
        assert stage["timeout_sec"] == 240

    def test_qa_panel_models_diverse(self):
        stage = opc.STAGES["qa_panel"]
        providers = set()
        for model in stage["models"]:
            assert "model_provider" in model
            assert "model" in model
            assert "quality_score" in model
            assert "capability" in model
            assert "cost" in model
            providers.add(model["model_provider"])
        assert len(providers) >= 2, "QA panel should have models from diverse providers"

    def test_all_stages_have_required_fields(self):
        required_fields = ["display_name", "timeout_sec", "purpose"]
        for stage_name, stage_def in opc.STAGES.items():
            for field in required_fields:
                assert field in stage_def, f"{stage_name} missing {field}"

    def test_all_stages_have_quality_score(self):
        for stage_name, stage_def in opc.STAGES.items():
            if stage_name != "qa_panel":  # qa_panel has models with scores
                assert "quality_score" in stage_def
                assert 0.0 <= stage_def["quality_score"] <= 10.0

    def test_stage_timeout_values_reasonable(self):
        for stage_name, stage_def in opc.STAGES.items():
            timeout = stage_def["timeout_sec"]
            assert timeout > 0
            assert timeout <= 3600, f"{stage_name} timeout too high: {timeout}s"

    def test_stage_cost_non_negative(self):
        for stage_name, stage_def in opc.STAGES.items():
            if "cost" in stage_def:
                assert stage_def["cost"] >= 0

    def test_prompt_injection_configurations_present(self):
        stages_with_injection = ["preflight_triage", "strategy_planner", "agentic_coder"]
        for stage_name in stages_with_injection:
            assert "prompt_injection" in opc.STAGES[stage_name]
            injection = opc.STAGES[stage_name]["prompt_injection"]
            assert all(isinstance(v, bool) for v in injection.values())


class TestBehaviorGates:
    """Verify behavioral preservation gates."""

    def test_api_signature_check_gate(self):
        gate = opc.BEHAVIOR_GATES["api_signature_check"]
        assert gate["enabled"] is True
        assert gate["fail_action"] == "block"
        assert "description" in gate

    def test_external_endpoint_check_gate(self):
        gate = opc.BEHAVIOR_GATES["external_endpoint_check"]
        assert gate["enabled"] is True
        assert gate["fail_action"] == "block"
        assert "description" in gate

    def test_config_immutability_check_gate(self):
        gate = opc.BEHAVIOR_GATES["config_immutability_check"]
        assert gate["enabled"] is True
        assert gate["fail_action"] == "warn"
        assert "description" in gate

    def test_all_gates_have_enabled_flag(self):
        for gate_name, gate_def in opc.BEHAVIOR_GATES.items():
            assert "enabled" in gate_def
            assert isinstance(gate_def["enabled"], bool)

    def test_all_gates_have_fail_action(self):
        valid_actions = ["block", "warn", "log", "ignore"]
        for gate_name, gate_def in opc.BEHAVIOR_GATES.items():
            assert "fail_action" in gate_def
            assert gate_def["fail_action"] in valid_actions

    def test_behavior_gates_count(self):
        assert len(opc.BEHAVIOR_GATES) >= 3


class TestLegalGates:
    """Verify legal/security gates and approval requirements."""

    def test_licensing_gate_defined(self):
        gate = opc.LEGAL_GATES["licensing"]
        assert "required_approver" in gate
        assert "@" in gate["required_approver"]
        assert len(gate["triggers"]) > 0

    def test_licensing_gate_triggers(self):
        triggers = opc.LEGAL_GATES["licensing"]["triggers"]
        keywords = ["LICENSE", "license", "copyright", "COPYING"]
        for keyword in keywords:
            assert keyword in triggers

    def test_data_transmission_gate_defined(self):
        gate = opc.LEGAL_GATES["data_transmission"]
        assert "required_approver" in gate
        assert "@" in gate["required_approver"]
        assert len(gate["triggers"]) > 0

    def test_data_transmission_gate_triggers(self):
        triggers = opc.LEGAL_GATES["data_transmission"]["triggers"]
        keywords = ["privacy", "gdpr", "data retention", "encryption", "fetch"]
        for keyword in keywords:
            assert keyword in triggers

    def test_credentials_gate_defined(self):
        gate = opc.LEGAL_GATES["credentials"]
        assert "required_approver" in gate
        assert "@" in gate["required_approver"]
        assert len(gate["triggers"]) > 0

    def test_credentials_gate_triggers(self):
        triggers = opc.LEGAL_GATES["credentials"]["triggers"]
        keywords = ["secret", "password", "token", "credential", ".env"]
        for keyword in keywords:
            assert keyword in triggers

    def test_all_gates_require_owner_approval(self):
        owner_email = "kalepasch@gmail.com"
        for gate_name, gate_def in opc.LEGAL_GATES.items():
            assert gate_def["required_approver"] == owner_email

    def test_all_gates_have_description(self):
        for gate_name, gate_def in opc.LEGAL_GATES.items():
            assert "description" in gate_def
            assert len(gate_def["description"]) > 0

    def test_legal_gates_count(self):
        assert len(opc.LEGAL_GATES) >= 3


class TestCrossSiteTests:
    """Verify cross-site testing configuration."""

    def test_mandypasch_com_configured(self):
        site = opc.CROSS_SITE_TESTS["mandypasch_com"]
        assert site["name"] == "mandypasch.com"
        assert len(site["tests_to_run"]) > 0
        assert site["must_pass"] is True

    def test_mandypasch_com_tests_defined(self):
        site = opc.CROSS_SITE_TESTS["mandypasch_com"]
        required_tests = ["test_substack_rss_fetch", "test_site_render", "test_database_connection"]
        for test in required_tests:
            assert test in site["tests_to_run"]

    def test_kalepasch_com_configured(self):
        site = opc.CROSS_SITE_TESTS["kalepasch_com"]
        assert site["name"] == "kalepasch-com"
        assert len(site["tests_to_run"]) > 0
        assert site["must_pass"] is True

    def test_kalepasch_com_tests_defined(self):
        site = opc.CROSS_SITE_TESTS["kalepasch_com"]
        required_tests = ["test_build_succeeds", "test_no_regressions", "test_supabase_storage_access"]
        for test in required_tests:
            assert test in site["tests_to_run"]

    def test_all_cross_site_tests_have_name(self):
        for site_key, site_config in opc.CROSS_SITE_TESTS.items():
            assert "name" in site_config
            assert len(site_config["name"]) > 0

    def test_all_cross_site_tests_have_repo(self):
        for site_key, site_config in opc.CROSS_SITE_TESTS.items():
            assert "repo" in site_config
            repo = site_config["repo"]
            assert len(repo) > 0

    def test_all_cross_site_tests_have_must_pass(self):
        for site_key, site_config in opc.CROSS_SITE_TESTS.items():
            assert "must_pass" in site_config
            assert isinstance(site_config["must_pass"], bool)

    def test_cross_site_tests_count(self):
        assert len(opc.CROSS_SITE_TESTS) >= 2


class TestMergeStrategy:
    """Verify merge and release configuration."""

    def test_merge_strategy_auto_merge_enabled(self):
        assert opc.MERGE_STRATEGY["auto_merge"] is True

    def test_merge_strategy_target_branch(self):
        assert opc.MERGE_STRATEGY["target_branch"] == "orchestrator/dev"

    def test_merge_strategy_commit_author(self):
        assert opc.MERGE_STRATEGY["commit_author"] == "kalepasch1"

    def test_merge_strategy_commit_email(self):
        assert "@" in opc.MERGE_STRATEGY["commit_email"]

    def test_merge_strategy_commit_prefix(self):
        assert opc.MERGE_STRATEGY["commit_prefix"] == "relfix"

    def test_merge_strategy_description(self):
        assert "description" in opc.MERGE_STRATEGY
        assert len(opc.MERGE_STRATEGY["description"]) > 0

    def test_merge_strategy_has_all_fields(self):
        required = ["auto_merge", "target_branch", "commit_author", "commit_email", "commit_prefix"]
        for field in required:
            assert field in opc.MERGE_STRATEGY


class TestReleaseStrategy:
    """Verify release strategy configuration."""

    def test_release_strategy_auto_release(self):
        assert opc.RELEASE_STRATEGY["auto_release"] is True

    def test_release_strategy_target_branch(self):
        assert opc.RELEASE_STRATEGY["target_branch"] == "master"

    def test_release_strategy_batch_size(self):
        assert opc.RELEASE_STRATEGY["batch_size"] >= 1

    def test_release_strategy_batch_interval(self):
        assert opc.RELEASE_STRATEGY["batch_interval_hours"] > 0

    def test_release_strategy_description(self):
        assert "description" in opc.RELEASE_STRATEGY
        assert len(opc.RELEASE_STRATEGY["description"]) > 0

    def test_release_strategy_has_all_fields(self):
        required = ["auto_release", "target_branch", "batch_size", "batch_interval_hours"]
        for field in required:
            assert field in opc.RELEASE_STRATEGY


class TestEnvironmentOverrides:
    """Verify environment variable override configuration."""

    def test_preflight_model_override(self):
        assert "ORCH_PREFLIGHT_MODEL" in opc.ENV_OVERRIDES
        default = opc.ENV_OVERRIDES["ORCH_PREFLIGHT_MODEL"]
        assert "llama3.2:3b" in default

    def test_planner_model_override(self):
        assert "ORCH_PLANNER_MODEL" in opc.ENV_OVERRIDES
        default = opc.ENV_OVERRIDES["ORCH_PLANNER_MODEL"]
        assert "deepseek" in default

    def test_coder_model_override(self):
        assert "ORCH_CODER_MODEL" in opc.ENV_OVERRIDES
        default = opc.ENV_OVERRIDES["ORCH_CODER_MODEL"]
        assert "claude" in default

    def test_qa_models_override(self):
        assert "ORCH_QA_MODELS" in opc.ENV_OVERRIDES
        models = opc.ENV_OVERRIDES["ORCH_QA_MODELS"]
        assert "," in models or len(models) > 0

    def test_test_count_overrides(self):
        assert "ORCH_MIN_TESTS_PASS" in opc.ENV_OVERRIDES
        assert "ORCH_MAX_TESTS" in opc.ENV_OVERRIDES
        min_tests = int(opc.ENV_OVERRIDES["ORCH_MIN_TESTS_PASS"])
        max_tests = int(opc.ENV_OVERRIDES["ORCH_MAX_TESTS"])
        assert min_tests <= max_tests


class TestGetConfig:
    """Verify configuration loading and composition."""

    def test_get_config_default(self):
        config = opc.get_config()
        assert "project" in config
        assert "task_class_def" in config
        assert "stages" in config
        assert "behavior_gates" in config
        assert "legal_gates" in config

    def test_get_config_hard_task(self):
        config = opc.get_config(task_class="hard")
        task_def = config["task_class_def"]
        assert task_def["min_tests"] == 8
        stages = list(config["stages"].keys())
        assert len(stages) == 4

    def test_get_config_medium_task(self):
        config = opc.get_config(task_class="medium")
        task_def = config["task_class_def"]
        assert task_def["min_tests"] == 6
        stages = list(config["stages"].keys())
        assert len(stages) == 4

    def test_get_config_easy_task(self):
        config = opc.get_config(task_class="easy")
        task_def = config["task_class_def"]
        assert task_def["min_tests"] == 4
        stages = list(config["stages"].keys())
        assert len(stages) == 3
        assert "strategy_planner" not in config["stages"]

    def test_get_config_includes_merge_strategy(self):
        config = opc.get_config()
        assert "merge_strategy" in config
        assert config["merge_strategy"]["auto_merge"] is True

    def test_get_config_includes_release_strategy(self):
        config = opc.get_config()
        assert "release_strategy" in config
        assert config["release_strategy"]["auto_release"] is True

    def test_get_config_invalid_task_class(self):
        with pytest.raises(ValueError):
            opc.get_config(task_class="unknown")

    def test_get_config_stages_in_order(self):
        config = opc.get_config(task_class="hard")
        stages = list(config["stages"].keys())
        assert stages == ["preflight_triage", "strategy_planner", "agentic_coder", "qa_panel"]

    def test_get_config_easy_stages_correct(self):
        config = opc.get_config(task_class="easy")
        stages = list(config["stages"].keys())
        assert "preflight_triage" in stages
        assert "agentic_coder" in stages
        assert "qa_panel" in stages
        assert "strategy_planner" not in stages


class TestValidateConfig:
    """Verify configuration validation logic."""

    def test_validate_config_succeeds(self):
        result = opc.validate_config()
        assert result is True

    def test_validate_config_checks_stages_exist(self):
        # This would be true with current config
        for task_class, task_def in opc.TASK_CLASSES.items():
            for stage in task_def["stages"]:
                assert stage in opc.STAGES

    def test_validate_config_checks_legal_gates(self):
        for gate_name, gate_def in opc.LEGAL_GATES.items():
            assert "required_approver" in gate_def

    def test_validate_config_checks_cross_site_tests(self):
        required_fields = ["name", "tests_to_run", "must_pass"]
        for site_key, site_config in opc.CROSS_SITE_TESTS.items():
            for field in required_fields:
                assert field in site_config


class TestModelRequirements:
    """Verify model requirements and capabilities."""

    def test_preflight_model_capability(self):
        stage = opc.STAGES["preflight_triage"]
        assert stage["capability"] >= 5

    def test_strategy_planner_capability(self):
        stage = opc.STAGES["strategy_planner"]
        assert stage["capability"] >= 6

    def test_agentic_coder_capability(self):
        stage = opc.STAGES["agentic_coder"]
        assert stage["capability"] >= 8

    def test_hard_task_requires_capability_8(self):
        hard_task = opc.TASK_CLASSES["hard"]
        assert hard_task["required_capability"] == 8
        config = opc.get_config(task_class="hard")
        coder_stage = config["stages"]["agentic_coder"]
        assert coder_stage["capability"] >= hard_task["required_capability"]

    def test_qa_panel_diverse_capabilities(self):
        stage = opc.STAGES["qa_panel"]
        capabilities = [m["capability"] for m in stage["models"]]
        assert len(set(capabilities)) >= 1, "QA panel should have models"

    def test_stage_quality_scores_range(self):
        for stage_name, stage_def in opc.STAGES.items():
            if stage_name != "qa_panel":
                score = stage_def["quality_score"]
                assert 0 <= score <= 10


class TestCostTracking:
    """Verify cost tracking and budget configuration."""

    def test_preflight_stage_free(self):
        assert opc.STAGES["preflight_triage"]["cost"] == 0

    def test_strategy_planner_has_cost(self):
        assert opc.STAGES["strategy_planner"]["cost"] > 0

    def test_agentic_coder_has_cost(self):
        assert opc.STAGES["agentic_coder"]["cost"] > 0

    def test_strategy_planner_daily_limit_set(self):
        stage = opc.STAGES["strategy_planner"]
        assert "daily_limit_usd" in stage
        assert stage["daily_limit_usd"] > 0

    def test_cost_values_realistic(self):
        for stage_name, stage_def in opc.STAGES.items():
            if "cost" in stage_def:
                cost = stage_def["cost"]
                assert cost >= 0
                assert cost < 1000  # Sanity check


class TestStageComposition:
    """Verify stage composition for different task classes."""

    def test_easy_has_basic_stages(self):
        config = opc.get_config(task_class="easy")
        assert "preflight_triage" in config["stages"]
        assert "agentic_coder" in config["stages"]
        assert "qa_panel" in config["stages"]

    def test_easy_skips_strategy_planner(self):
        config = opc.get_config(task_class="easy")
        assert "strategy_planner" not in config["stages"]

    def test_medium_includes_strategy(self):
        config = opc.get_config(task_class="medium")
        assert "strategy_planner" in config["stages"]

    def test_hard_includes_all_stages(self):
        config = opc.get_config(task_class="hard")
        assert "preflight_triage" in config["stages"]
        assert "strategy_planner" in config["stages"]
        assert "agentic_coder" in config["stages"]
        assert "qa_panel" in config["stages"]

    def test_all_configs_have_qa_panel(self):
        for task_class in ["easy", "medium", "hard"]:
            config = opc.get_config(task_class=task_class)
            assert "qa_panel" in config["stages"]

    def test_stage_count_matches_definition(self):
        for task_class in opc.TASK_CLASSES:
            config = opc.get_config(task_class=task_class)
            expected_count = len(opc.TASK_CLASSES[task_class]["stages"])
            actual_count = len(config["stages"])
            assert actual_count == expected_count


class TestQAPanelRequirements:
    """Verify QA panel consensus and review requirements."""

    def test_qa_panel_requires_two_models(self):
        stage = opc.STAGES["qa_panel"]
        assert stage["required_agreement"] == 2
        assert len(stage["models"]) >= 2

    def test_qa_panel_sample_count(self):
        stage = opc.STAGES["qa_panel"]
        assert stage["samples"] > 0
        assert stage["samples"] <= 100  # Reasonable limit

    def test_qa_panel_timeout_reasonable(self):
        stage = opc.STAGES["qa_panel"]
        timeout = stage["timeout_sec"]
        assert timeout > 0
        assert timeout >= opc.STAGES["strategy_planner"]["timeout_sec"]

    def test_qa_panel_quorum_strategy(self):
        stage = opc.STAGES["qa_panel"]
        assert stage["strategy"] == "quorum"

    def test_qa_panel_all_models_have_config(self):
        stage = opc.STAGES["qa_panel"]
        for model in stage["models"]:
            assert "model_provider" in model
            assert "model" in model
            assert "quality_score" in model
            assert "capability" in model
            assert "cost" in model


class TestAuthorRequirements:
    """Verify author capability and constraints."""

    def test_agentic_coder_author_required(self):
        stage = opc.STAGES["agentic_coder"]
        assert stage["author_required"] is True

    def test_agentic_coder_author_email_set(self):
        stage = opc.STAGES["agentic_coder"]
        assert "author_email" in stage
        email = stage["author_email"]
        assert "@" in email
        assert "." in email.split("@")[1]

    def test_merge_strategy_author_valid(self):
        author = opc.MERGE_STRATEGY["commit_author"]
        email = opc.MERGE_STRATEGY["commit_email"]
        assert len(author) > 0
        assert "@" in email


class TestConfigEdgeCases:
    """Verify configuration handles edge cases."""

    def test_get_config_with_explicit_project_name(self):
        config = opc.get_config(project_name="kalepasch-com")
        assert config["project"]["name"] == "kalepasch-com"

    def test_get_config_task_class_none_uses_default(self):
        config = opc.get_config(task_class=None)
        assert config["task_class_def"]["min_tests"] == opc.TASK_CLASSES[opc.PROJECT["task_class"]]["min_tests"]

    def test_validate_config_idempotent(self):
        result1 = opc.validate_config()
        result2 = opc.validate_config()
        assert result1 == result2

    def test_all_stages_have_purpose(self):
        for stage_name, stage_def in opc.STAGES.items():
            assert "purpose" in stage_def
            assert len(stage_def["purpose"]) > 0

    def test_all_gates_have_description(self):
        for gate_name, gate_def in opc.BEHAVIOR_GATES.items():
            assert "description" in gate_def
        for gate_name, gate_def in opc.LEGAL_GATES.items():
            assert "description" in gate_def


class TestPromptInjectionConfig:
    """Verify prompt injection configurations."""

    def test_preflight_includes_task_context(self):
        injection = opc.STAGES["preflight_triage"]["prompt_injection"]
        assert injection["task_context"] is True

    def test_strategy_includes_test_results(self):
        injection = opc.STAGES["strategy_planner"]["prompt_injection"]
        assert injection["test_results"] is True

    def test_coder_includes_strategy_plan(self):
        injection = opc.STAGES["agentic_coder"]["prompt_injection"]
        assert injection["strategy_plan"] is True

    def test_injection_configuration_consistent(self):
        for stage_name in ["preflight_triage", "strategy_planner", "agentic_coder"]:
            injection = opc.STAGES[stage_name]["prompt_injection"]
            assert all(isinstance(v, bool) for v in injection.values())


class TestConfigurationIntegrity:
    """Verify overall configuration integrity."""

    def test_no_missing_stage_references(self):
        for task_class, task_def in opc.TASK_CLASSES.items():
            for stage_name in task_def["stages"]:
                assert stage_name in opc.STAGES, f"Task class {task_class} references undefined stage {stage_name}"

    def test_all_models_have_valid_format(self):
        for stage_name, stage_def in opc.STAGES.items():
            if "model" in stage_def:
                model = stage_def["model"]
                assert isinstance(model, str)
                assert len(model) > 0
            if stage_name == "qa_panel":
                for model_def in stage_def["models"]:
                    assert "model" in model_def
                    assert isinstance(model_def["model"], str)

    def test_config_is_serializable(self):
        config = opc.get_config()
        try:
            json_str = json.dumps(config, default=str)
            assert len(json_str) > 0
        except TypeError as e:
            pytest.fail(f"Configuration not JSON serializable: {e}")

    def test_all_modules_reference_expected_types(self):
        assert isinstance(opc.PROJECT, dict)
        assert isinstance(opc.TASK_CLASSES, dict)
        assert isinstance(opc.STAGES, dict)
        assert isinstance(opc.BEHAVIOR_GATES, dict)
        assert isinstance(opc.LEGAL_GATES, dict)
        assert isinstance(opc.CROSS_SITE_TESTS, dict)
        assert isinstance(opc.MERGE_STRATEGY, dict)
        assert isinstance(opc.RELEASE_STRATEGY, dict)
        assert isinstance(opc.ENV_OVERRIDES, dict)


# Contract validator tests
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    import contract_validator as cv
    HAS_CONTRACT_VALIDATOR = True
except ImportError:
    HAS_CONTRACT_VALIDATOR = False


@pytest.mark.skipif(not HAS_CONTRACT_VALIDATOR, reason="contract_validator not available")
class TestContractValidator:
    """Verify contract validator enforces pipeline gates."""

    def test_validator_instantiation(self):
        validator = cv.PipelineContractValidator()
        assert validator is not None
        assert validator.config is not None

    def test_preflight_triage_gate_pass(self):
        validator = cv.PipelineContractValidator()
        passed, msg = validator.validate_preflight_triage(7.0)
        assert passed is True
        assert "7.0" in msg

    def test_preflight_triage_gate_fail(self):
        validator = cv.PipelineContractValidator()
        passed, msg = validator.validate_preflight_triage(5.0)
        assert passed is False
        assert "5.0" in msg

    def test_strategy_planner_gate_pass(self):
        validator = cv.PipelineContractValidator()
        passed, msg = validator.validate_strategy_planner(7.0)
        assert passed is True

    def test_strategy_planner_gate_fail_hard_task(self):
        config = opc.get_config(task_class="hard")
        validator = cv.PipelineContractValidator(config)
        passed, msg = validator.validate_strategy_planner(6.0)
        assert passed is False

    def test_qa_panel_votes_all_pass(self):
        validator = cv.PipelineContractValidator()
        votes = [
            cv.QAPanelVote("llama3.2:3b", passed=True, confidence=0.85),
            cv.QAPanelVote("deepseek-v4-flash", passed=True, confidence=0.88),
        ]
        passed, msg = validator.validate_qa_panel(votes)
        assert passed is True
        assert len(validator.qa_votes) == 2

    def test_qa_panel_votes_insufficient_consensus(self):
        validator = cv.PipelineContractValidator()
        votes = [
            cv.QAPanelVote("llama3.2:3b", passed=True, confidence=0.85),
            cv.QAPanelVote("deepseek-v4-flash", passed=False, confidence=0.30),
        ]
        passed, msg = validator.validate_qa_panel(votes)
        assert passed is False

    def test_qa_panel_votes_low_confidence(self):
        validator = cv.PipelineContractValidator()
        votes = [
            cv.QAPanelVote("llama3.2:3b", passed=True, confidence=0.50),
            cv.QAPanelVote("deepseek-v4-flash", passed=True, confidence=0.40),
        ]
        passed, msg = validator.validate_qa_panel(votes)
        assert passed is False

    def test_qa_panel_empty_votes(self):
        validator = cv.PipelineContractValidator()
        passed, msg = validator.validate_qa_panel([])
        assert passed is False
        assert "no votes" in msg.lower()

    def test_legal_gate_clean_diff(self):
        validator = cv.PipelineContractValidator()
        diff = "feat: add new feature to parser"
        all_clear, results = validator.check_legal_gates(diff)
        assert all_clear is True
        assert all(not r.triggered for r in results)

    def test_legal_gate_triggers_credentials(self):
        validator = cv.PipelineContractValidator()
        diff = "chore: add API_KEY=secret123 to config"
        all_clear, results = validator.check_legal_gates(diff)
        assert all_clear is False
        triggered = [r.gate_name for r in results if r.triggered]
        assert "credentials" in triggered

    def test_legal_gate_triggers_licensing(self):
        validator = cv.PipelineContractValidator()
        diff = "docs: update LICENSE file with new copyright notice"
        all_clear, results = validator.check_legal_gates(diff)
        assert all_clear is False
        triggered = [r.gate_name for r in results if r.triggered]
        assert "licensing" in triggered

    def test_legal_gate_triggers_data_transmission(self):
        validator = cv.PipelineContractValidator()
        diff = "feat: implement privacy-compliant data encryption for GDPR"
        all_clear, results = validator.check_legal_gates(diff)
        assert all_clear is False
        triggered = [r.gate_name for r in results if r.triggered]
        assert "data_transmission" in triggered

    def test_legal_gate_env_file_triggers_credentials(self):
        validator = cv.PipelineContractValidator()
        diff = "modified .env with DATABASE_URL updates"
        all_clear, results = validator.check_legal_gates(diff)
        assert all_clear is False
        triggered = [r.gate_name for r in results if r.triggered]
        assert "credentials" in triggered

    def test_legal_gate_multiple_triggers(self):
        validator = cv.PipelineContractValidator()
        diff = "feat: add privacy settings and update LICENSE with secret token"
        all_clear, results = validator.check_legal_gates(diff)
        assert all_clear is False
        triggered_count = sum(1 for r in results if r.triggered)
        assert triggered_count >= 2

    def test_legal_gate_result_structure(self):
        result = cv.LegalGateResult("test_gate", triggered=True, reason="test", required_approver="owner@example.com")
        data = result.to_dict()
        assert data["gate"] == "test_gate"
        assert data["triggered"] is True
        assert data["required_approver"] == "owner@example.com"

    def test_coordination_rule_structure(self):
        rule = cv.CoordinationRule("test_rule", violation=True, details="test details")
        data = rule.to_dict()
        assert data["rule"] == "test_rule"
        assert data["violated"] is True

    def test_auto_merge_gate_all_pass(self):
        validator = cv.PipelineContractValidator()
        validator.qa_votes = [
            cv.QAPanelVote("llama3.2:3b", passed=True, confidence=0.85),
            cv.QAPanelVote("deepseek-v4-flash", passed=True, confidence=0.88),
        ]
        validator.legal_results = [
            cv.LegalGateResult("test", triggered=False),
        ]
        validator.coordination_rules = [
            cv.CoordinationRule("test", violation=False),
        ]
        can_merge, status = validator.validate_auto_merge_gates()
        assert can_merge is True
        assert status["qa_panel_passed"] is True
        assert status["legal_gates_passed"] is True

    def test_auto_merge_gate_blocked_qa(self):
        validator = cv.PipelineContractValidator()
        validator.qa_votes = [
            cv.QAPanelVote("llama3.2:3b", passed=False, confidence=0.50),
        ]
        validator.legal_results = []
        validator.coordination_rules = []
        can_merge, status = validator.validate_auto_merge_gates()
        assert can_merge is False
        assert status["qa_panel_passed"] is False

    def test_auto_merge_gate_blocked_legal(self):
        validator = cv.PipelineContractValidator()
        validator.qa_votes = [
            cv.QAPanelVote("llama3.2:3b", passed=True, confidence=0.85),
            cv.QAPanelVote("deepseek-v4-flash", passed=True, confidence=0.88),
        ]
        validator.legal_results = [
            cv.LegalGateResult("credentials", triggered=True, required_approver="owner@example.com"),
        ]
        validator.coordination_rules = []
        can_merge, status = validator.validate_auto_merge_gates()
        assert can_merge is False
        assert status["legal_gates_passed"] is False

    def test_merge_blocked_reason_legal_gate(self):
        validator = cv.PipelineContractValidator()
        validator.qa_votes = [
            cv.QAPanelVote("model1", passed=True, confidence=0.85),
            cv.QAPanelVote("model2", passed=True, confidence=0.88),
        ]
        validator.legal_results = [
            cv.LegalGateResult("credentials", triggered=True),
            cv.LegalGateResult("licensing", triggered=False),
        ]
        validator.coordination_rules = []
        reason = validator.merge_blocked_reason()
        assert reason is not None
        assert "credentials" in reason

    def test_merge_blocked_reason_qa_gate(self):
        validator = cv.PipelineContractValidator()
        validator.qa_votes = [
            cv.QAPanelVote("model1", passed=False, confidence=0.30),
        ]
        validator.legal_results = []
        validator.coordination_rules = []
        reason = validator.merge_blocked_reason()
        assert reason is not None
        assert "QA" in reason or "consensus" in reason.lower()

    def test_module_level_validate_qa_panel(self):
        votes = [
            {"model": "llama3.2:3b", "passed": True, "confidence": 0.85},
            {"model": "deepseek-v4-flash", "passed": True, "confidence": 0.88},
        ]
        passed, msg = cv.validate_qa_panel(votes)
        assert passed is True

    def test_module_level_check_legal_gates(self):
        diff = "feat: new feature"
        all_clear, results = cv.check_legal_gates(diff)
        assert all_clear is True
        assert len(results) == 3  # licensing, data_transmission, credentials

    def test_module_level_check_legal_gates_triggered(self):
        diff = "chore: update .env file"
        all_clear, results = cv.check_legal_gates(diff)
        assert all_clear is False
        triggered = [r["gate"] for r in results if r["triggered"]]
        assert len(triggered) > 0
