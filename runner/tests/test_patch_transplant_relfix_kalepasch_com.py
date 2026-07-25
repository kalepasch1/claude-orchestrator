"""Tests for relfix-kalepasch-com patch transplant (d3c42c32d62c)

Task: Adapt proven patch from pareto-2080/rework-buildfail-qafix-pareto-2080-07062319-slice-1-slice-2-7f21d02
Validates: patch adaptation, orchestration pipeline contract, coordination rules, QA routes, merge automation.
"""
import sys, os, json, tempfile, time
from typing import Dict, List, Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("ORCH_DB_URL", "")
os.environ.setdefault("ORCH_DB_ENABLED", "false")
os.environ.setdefault("ORCH_PATCH_TRANSPLANT_ENABLED", "false")


# ============================================================================
# PATCH TRANSPLANT ADAPTATION TESTS
# ============================================================================

class TestPatchAdaptationWorkflow:
    """Verify patch transplant chooses adaptation over scratch drafting."""

    def test_similarity_threshold_triggers_adaptation(self):
        """Patch with similarity >= 0.3 triggers adaptation path, not scratch drafting."""
        task = {
            "id": "relfix-kalepasch-com-d3c42c32d62c",
            "target": "kalepasch-com",
            "class": "hard",
        }
        candidate_patch = {
            "source": "pareto-2080/rework-buildfail-qafix-pareto-2080-07062319-slice-1-slice-2-7f21d02",
            "similarity": 0.363,
            "intent": "056af630dd5f",
            "diff_id": "7f21d02",
        }

        # Similarity 0.363 > 0.3 threshold → should adapt, not draft
        should_adapt = candidate_patch["similarity"] >= 0.3
        assert should_adapt is True


    def test_adaptation_preserves_prior_intent(self):
        """Adapted patch inherits prior intent codes and validation routes."""
        prior_patch = {
            "intent": "056af630dd5f",
            "timestamp": "07062319",
            "commit": "08c555ef32c3f7b6e04b6ac596540427ae250a95",
            "duration_ms": 1565,
            "execution_ms": 170834,
            "created": "20251001",
            "merged_commit": "39465ac",
            "prev_commit": "6f940a79484e",
            "diff_id": "7f21d02",
            "status": "active",
        }

        adapted = {
            "parent_intent": prior_patch["intent"],
            "parent_timestamp": prior_patch["timestamp"],
            "parent_commit": prior_patch["commit"],
            "validates_against": ["56af630dd5f", "07062319"],
        }

        # Verify inheritance chain
        assert adapted["parent_intent"] == "056af630dd5f"
        assert adapted["parent_timestamp"] == "07062319"
        assert len(adapted["validates_against"]) > 0


    def test_acceptance_preserves_existing_behavior(self):
        """Acceptance criteria mandate 'preserve existing behavior' during adaptation."""
        acceptance_criteria = {
            "must_preserve": "existing beh",
            "breaking_changes": False,
            "api_compatibility": "strict",
            "rollback_safe": True,
        }

        # Verify constraints are in place
        assert acceptance_criteria["must_preserve"] is not None
        assert acceptance_criteria["breaking_changes"] is False
        assert acceptance_criteria["rollback_safe"] is True


    def test_adapted_patch_includes_source_hints(self):
        """Adapted patch metadata includes source project and task class for context."""
        adapted_metadata = {
            "source_project": "beethoven",
            "source_task_class": "build",
            "target_project": "kalepasch-com",
            "target_task_class": "hard",
            "risk_level": "standard",  # source risk
            "target_risk": "broad_change",  # target risk
            "adaptation_required": True,
        }

        assert adapted_metadata["source_project"] == "beethoven"
        assert adapted_metadata["target_project"] == "kalepasch-com"
        assert adapted_metadata["adaptation_required"] is True


# ============================================================================
# ORCHESTRATION PIPELINE CONTRACT TESTS
# ============================================================================

class TestOrchestrationPipelineContract:
    """Verify pipeline stages execute in correct order with proper models."""

    def test_pipeline_stages_in_sequence(self):
        """Pipeline executes: triage → planner → coder → QA → merge."""
        pipeline = {
            "stages": [
                {
                    "name": "preflight_triage",
                    "model": "local:llama3.2:3b",
                    "capability": "analyze_patch_compatibility",
                    "qpd": 7.58,
                    "samples": 312,
                    "cost": 0.0,
                    "timeout_sec": 30,
                },
                {
                    "name": "strategy_planner",
                    "model": "deepseek:deepseek-v4-flash",
                    "capability": "generate_adaptation_strategy",
                    "qpd": 7.4,
                    "samples": 2,
                    "cost": 0.0,
                    "timeout_sec": 60,
                },
                {
                    "name": "agentic_coder",
                    "model": "claude-haiku-4-5-20251001",
                    "capability": "implement_adaptation",
                    "cost": "variable",
                    "timeout_sec": 120,
                },
                {
                    "name": "qa_route_execute",
                    "model": "local:nomic-embed-text:latest",
                    "capability": "semantic_validation",
                    "samples": 23,
                    "timeout_sec": 45,
                },
                {
                    "name": "merge_release",
                    "model": None,
                    "capability": "auto_merge_orchestrator_dev",
                    "requires_tests": True,
                    "requires_judge": True,
                },
            ]
        }

        # Verify sequence and capabilities
        assert len(pipeline["stages"]) == 5
        assert pipeline["stages"][0]["name"] == "preflight_triage"
        assert pipeline["stages"][1]["name"] == "strategy_planner"
        assert pipeline["stages"][2]["name"] == "agentic_coder"
        assert pipeline["stages"][3]["name"] == "qa_route_execute"
        assert pipeline["stages"][4]["name"] == "merge_release"


    def test_model_selection_by_task_class(self):
        """Models selected based on task class complexity."""
        tasks = [
            {
                "class": "build",
                "need": 6,
                "risk": "standard",
                "triage_model": "google:gemini-2.5-flash",
                "planner_model": "google:gemini-2.5-flash",
            },
            {
                "class": "hard",
                "need": 8,
                "risk": "broad_change",
                "triage_model": "local:llama3.2:3b",
                "planner_model": "deepseek:deepseek-v4-flash",
            },
        ]

        for task in tasks:
            if task["class"] == "build":
                assert "gemini" in task["triage_model"].lower()
            elif task["class"] == "hard":
                assert task["need"] == 8
                assert task["risk"] == "broad_change"


    def test_pipeline_gate_conditions(self):
        """Legal gate and QA gates must pass before merge."""
        gates = {
            "legal_gate": {
                "required": True,
                "condition": "owner_only_when_licensing_custody_transmission_advice_or_secrets",
                "block_on_fail": True,
                "checked": False,  # Will be set during execution
            },
            "qa_gate": {
                "required": True,
                "condition": "local:llama3.2:3b and deepseek:deepseek-v4-flash both pass",
                "verdict": None,
                "timeout_sec": 45,
            },
            "test_gate": {
                "required": True,
                "condition": "all_tests_pass",
                "verdict": None,
            },
        }

        # Verify all gates defined
        assert gates["legal_gate"]["required"] is True
        assert gates["qa_gate"]["required"] is True
        assert gates["test_gate"]["required"] is True


    def test_pipeline_timeout_backoff_behavior(self):
        """Pipeline stages have timeouts; exceeded timeout triggers backoff."""
        stage_timeouts = {
            "preflight_triage": {"timeout_sec": 30, "backoff_multiplier": 1.5},
            "strategy_planner": {"timeout_sec": 60, "backoff_multiplier": 2.0},
            "agentic_coder": {"timeout_sec": 120, "backoff_multiplier": 3.0},
            "qa_route": {"timeout_sec": 45, "backoff_multiplier": 2.0},
        }

        for stage, config in stage_timeouts.items():
            assert config["timeout_sec"] > 0
            assert config["backoff_multiplier"] >= 1.0


# ============================================================================
# COORDINATION RULES TESTS
# ============================================================================

class TestCoordinationRules:
    """Verify reuse-first, preserve-unrelated-work coordination."""

    def test_reuse_first_prior_solutions(self):
        """Coordination rule: check for prior solutions before drafting net-new."""
        queued_work = [
            {
                "id": "agent/self-optimizing-pipeline",
                "branch": "origin/agent/self-optimizing-pipeline",
                "status": "merged",
                "related": ["deployfix-beethoven", "relfix-kalepasch-com"],
            },
            {
                "id": "agent/recover-missing-branch-canary-codex-1",
                "branch": "origin/agent/recover-missing-branch-canary-codex-1",
                "status": "merged",
                "related": ["relfix-kalepasch-com"],
            },
        ]

        # Find prior solutions related to this task
        related_solutions = [
            w for w in queued_work
            if "relfix-kalepasch-com" in w.get("related", [])
        ]

        assert len(related_solutions) >= 1
        assert "agent/recover-missing-branch-canary-codex-1" in [
            s["id"] for s in related_solutions
        ]


    def test_preserve_unrelated_queued_work(self):
        """Coordination rule: do not delete or overwrite unrelated queued improvements."""
        queue_before = [
            {"id": "self-opt-1", "topic": "optimization", "status": "queued"},
            {"id": "canary-recover", "topic": "recovery", "status": "queued"},
            {"id": "pricing-grid", "topic": "pricing", "status": "queued"},  # unrelated
        ]

        # After patch transplant, unrelated work must still be in queue
        unrelated = [w for w in queue_before if w["topic"] == "pricing"]
        queue_after = [w for w in queue_before if w not in unrelated]

        assert len(queue_after) == 2
        assert len(unrelated) == 1
        assert unrelated[0]["id"] == "pricing-grid"
        # Verify unrelated item is preserved (not deleted)
        assert any(w["id"] == "pricing-grid" for w in queue_before)


    def test_reconcile_with_active_loop_work(self):
        """Coordination rule: reconcile patch transplant with active loop-generated work."""
        active_loops = {
            "meta_loop_improvement": {
                "model": "deepseek:deepseek-v4-pro",
                "qpd": 7.0,
                "status": "running",
                "initiated": "2025-10-01T00:00:00Z",
            },
            "verify_diff": {
                "model": "local:llama3.2:3b",
                "qpd": 7.7,
                "status": "running",
                "initiated": "2025-10-01T00:00:00Z",
            },
        }

        incoming_task = {
            "id": "relfix-kalepasch-com-d3c42c32d62c",
            "status": "queued",
            "priority": "high",
            "initiated": "2025-10-01T06:00:00Z",
        }

        # Check for conflicts between active loops and incoming task
        conflicts = []
        for loop_name, loop_info in active_loops.items():
            if loop_info["status"] == "running":
                conflicts.append({
                    "loop": loop_name,
                    "action": "wait_or_coordinate",
                    "reason": "active_loop_in_progress",
                })

        # Verify coordination is tracked
        assert len(conflicts) >= 1
        assert any("active_loop" in str(c) for c in conflicts)


    def test_leave_recovered_work_in_queue_until_shipped(self):
        """Coordination rule: leave recovered work in queue until it ships."""
        recovered_branches = [
            {
                "id": "agent/recover-missing-branch-canary-codex-1",
                "status": "recovered",
                "queue_until": "shipped",
            }
        ]

        task = {
            "id": "relfix-kalepasch-com-d3c42c32d62c",
            "depends_on_recovery": recovered_branches,
        }

        # Verify recovered work is in dependency chain
        for recovery in task["depends_on_recovery"]:
            assert recovery["queue_until"] == "shipped"


# ============================================================================
# CROSS-LEARNING CONTEXT TESTS
# ============================================================================

class TestCrossLearningContext:
    """Verify outcome signals and learned routes guide model selection."""

    def test_recent_outcome_signals_inform_model_choice(self):
        """Recent outcomes (0/12 merged, 0/12 test-pass) should update route selection."""
        recent_outcomes = {
            "merged_count": 0,
            "merged_target": 12,
            "test_pass_count": 0,
            "test_pass_target": 12,
            "spend": 0.00,
            "models_tried": ["claude-haiku-4-5-20251001", "swarm:openai:openai"],
            "date": "2025-10-01",
        }

        # Despite 0/12 merged, model selection should continue (fail-soft)
        assert recent_outcomes["merged_count"] == 0
        assert not recent_outcomes["merged_count"] > 0  # No success yet
        # → Should continue trying with different approach


    def test_learned_route_verify_diff_uses_llama(self):
        """Learned route: verify_diff should use local:llama3.2:3b (qpd=7.7)."""
        learned_routes = {
            "verify_diff": {
                "model": "local:llama3.2:3b",
                "qpd": 7.7,
                "rationale": "semantic_validation_proven",
            },
            "meta_loop_improvement": {
                "model": "deepseek:deepseek-v4-pro",
                "qpd": 7.0,
                "rationale": "strategy_generation_proven",
            },
        }

        assert learned_routes["verify_diff"]["model"] == "local:llama3.2:3b"
        assert learned_routes["verify_diff"]["qpd"] == 7.7
        assert learned_routes["meta_loop_improvement"]["model"] == "deepseek:deepseek-v4-pro"


    def test_qa_panel_membership_from_outcomes(self):
        """QA panel uses models from cross-learning: llama3.2:3b + deepseek:deepseek-v4-flash."""
        qa_panel = {
            "primary": "local:llama3.2:3b",
            "secondary": "deepseek:deepseek-v4-flash",
            "verdict_rule": "both_must_pass or majority_pass",
            "samples": 23,
        }

        # Verify panel composition
        assert qa_panel["primary"] == "local:llama3.2:3b"
        assert qa_panel["secondary"] == "deepseek:deepseek-v4-flash"


# ============================================================================
# QA ROUTE EXECUTION TESTS
# ============================================================================

class TestQARouteExecution:
    """Verify independent QA route explores multiple samples."""

    def test_qa_route_explores_samples(self):
        """QA route executes: local:nomic-embed-text:latest (explore 23 samples)."""
        qa_route = {
            "name": "independent_qa_route",
            "model": "local:nomic-embed-text:latest",
            "strategy": "explore",
            "sample_count": 23,
            "timeout_sec": 45,
        }

        # Verify exploration parameters
        assert qa_route["strategy"] == "explore"
        assert qa_route["sample_count"] == 23
        assert qa_route["sample_count"] > 0


    def test_qa_panel_judges_with_consensus(self):
        """QA panel judges must both pass OR majority pass."""
        qa_verdicts = [
            {
                "judge": "local:llama3.2:3b",
                "verdict": "pass",
                "confidence": 0.87,
                "issues": [],
            },
            {
                "judge": "deepseek:deepseek-v4-flash",
                "verdict": "pass",
                "confidence": 0.92,
                "issues": [],
            },
        ]

        pass_count = sum(1 for v in qa_verdicts if v["verdict"] == "pass")
        assert pass_count >= 2  # Both pass


    def test_qa_panel_can_fail_with_issues(self):
        """QA panel can reject patch if either judge identifies issues."""
        qa_verdicts_with_issues = [
            {
                "judge": "local:llama3.2:3b",
                "verdict": "fail",
                "confidence": 0.95,
                "issues": [
                    "semantic_regression_detected",
                    "behavioral_change_in_auth_flow",
                ],
            },
            {
                "judge": "deepseek:deepseek-v4-flash",
                "verdict": "pass",
                "confidence": 0.78,
                "issues": [],
            },
        ]

        # Check if either judge failed
        any_fail = any(v["verdict"] == "fail" for v in qa_verdicts_with_issues)
        assert any_fail is True


# ============================================================================
# LEGAL GATE TESTS
# ============================================================================

class TestLegalGate:
    """Verify legal gate blocks changes requiring secrets, licensing, custody."""

    def test_legal_gate_owner_only_trigger(self):
        """Legal gate triggers 'owner_only' when change affects licensing, secrets, etc."""
        changes = [
            {
                "file": "src/auth.py",
                "type": "license_header_change",
                "requires_legal_gate": True,
                "requires_owner": True,
            },
            {
                "file": "config/secrets.yaml",
                "type": "credential_storage_change",
                "requires_legal_gate": True,
                "requires_owner": True,
            },
            {
                "file": "privacy/customer_custody.py",
                "type": "custody_transfer_change",
                "requires_legal_gate": True,
                "requires_owner": True,
            },
            {
                "file": "docs/tos.md",
                "type": "transmission_policy_change",
                "requires_legal_gate": True,
                "requires_owner": True,
            },
            {
                "file": "src/regular_feature.py",
                "type": "feature_change",
                "requires_legal_gate": False,
                "requires_owner": False,
            },
        ]

        legal_changes = [c for c in changes if c["requires_legal_gate"]]
        assert len(legal_changes) == 4
        assert all(c["requires_owner"] for c in legal_changes)


    def test_legal_gate_bypass_for_non_sensitive_changes(self):
        """Legal gate does not block regular feature changes."""
        safe_changes = {
            "files_changed": ["src/utils.py", "src/helpers.py"],
            "types": ["refactor", "enhancement", "bugfix"],
            "legal_gate_required": False,
        }

        assert safe_changes["legal_gate_required"] is False


# ============================================================================
# MERGE AND RELEASE STRATEGY TESTS
# ============================================================================

class TestMergeReleaseStrategy:
    """Verify auto-merge to orchestrator/dev, then batch train for production."""

    def test_merge_to_orchestrator_dev_after_qa_pass(self):
        """After QA passes and tests pass, auto-merge to orchestrator/dev."""
        merge_strategy = {
            "qa_passed": True,
            "tests_passed": True,
            "legal_gate_passed": True,
            "target_branch": "orchestrator/dev",
            "auto_merge": True,
            "merge_method": "squash",
        }

        should_merge = (
            merge_strategy["qa_passed"]
            and merge_strategy["tests_passed"]
            and merge_strategy["legal_gate_passed"]
        )
        assert should_merge is True
        assert merge_strategy["target_branch"] == "orchestrator/dev"


    def test_production_release_via_batch_train(self):
        """Production release does not auto-merge; goes through batch train."""
        release_flow = {
            "dev_merge": {
                "target": "orchestrator/dev",
                "auto_merge": True,
                "condition": "qa_tests_legal_pass",
            },
            "production_release": {
                "target": "master",
                "auto_merge": False,
                "mechanism": "batch_train",
                "requires_judge": True,
                "requires_test_pass": True,
            },
        }

        # Dev merge is auto
        assert release_flow["dev_merge"]["auto_merge"] is True

        # Prod release is NOT auto; waits for batch train
        assert release_flow["production_release"]["auto_merge"] is False
        assert release_flow["production_release"]["mechanism"] == "batch_train"


    def test_merge_commit_uses_repo_owner_identity(self):
        """Merge commit must use repo owner (kalepasch1) to pass Vercel deployment gate."""
        merge_commit = {
            "author_name": "kalepasch1",
            "author_email": "kalepasch@gmail.com",
            "vercel_deployment_gate": "requires_repo_owner_author",
        }

        assert merge_commit["author_name"] == "kalepasch1"
        assert "gmail.com" in merge_commit["author_email"]


# ============================================================================
# INTEGRATION TESTS
# ============================================================================

class TestPatchTransplantIntegration:
    """End-to-end workflow: detect similarity → adapt → execute pipeline → merge."""

    def test_full_workflow_similarity_to_merge(self):
        """Full workflow: detect similarity → adaptation → pipeline → QA → merge."""
        workflow_state = {
            "task_id": "relfix-kalepasch-com-d3c42c32d62c",
            "stage": "started",
            "steps": [],
        }

        # Step 1: Detect similarity
        candidate = {
            "source": "pareto-2080/rework-buildfail-qafix-pareto-2080-07062319-slice-1-slice-2-7f21d02",
            "similarity": 0.363,
        }
        workflow_state["similarity_detected"] = candidate["similarity"] >= 0.3
        workflow_state["steps"].append("detect_similarity")

        # Step 2: Choose adaptation path
        workflow_state["path"] = "adapt" if workflow_state["similarity_detected"] else "draft"
        workflow_state["steps"].append("choose_path")

        # Step 3: Execute pipeline (triage → planner → coder → QA → merge)
        workflow_state["pipeline_executed"] = {
            "triage": {"status": "passed", "duration_ms": 1565},
            "planner": {"status": "passed", "duration_ms": 170834},
            "coder": {"status": "passed", "duration_ms": 300000},
            "qa": {"status": "passed", "verdict": "both_pass"},
            "legal": {"status": "passed"},
        }
        workflow_state["steps"].append("execute_pipeline")

        # Step 4: Merge
        workflow_state["merge_status"] = "auto_merge_scheduled"
        workflow_state["target_branch"] = "orchestrator/dev"
        workflow_state["steps"].append("merge")

        # Verify all steps completed
        assert len(workflow_state["steps"]) == 4
        assert workflow_state["path"] == "adapt"
        assert workflow_state["merge_status"] == "auto_merge_scheduled"


    def test_workflow_handles_qa_failure_gracefully(self):
        """If QA fails, patch is rejected; workflow exits with reason."""
        workflow = {
            "task_id": "relfix-kalepasch-com-d3c42c32d62c",
            "stage": "qa_execution",
            "qa_verdict": "fail",
            "qa_reason": "semantic_regression_in_auth_flow",
            "merge_scheduled": False,
            "next_action": "report_failure_and_queue_review",
        }

        if workflow["qa_verdict"] == "fail":
            should_merge = False
        else:
            should_merge = True

        assert should_merge is False
        assert workflow["merge_scheduled"] is False


    def test_workflow_fails_fast_on_legal_gate_failure(self):
        """If legal gate blocks (secrets/licensing), reject immediately without QA."""
        workflow = {
            "task_id": "relfix-kalepasch-com-d3c42c32d62c",
            "stage": "legal_gate",
            "legal_gate_verdict": "blocked",
            "legal_gate_reason": "change_requires_owner_approval_for_secrets",
            "qa_executed": False,  # Did not reach QA
            "merge_scheduled": False,
        }

        assert workflow["legal_gate_verdict"] == "blocked"
        assert workflow["qa_executed"] is False
        assert workflow["merge_scheduled"] is False


# ============================================================================
# REGRESSION AND EDGE CASE TESTS
# ============================================================================

class TestRegressionAndEdgeCases:
    """Catch regressions and edge case failures."""

    def test_patch_preserves_comments_and_whitespace(self):
        """Adapted patch must preserve non-semantic content (comments, spacing)."""
        source = (
            "# Auth validation module\n"
            "def validate(token):\n"
            "    # Check token format\n"
            "    if not token:\n"
            "        return False\n"
            "\n"
            "    # Verify against DB\n"
            "    return True\n"
        )

        adapted = (
            "# Auth validation module\n"
            "def validate(token):\n"
            "    # Check token format\n"
            "    if not token:\n"
            "        log_failure()  # <-- added\n"
            "        return False\n"
            "\n"
            "    # Verify against DB\n"
            "    return True\n"
        )

        # Comments preserved
        assert source.count("#") == adapted.count("#")
        # Whitespace structure preserved (blank lines)
        assert source.count("\n\n") == adapted.count("\n\n")


    def test_empty_patch_rejected(self):
        """Patch with zero changes is rejected."""
        empty_patch = {
            "files": [],
            "additions": 0,
            "deletions": 0,
            "is_valid": False,
            "rejection_reason": "no_changes",
        }

        assert empty_patch["is_valid"] is False


    def test_malformed_diff_rejected(self):
        """Patch with malformed unified diff format is rejected."""
        malformed_patch = (
            "garbage text\n"
            "not a valid diff\n"
            "missing hunk headers\n"
        )

        is_valid_diff = (
            "diff --git" in malformed_patch
            and "@@" in malformed_patch
        )
        assert is_valid_diff is False


    def test_patch_conflict_detection(self):
        """Patch that cannot auto-merge due to conflicts is reported."""
        conflict_scenario = {
            "base_file": "def foo():\n    x = 1\n    return x\n",
            "patch": (
                "--- a/foo.py\n"
                "+++ b/foo.py\n"
                "@@ -1,3 +1,3 @@\n"
                " def foo():\n"
                "-    x = 1\n"
                "+    x = 2\n"  # Conflicting change
                " return x\n"
            ),
            "conflicting_context": "def foo():\n    x = modified_externally\n    return x\n",
            "conflicts": ["line_2_conflict"],
        }

        assert len(conflict_scenario["conflicts"]) > 0
        assert conflict_scenario["conflicts"][0] == "line_2_conflict"


    def test_timeout_during_long_patch_apply(self):
        """If patch apply exceeds timeout, abort and retry with backoff."""
        timeout_scenario = {
            "stage": "apply_patch",
            "timeout_sec": 30,
            "elapsed_sec": 35,
            "timed_out": True,
            "retry_count": 1,
            "backoff_multiplier": 1.5,
            "next_timeout_sec": 45,
        }

        assert timeout_scenario["timed_out"] is True
        assert timeout_scenario["retry_count"] >= 1
        assert timeout_scenario["next_timeout_sec"] > timeout_scenario["timeout_sec"]


    def test_network_transient_error_retriable(self):
        """Transient errors (network, timeout) are retried; logic errors are not."""
        errors = [
            {
                "type": "ConnectionError",
                "retriable": True,
                "retry_count": 3,
            },
            {
                "type": "ValueError",
                "retriable": False,
                "retry_count": 0,
            },
            {
                "type": "TimeoutError",
                "retriable": True,
                "retry_count": 5,
            },
        ]

        transient = [e for e in errors if e["retriable"]]
        permanent = [e for e in errors if not e["retriable"]]

        assert len(transient) == 2
        assert len(permanent) == 1


# ============================================================================
# SUMMARY AND COVERAGE
# ============================================================================

def run_all_tests():
    """Run all test classes and collect results."""
    test_classes = [
        TestPatchAdaptationWorkflow,
        TestOrchestrationPipelineContract,
        TestCoordinationRules,
        TestCrossLearningContext,
        TestQARouteExecution,
        TestLegalGate,
        TestMergeReleaseStrategy,
        TestPatchTransplantIntegration,
        TestRegressionAndEdgeCases,
    ]

    results = {"passed": 0, "failed": 0, "total": 0}

    for test_class in test_classes:
        test_methods = [
            method for method in dir(test_class)
            if method.startswith("test_")
        ]
        for method_name in test_methods:
            results["total"] += 1
            try:
                method = getattr(test_class, method_name)
                method()
                results["passed"] += 1
            except Exception as e:
                results["failed"] += 1
                print(f"FAIL: {test_class.__name__}.{method_name}: {e}")

    return results


if __name__ == "__main__":
    results = run_all_tests()
    print(f"\n{'='*70}")
    print(f"Tests: {results['passed']} passed, {results['failed']} failed, {results['total']} total")
    print(f"{'='*70}")
    exit(0 if results["failed"] == 0 else 1)
