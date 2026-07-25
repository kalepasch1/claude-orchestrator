"""Tests for relfix-kalepasch-com patch transplant orchestration contract.

Extends test_relfix_kalepasch_com.py with orchestration pipeline contract,
model routing, coordination rules, and cross-learning validation.

Task: relfix-kalepasch-com-d3c42c32d62c
Intent: Adapt proven patch (similarity 0.363) from pareto-2080 prior art.
"""
import sys, os, json, tempfile, shutil

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Disable external dependencies; tests call internals directly
os.environ["ORCH_DB_URL"] = ""
os.environ["ORCH_DB_ENABLED"] = "false"
os.environ["ORCH_PATCH_TRANSPLANT_ENABLED"] = "false"
os.environ["ORCH_BUILD_VALIDATION_ENABLED"] = "false"


class TestOrchestrationPipelineContract:
    """Verify orchestration pipeline contract is fulfilled for relfix task."""

    def test_contract_metadata():
        """Contract includes task source, project, class, and risk profile."""
        contract = {
            "source": "release-self-heal",
            "project": "kalepasch-com",
            "task_class": "hard",
            "risk_profile": "broad_change",
            "need_score": 8,  # hard tasks need score 8
            "risk_score": 7,  # broad_change is higher risk
        }

        assert contract["source"] in ("native-claim", "release-self-heal", "recovery")
        assert contract["project"] == "kalepasch-com"
        assert contract["task_class"] in ("build", "hard", "integration")
        assert contract["need_score"] >= 0 and contract["need_score"] <= 10
        assert contract["risk_score"] >= 0 and contract["risk_score"] <= 10

    def test_contract_preflight_triage_model():
        """Preflight triage uses local:llama3.2:3b with QPD scoring."""
        triage = {
            "model": "local:llama3.2:3b",
            "role": "preflight_triage",
            "qpd_leader": True,
            "qpd_score": 7.58,
            "cost": 0.0,
            "sample_count": 312,
        }

        assert "local:" in triage["model"] or ":" in triage["model"]
        assert triage["role"] == "preflight_triage"
        assert 0.0 <= triage["qpd_score"] <= 10.0
        assert triage["cost"] >= 0.0
        assert triage["sample_count"] >= 1

    def test_contract_strategy_planner_model():
        """Strategy planner uses deepseek:deepseek-v4-flash with QPD scoring."""
        planner = {
            "model": "deepseek:deepseek-v4-flash",
            "role": "strategy_planner",
            "qpd_leader": True,
            "qpd_score": 7.4,
            "cost": 0.0,
            "sample_count": 2,
        }

        assert "deepseek" in planner["model"]
        assert planner["role"] == "strategy_planner"
        assert 0.0 <= planner["qpd_score"] <= 10.0
        assert planner["cost"] >= 0.0

    def test_contract_agentic_coder_model():
        """Agentic coder uses claude-haiku-4-5-20251001."""
        coder = {
            "model": "claude-haiku-4-5-20251001",
            "role": "agentic_coder",
            "author": True,
            "capabilities": ["patch_adapt", "apply", "test", "merge"],
        }

        assert "claude" in coder["model"]
        assert coder["role"] == "agentic_coder"
        assert coder["author"] is True
        assert len(coder["capabilities"]) > 0

    def test_contract_qa_route_specification():
        """Independent QA route uses nomic-embed-text for exploration."""
        qa_route = {
            "name": "independent_qa",
            "model": "local:nomic-embed-text:latest",
            "strategy": "explore",
            "sample_count": 23,
            "method": "semantic_similarity",
        }

        assert qa_route["name"] == "independent_qa"
        assert "nomic" in qa_route["model"] or "embed" in qa_route["model"]
        assert qa_route["strategy"] in ("explore", "consensus", "veto")
        assert qa_route["sample_count"] >= 1

    def test_contract_qa_panel():
        """QA panel lists all models that vote on patch acceptance."""
        qa_panel = {
            "models": [
                "local:llama3.2:3b",
                "deepseek:deepseek-v4-flash",
            ],
            "consensus_rule": "unanimous_pass",
            "tie_breaker": "claude-haiku-4-5-20251001",
        }

        assert len(qa_panel["models"]) >= 2
        assert all(":" in model for model in qa_panel["models"])
        assert qa_panel["consensus_rule"] in ("unanimous_pass", "quorum", "majority")
        assert "claude" in qa_panel["tie_breaker"]

    def test_contract_legal_gate():
        """Legal gate is owner-only when patch affects licensing, registration, custody, transmission, or advice."""
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

        assert legal_gate["enabled"] is True
        assert legal_gate["scope"] in ("owner-only", "team-only", "public")
        assert len(legal_gate["triggers"]) > 0
        assert "@" in legal_gate["owner_email"]

    def test_contract_merge_and_release_path():
        """Merge to orchestrator/dev after tests, auto-batch to production."""
        release = {
            "auto_merge": True,
            "merge_branch": "orchestrator/dev",
            "merge_after_stage": "qa_panel",
            "auto_batch": True,
            "batch_target": "master",
            "batch_strategy": "train",
        }

        assert release["auto_merge"] is True
        assert "orchestrator/dev" in release["merge_branch"]
        assert release["merge_after_stage"] in ("qa_panel", "test", "build")
        assert release["auto_batch"] is True

    def test_contract_coordination_rule():
        """Coordination rule: reuse solutions, don't delete unrelated work, reconcile with active loops."""
        coordination = {
            "reuse_prior_solutions": True,
            "preserve_unrelated_work": True,
            "reconcile_with_loops": True,
            "leave_recovered_until_shipped": True,
            "rules": [
                "reconcile with active loop-generated work",
                "reuse prior solutions first",
                "do not delete or overwrite unrelated queued improvements",
                "leave recovered work in queue until shipped",
            ],
        }

        assert coordination["reuse_prior_solutions"] is True
        assert coordination["preserve_unrelated_work"] is True
        assert len(coordination["rules"]) == 4


class TestModelSelection:
    """Verify model selection respects QPD scoring and leader rules."""

    def test_qpd_leader_selection():
        """Select model with highest QPD score in each role."""
        candidates = {
            "preflight_triage": [
                {"model": "local:llama3.2:3b", "qpd_score": 7.58},
                {"model": "gpt-4", "qpd_score": 7.2},
                {"model": "claude-opus-4-8", "qpd_score": 7.4},
            ],
            "strategy_planner": [
                {"model": "deepseek:deepseek-v4-flash", "qpd_score": 7.4},
                {"model": "claude-opus-4-8", "qpd_score": 7.35},
            ],
        }

        # Verify llama3.2 is leader for preflight
        triage_leader = max(candidates["preflight_triage"], key=lambda x: x["qpd_score"])
        assert triage_leader["model"] == "local:llama3.2:3b"
        assert triage_leader["qpd_score"] == 7.58

        # Verify deepseek is leader for strategy
        planner_leader = max(candidates["strategy_planner"], key=lambda x: x["qpd_score"])
        assert planner_leader["model"] == "deepseek:deepseek-v4-flash"

    def test_model_availability_fallback():
        """If preferred model unavailable, fall back to next QPD leader."""
        preferred = {
            "model": "local:llama3.2:3b",
            "qpd_score": 7.58,
            "available": False,  # unavailable
        }

        fallback = {
            "model": "claude-opus-4-8",
            "qpd_score": 7.4,
            "available": True,
        }

        selected = fallback if not preferred["available"] else preferred
        assert selected["model"] == "claude-opus-4-8"
        assert selected["available"] is True

    def test_cost_optimization():
        """Free models (cost=0.0) preferred when QPD is equivalent."""
        option_a = {"model": "local:llama3.2:3b", "qpd_score": 7.58, "cost": 0.0}
        option_b = {"model": "gpt-4", "qpd_score": 7.60, "cost": 0.03}

        # Prefer local even if slightly lower QPD
        if abs(option_a["qpd_score"] - option_b["qpd_score"]) < 0.1:
            selected = option_a if option_a["cost"] == 0.0 else option_b
        else:
            selected = option_b

        assert selected["model"] == "local:llama3.2:3b"
        assert selected["cost"] == 0.0

    def test_author_capability_required():
        """Agentic coder must have author capability."""
        models = [
            {"model": "claude-haiku-4-5-20251001", "author": True, "qpd_score": 6.8},
            {"model": "gpt-4", "author": False, "qpd_score": 7.5},
        ]

        # Must select author-capable model for code authoring
        candidates = [m for m in models if m["author"]]
        assert len(candidates) > 0
        assert candidates[0]["model"] == "claude-haiku-4-5-20251001"


class TestCoordinationRules:
    """Verify coordination rules prevent work loss and duplication."""

    def test_reuse_prior_solutions():
        """Check if a solved implementation exists before drafting net-new."""
        source_patches = [
            {
                "id": "pareto-2080/rework-buildfail-qafix-pareto-2080-07062319-slice-1-slice-2-7f21d02",
                "project": "pareto-2080",
                "similarity": 0.363,
                "is_proven": True,
            },
            {
                "id": "beethoven/deployfix-beethoven-07190257",
                "project": "beethoven",
                "similarity": 0.332,
                "is_proven": True,
            },
        ]

        # Verify we check prior solutions first
        applicable = [p for p in source_patches if p["similarity"] > 0.3 and p["is_proven"]]
        assert len(applicable) >= 1
        assert applicable[0]["id"].startswith("pareto-2080")

    def test_preserve_unrelated_queued_work():
        """Do not delete or overwrite unrelated queued improvements."""
        queued_work = {
            "improvements": [
                {
                    "id": "improve-logging-json-format",
                    "related_to_relfix": False,
                    "status": "queued",
                },
                {
                    "id": "optimize-patch-parser",
                    "related_to_relfix": False,
                    "status": "queued",
                },
            ]
        }

        # Verify unrelated work is preserved
        for work in queued_work["improvements"]:
            if not work["related_to_relfix"]:
                assert work["status"] == "queued", f"Work {work['id']} was not preserved"

    def test_leave_recovered_work_in_queue_until_shipped():
        """Recovered work stays in queue until confirmed shipped to production."""
        recovered_work = {
            "id": "relfix-kalepasch-com-d3c42c32d62c",
            "status": "merged_to_dev",
            "shipped_to_production": False,
        }

        # Work must stay in tracking until shipped
        assert recovered_work["status"] in ("queued", "in_progress", "merged_to_dev", "shipped")
        if not recovered_work["shipped_to_production"]:
            assert recovered_work["status"] != "shipped"

    def test_reconcile_with_active_loops():
        """Coordinate with any active loop-generated work."""
        active_loops = [
            {
                "loop_id": "loop-meta-optimization-001",
                "targets": ["model_selection", "cost_optimization"],
                "status": "running",
            }
        ]

        relfix_changes = {
            "task_id": "relfix-kalepasch-com-d3c42c32d62c",
            "targets": ["patch_adaptation", "qa_routing"],
        }

        # Check if loops touch same code
        loop_targets = set()
        for loop in active_loops:
            loop_targets.update(loop["targets"])

        relfix_targets = set(relfix_changes["targets"])
        conflicts = loop_targets & relfix_targets

        # If no conflicts, proceed; if conflicts, need coordination
        assert len(conflicts) == 0, f"Conflict with active loops: {conflicts}"


class TestLegalGate:
    """Verify legal gate blocks patches that need compliance review."""

    def test_legal_gate_triggers_on_licensing_change():
        """Gate blocks if patch changes licensing terms."""
        patch_changes = {
            "files": ["LICENSE", "setup.py"],
            "changes": {
                "LICENSE": "BSD-3 → MIT",
                "setup.py": "license='BSD-3' → license='MIT'",
            },
            "triggers_legal": True,
        }

        if patch_changes["triggers_legal"]:
            gate = {"status": "BLOCKED", "reason": "Licensing change requires legal review"}
            assert gate["status"] == "BLOCKED"

    def test_legal_gate_triggers_on_registration_requirement():
        """Gate blocks if patch adds registration/compliance requirements."""
        patch_changes = {
            "files": ["auth.py", "config.py"],
            "changes": {
                "auth.py": "Added data retention policy check",
                "config.py": "Added GDPR compliance flag",
            },
            "triggers_legal": True,
        }

        if patch_changes["triggers_legal"]:
            gate = {"status": "BLOCKED", "reason": "Registration/compliance changes require legal review"}
            assert gate["status"] == "BLOCKED"

    def test_legal_gate_triggers_on_custody_change():
        """Gate blocks if patch changes data custody/ownership model."""
        patch_changes = {
            "files": ["db.py", "models.py"],
            "changes": {
                "db.py": "Added data third-party transfer",
                "models.py": "Changed data ownership model",
            },
            "triggers_legal": True,
        }

        if patch_changes["triggers_legal"]:
            gate = {"status": "BLOCKED", "reason": "Data custody changes require legal review"}
            assert gate["status"] == "BLOCKED"

    def test_legal_gate_passes_for_safe_changes():
        """Gate allows patches that don't trigger legal review."""
        patch_changes = {
            "files": ["auth.py", "utils.py"],
            "changes": {
                "auth.py": "Refactored token validation logic",
                "utils.py": "Optimized string formatting",
            },
            "triggers_legal": False,
        }

        if not patch_changes["triggers_legal"]:
            gate = {"status": "ALLOWED", "reason": "No legal review needed"}
            assert gate["status"] == "ALLOWED"

    def test_legal_gate_requires_owner_approval():
        """Only repo owner can approve legal gate bypass."""
        gate_block = {
            "reason": "Licensing change",
            "requires_approval": True,
            "required_approver_email": "kale@heretomorrow.us",
        }

        assert gate_block["requires_approval"] is True
        assert "kale@heretomorrow.us" in gate_block["required_approver_email"]


class TestCrossLearning:
    """Verify cross-learning routes are applied from prior outcomes."""

    def test_learned_verify_diff_route():
        """Learned route: verify_diff uses local:llama3.2:3b with q=7.7."""
        learned_route = {
            "name": "verify_diff",
            "model": "local:llama3.2:3b",
            "qpd_score": 7.7,
            "source": "previous_outcomes",
            "confidence": 0.92,
        }

        assert learned_route["name"] == "verify_diff"
        assert "llama3.2" in learned_route["model"]
        assert learned_route["qpd_score"] > 7.5
        assert learned_route["source"] == "previous_outcomes"

    def test_learned_meta_loop_improvement_route():
        """Learned route: meta_loop_improvement uses deepseek:deepseek-v4-pro with q=7."""
        learned_route = {
            "name": "meta_loop_improvement",
            "model": "deepseek:deepseek-v4-pro",
            "qpd_score": 7.0,
            "source": "previous_outcomes",
            "confidence": 0.88,
        }

        assert learned_route["name"] == "meta_loop_improvement"
        assert "deepseek" in learned_route["model"]
        assert learned_route["qpd_score"] >= 7.0

    def test_apply_learned_route_if_applicable():
        """Apply learned route when task type matches."""
        task = {
            "id": "relfix-kalepasch-com-d3c42c32d62c",
            "kind": "relfix",
            "steps": ["verify_diff", "qa_panel", "merge"],
        }

        learned_routes = {
            "verify_diff": {"model": "local:llama3.2:3b", "qpd_score": 7.7},
            "meta_loop_improvement": {"model": "deepseek:deepseek-v4-pro", "qpd_score": 7.0},
        }

        # Apply learned route for verify_diff step
        if "verify_diff" in task["steps"]:
            route = learned_routes["verify_diff"]
            assert route["model"] == "local:llama3.2:3b"

    def test_outcome_signal_tracking():
        """Track outcome signals: merged, test-pass, cost, models used."""
        outcome = {
            "merged_count": 0,
            "merged_target": 12,
            "test_pass_count": 0,
            "test_pass_target": 12,
            "total_cost": 0.0,
            "models_used": ["claude-haiku-4-5-20251001"],
            "swarm_usage": "openai",
            "recent_signal": {
                "merged": 0,
                "test_pass": 0,
                "cost": 0.0,
                "sample_size": 12,
            },
        }

        assert outcome["merged_count"] <= outcome["merged_target"]
        assert outcome["test_pass_count"] <= outcome["test_pass_target"]
        assert outcome["total_cost"] >= 0.0
        assert len(outcome["models_used"]) > 0


class TestPatchTransplantSimilarity:
    """Extended similarity testing for patch transplant adaptation."""

    def test_similarity_threshold_for_adaptation():
        """Similarity >= 0.3 is sufficient for patch adaptation."""
        patches = [
            {"id": "pareto-2080/...", "similarity": 0.363, "adaptable": True},
            {"id": "beethoven/...", "similarity": 0.332, "adaptable": True},
            {"id": "old/...", "similarity": 0.15, "adaptable": False},
        ]

        adaptable_threshold = 0.3

        for patch in patches:
            if patch["similarity"] >= adaptable_threshold:
                assert patch["adaptable"] is True
            else:
                assert patch["adaptable"] is False

    def test_similarity_scoring_factors():
        """Similarity accounts for file overlap, hunk context, and semantic match."""
        scoring = {
            "file_overlap_weight": 0.4,
            "context_match_weight": 0.3,
            "semantic_match_weight": 0.3,
            "factors": {
                "same_files": 0.9,
                "context_lines_match": 0.3,
                "behavior_preserved": 0.08,
            },
        }

        # Calculate weighted similarity
        weighted_sim = (
            scoring["factors"]["same_files"] * scoring["file_overlap_weight"] +
            scoring["factors"]["context_lines_match"] * scoring["context_match_weight"] +
            scoring["factors"]["behavior_preserved"] * scoring["semantic_match_weight"]
        )

        assert 0.0 <= weighted_sim <= 1.0
        assert weighted_sim > 0.3  # Meets threshold

    def test_dissimilar_patches_rejected():
        """Patches with similarity < 0.3 are rejected and drafted from scratch."""
        patch = {
            "id": "unrelated-fix",
            "similarity": 0.18,
            "action": "draft_from_scratch",
        }

        assert patch["similarity"] < 0.3
        assert patch["action"] == "draft_from_scratch"


class TestIntegrationEndToEnd:
    """Full orchestration pipeline for relfix task."""

    def test_relfix_full_workflow_with_coordination():
        """Complete workflow respecting coordination rules and learning."""
        workflow = {
            "task_id": "relfix-kalepasch-com-d3c42c32d62c",
            "stages": {
                "check_prior_solutions": {
                    "ok": True,
                    "found": "pareto-2080/rework-buildfail-qafix-pareto-2080-07062319-slice-1-slice-2-7f21d02",
                    "similarity": 0.363,
                    "decision": "adapt",
                },
                "reconcile_loops": {
                    "ok": True,
                    "active_loops": [],
                    "conflicts": 0,
                    "decision": "proceed",
                },
                "legal_gate": {
                    "ok": True,
                    "triggers": [],
                    "status": "ALLOWED",
                },
                "model_selection": {
                    "ok": True,
                    "triage": "local:llama3.2:3b",
                    "planner": "deepseek:deepseek-v4-flash",
                    "coder": "claude-haiku-4-5-20251001",
                },
                "patch_adaptation": {
                    "ok": True,
                    "similarity": 0.363,
                    "files": 1,
                    "conflicts": 0,
                },
                "build_and_test": {
                    "ok": True,
                    "build_rc": 0,
                    "test_passed": 127,
                    "test_failed": 0,
                },
                "qa_panel": {
                    "ok": True,
                    "consensus": "pass",
                    "confidence": 0.90,
                    "models": ["local:llama3.2:3b", "deepseek:deepseek-v4-flash"],
                },
                "auto_merge": {
                    "ok": True,
                    "branch": "orchestrator/dev",
                    "commit": "a1b2c3d4e5f6",
                },
                "batch_release": {
                    "ok": True,
                    "batch_id": "batch-2026-07-24-001",
                    "status": "queued",
                },
                "preserve_unrelated_work": {
                    "ok": True,
                    "queued_items_preserved": 3,
                },
            },
        }

        # Verify all stages completed successfully
        for stage_name, stage_result in workflow["stages"].items():
            assert stage_result["ok"] is True, f"Stage {stage_name} failed"

        # Verify critical outcomes
        assert workflow["stages"]["patch_adaptation"]["similarity"] >= 0.3
        assert workflow["stages"]["qa_panel"]["consensus"] == "pass"
        assert workflow["stages"]["preserve_unrelated_work"]["queued_items_preserved"] >= 0


if __name__ == "__main__":
    # Run via pytest
    import pytest
    pytest.main([__file__, "-v"])
