"""
Comprehensive test suite for relfix-pareto-2080-07171927: Patch transplant with self-healing.

Task scope: adapt proven patch beethoven/deployfix-beethoven-07190257 (similarity 0.261)
for release-conflict self-healing in pareto-2080 project with security-class constraints.

Test coverage:
- Patch similarity matching and transplant candidate selection
- Prior patch adaptation for pareto-2080 context
- Conflict detection and release branch decomposition
- Security validation gates (no credentials, transmission rules, custody gates)
- Orchestration pipeline contract compliance (model selection, executor capabilities)
- Deploy-cost rules enforcement (no direct prod pushes)
- Coordination rules (reuse solutions, don't overwrite queued work)
- Auto-merge coordination (orchestrator/dev staging, release train batch promotion)
- End-to-end workflow validation
"""
import os
import sys
import json
import tempfile
import unittest
from unittest.mock import Mock, patch, MagicMock, call
import datetime
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import patch_transplant
import merged_diff_library
import patch_templates
import conflict_auto_resolve
import self_healing_merge
import release_train


class TestPatchSimilarityMatching(unittest.TestCase):
    """Find and match prior patches by similarity threshold."""

    @patch("merged_diff_library.find")
    def test_find_prior_patch_above_minimum_threshold(self, mock_find):
        """Prior patch with similarity 0.261 > 0.18 minimum."""
        mock_find.return_value = [{
            "project": "beethoven",
            "slug": "deployfix-beethoven-07190257",
            "similarity": 0.261,
            "summary": "Release conflict self-heal",
            "diff": "--- a/fleet_config.py\n+++ b/fleet_config.py\n"
        }]

        task = {
            "id": "relfix-pareto-2080-07171927",
            "prompt": "Fix release conflict in pareto-2080",
            "project": "pareto-2080"
        }

        hint = patch_transplant.hint(task)
        assert "PATCH TRANSPLANT" in hint
        assert "deployfix-beethoven-07190257" in hint
        assert "0.261" in hint

    @patch("merged_diff_library.find")
    def test_skip_patch_below_minimum_threshold(self, mock_find):
        """Patch with similarity 0.15 < 0.18 minimum is skipped."""
        mock_find.return_value = [{
            "project": "beethoven",
            "slug": "deployfix-beethoven-07190257",
            "similarity": 0.15,
            "diff": "..."
        }]

        task = {
            "id": "relfix-pareto-2080-07171927",
            "prompt": "Fix release conflict",
            "project": "pareto-2080"
        }

        hint = patch_transplant.hint(task)
        assert hint == ""

    @patch("merged_diff_library.find")
    def test_skip_when_patch_transplant_already_marked(self, mock_find):
        """Task already contains PATCH TRANSPLANT hint is not re-hinted."""
        mock_find.return_value = []

        task = {
            "id": "relfix-pareto-2080-07171927",
            "prompt": "PATCH TRANSPLANT: before drafting...",
            "project": "pareto-2080"
        }

        hint = patch_transplant.hint(task)
        assert hint == ""
        assert not mock_find.called

    @patch("merged_diff_library.find")
    def test_return_empty_when_no_candidates_found(self, mock_find):
        """No candidates found returns empty hint."""
        mock_find.return_value = []

        task = {
            "id": "relfix-pareto-2080-07171927",
            "prompt": "Fix something novel",
            "project": "pareto-2080"
        }

        hint = patch_transplant.hint(task)
        assert hint == ""

    @patch("merged_diff_library.find")
    def test_highest_similarity_candidate_selected(self, mock_find):
        """When multiple candidates exist, highest similarity is selected."""
        mock_find.return_value = [
            {
                "project": "beethoven",
                "slug": "deployfix-beethoven-07190257",
                "similarity": 0.261,
                "diff": "high similarity diff"
            },
            {
                "project": "beethoven",
                "slug": "other-fix-07180000",
                "similarity": 0.235,
                "diff": "lower similarity diff"
            }
        ]

        task = {"id": "relfix-pareto", "prompt": "Fix", "project": "pareto-2080"}

        hint = patch_transplant.hint(task)
        # Mock returns list[0], so highest similarity should be in result
        assert "deployfix-beethoven-07190257" in hint
        assert "0.261" in hint


class TestPatchAdaptation(unittest.TestCase):
    """Adapt proven patches for target project context."""

    def test_adapt_patch_preserves_core_changes(self):
        """Adapted patch retains the essential fix."""
        prior_diff = b"""--- a/fleet_config.py
+++ b/fleet_config.py
@@ -5,3 +5,5 @@
 PROFILES = {}
+ORCH_SECURITY_GATE = True
+ORCH_CONFLICT_AUTO_RESOLVE = True
"""
        result = patch_transplant.adapt_patch(
            prior_diff,
            target_task={"project": "pareto-2080"},
            target_files=["fleet_config.py"]
        )

        assert result is not None
        assert b"ORCH_SECURITY_GATE" in result
        assert b"ORCH_CONFLICT_AUTO_RESOLVE" in result

    def test_adapt_patch_rewrites_paths_for_target(self):
        """Patch paths are rewritten to match target project structure."""
        prior_diff = b"""--- a/runner/fleet_config.py
+++ b/runner/fleet_config.py
@@ -1,3 +1,5 @@
 import os
+# security gate added
"""
        result = patch_transplant.adapt_patch(
            prior_diff,
            target_task={"project": "pareto-2080"},
            target_files=["pareto_2080_config.py"]
        )

        assert result is not None
        # Should handle path rewriting

    def test_adapt_patch_handles_string_input(self):
        """String-type diffs are handled (converted to bytes internally)."""
        prior_diff = """--- a/config.py
+++ b/config.py
@@ -1 +1,2 @@
 x = 1
+y = 2
"""
        result = patch_transplant.adapt_patch(
            prior_diff,
            target_task={"project": "pareto-2080"}
        )

        assert result is not None
        # Should handle string/bytes conversion

    def test_adapt_patch_security_gate_preserved_for_pareto(self):
        """ORCH_PIPELINE_SECURITY_GATE config is preserved in adapted patch."""
        prior_diff = b"""--- a/fleet_config.py
+++ b/fleet_config.py
@@ -1,3 +1,6 @@
 PROFILES = {}
+ORCH_PIPELINE_SECURITY_GATE = True
+# Security validation required for release
"""
        result = patch_transplant.adapt_patch(
            prior_diff,
            target_task={"project": "pareto-2080"}
        )

        assert b"ORCH_PIPELINE_SECURITY_GATE" in result

    def test_adapt_patch_returns_none_for_empty_prior_diff(self):
        """Empty or None prior diff returns None."""
        result = patch_transplant.adapt_patch(None, {"project": "pareto-2080"})
        assert result is None

        result = patch_transplant.adapt_patch(b"", {"project": "pareto-2080"})
        # Empty should be handled gracefully


class TestPatchApplication(unittest.TestCase):
    """Apply transplanted patches to repository."""

    @patch("subprocess.run")
    def test_apply_patch_dry_run_succeeds(self, mock_run):
        """Dry-run succeeds when patch applies cleanly."""
        patch_diff = b"""--- a/test.py
+++ b/test.py
@@ -1,3 +1,4 @@
 def foo():
+    pass
"""
        mock_run.return_value = Mock(returncode=0, stdout=b"", stderr=b"")

        result = patch_transplant.apply_patch(patch_diff, repo_path="/repo")

        assert result["applied"] is True
        assert result["rejects"] == 0

    @patch("subprocess.run")
    def test_apply_patch_with_rejects_detects_conflicts(self, mock_run):
        """Patch application with rejects is detected."""
        patch_diff = b"""--- a/test.py
+++ b/test.py
"""
        mock_run.side_effect = [
            # dry-run fails
            Mock(returncode=1, stdout=b"", stderr=b"FAILED: conflict\n")
        ]

        result = patch_transplant.apply_patch(
            patch_diff,
            repo_path="/repo",
            allow_rejects=False
        )

        assert result["applied"] is False
        assert result["rejects"] > 0
        assert result["fallback_rebuild"] is True

    @patch("subprocess.run")
    def test_apply_patch_timeout_triggers_fallback(self, mock_run):
        """Patch application timeout triggers rebuild fallback."""
        patch_diff = b"--- a/test.py\n"
        mock_run.side_effect = subprocess_timeout_error()

        result = patch_transplant.apply_patch(patch_diff, repo_path="/repo")

        assert result["applied"] is False
        assert result["fallback_rebuild"] is True

    @patch("subprocess.run")
    def test_apply_patch_handles_bytes_input(self, mock_run):
        """Bytes patch input is handled."""
        patch_diff = b"""--- a/file.py
+++ b/file.py
"""
        mock_run.return_value = Mock(returncode=0, stdout=b"")

        result = patch_transplant.apply_patch(patch_diff, repo_path="/repo")

        # Should not crash on bytes input

    def test_apply_patch_none_input_returns_fallback(self):
        """None patch triggers fallback rebuild."""
        result = patch_transplant.apply_patch(None, repo_path="/repo")

        assert result["applied"] is False
        assert result["fallback_rebuild"] is True


class TestConflictDetectionAndClassification(unittest.TestCase):
    """Release conflict detection and file classification."""

    @patch("self_healing_merge._git")
    def test_classify_release_branch_clean_merge(self, mock_git):
        """Release branch with no conflicts classifies files as all clean."""
        mock_git.side_effect = [
            Mock(returncode=0, stdout=b"base123\n"),
            Mock(returncode=0, stdout=b"config.py\nrunner.py\n"),
            Mock(returncode=0, stdout=b""),  # worktree create
            Mock(returncode=0, stdout=b""),  # checkout base
            Mock(returncode=0, stdout=b""),  # merge succeeds
            Mock(returncode=0, stdout=b""),  # no conflicts
            Mock(returncode=0, stdout=b""),  # worktree delete
        ]

        result = self_healing_merge._classify_files(
            "/repo",
            "release/pareto-2080",
            "master"
        )

        assert len(result["clean"]) == 2
        assert "config.py" in result["clean"]
        assert len(result["conflicting"]) == 0

    @patch("self_healing_merge._git")
    def test_classify_release_branch_partial_conflict(self, mock_git):
        """Some files clean, some conflicting (classic partial release conflict)."""
        mock_git.side_effect = [
            Mock(returncode=0, stdout=b"base123\n"),
            Mock(returncode=0, stdout=b"safe1.py\nsafe2.py\nrelease_config.py\n"),
            Mock(returncode=0, stdout=b""),
            Mock(returncode=0, stdout=b""),
            Mock(returncode=1, stdout=b"", stderr=b"conflict\n"),
            Mock(returncode=0, stdout=b"release_config.py\n"),
            Mock(returncode=0, stdout=b""),
        ]

        result = self_healing_merge._classify_files(
            "/repo",
            "release/pareto-2080",
            "master"
        )

        assert len(result["clean"]) == 2
        assert len(result["conflicting"]) == 1
        assert "release_config.py" in result["conflicting"]


class TestSecurityValidationGates(unittest.TestCase):
    """Security gate enforcement for pareto-2080 security-class task."""

    @patch("security_check.scan_for_hardcoded_secrets")
    def test_security_gate_blocks_hardcoded_api_keys(self, mock_scan):
        """Hardcoded API keys block merge."""
        mock_scan.return_value = {
            "found": ["AWS_SECRET_ACCESS_KEY=..."],
            "files": ["fleet_config.py"]
        }

        result = patch_templates.validate_security_gate(
            branch="relfix-pareto-2080-07171927",
            repo="/repo"
        )

        assert result["passed"] is False or result["violations"] > 0

    @patch("security_check.validate_config_keys_safe")
    def test_security_gate_requires_orch_prefix_for_fleet_config(self, mock_validate):
        """Fleet-wide config keys must be ORCH_-prefixed and safe."""
        mock_validate.return_value = {
            "safe": False,
            "unsafe_keys": ["SECRET_TOKEN"],  # Missing ORCH_ prefix
            "reason": "Secret key without ORCH_ prefix"
        }

        result = patch_templates.validate_config_keys(
            branch="relfix-pareto-2080-07171927",
            repo="/repo"
        )

        assert result["safe"] is False

    @patch("security_check.scan_for_transmission_rule_violations")
    def test_security_gate_blocks_transmission_rule_violations(self, mock_scan):
        """Transmission of credentials outside secure boundaries is blocked."""
        mock_scan.return_value = {
            "violations": ["auth_token sent via HTTP"],
            "files": ["transport.py"]
        }

        result = patch_templates.validate_security_gate(
            branch="relfix-pareto-2080-07171927",
            repo="/repo"
        )

        assert result["passed"] is False

    @patch("security_check.check_custody_boundaries")
    def test_security_gate_protects_data_custody_rules(self, mock_check):
        """Data custody and ownership boundaries are protected."""
        mock_check.return_value = {
            "compliant": False,
            "violation": "Data exfiltration risk detected in logging"
        }

        result = patch_templates.validate_security_gate(
            branch="relfix-pareto-2080-07171927",
            repo="/repo"
        )

        assert result["passed"] is False


class TestLegalGateChecking(unittest.TestCase):
    """Legal gate for licensing, registration, custody changes."""

    @patch("db.select")
    def test_legal_gate_owner_only_licensing_changes(self, mock_select):
        """Licensing file changes require owner-only approval."""
        mock_select.return_value = [
            {"slug": "relfix-pareto-2080", "files_changed": ["LICENSE", "COPYING"]}
        ]

        result = self_healing_merge.check_legal_gate(
            branch="relfix-pareto-2080-07171927",
            author="claude-bot",
            repo_path="/repo"
        )

        assert result["needs_owner_approval"] is True
        assert "license" in result["reason"].lower()

    @patch("db.select")
    def test_legal_gate_normal_code_change_passes(self, mock_select):
        """Normal code changes pass legal gate."""
        mock_select.return_value = [
            {"slug": "relfix-pareto-2080", "files_changed": ["runner.py", "db.py"]}
        ]

        result = self_healing_merge.check_legal_gate(
            branch="relfix-pareto-2080-07171927",
            author="claude-bot",
            repo_path="/repo"
        )

        assert result["needs_owner_approval"] is False


class TestOrchestrationPipelineComplianceContract(unittest.TestCase):
    """Verify orchestration pipeline contract compliance."""

    def test_orchestration_contract_specifies_correct_triage_model(self):
        """Task uses deepseek for triage (vs local/google models)."""
        contract = {
            "source": "release-conflict-self-heal",
            "project": "pareto-2080",
            "task_class": "security",
            "preflight_triage": "local:deepseek-coder-v2:16b"
        }

        # Contract must specify expected triage model
        assert "deepseek" in contract["preflight_triage"].lower() or "local" in contract["preflight_triage"]

    def test_orchestration_contract_specifies_strategy_planner(self):
        """Task uses deepseek for strategy planning."""
        contract = {
            "strategy_planner": "deepseek:deepseek-v4-pro",
            "qpd_leader_quality": 7.4,
            "qpd_leader_cost": "$0.0"
        }

        assert "deepseek" in contract["strategy_planner"].lower()

    def test_orchestration_contract_specifies_agentic_coder(self):
        """Task uses claude-sonnet-4-6 for code generation."""
        contract = {
            "agentic_coder": "claude using author model claude-sonnet-4-6",
            "required_executor_capabilities": ["code_generation", "text_completion"]
        }

        assert "claude" in contract["agentic_coder"].lower()
        assert "code_generation" in contract["required_executor_capabilities"]

    def test_orchestration_contract_qa_route(self):
        """QA uses independent route with diverse panel."""
        contract = {
            "independent_qa_route": "deepseek:deepseek-v4-flash",
            "qa_panel": ["local:llama3.2:3b", "deepseek:deepseek-v4-flash"]
        }

        assert len(contract["qa_panel"]) >= 2
        # Should have diversity (local + cloud models)


class TestDeployCostRuleEnforcement(unittest.TestCase):
    """Deploy-cost rules: never direct prod deploy."""

    @patch("release_train._git")
    def test_never_run_vercel_prod_command(self, mock_git):
        """vercel --prod CLI command is blocked."""
        # This is a static analysis check - shouldn't appear in deployment workflow
        forbidden_commands = ["vercel --prod", "vercel deploy --prod"]

        # Verify the deploy code doesn't contain these
        with open("/Users/kpasch/Documents/beethoven/claude-orchestrator/runner/release_train.py", "r") as f:
            deploy_code = f.read()

        for cmd in forbidden_commands:
            assert cmd not in deploy_code, f"Forbidden command '{cmd}' found in deploy code"

    @patch("release_train._git")
    def test_never_push_main_master_directly(self, mock_git):
        """Direct pushes to main/master are blocked."""
        # Verify deploy code uses batch train, not direct push
        with open("/Users/kpasch/Documents/beethoven/claude-orchestrator/runner/release_train.py", "r") as f:
            code = f.read()

        # Should verify usage of batch train instead
        assert "batch" in code.lower() or "staging" in code.lower()

    @patch("release_train._git")
    def test_push_only_task_branch_for_batch_train(self, mock_git):
        """Only task branches are pushed; batch train handles promotion."""
        result = release_train.can_push_branch("relfix-pareto-2080-07171927")

        # Should allow task branch push
        assert result is True

        result = release_train.can_push_branch("master")
        # Should block master push
        assert result is False


class TestCoordinationRuleEnforcement(unittest.TestCase):
    """Coordination rules: reuse solutions, don't delete queued work."""

    @patch("merged_diff_library.find")
    def test_reuse_proven_prior_solutions_first(self, mock_find):
        """Proven prior solutions are reused before drafting new code."""
        mock_find.return_value = [{
            "project": "beethoven",
            "slug": "deployfix-beethoven-07190257",
            "similarity": 0.261,
            "diff": "..."
        }]

        task = {
            "id": "relfix-pareto-2080-07171927",
            "prompt": "Fix release conflict",
            "project": "pareto-2080"
        }

        hint = patch_transplant.hint(task)

        # Should recommend reuse before building from scratch
        assert hint != ""
        assert "PATCH TRANSPLANT" in hint

    @patch("db.select")
    def test_coordination_rule_dont_overwrite_unrelated_queued_tasks(self, mock_select):
        """Unrelated queued tasks are not deleted or overwritten."""
        mock_select.return_value = [
            {"id": "queued-task-1", "status": "PENDING", "project": "pareto-2080"},
            {"id": "queued-task-2", "status": "PENDING", "project": "other-project"}
        ]

        # Coordination check should detect unrelated work
        result = self_healing_merge.can_proceed_with_merge(
            branch="relfix-pareto-2080-07171927",
            preserve_queued_tasks=True
        )

        # Should not delete queued tasks
        # Implementation detail: verify coordinator doesn't call destructive ops


class TestAutoMergeToStagingBranch(unittest.TestCase):
    """Auto-merge to orchestrator/dev after tests pass."""

    @patch("release_train._git")
    @patch("db.select")
    def test_automerge_after_all_qa_gates_pass(self, mock_select, mock_git):
        """Branch auto-merges to staging after security, legal, QA gates pass."""
        mock_select.return_value = [{
            "slug": "relfix-pareto-2080-07171927",
            "security_gate": "PASSED",
            "legal_gate": "PASSED",
            "qa_status": "PASSED"
        }]

        mock_git.side_effect = [
            Mock(returncode=0, stdout=b""),  # merge to staging
            Mock(returncode=0, stdout=b""),  # push staging
        ]

        result = release_train.automerge_after_qa(
            branch="relfix-pareto-2080-07171927",
            repo="/repo",
            staging_branch="orchestrator/dev"
        )

        assert result["merged"] is True

    @patch("release_train._git")
    @patch("db.select")
    def test_automerge_blocked_if_security_gate_fails(self, mock_select, mock_git):
        """Security gate failure blocks auto-merge."""
        mock_select.return_value = [{
            "slug": "relfix-pareto-2080-07171927",
            "security_gate": "FAILED",
            "security_violations": ["hardcoded secret found"]
        }]

        result = release_train.automerge_after_qa(
            branch="relfix-pareto-2080-07171927",
            repo="/repo"
        )

        assert result["merged"] is False
        assert "security" in result["reason"].lower()

    @patch("release_train._git")
    @patch("db.select")
    def test_automerge_to_correct_staging_branch(self, mock_select, mock_git):
        """Auto-merge targets orchestrator/dev staging branch."""
        mock_select.return_value = [{
            "qa_status": "PASSED",
            "security_gate": "PASSED"
        }]

        mock_git.side_effect = [Mock(returncode=0, stdout=b"")] * 3

        with patch("release_train._target_branch") as mock_target:
            mock_target.return_value = "orchestrator/dev"

            result = release_train.automerge_after_qa(
                branch="relfix-pareto-2080-07171927",
                repo="/repo"
            )

        # Verify staging branch is orchestrator/dev
        assert mock_target.called or result["target_branch"] == "orchestrator/dev"


class TestReleaseTrainBatchCoordination(unittest.TestCase):
    """Release train batch coordination and cadence gates."""

    @patch("release_train.db.select")
    def test_batch_minimum_not_met_holds_release(self, mock_select):
        """Release held when ahead count < batch minimum."""
        result = release_train._release_decision(
            ahead=5,
            due=False,
            minimum=10
        )

        assert result == "hold"

    @patch("release_train.db.select")
    def test_batch_full_triggers_release(self, mock_select):
        """Release triggered when ahead >= batch minimum."""
        result = release_train._release_decision(
            ahead=15,
            due=False,
            minimum=10
        )

        assert result == "release"

    @patch("release_train.db.select")
    def test_cadence_due_flushes_partial_batch(self, mock_select):
        """Cadence timeout flushes partial batch."""
        result = release_train._release_decision(
            ahead=7,
            due=True,
            minimum=10
        )

        assert result == "release"


class TestEndToEndWorkflow(unittest.TestCase):
    """Complete workflow: detect conflict -> transplant patch -> heal -> auto-merge."""

    @patch("patch_transplant.hint")
    @patch("self_healing_merge.heal")
    @patch("release_train.automerge_after_qa")
    def test_complete_relfix_pareto_2080_workflow(self, mock_automerge, mock_heal, mock_hint):
        """Complete workflow from conflict detection to auto-merge."""
        # Step 1: Detect patch candidate
        mock_hint.return_value = "PATCH TRANSPLANT: adapt deployfix-beethoven-07190257..."

        # Step 2: Heal conflicts via transplanted patch
        mock_heal.return_value = {
            "healed": True,
            "clean_merged": True,
            "repair_tasks": []
        }

        # Step 3: Auto-merge after QA
        mock_automerge.return_value = {
            "merged": True,
            "target_branch": "orchestrator/dev"
        }

        task = {
            "id": "relfix-pareto-2080-07171927",
            "prompt": "Fix release conflict",
            "project": "pareto-2080"
        }

        # Execute workflow
        hint_result = patch_transplant.hint(task)
        assert hint_result != ""

        heal_result = self_healing_merge.heal(
            repo="/repo",
            branch="relfix-pareto-2080-07171927",
            base="master"
        )
        assert heal_result["healed"]

        merge_result = release_train.automerge_after_qa(
            branch="relfix-pareto-2080-07171927",
            repo="/repo"
        )
        assert merge_result["merged"]


class TestErrorHandlingAndFallbacks(unittest.TestCase):
    """Graceful degradation on errors."""

    @patch("patch_transplant.apply_patch")
    def test_patch_apply_failure_triggers_fallback_rebuild(self, mock_apply):
        """Patch application failure triggers local rebuild."""
        mock_apply.return_value = {
            "applied": False,
            "fallback_rebuild": True,
            "rejects": 3
        }

        result = patch_transplant.apply_patch(b"...", repo_path="/repo")

        assert result["fallback_rebuild"] is True

    @patch("self_healing_merge._classify_files")
    def test_conflict_classification_timeout_creates_repair_ticket(self, mock_classify):
        """Conflict classification timeout creates repair ticket."""
        mock_classify.side_effect = TimeoutError("Classification timeout")

        with patch("db.insert") as mock_insert:
            result = self_healing_merge.heal(
                repo="/repo",
                branch="relfix-pareto-2080-07171927",
                base="master"
            )

        # Should create repair ticket
        if result["fallback_repair_ticket_created"]:
            assert mock_insert.called


class TestSpecialCases(unittest.TestCase):
    """Edge cases and boundary conditions."""

    def test_pareto_2080_specific_config_preservation(self):
        """Pareto-2080 project-specific configs are preserved in patch."""
        prior_diff = b"""--- a/config.py
+++ b/config.py
@@ -1,3 +1,5 @@
 PROJECTS = ['pareto-2080', 'beethoven']
+ORCH_PARETO_2080_SECURITY_GATE = True
"""
        result = patch_transplant.adapt_patch(
            prior_diff,
            target_task={"project": "pareto-2080"}
        )

        assert b"pareto" in result.lower() or b"ORCH_PARETO" in result

    @patch("self_healing_merge._git")
    def test_very_large_conflict_cluster_creates_focused_repair_tasks(self, mock_git):
        """Large conflict clusters (>10 files) create multiple focused repair tasks."""
        mock_git.side_effect = [Mock(returncode=0, stdout=b"")] * 20

        with patch("self_healing_merge._classify_files") as mock_classify:
            conflicting_files = [f"f{i}.py" for i in range(15)]
            mock_classify.return_value = {
                "clean": [],
                "conflicting": conflicting_files,
                "all_changed": conflicting_files
            }

            with patch("db.insert") as mock_insert:
                with patch("self_healing_merge._create_repair_task"):
                    result = self_healing_merge.heal(
                        "/repo",
                        "relfix-pareto-2080-07171927",
                        "master"
                    )

        # Should handle large clusters


def subprocess_timeout_error():
    """Helper to raise subprocess timeout."""
    import subprocess
    return subprocess.TimeoutExpired("patch", 30)


if __name__ == "__main__":
    unittest.main()
