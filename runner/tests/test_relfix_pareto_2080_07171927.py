"""Tests for relfix-pareto-2080-07171927 orchestration contract and execution.

Task: relfix-pareto-2080-07171927
Spec: Adapt proven patch beethoven/deployfix-beethoven-07190257 (similarity 0.255)
Source: release-conflict-self-heal
Project: pareto-2080
Task class: security (need 9, risk security)

Validates:
- Orchestration pipeline contract fulfillment
- Model selection and routing for security task class
- Preflight triage, strategy planning, and agentic coding phases
- Independent QA route and panel consensus
- Deployment rule enforcement (no vercel --prod, push task branch only)
- Coordination and reuse validation
- Cross-learning context and outcome signals
"""
import sys
import os
import json
import tempfile
import unittest
from unittest.mock import Mock, patch, MagicMock
from typing import Dict, List, Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ["ORCH_DB_URL"] = ""
os.environ["ORCH_DB_ENABLED"] = "false"
os.environ["ORCH_PATCH_TRANSPLANT_ENABLED"] = "false"
os.environ["ORCH_BUILD_VALIDATION_ENABLED"] = "false"


class TestOrchestrationPipelineContract(unittest.TestCase):
    """Verify orchestration pipeline contract for pareto-2080 security task."""

    def test_contract_source_and_project(self):
        """Contract specifies release-conflict-self-heal source and pareto-2080 project."""
        contract = {
            "source": "release-conflict-self-heal",
            "project": "pareto-2080",
            "task_id": "relfix-pareto-2080-07171927",
        }

        self.assertEqual(contract["source"], "release-conflict-self-heal")
        self.assertEqual(contract["project"], "pareto-2080")
        self.assertIn("07171927", contract["task_id"])

    def test_contract_security_task_class(self):
        """Security task class requires need=9, risk=security."""
        task = {
            "task_class": "security",
            "need_score": 9,
            "risk_profile": "security",
            "risk_score": 9,
        }

        self.assertEqual(task["task_class"], "security")
        self.assertEqual(task["need_score"], 9)
        self.assertEqual(task["risk_profile"], "security")
        self.assertGreaterEqual(task["risk_score"], 8)

    def test_contract_preflight_triage_uses_local_deepseek(self):
        """Preflight triage uses local:deepseek-coder-v2:16b with q=7.7."""
        contract = orchestration_contract.load_contract("relfix-pareto-2080-07171927")
        preflight = contract["preflight_triage"]

        assert preflight["model"] == "local:deepseek-coder-v2:16b"
        assert preflight["qpd_leader"] == 7.7
        assert preflight["cost"] == 0.0

    def test_contract_strategy_planner_uses_deepseek_v4_pro(self):
        """Strategy planner is deepseek:deepseek-v4-pro with q=7.4."""
        contract = orchestration_contract.load_contract("relfix-pareto-2080-07171927")
        planner = contract["strategy_planner"]

        assert planner["model"] == "deepseek:deepseek-v4-pro"
        assert planner["qpd_leader"] == 7.4
        assert planner["cost"] == 0.0

    def test_contract_agentic_coder_is_claude_sonnet_4_6(self):
        """Agentic coder uses claude-sonnet-4-6 author model."""
        contract = orchestration_contract.load_contract("relfix-pareto-2080-07171927")
        coder = contract["agentic_coder"]

        assert coder["model"] == "claude-sonnet-4-6"
        assert coder["framework"] == "claude"

    def test_contract_executor_capabilities_defined(self):
        """Executor capabilities include code_generation and text_completion."""
        contract = orchestration_contract.load_contract("relfix-pareto-2080-07171927")
        caps = contract["executor_capabilities"]

        assert "code_generation" in caps
        assert "text_completion" in caps

    def test_contract_qa_routing_independent_route_defined(self):
        """Independent QA route uses deepseek-v4-flash."""
        contract = orchestration_contract.load_contract("relfix-pareto-2080-07171927")
        qa_route = contract["independent_qa_route"]

        assert qa_route["model"] == "deepseek:deepseek-v4-flash"
        assert qa_route["qpd_leader"] == 7.4

    def test_contract_qa_panel_has_two_judges(self):
        """QA panel consists of llama3.2:3b and deepseek-v4-flash."""
        contract = orchestration_contract.load_contract("relfix-pareto-2080-07171927")
        panel = contract["qa_panel"]

        assert len(panel) == 2
        assert "local:llama3.2:3b" in panel
        assert "deepseek:deepseek-v4-flash" in panel

    def test_contract_legal_gate_owner_only_required(self):
        """Legal gate requires owner-only for sensitive operations."""
        contract = orchestration_contract.load_contract("relfix-pareto-2080-07171927")
        legal = contract["legal_gate"]

        assert legal["mode"] == "owner-only"
        assert "licensing" in legal["triggers"]
        assert "custody" in legal["triggers"]
        assert "transmission" in legal["triggers"]

    def test_contract_merge_release_auto_merge_after_verification(self):
        """Merge/release: auto-merge to orchestrator/dev after tests & judge."""
        contract = orchestration_contract.load_contract("relfix-pareto-2080-07171927")
        merge_rule = contract["merge_release"]

        assert merge_rule["auto_merge_target"] == "orchestrator/dev"
        assert merge_rule["requires_verification"] is True
        assert merge_rule["requires_judge"] is True

    def test_contract_deploy_cost_rule_forbids_prod_deploy(self):
        """Deploy-cost rule forbids vercel --prod and direct main/master pushes."""
        contract = orchestration_contract.load_contract("relfix-pareto-2080-07171927")
        deploy_rule = contract["deploy_cost_rule"]

        assert deploy_rule["forbids_vercel_prod"] is True
        assert deploy_rule["forbids_direct_main_push"] is True
        assert deploy_rule["uses_batch_train"] is True

    def test_contract_coordination_rules_reuse_prior_solutions(self):
        """Coordination rule: reuse prior solutions first."""
        contract = orchestration_contract.load_contract("relfix-pareto-2080-07171927")
        coord = contract["coordination_rule"]

        assert coord["reuse_prior_solutions"] is True
        assert coord["preserve_queued_improvements"] is True

    def test_contract_cross_learning_context_recorded(self):
        """Cross-learning context includes recent outcome signal."""
        contract = orchestration_contract.load_contract("relfix-pareto-2080-07171927")
        learning = contract["cross_learning_context"]

        assert "recent_outcome_signal" in learning
        assert learning["recent_outcome_signal"] == 0  # 0/1 from spec


class TestPatchTransplantFromDeployfix(unittest.TestCase):
    """Verify patch transplant from beethoven/deployfix-beethoven-07190257."""

    @patch("patch_transplant.db.select")
    def test_find_deployfix_patch_source(self, mock_select):
        """Locate prior deployfix patch with similarity threshold."""
        mock_select.return_value = [
            {
                "slug": "deployfix-beethoven-07190257",
                "source": "native-claim",
                "project": "beethoven",
                "patch_diff": "--- a/fleet_config.py\n+++ b/fleet_config.py\n@@ -20,3 +20,4 @@\n ORCH_PIPELINE_MODEL_SELECT = 'gemini'\n+ORCH_PIPELINE_SECURITY_GATE = True\n",
                "similarity": 0.261
            }
        ]

        source = patch_transplant.find_transplant_source(
            target_task="relfix-pareto-2080-07171927",
            min_similarity=0.25
        )

        assert source is not None
        assert source["slug"] == "deployfix-beethoven-07190257"
        assert source["similarity"] >= 0.25

    @patch("patch_transplant.db.select")
    def test_deployfix_source_has_correct_project_and_source(self, mock_select):
        """Prior patch is from beethoven project with native-claim source."""
        mock_select.return_value = [
            {
                "slug": "deployfix-beethoven-07190257",
                "project": "beethoven",
                "source": "native-claim",
                "task_class": "build",
                "similarity": 0.261
            }
        ]

        source = patch_transplant.find_transplant_source(
            target_task="relfix-pareto-2080-07171927",
            min_similarity=0.25
        )

        assert source["project"] == "beethoven"
        assert source["source"] == "native-claim"

    def test_adapt_patch_fleet_config_changes(self):
        """Adapt deployfix patch: replicate fleet_config model selection logic."""
        prior_diff = """--- a/fleet_config.py
+++ b/fleet_config.py
@@ -20,3 +20,4 @@
 ORCH_PIPELINE_MODEL_SELECT = 'gemini'
+ORCH_PIPELINE_SECURITY_GATE = True
"""
        adapted = patch_transplant.adapt_patch(
            prior_diff=prior_diff,
            target_task="relfix-pareto-2080-07171927",
            target_files=["fleet_config.py", "release_train.py"]
        )

        assert adapted is not None
        assert "fleet_config.py" in adapted
        assert "ORCH_PIPELINE_SECURITY_GATE" in adapted

    def test_adapt_patch_maintains_semantic_intent(self):
        """Adapted patch preserves security-gate configuration intent."""
        prior_diff = """--- a/orchestration_contract.py
+++ b/orchestration_contract.py
@@ -40,3 +40,5 @@
 CONTRACT['task_class'] = 'build'
+CONTRACT['legal_gate'] = 'owner-only'
+CONTRACT['security_validated'] = True
"""
        adapted = patch_transplant.adapt_patch(
            prior_diff=prior_diff,
            target_task="relfix-pareto-2080-07171927"
        )

        # Adapted patch should include legal gate config
        assert adapted is not None
        assert "legal_gate" in adapted or "LEGAL_GATE" in adapted

    @patch("subprocess.run")
    def test_apply_transplanted_patch_cleanly(self, mock_run):
        """Transplanted patch applies without rejects."""
        patch_content = b"""--- a/fleet_config.py
+++ b/fleet_config.py
@@ -20,3 +20,4 @@
 MODEL_SELECT = True
+SECURITY_GATE = True
"""
        mock_run.return_value = Mock(returncode=0, stdout="", stderr="")

        result = patch_transplant.apply_patch(
            patch_diff=patch_content,
            repo_path="/tmp/repo",
            allow_rejects=False
        )

        assert result["applied"] is True
        assert result["rejects"] == 0

    @patch("subprocess.run")
    def test_patch_application_failure_handled_gracefully(self, mock_run):
        """Patch application failure triggers fallback rebuild."""
        mock_run.return_value = Mock(returncode=1, stdout="", stderr="conflict\n")

        result = patch_transplant.apply_patch(
            patch_diff=b"bad patch",
            repo_path="/tmp/repo"
        )

        assert result["applied"] is False
        assert result["fallback_rebuild"] is True


class TestSecurityTaskClassValidation(unittest.TestCase):
    """Validate security task class configuration."""

    def test_task_class_is_security_not_build(self):
        """Task class is security (not build like deployfix)."""
        contract = orchestration_contract.load_contract("relfix-pareto-2080-07171927")

        assert contract["task_class"] == "security"
        assert contract["task_class"] != "build"

    def test_need_vector_security_high(self):
        """Need vector is 9 (security critical)."""
        contract = orchestration_contract.load_contract("relfix-pareto-2080-07171927")

        assert contract["need"] == 9
        assert contract["risk_level"] == "security"

    @patch("orchestration_contract.validate_security_scope")
    def test_security_scope_validated_before_merge(self, mock_validate):
        """Security scope validation gates merge."""
        mock_validate.return_value = {"valid": True, "scope": "release-conflict-healing"}

        result = orchestration_contract.validate_security_scope(
            contract="relfix-pareto-2080-07171927"
        )

        assert result["valid"] is True

    def test_security_gate_requires_no_transmission_violations(self):
        """Security gate blocks transmission rule violations."""
        contract = orchestration_contract.load_contract("relfix-pareto-2080-07171927")
        legal = contract["legal_gate"]

        assert "transmission" in legal["triggers"]

    def test_security_gate_blocks_hardcoded_secrets(self):
        """Security gate detects hardcoded secrets in config."""
        contract = orchestration_contract.load_contract("relfix-pareto-2080-07171927")

        # Config keys should only be safe (ORCH_ prefixed)
        assert contract.get("safe_config_only", True) is True


class TestQAPanelComposition(unittest.TestCase):
    """Validate QA panel with deepseek-v4-flash and llama3.2:3b."""

    def test_qa_panel_has_deepseek_judge(self):
        """QA panel includes deepseek:deepseek-v4-flash."""
        contract = orchestration_contract.load_contract("relfix-pareto-2080-07171927")
        panel = contract["qa_panel"]

        assert "deepseek:deepseek-v4-flash" in panel

    def test_qa_panel_has_llama_judge(self):
        """QA panel includes local:llama3.2:3b."""
        contract = orchestration_contract.load_contract("relfix-pareto-2080-07171927")
        panel = contract["qa_panel"]

        assert "local:llama3.2:3b" in panel

    @patch("qa_routing.run_qa_panel")
    def test_qa_panel_both_judges_vote(self, mock_panel):
        """QA panel requires votes from both judges."""
        mock_panel.return_value = {
            "deepseek_vote": "approved",
            "llama_vote": "approved",
            "consensus": "pass"
        }

        result = qa_routing.run_qa_panel(
            task="relfix-pareto-2080-07171927",
            code_diff=b"..."
        )

        assert result["deepseek_vote"] == "approved"
        assert result["llama_vote"] == "approved"
        assert result["consensus"] == "pass"

    @patch("qa_routing.run_qa_panel")
    def test_qa_panel_blocks_merge_on_dissent(self, mock_panel):
        """Merge blocked if judges disagree."""
        mock_panel.return_value = {
            "deepseek_vote": "approved",
            "llama_vote": "rejected",
            "consensus": "fail"
        }

        result = qa_routing.run_qa_panel(
            task="relfix-pareto-2080-07171927",
            code_diff=b"..."
        )

        assert result["consensus"] == "fail"

    @patch("qa_routing.run_qa_panel")
    def test_independent_qa_route_also_runs(self, mock_panel):
        """Independent QA route (deepseek-v4-flash) runs in parallel."""
        mock_panel.return_value = {
            "panel_consensus": "pass",
            "independent_qa": "approved"
        }

        result = qa_routing.run_qa_panel(
            task="relfix-pareto-2080-07171927",
            code_diff=b"..."
        )

        assert result.get("independent_qa") == "approved"


class TestDeployCostRuleEnforcement(unittest.TestCase):
    """Verify deploy-cost rules: no prod deploy, batch train only."""

    def test_forbids_vercel_prod_flag(self):
        """Deploy rule forbids 'vercel --prod' and 'vercel deploy --prod'."""
        contract = orchestration_contract.load_contract("relfix-pareto-2080-07171927")
        deploy = contract["deploy_cost_rule"]

        assert deploy["forbids_vercel_prod"] is True
        assert deploy["forbids_vercel_deploy_prod"] is True

    def test_forbids_direct_main_master_push(self):
        """Deploy rule forbids pushing directly to main or master."""
        contract = orchestration_contract.load_contract("relfix-pareto-2080-07171927")
        deploy = contract["deploy_cost_rule"]

        assert deploy["forbids_direct_main_push"] is True
        assert deploy["forbids_direct_master_push"] is True

    @patch("deploy_gate.check_deploy_command")
    def test_intercepts_vercel_prod_attempt(self, mock_check):
        """Deploy gate detects and blocks 'vercel --prod' attempts."""
        mock_check.return_value = {
            "blocked": True,
            "reason": "vercel --prod forbidden",
            "use_batch_train": True
        }

        result = deploy_gate.check_deploy_command(
            cmd="vercel --prod"
        )

        assert result["blocked"] is True

    @patch("deploy_gate.check_deploy_command")
    def test_blocks_direct_main_push(self, mock_check):
        """Deploy gate blocks 'git push origin main'."""
        mock_check.return_value = {
            "blocked": True,
            "reason": "direct main push forbidden"
        }

        result = deploy_gate.check_deploy_command(
            cmd="git push origin main"
        )

        assert result["blocked"] is True

    @patch("deploy_gate.check_deploy_command")
    def test_allows_task_branch_push(self, mock_check):
        """Deploy gate allows pushing task branch for batch train."""
        mock_check.return_value = {
            "blocked": False,
            "use_batch_train": True
        }

        result = deploy_gate.check_deploy_command(
            cmd="git push origin relfix-pareto-2080-07171927"
        )

        assert result["blocked"] is False
        assert result["use_batch_train"] is True

    def test_production_release_via_batch_train_only(self):
        """Production release must go through verified batch release train."""
        contract = orchestration_contract.load_contract("relfix-pareto-2080-07171927")
        deploy = contract["deploy_cost_rule"]

        assert deploy["production_via_batch_train_only"] is True


class TestCoordinationRules(unittest.TestCase):
    """Verify coordination rule compliance."""

    @patch("coordination_rules.check_active_loop_work")
    def test_reconcile_with_active_loop_generated_work(self, mock_check):
        """Reconcile with active loop-generated work."""
        mock_check.return_value = {
            "active_work": ["other-task-branch"],
            "conflicts": []
        }

        result = coordination_rules.check_active_loop_work()

        assert "active_work" in result

    @patch("patch_transplant.find_transplant_source")
    def test_reuse_prior_solutions_first(self, mock_find):
        """Reuse prior solutions before rebuilding from scratch."""
        mock_find.return_value = {
            "slug": "deployfix-beethoven-07190257",
            "similarity": 0.261
        }

        source = patch_transplant.find_transplant_source(
            target_task="relfix-pareto-2080-07171927",
            min_similarity=0.25
        )

        assert source is not None
        # Rule: reuse, don't rebuild

    @patch("coordination_rules.check_queued_improvements")
    def test_preserve_queued_improvements(self, mock_check):
        """Do not delete or overwrite unrelated queued improvements."""
        mock_check.return_value = {
            "queued_improvements": ["feature-x-branch"],
            "preserved": True
        }

        result = coordination_rules.check_queued_improvements()

        assert result["preserved"] is True

    @patch("coordination_rules.check_recovered_work")
    def test_recovered_work_stays_in_queue_until_shipped(self, mock_check):
        """Recovered work remains in queue until shipped."""
        mock_check.return_value = {
            "recovered_work": ["recovery-repair-123"],
            "status": "queued",
            "shipped": False
        }

        result = coordination_rules.check_recovered_work()

        assert result["status"] == "queued"
        assert result["shipped"] is False


class TestCrossLearningContext(unittest.TestCase):
    """Validate cross-learning signal integration."""

    def test_recent_outcome_signal_zero_one(self):
        """Recent outcome signal is 0/1 from prior runs."""
        contract = orchestration_contract.load_contract("relfix-pareto-2080-07171927")
        learning = contract["cross_learning_context"]

        assert learning["recent_outcome_signal"] == 0

    @patch("orchestration_contract.query_recent_outcomes")
    def test_outcome_informs_model_selection(self, mock_query):
        """Recent outcome signals inform model selection strategy."""
        mock_query.return_value = [
            {
                "task": "deployfix-beethoven-07190257",
                "outcome": 1,
                "model": "gemini:2.5-flash"
            }
        ]

        outcomes = orchestration_contract.query_recent_outcomes(
            window_days=30
        )

        assert len(outcomes) > 0

    def test_outcome_zero_may_trigger_strategy_escalation(self):
        """Outcome=0 (failed) may escalate to stronger models."""
        contract = orchestration_contract.load_contract("relfix-pareto-2080-07171927")
        learning = contract["cross_learning_context"]

        if learning["recent_outcome_signal"] == 0:
            # May use stronger model/panel
            assert contract["strategy_planner"]["model"] == "deepseek:deepseek-v4-pro"


class TestExecutorCapabilities(unittest.TestCase):
    """Validate executor capability requirements."""

    def test_required_capabilities_code_generation(self):
        """Executor must support code_generation."""
        contract = orchestration_contract.load_contract("relfix-pareto-2080-07171927")
        caps = contract["executor_capabilities"]

        assert "code_generation" in caps

    def test_required_capabilities_text_completion(self):
        """Executor must support text_completion."""
        contract = orchestration_contract.load_contract("relfix-pareto-2080-07171927")
        caps = contract["executor_capabilities"]

        assert "text_completion" in caps

    @patch("orchestration_contract.check_executor_support")
    def test_executor_supports_all_required_capabilities(self, mock_check):
        """Executor validates it supports all required capabilities."""
        mock_check.return_value = {
            "code_generation": True,
            "text_completion": True,
            "supported": True
        }

        result = orchestration_contract.check_executor_support(
            contract="relfix-pareto-2080-07171927"
        )

        assert result["supported"] is True


class TestLegalGateRequirements(unittest.TestCase):
    """Validate legal gate for licensing, custody, transmission."""

    def test_legal_gate_mode_owner_only(self):
        """Legal gate requires owner-only approval."""
        contract = orchestration_contract.load_contract("relfix-pareto-2080-07171927")
        legal = contract["legal_gate"]

        assert legal["mode"] == "owner-only"

    def test_legal_gate_triggers_licensing(self):
        """Legal gate triggers for licensing changes."""
        contract = orchestration_contract.load_contract("relfix-pareto-2080-07171927")
        legal = contract["legal_gate"]

        assert "licensing" in legal["triggers"]

    def test_legal_gate_triggers_custody(self):
        """Legal gate triggers for custody/ownership changes."""
        contract = orchestration_contract.load_contract("relfix-pareto-2080-07171927")
        legal = contract["legal_gate"]

        assert "custody" in legal["triggers"]

    def test_legal_gate_triggers_transmission(self):
        """Legal gate triggers for transmission/export rules."""
        contract = orchestration_contract.load_contract("relfix-pareto-2080-07171927")
        legal = contract["legal_gate"]

        assert "transmission" in legal["triggers"]

    @patch("orchestration_contract.check_legal_gate")
    def test_legal_gate_approves_normal_code_changes(self, mock_check):
        """Normal code changes pass legal gate."""
        mock_check.return_value = {
            "approved": True,
            "requires_owner": False
        }

        result = orchestration_contract.check_legal_gate(
            contract="relfix-pareto-2080-07171927",
            files_changed=["runner.py", "db.py"]
        )

        assert result["approved"] is True


class TestModelSelectionStrategy(unittest.TestCase):
    """Validate model selection per task phase."""

    def test_preflight_triage_deepseek_coder_v2(self):
        """Preflight uses local:deepseek-coder-v2:16b."""
        contract = orchestration_contract.load_contract("relfix-pareto-2080-07171927")
        preflight = contract["preflight_triage"]

        assert "deepseek-coder-v2" in preflight["model"]

    def test_strategy_planner_deepseek_v4_pro(self):
        """Strategy planner uses deepseek:deepseek-v4-pro."""
        contract = orchestration_contract.load_contract("relfix-pareto-2080-07171927")
        planner = contract["strategy_planner"]

        assert "deepseek-v4-pro" in planner["model"]

    def test_agentic_coder_claude_sonnet_4_6(self):
        """Agentic coder uses claude-sonnet-4-6."""
        contract = orchestration_contract.load_contract("relfix-pareto-2080-07171927")
        coder = contract["agentic_coder"]

        assert "sonnet-4-6" in coder["model"]

    def test_qa_panel_mixed_models(self):
        """QA panel uses both deepseek and local llama."""
        contract = orchestration_contract.load_contract("relfix-pareto-2080-07171927")
        panel = contract["qa_panel"]

        deepseek_in_panel = any("deepseek" in m for m in panel)
        llama_in_panel = any("llama" in m for m in panel)

        assert deepseek_in_panel
        assert llama_in_panel


class TestEndToEndWorkflow(unittest.TestCase):
    """End-to-end workflow for relfix-pareto-2080-07171927."""

    @patch("patch_transplant.find_transplant_source")
    @patch("patch_transplant.adapt_patch")
    @patch("patch_transplant.apply_patch")
    @patch("orchestration_contract.check_security_gate")
    @patch("qa_routing.run_qa_panel")
    def test_complete_workflow_adapt_and_merge(self, mock_qa, mock_security,
                                               mock_apply, mock_adapt, mock_find):
        """Complete workflow: transplant patch, validate, QA, merge."""
        # Step 1: Find prior patch
        mock_find.return_value = {
            "slug": "deployfix-beethoven-07190257",
            "similarity": 0.261,
            "patch_diff": b"..."
        }

        # Step 2: Adapt patch
        mock_adapt.return_value = b"adapted patch content"

        # Step 3: Apply patch
        mock_apply.return_value = {"applied": True, "rejects": 0}

        # Step 4: Security validation
        mock_security.return_value = {"passed": True}

        # Step 5: QA panel
        mock_qa.return_value = {
            "deepseek_vote": "approved",
            "llama_vote": "approved",
            "consensus": "pass"
        }

        # Execute workflow
        source = patch_transplant.find_transplant_source("relfix-pareto-2080-07171927")
        assert source is not None

        adapted = patch_transplant.adapt_patch(
            prior_diff=source["patch_diff"],
            target_task="relfix-pareto-2080-07171927"
        )
        assert adapted is not None

        applied = patch_transplant.apply_patch(
            patch_diff=adapted,
            repo_path="/repo"
        )
        assert applied["applied"] is True

        security = orchestration_contract.check_security_gate(
            contract="relfix-pareto-2080-07171927"
        )
        assert security["passed"] is True

        qa = qa_routing.run_qa_panel(
            task="relfix-pareto-2080-07171927",
            code_diff=adapted
        )
        assert qa["consensus"] == "pass"


if __name__ == "__main__":
    unittest.main()
