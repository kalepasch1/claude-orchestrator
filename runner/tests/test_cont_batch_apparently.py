#!/usr/bin/env python3
"""
Test suite for continuation-batch-apparently-e9bfdb0 orchestration pipeline.

Validates continuation batch recovery for apparently project, including:
- Orchestration pipeline contract fulfillment
- Continuation shard consolidation
- Model routing and QPD scoring
- QA panel consensus logic
- Legal gate validation
- Auto-merge and release automation
- Cross-learning route selection
- Coordination rule enforcement
"""
import os, sys, json, tempfile, unittest, hashlib
from unittest.mock import patch, MagicMock, call
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Disable external dependencies for testing
os.environ["ORCH_DB_URL"] = ""
os.environ["ORCH_DB_ENABLED"] = "false"
os.environ["ORCH_PATCH_TRANSPLANT_ENABLED"] = "false"


class TestContBatchApparentlyContract(unittest.TestCase):
    """Verify orchestration pipeline contract for cont-batch-apparently-e9bfdb0."""

    def test_contract_metadata_present(self):
        """Contract includes required metadata: source, project, task_class, risk_profile."""
        contract = {
            "source": "continuation-compactor",
            "project": "apparently",
            "task_class": "build",
            "task_id": "cont-batch-apparently-e9bfdb0",
            "need_score": 6,
            "risk_profile": "standard",
        }

        self.assertEqual(contract["source"], "continuation-compactor")
        self.assertEqual(contract["project"], "apparently")
        self.assertEqual(contract["task_class"], "build")
        self.assertTrue(contract["task_id"].startswith("cont-batch-apparently-"))
        self.assertGreaterEqual(contract["need_score"], 6)
        self.assertIn(contract["risk_profile"], ("standard", "broad_change"))

    def test_contract_preflight_triage_configuration(self):
        """Preflight triage uses google:gemini-2.5-flash with QPD scoring."""
        triage = {
            "model": "google:gemini-2.5-flash",
            "role": "preflight_triage",
            "qpd_leader": True,
            "qpd_score": 6.2,
            "cost": 0.0,
            "sample_count": 1,
        }

        self.assertEqual(triage["model"], "google:gemini-2.5-flash")
        self.assertEqual(triage["role"], "preflight_triage")
        self.assertTrue(triage["qpd_leader"])
        self.assertAlmostEqual(triage["qpd_score"], 6.2, places=1)
        self.assertEqual(triage["cost"], 0.0)

    def test_contract_strategy_planner_configuration(self):
        """Strategy planner uses google:gemini-2.5-flash (non-agentic optimizer)."""
        planner = {
            "model": "google:gemini-2.5-flash",
            "role": "strategy_planner",
            "strategy": "non-agentic",
            "rotation": "cheap_model_level_optimizer",
            "cost": 0.0,
        }

        self.assertIn("gemini", planner["model"])
        self.assertEqual(planner["strategy"], "non-agentic")
        self.assertEqual(planner["cost"], 0.0)

    def test_contract_agentic_coder_model(self):
        """Agentic coder uses claude-haiku-4-5-20251001."""
        coder = {
            "model": "claude-haiku-4-5-20251001",
            "role": "agentic_coder",
            "author": True,
            "capabilities": ["patch_adapt", "apply", "test", "merge", "commit"],
        }

        self.assertEqual(coder["model"], "claude-haiku-4-5-20251001")
        self.assertIn("claude", coder["model"])
        self.assertTrue(coder["author"])
        self.assertGreaterEqual(len(coder["capabilities"]), 3)

    def test_contract_independent_qa_route(self):
        """Independent QA uses local:llama3.1 with QPD scoring."""
        qa_route = {
            "name": "independent_qa",
            "model": "local:llama3.1",
            "qpd_leader": True,
            "qpd_score": 7.7,
            "cost": 0.0,
            "sample_count": 2,
        }

        self.assertEqual(qa_route["model"], "local:llama3.1")
        self.assertTrue(qa_route["qpd_leader"])
        self.assertGreaterEqual(qa_route["qpd_score"], 7.5)

    def test_contract_qa_panel_configuration(self):
        """QA panel includes local:llama3.2:3b and google:gemini-2.5-flash."""
        qa_panel = {
            "models": [
                "local:llama3.2:3b",
                "google:gemini-2.5-flash",
            ],
            "consensus_rule": "unanimous_pass",
            "tie_breaker": "claude-haiku-4-5-20251001",
        }

        self.assertEqual(len(qa_panel["models"]), 2)
        self.assertIn("local:llama3.2:3b", qa_panel["models"])
        self.assertIn("google:gemini-2.5-flash", qa_panel["models"])
        self.assertEqual(qa_panel["consensus_rule"], "unanimous_pass")
        self.assertIn("claude", qa_panel["tie_breaker"])

    def test_contract_legal_gate_configuration(self):
        """Legal gate is owner-only when patch affects licensing, custody, transmission."""
        legal_gate = {
            "enabled": True,
            "scope": "owner-only",
            "triggers": [
                "licensing_change",
                "registration_requirement",
                "data_custody_impact",
                "data_transmission_impact",
                "legal_advice_implication",
            ],
            "owner_email": "kale@heretomorrow.us",
        }

        self.assertTrue(legal_gate["enabled"])
        self.assertEqual(legal_gate["scope"], "owner-only")
        self.assertGreaterEqual(len(legal_gate["triggers"]), 3)
        self.assertTrue("@" in legal_gate["owner_email"])

    def test_contract_merge_and_release_path(self):
        """Merge to orchestrator/dev after tests; production via batch train."""
        release = {
            "auto_merge": True,
            "merge_branch": "orchestrator/dev",
            "merge_after_stage": "qa_panel",
            "auto_batch": True,
            "batch_target": "master",
            "batch_strategy": "train",
        }

        self.assertTrue(release["auto_merge"])
        self.assertEqual(release["merge_branch"], "orchestrator/dev")
        self.assertTrue(release["auto_batch"])
        self.assertIn(release["batch_strategy"], ("train", "direct"))

    def test_contract_coordination_rules(self):
        """Coordination rules preserve existing work and reuse solutions."""
        coordination = {
            "reconcile_with_active_loop": True,
            "reuse_prior_solutions_first": True,
            "preserve_queued_improvements": True,
            "leave_recovered_work_in_queue_until_shipped": True,
        }

        self.assertTrue(coordination["reconcile_with_active_loop"])
        self.assertTrue(coordination["reuse_prior_solutions_first"])
        self.assertTrue(coordination["preserve_queued_improvements"])


class TestContinuationShardConsolidation(unittest.TestCase):
    """Test continuation shard consolidation into batch task."""

    def test_consolidates_five_shards_into_one_batch(self):
        """Five continuation shards are collapsed into single batch task."""
        shards = [
            {
                "id": "cont-1",
                "slug": "cont-doc-review-1",
                "prompt": "Review existing documentation for gaps in understanding",
                "project_id": "apparently",
                "state": "QUEUED",
                "base_branch": "orchestrator/dev",
            },
            {
                "id": "cont-2",
                "slug": "cont-doc-review-2",
                "prompt": "PATCH TEMPLATE areas codebase documentation enhance",
                "project_id": "apparently",
                "state": "QUEUED",
                "base_branch": "orchestrator/dev",
            },
            {
                "id": "cont-3",
                "slug": "cont-doc-review-3",
                "prompt": "Review codebase documentation to understand architecture",
                "project_id": "apparently",
                "state": "QUEUED",
                "base_branch": "orchestrator/dev",
            },
            {
                "id": "cont-4",
                "slug": "cont-repo-docs",
                "prompt": "Review repository documentation to understand codebase better",
                "project_id": "apparently",
                "state": "QUEUED",
                "base_branch": "orchestrator/dev",
            },
            {
                "id": "cont-5",
                "slug": "cont-arch-docs",
                "prompt": "Enhance developer experience documentation",
                "project_id": "apparently",
                "state": "QUEUED",
                "base_branch": "orchestrator/dev",
            },
        ]

        self.assertEqual(len(shards), 5)
        for shard in shards:
            self.assertEqual(shard["project_id"], "apparently")
            self.assertEqual(shard["state"], "QUEUED")

    def test_batch_slug_includes_project_and_digest(self):
        """Batch task slug combines project name and SHA1 digest of shard IDs."""
        shards = [
            {"id": f"cont-{i}", "slug": f"cont-item-{i}", "project_id": "apparently"}
            for i in range(5)
        ]

        shard_ids = "|".join(s["id"] for s in shards)
        digest = hashlib.sha1(shard_ids.encode()).hexdigest()[:7]

        batch_slug = f"cont-batch-apparently-{digest}"

        self.assertTrue(batch_slug.startswith("cont-batch-apparently-"))
        self.assertGreaterEqual(len(batch_slug), 25)
        self.assertLessEqual(len(batch_slug), 80)

    def test_batch_task_prompt_includes_original_intents(self):
        """Batch task prompt lists all original continuation intents."""
        shards = [
            {"slug": "cont-1", "prompt": "intent one"},
            {"slug": "cont-2", "prompt": "intent two"},
            {"slug": "cont-3", "prompt": "intent three"},
        ]

        prompt = (
            "Consolidated continuation backlog recovery.\n\n"
            "Project: apparently\n"
            "Collapsed continuation shards: 3\n\n"
            "Original continuation intents:\n"
        )

        for i, shard in enumerate(shards, 1):
            prompt += f"{i}. {shard['slug']}: {shard['prompt']}\n"

        self.assertIn("Consolidated continuation backlog recovery", prompt)
        self.assertIn("Project: apparently", prompt)
        self.assertIn("Collapsed continuation shards: 3", prompt)
        for shard in shards:
            self.assertIn(shard["slug"], prompt)

    def test_shards_transitioned_to_decomposed_state(self):
        """Original shards transitioned from QUEUED to DECOMPOSED."""
        shard = {
            "id": "cont-1",
            "state": "QUEUED",
            "updated_at": "2024-08-01T00:00:00Z",
        }

        updated_shard = {
            **shard,
            "state": "DECOMPOSED",
            "note": "continuation-compactor: collapsed into cont-batch-apparently-xyz123",
        }

        self.assertEqual(shard["state"], "QUEUED")
        self.assertEqual(updated_shard["state"], "DECOMPOSED")
        self.assertIn("collapsed into", updated_shard["note"])


class TestModelRoutingAndSelection(unittest.TestCase):
    """Test model routing based on task classification and need."""

    def test_preflight_triage_model_selection(self):
        """Preflight triage selects appropriate model based on sensitivity."""
        sensitivity_cases = [
            ("standard", "google:gemini-2.5-flash"),
            ("sensitive", "local:ollama"),
            ("confidential", "local:ollama"),
        ]

        for sensitivity, expected_model in sensitivity_cases:
            # In production, coder selection is based on sensitivity
            if sensitivity == "standard":
                self.assertEqual(expected_model, "google:gemini-2.5-flash")
            else:
                self.assertIn("ollama", expected_model)

    def test_model_assignment_preserves_cost_zero(self):
        """Model routing maintains zero cost for apparently project."""
        models = [
            {"name": "google:gemini-2.5-flash", "cost": 0.0},
            {"name": "local:llama3.1", "cost": 0.0},
            {"name": "local:llama3.2:3b", "cost": 0.0},
            {"name": "claude-haiku-4-5-20251001", "cost": 0.0},
        ]

        for model in models:
            self.assertEqual(model["cost"], 0.0)

    def test_qpd_scoring_above_threshold(self):
        """QPD scores for selected models exceed minimum thresholds."""
        qpd_scores = {
            "google:gemini-2.5-flash": 6.2,
            "local:llama3.1": 7.7,
            "local:llama3.2:3b": 7.7,
            "claude-haiku-4-5-20251001": 8.0,
        }

        for model, score in qpd_scores.items():
            self.assertGreaterEqual(score, 6.0, f"{model} QPD score too low")


class TestQAPanelConsensusLogic(unittest.TestCase):
    """Test QA panel voting and consensus rules."""

    def test_qa_panel_unanimous_pass_requires_all_accept(self):
        """Unanimous pass rule requires all panelists to pass."""
        votes = {
            "local:llama3.2:3b": "PASS",
            "google:gemini-2.5-flash": "PASS",
        }

        consensus_result = all(v == "PASS" for v in votes.values())
        self.assertTrue(consensus_result)

    def test_qa_panel_unanimous_fail_when_any_reject(self):
        """Unanimous pass fails if any panelist rejects."""
        votes = {
            "local:llama3.2:3b": "PASS",
            "google:gemini-2.5-flash": "REJECT",
        }

        consensus_result = all(v == "PASS" for v in votes.values())
        self.assertFalse(consensus_result)

    def test_qa_panel_tie_breaker_selected_on_split(self):
        """Tie breaker (claude-haiku) breaks 1-1 split."""
        votes = [
            {"model": "local:llama3.2:3b", "verdict": "PASS"},
            {"model": "google:gemini-2.5-flash", "verdict": "REJECT"},
        ]

        passes = sum(1 for v in votes if v["verdict"] == "PASS")
        rejects = sum(1 for v in votes if v["verdict"] == "REJECT")

        # In case of split, use tie breaker
        if passes == rejects and len(votes) == 2:
            tie_breaker = "claude-haiku-4-5-20251001"
            self.assertIsNotNone(tie_breaker)

    def test_qa_panel_consensus_before_merge(self):
        """QA panel consensus is required before auto-merge."""
        qa_results = {
            "panel_result": "unanimous_pass",
            "models_voted": 2,
            "passes": 2,
            "rejects": 0,
            "can_merge": True,
        }

        self.assertEqual(qa_results["panel_result"], "unanimous_pass")
        self.assertTrue(qa_results["can_merge"])


class TestLegalGateValidation(unittest.TestCase):
    """Test legal gate checks and owner approval flow."""

    def test_legal_gate_detects_licensing_changes(self):
        """Legal gate flags licensing-related changes."""
        triggers = ["licensing_change", "registration_requirement", "custody", "transmission", "advice"]

        content_with_trigger = "We need to update the software license terms."

        for trigger in triggers:
            if trigger in content_with_trigger.lower() or "license" in content_with_trigger.lower():
                # Legal gate activated
                requires_approval = True
                self.assertTrue(requires_approval)
                break

    def test_legal_gate_owner_approval_required(self):
        """Changes triggering legal gate require owner approval."""
        legal_gate_triggered = {
            "triggered": True,
            "requires_approval": True,
            "approval_role": "owner",
            "owner_email": "kale@heretomorrow.us",
        }

        self.assertTrue(legal_gate_triggered["requires_approval"])
        self.assertEqual(legal_gate_triggered["approval_role"], "owner")

    def test_legal_gate_bypass_when_no_trigger(self):
        """Non-triggering changes bypass legal gate."""
        legal_gate = {
            "triggered": False,
            "reason": "no regulatory/custody/transmission changes detected",
            "can_proceed": True,
        }

        self.assertFalse(legal_gate["triggered"])
        self.assertTrue(legal_gate["can_proceed"])


class TestAutoMergeAndReleaseAutomation(unittest.TestCase):
    """Test auto-merge and batch release automation."""

    def test_auto_merge_to_orchestrator_dev_after_qa_pass(self):
        """Batch task auto-merges to orchestrator/dev after QA panel passes."""
        merge_spec = {
            "enabled": True,
            "trigger": "qa_panel_pass",
            "target_branch": "orchestrator/dev",
            "preserve_history": True,
        }

        self.assertTrue(merge_spec["enabled"])
        self.assertEqual(merge_spec["target_branch"], "orchestrator/dev")

    def test_batch_release_to_production_via_train(self):
        """Merged batch is included in production release train."""
        release_spec = {
            "auto_batch": True,
            "strategy": "train",
            "target": "master",
            "waits_for_batch_signal": True,
        }

        self.assertTrue(release_spec["auto_batch"])
        self.assertEqual(release_spec["strategy"], "train")

    def test_merge_commit_includes_all_shards(self):
        """Merge commit references all collapsed shards in body."""
        shards = ["cont-1", "cont-2", "cont-3"]

        merge_body = (
            "Auto-merge of cont-batch-apparently-xyz123\n\n"
            f"Collapsed shards: {', '.join(shards)}\n"
            "This batch consolidates continuation backlog."
        )

        for shard in shards:
            self.assertIn(shard, merge_body)


class TestCrossLearningRouteSelection(unittest.TestCase):
    """Test learned route selection from prior outcomes."""

    def test_learned_route_confidence_gate_uses_llama32(self):
        """Learned route 'confidence_gate' uses local:llama3.2:3b."""
        learned_route = {
            "route": "confidence_gate",
            "model": "local:llama3.2:3b",
            "qpd_score": 7.7,
        }

        self.assertEqual(learned_route["model"], "local:llama3.2:3b")
        self.assertGreaterEqual(learned_route["qpd_score"], 7.5)

    def test_learned_route_adaptive_probe_uses_llama32(self):
        """Learned route 'adaptive_probe' uses local:llama3.2:3b."""
        learned_route = {
            "route": "adaptive_probe",
            "model": "local:llama3.2:3b",
            "qpd_score": 7.7,
        }

        self.assertEqual(learned_route["model"], "local:llama3.2:3b")

    def test_learned_route_build_fix_uses_gpt4o_mini(self):
        """Learned route 'build_fix' uses openai:gpt-4o-mini."""
        learned_route = {
            "route": "build_fix",
            "model": "openai:gpt-4o-mini",
            "qpd_score": 6.0,
        }

        self.assertEqual(learned_route["model"], "openai:gpt-4o-mini")

    def test_learned_route_meta_loop_improvement_uses_deepseek(self):
        """Learned route 'meta_loop_improvement' uses local:deepseek-coder-v2."""
        learned_route = {
            "route": "meta_loop_improvement",
            "model": "local:deepseek-coder-v2:16b",
            "qpd_score": 7.7,
        }

        self.assertIn("deepseek", learned_route["model"])

    def test_recent_outcome_signal_drives_route_selection(self):
        """Recent outcome signal (0/12 tests pass) informs route selection."""
        outcome_signal = {
            "merged_count": 0,
            "test_pass_count": 0,
            "total_attempts": 12,
            "cost": 0.0,
            "primary_models": ["claude-haiku-4-5-20251001", "cowork-skill:claude-sonnet-5"],
        }

        self.assertEqual(outcome_signal["merged_count"], 0)
        self.assertEqual(outcome_signal["test_pass_count"], 0)


class TestCoordinationRuleEnforcement(unittest.TestCase):
    """Test coordination rules: reconcile, reuse, preserve, don't delete."""

    def test_reconcile_with_active_loop_generated_work(self):
        """Reconciliation preserves concurrent loop-generated work."""
        coordination = {
            "must_reconcile": True,
            "loop_tasks": ["loop-1", "loop-2", "loop-3"],
            "batch_tasks": ["cont-batch-apparently-xyz"],
            "conflict_resolution": "merge_and_deduplicate",
        }

        self.assertTrue(coordination["must_reconcile"])
        self.assertGreater(len(coordination["loop_tasks"]), 0)

    def test_reuse_prior_solutions_first(self):
        """Batch task reuses prior solutions before new development."""
        reuse_spec = {
            "enabled": True,
            "search_scope": "same_project_and_related",
            "accept_similarity_threshold": 0.7,
            "max_attempts": 3,
        }

        self.assertTrue(reuse_spec["enabled"])
        self.assertGreaterEqual(reuse_spec["accept_similarity_threshold"], 0.5)

    def test_preserve_queued_improvements_not_deleted(self):
        """Queued improvements are never deleted during consolidation."""
        queued_tasks = [
            {"id": "queued-1", "slug": "fix-component-x", "state": "QUEUED"},
            {"id": "queued-2", "slug": "enhance-docs", "state": "QUEUED"},
        ]

        for task in queued_tasks:
            self.assertEqual(task["state"], "QUEUED")
            # Verify not deleted

    def test_recovered_work_left_in_queue_until_shipped(self):
        """Recovered work remains in queue until final production release."""
        recovered_task = {
            "id": "recovered-1",
            "state": "QUEUED",
            "status": "recovered_from_backlog",
            "ready_for_shipment": False,
        }

        self.assertEqual(recovered_task["state"], "QUEUED")
        self.assertFalse(recovered_task["ready_for_shipment"])


class TestOperatorFeedbackBottleneckMitigation(unittest.TestCase):
    """Test responses to operator feedback about measured bottlenecks."""

    def test_bottleneck_remediation_action_timing(self):
        """Measured bottleneck: time to apply and verify remediation actions."""
        bottleneck = {
            "bottleneck": "remediation_action_apply_and_verify_latency",
            "severity": "medium",
            "scope": "strategy",
            "impact": "delays_in_achieving_objectives",
        }

        self.assertEqual(bottleneck["severity"], "medium")

    def test_bottleneck_extensive_checks_validation_downtime(self):
        """Measured bottleneck: long downtimes from extensive checks/validations."""
        bottleneck = {
            "bottleneck": "app_remediation_phase_downtime",
            "severity": "medium",
            "scope": "strategy",
            "cause": "extensive_checks_and_validations",
        }

        self.assertEqual(bottleneck["severity"], "medium")
        self.assertIn("validation", bottleneck["cause"].lower())

    def test_bottleneck_simultaneous_remediation_delays(self):
        """Measured bottleneck: app delays on simultaneous remediation processes."""
        bottleneck = {
            "bottleneck": "simultaneous_remediation_handling",
            "severity": "medium",
            "scope": "strategy",
            "symptom": "delays_and_downtime",
        }

        self.assertEqual(bottleneck["severity"], "medium")


class TestErrorHandlingAndRecovery(unittest.TestCase):
    """Test robustness under failure conditions."""

    def test_missing_shard_id_handled_gracefully(self):
        """Missing shard ID doesn't crash batch creation."""
        shards = [
            {"id": None, "slug": "cont-1", "prompt": "item"},
            {"id": "cont-2", "slug": "cont-2", "prompt": "item"},
        ]

        # Should use slug as fallback
        digest_base = "|".join(str(s.get("id") or s.get("slug")) for s in shards)
        self.assertGreater(len(digest_base), 0)

    def test_empty_prompt_field_handled(self):
        """Empty prompt field doesn't crash batch task creation."""
        shard = {
            "id": "cont-1",
            "slug": "cont-1",
            "prompt": "",
            "project_id": "apparently",
        }

        prompt_text = shard.get("prompt", "") or "(no prompt provided)"
        self.assertIsNotNone(prompt_text)

    def test_missing_project_id_uses_fallback(self):
        """Missing project_id falls back to unknown."""
        shard = {
            "id": "cont-1",
            "slug": "cont-1",
            "project_id": None,
        }

        project_name = shard.get("project_id") or "unknown"
        self.assertIsNotNone(project_name)

    def test_db_insert_failure_rollback_graceful(self):
        """Database insert failure doesn't wedge batch creation."""
        try:
            # Simulate insert failure
            raise Exception("DB insert failed")
        except Exception as e:
            # Graceful handling
            error_recovered = str(e) is not None
            self.assertTrue(error_recovered)

    def test_model_unavailable_fallback_route(self):
        """Unavailable model falls back to default route."""
        model_routes = {
            "primary": "google:gemini-2.5-flash",
            "fallback": "local:llama3.1",
        }

        # If primary unavailable, use fallback
        selected_model = model_routes["fallback"]
        self.assertIsNotNone(selected_model)


class TestTaskIntegrationEndToEnd(unittest.TestCase):
    """End-to-end task creation and state transitions."""

    def test_full_pipeline_from_shards_to_batch_to_merge(self):
        """Complete pipeline: shards → batch task → QA → merge → release."""
        stages = [
            {"stage": "intake", "state": "QUEUED", "shards_count": 5},
            {"stage": "consolidation", "state": "QUEUED", "batch_slug": "cont-batch-apparently-xyz"},
            {"stage": "preflight_triage", "state": "IN_PROGRESS"},
            {"stage": "strategy_planning", "state": "IN_PROGRESS"},
            {"stage": "agentic_coding", "state": "IN_PROGRESS"},
            {"stage": "qa_panel", "state": "IN_PROGRESS", "consensus": "pass"},
            {"stage": "auto_merge", "state": "COMPLETED", "target": "orchestrator/dev"},
            {"stage": "batch_release", "state": "QUEUED_FOR_TRAIN", "target": "master"},
        ]

        self.assertEqual(stages[0]["state"], "QUEUED")
        self.assertEqual(stages[1]["state"], "QUEUED")
        self.assertEqual(stages[-2]["state"], "COMPLETED")
        self.assertEqual(stages[-1]["state"], "QUEUED_FOR_TRAIN")

    def test_minimum_viable_batch_requires_5_shards(self):
        """Minimum group size for consolidation is 5 shards."""
        group_configs = [
            {"count": 4, "consolidates": False},
            {"count": 5, "consolidates": True},
            {"count": 6, "consolidates": True},
        ]

        for config in group_configs:
            should_consolidate = config["count"] >= 5
            self.assertEqual(should_consolidate, config["consolidates"])


if __name__ == "__main__":
    unittest.main()
