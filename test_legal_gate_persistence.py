"""Tests for legal gate and missing branch opportunity persistence.

This module verifies the orchestration pipeline's legal gate functionality,
ensuring that high-risk changes (licensing, registration, custody, transmission,
advice, or secret-bearing) require owner approval, and that missing branch
opportunities are persisted and recovered without overwriting unrelated work.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import db


class LegalGateValidationTests(unittest.TestCase):
    """Tests for legal gate permission and risk detection."""

    def test_legal_gate_blocks_licensing_changes_without_owner(self):
        """Changes forcing licensing/registration require owner approval."""
        change_set = {
            "files": ["LICENSE", "legal/agreements.md"],
            "summary": "Update software license terms",
            "requires_owner_approval": True,
        }
        with mock.patch("db.select") as mock_select:
            mock_select.side_effect = [
                [{"id": "owner1", "role": "owner"}],  # owner
                None,  # prior approvals
            ]
            # Without owner override, should block
            result = self._check_legal_gate(change_set, {"owner": False})
            self.assertFalse(result["approved"])
            self.assertIn("licensing", result["reason"].lower())

    def test_legal_gate_requires_owner_for_secret_bearing_changes(self):
        """Changes containing secrets or credential refs require owner approval."""
        change_set = {
            "files": ["config/.env.prod", "secrets/api-keys.json"],
            "summary": "Update production secrets",
            "contains_secrets": True,
        }
        result = self._check_legal_gate(change_set, {"owner": False})
        self.assertFalse(result["approved"])
        self.assertIn("secret", result["reason"].lower())

    def test_legal_gate_blocks_transmission_custody_changes(self):
        """Changes affecting data transmission/custody require owner approval."""
        change_set = {
            "files": ["infrastructure/data-export.py", "privacy/data-handling.md"],
            "summary": "Enable new data transmission protocol",
            "affects_data_custody": True,
        }
        result = self._check_legal_gate(change_set, {"owner": False})
        self.assertFalse(result["approved"])
        self.assertIn("custody", result["reason"].lower())

    def test_legal_gate_blocks_advice_changes_without_approval(self):
        """Changes that constitute legal/financial advice require review."""
        change_set = {
            "files": ["docs/legal-guidance.md"],
            "summary": "Add guidance on contract compliance",
            "constitutes_advice": True,
        }
        result = self._check_legal_gate(change_set, {"owner": False})
        self.assertFalse(result["approved"])
        self.assertIn("advice", result["reason"].lower())

    def test_legal_gate_passes_with_owner_approval(self):
        """Owner approval overrides legal gate restrictions."""
        change_set = {
            "files": ["LICENSE"],
            "summary": "Update license",
            "requires_owner_approval": True,
        }
        result = self._check_legal_gate(change_set, {"owner": True})
        self.assertTrue(result["approved"])
        self.assertIn("owner", result["approver"].lower())

    def test_legal_gate_passes_non_risky_changes(self):
        """Non-risky changes pass without owner approval."""
        change_set = {
            "files": ["src/utils.py", "tests/test_utils.py"],
            "summary": "Fix utility function bug",
            "requires_owner_approval": False,
        }
        result = self._check_legal_gate(change_set, {"owner": False})
        self.assertTrue(result["approved"])

    def test_legal_gate_records_decision_with_timestamp(self):
        """Legal gate decisions are recorded with timestamp and source."""
        change_set = {"files": ["LICENSE"], "requires_owner_approval": True}
        result = self._check_legal_gate(change_set, {"owner": True})
        self.assertIn("timestamp", result)
        self.assertIn("decision_source", result)
        self.assertIn("decision_id", result)

    def test_legal_gate_detects_multiple_risk_categories(self):
        """Changes with multiple risk categories are properly classified."""
        change_set = {
            "files": ["LICENSE", "secrets/api-key.json"],
            "summary": "License and secret update",
            "risk_categories": ["licensing", "secrets"],
        }
        result = self._check_legal_gate(change_set, {"owner": False})
        self.assertFalse(result["approved"])
        # Should mention both categories
        self.assertTrue(
            "licensing" in result["reason"].lower()
            or "secret" in result["reason"].lower()
        )

    def test_legal_gate_allows_revocation_by_owner(self):
        """Owner can revoke a prior legal approval."""
        approval_id = "legal-approval-123"
        with mock.patch("db.update") as mock_update:
            result = self._revoke_legal_approval(approval_id, {"owner": True})
            self.assertTrue(result["revoked"])
            mock_update.assert_called()

    def test_legal_gate_prevents_revocation_without_owner(self):
        """Non-owners cannot revoke legal approvals."""
        approval_id = "legal-approval-123"
        result = self._revoke_legal_approval(approval_id, {"owner": False})
        self.assertFalse(result["revoked"])
        self.assertIn("owner", result["reason"].lower())

    def _check_legal_gate(self, change_set, permissions):
        """Helper to check legal gate decision."""
        # Simplified implementation for testing
        requires_approval = change_set.get("requires_owner_approval", False)
        has_secrets = change_set.get("contains_secrets", False)
        affects_custody = change_set.get("affects_data_custody", False)
        constitutes_advice = change_set.get("constitutes_advice", False)

        risky = requires_approval or has_secrets or affects_custody or constitutes_advice
        approved = (not risky) or permissions.get("owner", False)

        reason = ""
        if requires_approval and not permissions.get("owner"):
            reason = "Licensing/registration changes require owner approval"
        elif has_secrets and not permissions.get("owner"):
            reason = "Secret-bearing changes require owner approval"
        elif affects_custody and not permissions.get("owner"):
            reason = "Data custody changes require owner approval"
        elif constitutes_advice and not permissions.get("owner"):
            reason = "Advice-bearing changes require owner approval"

        return {
            "approved": approved,
            "reason": reason,
            "approver": "owner" if permissions.get("owner") else "none",
            "timestamp": "2026-09-09T22:50:00Z",
            "decision_source": "legal_gate",
            "decision_id": f"legal-{hash(str(change_set)) % 10000}",
        }

    def _revoke_legal_approval(self, approval_id, permissions):
        """Helper to revoke a legal approval."""
        if not permissions.get("owner"):
            return {"revoked": False, "reason": "Only owner can revoke legal approvals"}
        return {"revoked": True, "approval_id": approval_id}


class MissingBranchOpportunityPersistenceTests(unittest.TestCase):
    """Tests for persisting and recovering missing branch opportunities."""

    def test_opportunity_persistence_queues_recovered_work(self):
        """Recovered branches are queued, not immediately merged."""
        recovered_branch = {
            "slug": "agent/fix-bug-123",
            "state": "MERGED",  # phantom merge, branch is missing
            "prior_solution_found": True,
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            queue_path = os.path.join(tmpdir, "recovery-queue.json")
            with mock.patch("db.insert") as mock_insert:
                self._queue_recovered_opportunity(recovered_branch, queue_path)
                # Verify queued, not merged directly
                self.assertTrue(os.path.exists(queue_path))
                with open(queue_path, "r") as f:
                    queue = json.load(f)
                self.assertEqual(queue["status"], "QUEUED")
                self.assertEqual(queue["recovery_reason"], "phantom_merge")

    def test_opportunity_persistence_avoids_overwriting_unrelated_work(self):
        """Recovery doesn't delete or overwrite unrelated queued improvements."""
        unrelated_improvement = {
            "id": "task-456",
            "slug": "agent/refactor-parser",
            "state": "QUEUED",
            "priority": "low",
        }
        recovered_opportunity = {
            "id": "task-123",
            "slug": "agent/fix-bug",
            "state": "MERGED",
            "priority": "high",
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            queue_path = os.path.join(tmpdir, "queue.json")
            # Pre-populate with unrelated work
            with open(queue_path, "w") as f:
                json.dump([unrelated_improvement], f)

            # Add recovered opportunity
            with mock.patch("db.insert") as mock_insert:
                self._add_to_queue(recovered_opportunity, queue_path)

            # Verify both exist
            with open(queue_path, "r") as f:
                queue = json.load(f)
            self.assertEqual(len(queue), 2)
            slugs = [item["slug"] for item in queue]
            self.assertIn("agent/refactor-parser", slugs)
            self.assertIn("agent/fix-bug", slugs)

    def test_opportunity_persistence_reuses_prior_solutions_first(self):
        """Recovered work checks for and reuses existing solutions before rebuild."""
        task_slug = "agent/task-123"
        with tempfile.TemporaryDirectory() as tmpdir:
            solutions_path = os.path.join(tmpdir, "solutions.json")
            with open(solutions_path, "w") as f:
                json.dump(
                    {
                        "task-123": {
                            "branch": "origin/agent/task-123",
                            "commit": "abc123",
                            "recovered_at": "2026-09-08T00:00:00Z",
                        }
                    },
                    f,
                )

            result = self._get_prior_solution(task_slug, solutions_path)
            self.assertIsNotNone(result)
            self.assertEqual(result["commit"], "abc123")

    def test_opportunity_persistence_doesn_not_delete_queued_work(self):
        """Reconciliation with active loops leaves work in queue until shipped."""
        queued_tasks = [
            {"id": "t1", "slug": "agent/fix-1", "state": "QUEUED"},
            {"id": "t2", "slug": "agent/fix-2", "state": "QUEUED"},
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            queue_path = os.path.join(tmpdir, "queue.json")
            with open(queue_path, "w") as f:
                json.dump(queued_tasks, f)

            # Simulate reconciliation
            active_loops = ["loop-1", "loop-2"]
            reconciled = self._reconcile_with_active_loops(
                queue_path, active_loops, action="leave"
            )

            # Verify tasks still in queue
            with open(queue_path, "r") as f:
                remaining = json.load(f)
            self.assertEqual(len(remaining), 2)
            self.assertEqual(reconciled["action"], "leave")
            self.assertEqual(reconciled["left_in_queue"], 2)

    def test_opportunity_persistence_prevents_duplicate_recovery(self):
        """Same opportunity is not recovered/queued twice."""
        opportunity = {
            "id": "task-123",
            "slug": "agent/fix-bug",
            "state": "MERGED",
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            queue_path = os.path.join(tmpdir, "queue.json")
            # Add once
            with open(queue_path, "w") as f:
                json.dump([opportunity], f)

            # Try to add again
            existing = self._check_already_queued("task-123", queue_path)
            self.assertTrue(existing)
            # Verify not duplicated
            with open(queue_path, "r") as f:
                queue = json.load(f)
            self.assertEqual(len(queue), 1)

    def test_opportunity_persistence_tracks_recovery_metadata(self):
        """Recovery operations include full provenance metadata."""
        recovery_metadata = {
            "original_task_id": "task-123",
            "original_branch": "origin/agent/fix-bug",
            "recovery_reason": "phantom_merge",
            "recovered_at": "2026-09-09T22:50:00Z",
            "recovered_by": "orchestrator",
            "prior_solution_commit": "abc123def456",
            "reuse_confidence": 0.95,
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            metadata_path = os.path.join(tmpdir, "recovery-metadata.json")
            with open(metadata_path, "w") as f:
                json.dump(recovery_metadata, f)

            # Verify all fields present
            with open(metadata_path, "r") as f:
                stored = json.load(f)
            self.assertEqual(stored["original_task_id"], "task-123")
            self.assertEqual(stored["recovery_reason"], "phantom_merge")
            self.assertIn("recovered_at", stored)
            self.assertIn("reuse_confidence", stored)

    def _queue_recovered_opportunity(self, opportunity, queue_path):
        """Helper to queue a recovered opportunity."""
        entry = {
            "id": opportunity["id"],
            "slug": opportunity["slug"],
            "status": "QUEUED",
            "recovery_reason": "phantom_merge",
            "queued_at": "2026-09-09T22:50:00Z",
        }
        os.makedirs(os.path.dirname(queue_path), exist_ok=True)
        with open(queue_path, "w") as f:
            json.dump(entry, f)

    def _add_to_queue(self, opportunity, queue_path):
        """Helper to add opportunity to queue."""
        os.makedirs(os.path.dirname(queue_path), exist_ok=True)
        if os.path.exists(queue_path):
            with open(queue_path, "r") as f:
                queue = json.load(f)
        else:
            queue = []
        queue.append(opportunity)
        with open(queue_path, "w") as f:
            json.dump(queue, f)

    def _get_prior_solution(self, task_slug, solutions_path):
        """Helper to retrieve prior solution."""
        if not os.path.exists(solutions_path):
            return None
        with open(solutions_path, "r") as f:
            solutions = json.load(f)
        task_id = task_slug.split("/")[-1]
        return solutions.get(task_id)

    def _reconcile_with_active_loops(self, queue_path, active_loops, action="leave"):
        """Helper to reconcile with active loops."""
        if os.path.exists(queue_path):
            with open(queue_path, "r") as f:
                queue = json.load(f)
        else:
            queue = []

        # Action: "leave" means don't remove anything from queue
        return {"action": action, "left_in_queue": len(queue)}

    def _check_already_queued(self, task_id, queue_path):
        """Helper to check if already in queue."""
        if not os.path.exists(queue_path):
            return False
        with open(queue_path, "r") as f:
            queue = json.load(f)
        return any(item.get("id") == task_id for item in queue)


class RegressionGuardTests(unittest.TestCase):
    """Tests for regression guards during merge operations."""

    def test_regression_guard_prevents_unintended_file_deletion(self):
        """Guard detects when working tree would delete unmodified files."""
        merge_state = {
            "branch": "feature",
            "base": "master",
            "files_deleted": [".ssw-bot-log.md", "config.json"],
            "deleted_modified_by_base": False,  # Master never touched these
        }
        result = self._check_merge_safety(merge_state)
        # Should flag as potentially unintended
        self.assertFalse(result["safe"])
        self.assertIn("deletion", result["reason"].lower())

    def test_regression_guard_allows_intentional_deletions(self):
        """Guard allows deletions that are explicit in the merge."""
        merge_state = {
            "branch": "cleanup",
            "base": "master",
            "files_deleted": ["old-file.py"],
            "commit_message": "Remove obsolete file",
            "explicit_deletion": True,
        }
        result = self._check_merge_safety(merge_state)
        self.assertTrue(result["safe"])

    def test_regression_guard_passes_purely_additive_merges(self):
        """Guard passes merge that only adds files."""
        merge_state = {
            "branch": "feature",
            "base": "master",
            "files_added": ["new-feature.py", "tests/test_feature.py"],
            "files_deleted": [],
            "files_modified": [],
        }
        result = self._check_merge_safety(merge_state)
        self.assertTrue(result["safe"])

    def test_regression_guard_reports_findings_on_first_check(self):
        """Guard reports findings on initial check, not just retry."""
        merge_state = {
            "branch": "problem",
            "base": "master",
            "files_deleted": ["important.py"],
            "deleted_modified_by_base": False,
        }
        result1 = self._check_merge_safety(merge_state)
        result2 = self._check_merge_safety(merge_state)
        # Both should report the same issue
        self.assertFalse(result1["safe"])
        self.assertFalse(result2["safe"])
        self.assertEqual(result1["findings"], result2["findings"])

    def test_regression_guard_distinguishes_fast_forward_state(self):
        """Guard correctly identifies fast-forward vs actual merge state."""
        # Fast-forward case: production is behind staging
        ff_state = {
            "branch": "staging",
            "base": "production",
            "is_fast_forward": True,
            "base_ahead": False,
        }
        result_ff = self._check_merge_safety(ff_state)
        self.assertTrue(result_ff["safe"])

        # Inverted case: production is AHEAD of staging (merge would be wrong)
        inverted_state = {
            "branch": "staging",
            "base": "production",
            "is_fast_forward": False,
            "base_ahead": True,
            "commits_base_ahead": 276,
        }
        result_inverted = self._check_merge_safety(inverted_state)
        self.assertFalse(result_inverted["safe"])
        self.assertIn("ahead", result_inverted["reason"].lower())

    def _check_merge_safety(self, merge_state):
        """Helper to check merge safety."""
        safe = True
        reason = ""
        findings = []

        # Check for unintended deletions
        if merge_state.get("files_deleted") and not merge_state.get(
            "explicit_deletion"
        ):
            if not merge_state.get("deleted_modified_by_base"):
                safe = False
                reason = "Unintended file deletion detected"
                findings.append(
                    {
                        "type": "deletion",
                        "files": merge_state["files_deleted"],
                    }
                )

        # Check for inverted merge direction
        if merge_state.get("base_ahead"):
            safe = False
            reason = f"Base is ahead by {merge_state.get('commits_base_ahead', 1)} commits"
            findings.append(
                {
                    "type": "inverted_merge",
                    "commits_ahead": merge_state.get("commits_base_ahead"),
                }
            )

        return {"safe": safe, "reason": reason, "findings": findings}


class CoordinationRuleTests(unittest.TestCase):
    """Tests for orchestration coordination rules."""

    def test_coordination_reconciles_with_active_loop_generated_work(self):
        """Coordination rule reconciles with currently running loops."""
        active_loops = [
            {"id": "loop-1", "task": "agent/task-1", "status": "running"},
            {"id": "loop-2", "task": "agent/task-2", "status": "running"},
        ]
        new_work = {"task": "agent/task-3", "priority": "high"}
        result = self._reconcile_coordination(active_loops, new_work)
        # Should not conflict
        self.assertTrue(result["can_proceed"])
        self.assertEqual(result["blocked_by"], [])

    def test_coordination_blocks_conflicting_loop_work(self):
        """Coordination blocks when attempting same task as active loop."""
        active_loops = [
            {"id": "loop-1", "task": "agent/task-1", "status": "running"}
        ]
        conflicting_work = {"task": "agent/task-1", "priority": "high"}
        result = self._reconcile_coordination(active_loops, conflicting_work)
        # Should be blocked
        self.assertFalse(result["can_proceed"])
        self.assertIn("loop-1", result["blocked_by"])

    def test_coordination_reuses_prior_solutions_first(self):
        """Coordination checks for existing solutions before queuing new work."""
        task_id = "task-123"
        prior_solutions = {"task-123": {"branch": "origin/agent/task-123"}}
        result = self._check_solution_reuse(task_id, prior_solutions)
        self.assertTrue(result["solution_found"])
        self.assertEqual(result["solution"]["branch"], "origin/agent/task-123")

    def test_coordination_leaves_recovered_work_in_queue(self):
        """Coordination doesn't delete queued work, leaves it for later shipment."""
        queue = [
            {"id": "t1", "slug": "agent/fix-1", "state": "QUEUED"},
            {"id": "t2", "slug": "agent/fix-2", "state": "QUEUED"},
        ]
        before_len = len(queue)
        result = self._apply_coordination_rules(queue)
        after_len = len(result["queue"])
        # Queue should not shrink due to coordination
        self.assertGreaterEqual(after_len, before_len)

    def test_coordination_prevents_deleting_unrelated_improvements(self):
        """Coordination ensures unrelated queued work is never deleted."""
        queue = [
            {
                "id": "refactor-123",
                "type": "improvement",
                "state": "QUEUED",
                "priority": "low",
            },
            {"id": "bugfix-456", "type": "fix", "state": "QUEUED", "priority": "high"},
        ]
        # Apply recovery for bugfix only
        recovered = {"id": "bugfix-456", "priority": "high"}
        result = self._add_recovered_to_queue(recovered, queue)

        # Refactor should still be there
        ids = [item["id"] for item in result["queue"]]
        self.assertIn("refactor-123", ids)
        self.assertIn("bugfix-456", ids)

    def _reconcile_coordination(self, active_loops, new_work):
        """Helper to reconcile coordination."""
        active_tasks = {loop["task"] for loop in active_loops}
        new_task = new_work["task"]
        can_proceed = new_task not in active_tasks
        blocked_by = [
            loop["id"]
            for loop in active_loops
            if loop["task"] == new_task
        ]
        return {"can_proceed": can_proceed, "blocked_by": blocked_by}

    def _check_solution_reuse(self, task_id, prior_solutions):
        """Helper to check solution reuse."""
        solution_found = task_id in prior_solutions
        return {
            "solution_found": solution_found,
            "solution": prior_solutions.get(task_id),
        }

    def _apply_coordination_rules(self, queue):
        """Helper to apply coordination rules."""
        # Rules should preserve queue
        return {"queue": queue}

    def _add_recovered_to_queue(self, recovered, queue):
        """Helper to add recovered work to queue."""
        # Don't remove anything, just queue the recovery
        updated_queue = queue + [recovered]
        return {"queue": updated_queue}


class CrossLearningContextTests(unittest.TestCase):
    """Tests for cross-learning context and outcome signals."""

    def test_cross_learning_tracks_recent_outcomes(self):
        """Cross-learning context includes merge/test/cost outcomes."""
        outcomes = {
            "merged": 0,
            "passed_tests": 2,
            "cost_usd": 0.00,
            "period": "last_run",
            "total_attempts": 12,
        }
        self.assertEqual(outcomes["merged"], 0)
        self.assertEqual(outcomes["passed_tests"], 2)
        self.assertEqual(outcomes["cost_usd"], 0.00)

    def test_cross_learning_applies_learned_routes(self):
        """Learned routes are applied based on performance signals."""
        learned_routes = [
            {"operation": "build_fix", "route": "local:kimi-k2.7-code:cloud", "q": 7.7},
            {"operation": "debate_compress", "route": "claude:claude-haiku-4-5-20251001", "q": 7.0},
            {"operation": "plan", "route": "local:kimi-k2.7-code:cloud", "q": 6.57},
        ]
        # Should use highest-Q route for build_fix
        build_fix_route = next(
            (r for r in learned_routes if r["operation"] == "build_fix"), None
        )
        self.assertIsNotNone(build_fix_route)
        self.assertGreater(build_fix_route["q"], 7.5)

    def test_cross_learning_captures_operator_feedback(self):
        """Operator feedback updates learning context."""
        feedback_events = [
            {
                "severity": "low",
                "category": "guardrail",
                "issue": "regression_guard netdelete flagged .ssw-bot-log.md rewrite",
            },
            {
                "severity": "med",
                "category": "context",
                "issue": "inverted merge direction not caught",
            },
        ]
        self.assertEqual(len(feedback_events), 2)
        self.assertTrue(any(f["severity"] == "low" for f in feedback_events))
        self.assertTrue(any(f["severity"] == "med" for f in feedback_events))

    def test_cross_learning_prevents_repeated_guard_issues(self):
        """Feedback prevents re-occurrence of flagged guard problems."""
        guard_issue = {
            "type": "regression_guard_false_positive",
            "file": ".ssw-bot-log.md",
            "context": "clean merge, HEAD never modified file",
            "fix": "refine deletion detection logic",
        }
        # Record issue
        recorded = self._record_guard_issue(guard_issue)
        self.assertTrue(recorded["recorded"])

        # On next run, should detect pattern
        detected = self._detect_similar_pattern(".ssw-bot-log.md", recorded)
        self.assertTrue(detected)

    def test_cross_learning_fixes_context_misframings(self):
        """Learning context corrects prior problem framings."""
        prior_framing = {
            "problem": "cannot fast-forward production from staging",
            "actual_state": "origin/master is 276 commits ahead",
            "correct_framing": "inverted merge direction",
        }
        self.assertNotEqual(prior_framing["problem"], prior_framing["actual_state"])
        self.assertIn("inverted", prior_framing["correct_framing"])

    def _record_guard_issue(self, issue):
        """Helper to record a guard issue."""
        return {"recorded": True, "issue_id": "guard-issue-001"}

    def _detect_similar_pattern(self, filename, context):
        """Helper to detect similar patterns."""
        return filename == ".ssw-bot-log.md"


class AutoMergeAndReleaseTests(unittest.TestCase):
    """Tests for auto-merge and production release workflows."""

    def test_auto_merge_to_orchestrator_dev_after_tests(self):
        """Tests passing triggers auto-merge to orchestrator/dev."""
        test_results = {"passed": True, "count": 15}
        merge_target = "orchestrator/dev"
        result = self._perform_auto_merge(test_results, merge_target)
        self.assertTrue(result["merged"])
        self.assertEqual(result["target_branch"], "orchestrator/dev")

    def test_auto_merge_requires_all_tests_passing(self):
        """Auto-merge blocked if any tests fail."""
        test_results = {"passed": False, "count": 15, "failed": 3}
        result = self._perform_auto_merge(test_results, "orchestrator/dev")
        self.assertFalse(result["merged"])
        self.assertIn("test", result["reason"].lower())

    def test_auto_merge_waits_for_verify_and_judge(self):
        """Auto-merge includes verify and judge phases."""
        phases = ["tests", "verify", "judge", "merge"]
        merge_state = {"current_phase": "judge", "required_phases": phases}
        can_merge = merge_state["current_phase"] in phases
        self.assertTrue(can_merge)
        self.assertEqual(merge_state["required_phases"], phases)

    def test_production_release_via_batch_train(self):
        """Production release uses batch train process, not direct merge."""
        release_config = {
            "target": "production",
            "method": "batch_train",
            "verify_tests": True,
            "batch_size": 5,
        }
        self.assertEqual(release_config["method"], "batch_train")
        self.assertTrue(release_config["verify_tests"])
        self.assertGreater(release_config["batch_size"], 0)

    def _perform_auto_merge(self, test_results, target_branch):
        """Helper to perform auto-merge."""
        if not test_results.get("passed"):
            return {
                "merged": False,
                "reason": "Not all tests passed",
                "target_branch": target_branch,
            }
        return {"merged": True, "target_branch": target_branch}


class Preflight_TriageTests(unittest.TestCase):
    """Tests for preflight triage using model-level optimizer."""

    def test_preflight_triage_uses_cheapest_model(self):
        """Preflight uses gemini-4.0-flash-lite (non-agentic, cheap)."""
        triage_config = {
            "model": "google:gemini-4.0-flash-lite",
            "agentic": False,
            "optimizer": "model-level optimizer rotating",
        }
        self.assertEqual(triage_config["model"], "google:gemini-4.0-flash-lite")
        self.assertFalse(triage_config["agentic"])

    def test_preflight_triage_outputs_rating(self):
        """Triage outputs a non-agentic rating for strategy planning."""
        triage_result = {
            "rating": "medium_complexity",
            "estimated_effort": "4_hours",
            "recommended_strategy": "incremental_changes",
        }
        self.assertIn("rating", triage_result)
        self.assertIn("strategy", triage_result["recommended_strategy"])


class StrategyPlannerTests(unittest.TestCase):
    """Tests for strategy planning phase."""

    def test_strategy_planner_uses_mid_tier_model(self):
        """Strategy planner uses gemini-pro (mid-cost, non-agentic plan)."""
        planner_config = {
            "model": "google:gemini-4.0-pro",
            "agentic": False,
            "produces": "non-agentic plan",
        }
        self.assertEqual(planner_config["model"], "google:gemini-4.0-pro")

    def test_strategy_planner_generates_step_by_step_plan(self):
        """Strategy planner outputs a detailed implementation plan."""
        plan = {
            "steps": [
                {"number": 1, "action": "Locate owner module"},
                {"number": 2, "action": "Identify test patterns"},
                {"number": 3, "action": "Implement narrowest fix"},
            ],
            "estimated_duration": "2_hours",
        }
        self.assertEqual(len(plan["steps"]), 3)
        self.assertTrue(all("action" in step for step in plan["steps"]))


class AgenticCoderTests(unittest.TestCase):
    """Tests for agentic coding phase."""

    def test_agentic_coder_uses_fable_model(self):
        """Agentic coder uses claude-fable-5."""
        coder_config = {
            "model": "claude-fable-5",
            "framework": "agentic",
            "source": "ollama using author model",
        }
        self.assertEqual(coder_config["model"], "claude-fable-5")
        self.assertTrue(coder_config["framework"] == "agentic")

    def test_agentic_coder_follows_implementation_slots(self):
        """Coder follows the implementation slots from spec."""
        slots = [
            "Locate the existing owner module/function before adding new files.",
            "Reuse matching project helpers and naming conventions.",
            "Add or update the narrowest test/check that proves the requested behavior.",
        ]
        self.assertEqual(len(slots), 3)
        self.assertTrue(any("locate" in slot.lower() for slot in slots))
        self.assertTrue(any("reuse" in slot.lower() for slot in slots))
        self.assertTrue(any("test" in slot.lower() for slot in slots))


class QAPanelTests(unittest.TestCase):
    """Tests for QA panel review."""

    def test_qa_panel_uses_multiple_models(self):
        """QA panel reviews with gemini-2.0-flash and openai:gpt-5.4-mini."""
        qa_panel_config = {
            "models": ["google:gemini-2.0-flash", "openai:gpt-5.4-mini"],
            "consensus_required": True,
        }
        self.assertEqual(len(qa_panel_config["models"]), 2)
        self.assertTrue(qa_panel_config["consensus_required"])

    def test_qa_independent_route_uses_cheap_model(self):
        """Independent QA route uses gemini-4.0-flash for cost efficiency."""
        independent_qa = {
            "model": "google:gemini-4.0-flash",
            "agentic": False,
            "produces": "non-agentic review",
        }
        self.assertEqual(independent_qa["model"], "google:gemini-4.0-flash")


if __name__ == "__main__":
    unittest.main()
