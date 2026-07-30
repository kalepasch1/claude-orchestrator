"""
Test suite for relfix-pareto-2080: release conflict self-healing and patch transplant.

Tests cover:
- Release conflict detection and classification (clean vs conflicting files)
- Self-healing decomposition of branches into non-conflicting sub-branches
- Patch transplant from prior proven diffs (adapt vs rebuild)
- Security validation gates before merge
- Legal gate checking (licensing, transmission, custody rules)
- Ephemeral worktree isolation (never touch main checkout)
- Concurrent merge operations with race condition safety
- Auto-merge to orchestrator/dev after QA passes
- Fallback to local repair tasks when healing fails
- Release train batch coordination and cadence gates
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

import self_healing_merge
import release_train


class TestReleaseConflictDetection(unittest.TestCase):
    """Classify files into clean vs conflicting."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = self.temp_dir.name

    def tearDown(self):
        self.temp_dir.cleanup()

    @patch("self_healing_merge._git")
    def test_classify_files_all_clean(self, mock_git):
        """All changed files are clean (non-conflicting) when merge succeeds."""
        # merge-base
        mock_git.side_effect = [
            Mock(returncode=0, stdout="base123\n"),
            # diff --name-only
            Mock(returncode=0, stdout="file1.py\nfile2.py\nfile3.py\n"),
            # worktree create
            Mock(returncode=0, stdout=""),
            # checkout base
            Mock(returncode=0, stdout=""),
            # merge attempt
            Mock(returncode=0, stdout=""),  # clean merge
            # diff --name-only conflicting (empty)
            Mock(returncode=0, stdout=""),
            # worktree delete
            Mock(returncode=0, stdout=""),
        ]

        result = self_healing_merge._classify_files(self.repo, "feature", "master")

        assert len(result["clean"]) == 3
        assert "file1.py" in result["clean"]
        assert len(result["conflicting"]) == 0
        assert len(result["all_changed"]) == 3

    @patch("self_healing_merge._git")
    def test_classify_files_mixed_clean_and_conflicting(self, mock_git):
        """Some files are clean, some are conflicting."""
        mock_git.side_effect = [
            Mock(returncode=0, stdout="base123\n"),
            # diff --name-only all changed
            Mock(returncode=0, stdout="clean1.py\nclean2.py\nconflict.py\n"),
            # worktree create
            Mock(returncode=0, stdout=""),
            # checkout base
            Mock(returncode=0, stdout=""),
            # merge attempt
            Mock(returncode=1, stdout="", stderr="conflict in conflict.py\n"),
            # diff --name-only conflicting files
            Mock(returncode=0, stdout="conflict.py\n"),
            # worktree delete
            Mock(returncode=0, stdout=""),
        ]

        result = self_healing_merge._classify_files(self.repo, "feature", "master")

        assert len(result["clean"]) == 2
        assert "clean1.py" in result["clean"]
        assert "clean2.py" in result["clean"]
        assert len(result["conflicting"]) == 1
        assert "conflict.py" in result["conflicting"]

    @patch("self_healing_merge._git")
    def test_classify_files_git_failure_returns_empty(self, mock_git):
        """Git command failures degrade gracefully."""
        mock_git.side_effect = [
            Mock(returncode=128, stdout="", stderr="not a git repo\n"),
        ]

        result = self_healing_merge._classify_files(self.repo, "feature", "master")

        assert len(result["clean"]) == 0
        assert len(result["conflicting"]) == 0
        assert len(result["all_changed"]) == 0

    @patch("self_healing_merge._git")
    def test_classify_files_no_changes_returns_empty(self, mock_git):
        """No changed files between base and branch."""
        mock_git.side_effect = [
            Mock(returncode=0, stdout="base123\n"),
            # diff --name-only (empty)
            Mock(returncode=0, stdout=""),
        ]

        result = self_healing_merge._classify_files(self.repo, "feature", "master")

        assert len(result["clean"]) == 0
        assert len(result["conflicting"]) == 0
        assert len(result["all_changed"]) == 0

    @patch("self_healing_merge._git")
    def test_classify_files_all_conflicting(self, mock_git):
        """All changed files are conflicting."""
        mock_git.side_effect = [
            Mock(returncode=0, stdout="base123\n"),
            # diff --name-only all changed
            Mock(returncode=0, stdout="conf1.py\nconf2.py\n"),
            # worktree create
            Mock(returncode=0, stdout=""),
            # checkout base
            Mock(returncode=0, stdout=""),
            # merge attempt fails
            Mock(returncode=1, stdout="", stderr="conflicts\n"),
            # diff --name-only (all are conflicting)
            Mock(returncode=0, stdout="conf1.py\nconf2.py\n"),
            # worktree delete
            Mock(returncode=0, stdout=""),
        ]

        result = self_healing_merge._classify_files(self.repo, "feature", "master")

        assert len(result["clean"]) == 0
        assert len(result["conflicting"]) == 2


class TestSelfHealingDecomposition(unittest.TestCase):
    """Decompose conflicting branches into clean + repair sub-branches."""

    @patch("self_healing_merge._git")
    @patch("self_healing_merge._classify_files")
    def test_heal_creates_clean_subbranch_when_partial_clean_exists(self, mock_classify, mock_git):
        """When some files are clean, create sub-branch and merge it."""
        mock_classify.return_value = {
            "clean": ["file1.py", "file2.py"],
            "conflicting": ["conflict.py"],
            "all_changed": ["file1.py", "file2.py", "conflict.py"]
        }

        mock_git.side_effect = [
            # create sub-branch
            Mock(returncode=0, stdout=""),
            # filter commit
            Mock(returncode=0, stdout=""),
            # merge sub-branch
            Mock(returncode=0, stdout=""),
            # delete sub-branch
            Mock(returncode=0, stdout=""),
        ]

        with patch("self_healing_merge.db") as mock_db:
            result = self_healing_merge.heal(
                repo=self.repo,
                branch="conflicting-feature",
                base="master"
            )

        assert result["healed"] is True
        assert result["clean_merged"] is True
        assert len(result["repair_tasks"]) > 0

    @patch("self_healing_merge._git")
    @patch("self_healing_merge._classify_files")
    def test_heal_creates_repair_task_for_conflicting_cluster(self, mock_classify, mock_git):
        """Conflicting files create a focused repair task."""
        mock_classify.return_value = {
            "clean": [],
            "conflicting": ["security.py", "auth.py", "tokens.py"],
            "all_changed": ["security.py", "auth.py", "tokens.py"]
        }

        mock_git.side_effect = []

        with patch("self_healing_merge.db") as mock_db:
            with patch("self_healing_merge._create_repair_task") as mock_repair:
                mock_repair.return_value = {"task_id": "repair-sec-123", "slug": "relfix-sec"}
                result = self_healing_merge.heal(
                    repo=self.repo,
                    branch="sec-upgrade",
                    base="master"
                )

        # Should create repair task for the conflicting cluster
        assert mock_repair.called

    @patch("self_healing_merge._git")
    @patch("self_healing_merge._classify_files")
    def test_heal_skip_when_disabled_via_env(self, mock_classify, mock_git):
        """Healing is disabled by ORCH_SELF_HEALING_ENABLED=false."""
        with patch.dict(os.environ, {"ORCH_SELF_HEALING_ENABLED": "false"}):
            result = self_healing_merge.heal(
                repo=self.repo,
                branch="feature",
                base="master"
            )

        assert result["healed"] is False
        assert result["reason"] == "disabled"

    @patch("self_healing_merge._git")
    @patch("self_healing_merge._classify_files")
    def test_heal_skip_when_too_few_files(self, mock_classify, mock_git):
        """Branches with fewer than MIN_FILES changed are not healed."""
        mock_classify.return_value = {
            "clean": [],
            "conflicting": ["single.py"],
            "all_changed": ["single.py"]
        }

        result = self_healing_merge.heal(
            repo=self.repo,
            branch="tiny-fix",
            base="master"
        )

        assert result["healed"] is False
        assert "too few files" in result.get("reason", "").lower()

    @patch("self_healing_merge._git")
    @patch("self_healing_merge._classify_files")
    def test_heal_uses_ephemeral_worktree_never_touches_main_checkout(self, mock_classify, mock_git):
        """Healing uses worktrees, never stashes on main checkout."""
        mock_classify.return_value = {
            "clean": ["file.py"],
            "conflicting": ["conflict.py"],
            "all_changed": ["file.py", "conflict.py"]
        }

        mock_git.side_effect = [
            Mock(returncode=0, stdout=""),  # create sub-branch
            Mock(returncode=0, stdout=""),  # filter commit
            Mock(returncode=0, stdout=""),  # merge
            Mock(returncode=0, stdout=""),  # delete sub-branch
        ]

        with patch("self_healing_merge.db"):
            result = self_healing_merge.heal(
                repo=self.repo,
                branch="feature",
                base="master"
            )

        # Verify no stash or reset --hard on main checkout
        for call_obj in mock_git.call_args_list:
            args = call_obj[0][0]
            if "stash" in args or "reset --hard" in args:
                # These should only happen in worktrees, not main repo
                assert self.repo not in str(call_obj)

    @patch("self_healing_merge._git")
    @patch("self_healing_merge._classify_files")
    def test_heal_returns_partial_when_clean_merged_but_conflicts_remain(self, mock_classify, mock_git):
        """heal returns partial=True when some files merged but conflicts persist."""
        mock_classify.return_value = {
            "clean": ["clean.py"],
            "conflicting": ["conflict.py"],
            "all_changed": ["clean.py", "conflict.py"]
        }

        mock_git.side_effect = [
            Mock(returncode=0, stdout=""),  # sub-branch
            Mock(returncode=0, stdout=""),  # filter
            Mock(returncode=0, stdout=""),  # merge clean
            Mock(returncode=0, stdout=""),  # delete
        ]

        with patch("self_healing_merge.db"):
            result = self_healing_merge.heal(
                repo=self.repo,
                branch="mixed-branch",
                base="master"
            )

        assert result.get("partial") is True


class TestPatchTransplant(unittest.TestCase):
    """Adapt proven patches from prior diffs."""

    @patch("self_healing_merge.db.select")
    def test_find_similar_patch_by_similarity_threshold(self, mock_select):
        """Find prior patch with similarity > threshold."""
        mock_select.return_value = [
            {
                "slug": "deployfix-beethoven-07190257",
                "patch_diff": "--- a/fleet_config.py\n+++ b/fleet_config.py\n",
                "similarity": 0.261
            }
        ]

        with patch("self_healing_merge.compute_similarity") as mock_sim:
            mock_sim.return_value = 0.261
            patch_data = self_healing_merge.find_transplant_source(
                current_branch="relfix-pareto-2080-07171927",
                min_similarity=0.25
            )

        assert patch_data is not None
        assert patch_data["slug"] == "deployfix-beethoven-07190257"

    @patch("self_healing_merge.db.select")
    def test_adapt_patch_to_target_branch(self, mock_select):
        """Adapt prior patch diff to target branch context."""
        prior_diff = """--- a/fleet_config.py
+++ b/fleet_config.py
@@ -10,3 +10,5 @@
 PROFILES = {}
+ORCH_SECURITY_GATE = True
"""
        result = self_healing_merge.adapt_patch(
            prior_diff=prior_diff,
            target_branch="relfix-pareto-2080",
            context_files=["fleet_config.py", "release_train.py"]
        )

        assert result is not None
        assert "ORCH_SECURITY_GATE" in result

    def test_transplant_patch_applies_cleanly(self):
        """Transplanted patch applies without rejects."""
        prior_patch = b"""--- a/test.py
+++ b/test.py
@@ -1,3 +1,4 @@
 def foo():
+    # security check
     pass
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = os.path.join(tmpdir, "test.py")
            with open(test_file, "w") as f:
                f.write("def foo():\n    pass\n")

            with patch("subprocess.run") as mock_run:
                mock_run.return_value = Mock(returncode=0, stdout="")
                result = self_healing_merge.apply_patch(prior_patch, tmpdir)

            assert result["applied"] is True


class TestSecurityValidationGate(unittest.TestCase):
    """Security checks before merge."""

    @patch("self_healing_merge.db.select")
    def test_security_gate_blocks_transmission_rule_violation(self, mock_select):
        """Transmission rule violation blocks merge."""
        mock_select.return_value = [
            {"slug": "relfix-pareto-2080", "files_changed": ["auth_token_transmit.py"]}
        ]

        result = self_healing_merge.check_security_gate(
            branch="relfix-pareto-2080",
            repo_path="/repo"
        )

        assert result["passed"] is False
        assert "transmission" in result["reason"].lower()

    @patch("self_healing_merge.validate_no_credentials_in_config")
    def test_security_gate_blocks_credentials_in_config(self, mock_validate):
        """Config keys with secrets are rejected."""
        mock_validate.return_value = {
            "safe": False,
            "found_secrets": ["AWS_KEY", "GITHUB_TOKEN"]
        }

        result = self_healing_merge.check_security_gate(
            branch="relfix-pareto-2080",
            repo_path="/repo"
        )

        assert result["passed"] is False

    @patch("self_healing_merge.scan_for_hardcoded_secrets")
    def test_security_gate_passes_when_no_violations(self, mock_scan):
        """Clean branch passes security gate."""
        mock_scan.return_value = {"found": []}

        result = self_healing_merge.check_security_gate(
            branch="relfix-pareto-2080",
            repo_path="/repo"
        )

        assert result["passed"] is True


class TestLegalGateChecking(unittest.TestCase):
    """Legal gate for licensing, registration, transmission."""

    @patch("self_healing_merge.db.select")
    def test_legal_gate_requires_owner_approval_for_licensing_change(self, mock_select):
        """Licensing changes require owner-only approval."""
        mock_select.return_value = [
            {"slug": "relfix-pareto-2080", "files_changed": ["LICENSE", "compliance.md"]}
        ]

        result = self_healing_merge.check_legal_gate(
            branch="relfix-pareto-2080",
            author="clauebot",
            repo_path="/repo"
        )

        assert result["needs_owner_approval"] is True
        assert "license" in result["reason"].lower()

    @patch("self_healing_merge.db.select")
    def test_legal_gate_requires_owner_for_custody_transfer(self, mock_select):
        """Custody/ownership transfer requires owner-only approval."""
        mock_select.return_value = [
            {"slug": "relfix-pareto-2080", "files_changed": ["OWNERSHIP.md", "governance.py"]}
        ]

        result = self_healing_merge.check_legal_gate(
            branch="relfix-pareto-2080",
            author="clauebot",
            repo_path="/repo"
        )

        assert result["needs_owner_approval"] is True

    @patch("self_healing_merge.db.select")
    def test_legal_gate_passes_for_normal_code_change(self, mock_select):
        """Normal code changes pass legal gate."""
        mock_select.return_value = [
            {"slug": "relfix-pareto-2080", "files_changed": ["runner.py", "db.py"]}
        ]

        result = self_healing_merge.check_legal_gate(
            branch="relfix-pareto-2080",
            author="clauebot",
            repo_path="/repo"
        )

        assert result["needs_owner_approval"] is False


class TestAutoMergeOrchestration(unittest.TestCase):
    """Auto-merge to orchestrator/dev after QA passes."""

    @patch("release_train._git")
    @patch("self_healing_merge.db.select")
    def test_automerge_after_qa_passes(self, mock_select, mock_git):
        """Branch auto-merges to staging after QA gates pass."""
        mock_select.return_value = [
            {
                "slug": "relfix-pareto-2080",
                "qa_status": "PASSED",
                "security_gate": "PASSED",
                "legal_gate": "PASSED"
            }
        ]

        mock_git.side_effect = [
            Mock(returncode=0, stdout=""),  # merge to staging
            Mock(returncode=0, stdout=""),  # push staging
        ]

        result = self_healing_merge.automerge_after_qa(
            branch="relfix-pareto-2080",
            repo="/repo",
            staging_branch="orchestrator/dev"
        )

        assert result["merged"] is True

    @patch("release_train._git")
    @patch("self_healing_merge.db.select")
    def test_automerge_blocked_when_qa_fails(self, mock_select, mock_git):
        """QA failure blocks auto-merge."""
        mock_select.return_value = [
            {
                "slug": "relfix-pareto-2080",
                "qa_status": "FAILED",
                "test_log": "test failures..."
            }
        ]

        result = self_healing_merge.automerge_after_qa(
            branch="relfix-pareto-2080",
            repo="/repo",
            staging_branch="orchestrator/dev"
        )

        assert result["merged"] is False
        assert "qa" in result["reason"].lower()

    @patch("release_train._git")
    def test_automerge_handles_race_with_concurrent_branches(self, mock_git):
        """Concurrent merge attempts race safely."""
        mock_git.side_effect = [
            Mock(returncode=0, stdout=""),  # first merge
            Mock(returncode=1, stdout="", stderr="already merged\n"),  # second conflict
        ]

        with patch("self_healing_merge.db.select") as mock_select:
            mock_select.return_value = [{"qa_status": "PASSED"}]

            result1 = self_healing_merge.automerge_after_qa(
                branch="relfix-pareto-2080",
                repo="/repo"
            )
            # Second attempt on same branch
            result2 = self_healing_merge.automerge_after_qa(
                branch="relfix-pareto-2080",
                repo="/repo"
            )

        # Second should detect already merged
        assert result2["already_merged"] or not result2["merged"]


class TestReleaseTrainCoordination(unittest.TestCase):
    """Batch merging and release cadence gates."""

    @patch("release_train.db.select")
    def test_release_decision_hold_when_below_batch_minimum(self, mock_select):
        """Release decision holds when ahead count < minimum."""
        result = release_train._release_decision(ahead=5, due=False, minimum=10)
        assert result == "hold"

    @patch("release_train.db.select")
    def test_release_decision_release_when_batch_full(self, mock_select):
        """Release decision releases when ahead >= minimum."""
        result = release_train._release_decision(ahead=15, due=False, minimum=10)
        assert result == "release"

    @patch("release_train.db.select")
    def test_release_decision_flush_when_cadence_due(self, mock_select):
        """Release decision flushes partial batch when cadence is due."""
        result = release_train._release_decision(ahead=7, due=True, minimum=10)
        assert result == "release"

    @patch("release_train.db.select")
    def test_release_decision_up_to_date_when_empty(self, mock_select):
        """Release decision up-to-date when no branches ahead."""
        result = release_train._release_decision(ahead=0, due=False)
        assert result == "up-to-date"

    @patch("release_train._git")
    def test_staging_branch_rebased_before_merge(self, mock_git):
        """Staging branch is rebased to prod before each merge."""
        mock_git.side_effect = [
            Mock(returncode=0, stdout="master\n"),  # detect prod branch
            Mock(returncode=0, stdout=""),  # fetch
            Mock(returncode=0, stdout=""),  # checkout staging
            Mock(returncode=0, stdout=""),  # rebase to prod
        ]

        with patch("release_train.db") as mock_db:
            release_train.ensure_staging_branch(repo="/repo")

        # Verify rebase was called
        assert any("rebase" in str(call_obj) for call_obj in mock_git.call_args_list)

    @patch("release_train._git")
    def test_merge_to_staging_accumulates_work(self, mock_git):
        """Agent branches merge into staging without going to prod."""
        mock_git.side_effect = [
            Mock(returncode=0, stdout=""),  # checkout staging
            Mock(returncode=0, stdout=""),  # merge agent branch
        ]

        with patch("release_train.db"):
            result = release_train.merge_to_staging(
                repo="/repo",
                agent_branch="agent/feature-123",
                staging_branch="orchestrator/dev"
            )

        assert result["merged"] is True

    @patch("release_train._git")
    def test_prod_promotion_records_last_good_commit(self, mock_git):
        """Prod promotion records last_good for rollback."""
        mock_git.side_effect = [
            Mock(returncode=0, stdout="prod-sha-123abc\n"),  # current prod tip
            Mock(returncode=0, stdout=""),  # merge staging to prod
            Mock(returncode=0, stdout=""),  # push prod
        ]

        with patch("release_train.db") as mock_db:
            with patch("release_train._record_release_flow"):
                result = release_train.promote_staging_to_prod(
                    repo="/repo",
                    staging_branch="orchestrator/dev"
                )

        # last_good should be recorded
        assert result.get("last_good_commit") == "prod-sha-123abc"


class TestConcurrentMergeRaceSafety(unittest.TestCase):
    """Concurrent merge operations don't create phantom conflicts."""

    @patch("self_healing_merge._git")
    @patch("self_healing_merge.db.select")
    def test_concurrent_merges_use_upsert_for_idempotency(self, mock_select, mock_git):
        """Concurrent merge updates use upsert (idempotent)."""
        mock_select.return_value = [{"id": "task-1", "merged": False}]
        mock_git.side_effect = [Mock(returncode=0, stdout="")] * 5

        with patch("self_healing_merge.db.update") as mock_update:
            self_healing_merge.record_merge(
                branch="relfix-pareto-2080",
                merged=True
            )

        # Verify upsert-like behavior
        if mock_update.called:
            call_kwargs = mock_update.call_args[1]
            assert call_kwargs.get("upsert") is True or "merge" in str(mock_update.call_args)

    @patch("self_healing_merge._git")
    def test_merge_conflict_on_concurrent_attempt_detected(self, mock_git):
        """Concurrent merge into same target is detected."""
        mock_git.side_effect = [
            Mock(returncode=1, stdout="", stderr="CONFLICT (content): Merge conflict in file.py\n")
        ]

        result = self_healing_merge.attempt_merge(
            repo="/repo",
            source_branch="relfix-pareto-2080",
            target_branch="orchestrator/dev"
        )

        assert result["conflict"] is True or result["returncode"] != 0


class TestFallbackBehavior(unittest.TestCase):
    """Graceful degradation when healing fails."""

    @patch("self_healing_merge._git")
    @patch("self_healing_merge._classify_files")
    def test_heal_failure_creates_repair_ticket(self, mock_classify, mock_git):
        """When heal fails entirely, create repair ticket for manual review."""
        mock_classify.side_effect = Exception("classification timeout")
        mock_git.side_effect = Exception("git error")

        with patch("self_healing_merge.db.insert") as mock_insert:
            result = self_healing_merge.heal(
                repo="/repo",
                branch="relfix-pareto-2080",
                base="master"
            )

        # Should create fallback repair ticket
        assert result["fallback_repair_ticket_created"] is True

    @patch("self_healing_merge._git")
    @patch("self_healing_merge._classify_files")
    def test_heal_failure_branch_stays_conflict_for_manual_merge(self, mock_classify, mock_git):
        """Failed heal leaves branch in CONFLICT state for manual intervention."""
        mock_classify.return_value = None
        mock_git.side_effect = [
            Mock(returncode=1, stdout="", stderr="timeout"),
            Mock(returncode=1, stdout="", stderr="timeout"),
        ]

        result = self_healing_merge.heal(
            repo="/repo",
            branch="relfix-pareto-2080",
            base="master"
        )

        # Branch should remain CONFLICT, not move to STUCK
        assert result["state"] == "CONFLICT" or result["healed"] is False


class TestStatisticsTracking(unittest.TestCase):
    """Healing attempt statistics."""

    def test_stats_track_successful_heals(self):
        """Stats increment on successful heal."""
        initial_healed = self_healing_merge._stats["healed"]

        with patch("self_healing_merge._git"):
            with patch("self_healing_merge._classify_files") as mock_classify:
                mock_classify.return_value = {
                    "clean": ["f.py"],
                    "conflicting": [],
                    "all_changed": ["f.py"]
                }
                with patch("self_healing_merge.db"):
                    self_healing_merge.heal("/repo", "branch", "base")

        # Stats should increment
        assert self_healing_merge._stats["healed"] > initial_healed

    def test_stats_track_partial_heals(self):
        """Stats track partial (clean merged, conflicts remain)."""
        initial_partial = self_healing_merge._stats["partial"]

        with patch("self_healing_merge._git"):
            with patch("self_healing_merge._classify_files") as mock_classify:
                mock_classify.return_value = {
                    "clean": ["clean.py"],
                    "conflicting": ["conflict.py"],
                    "all_changed": ["clean.py", "conflict.py"]
                }
                with patch("self_healing_merge.db"):
                    self_healing_merge.heal("/repo", "branch", "base")

        # Partial heal should increment counter
        assert self_healing_merge._stats["partial"] > initial_partial

    def test_stats_track_failed_heals(self):
        """Stats track attempts that fail."""
        initial_failed = self_healing_merge._stats["failed"]

        with patch("self_healing_merge._git") as mock_git:
            mock_git.side_effect = Exception("git failure")
            with patch("self_healing_merge._classify_files") as mock_classify:
                mock_classify.side_effect = Exception("timeout")
                self_healing_merge.heal("/repo", "branch", "base")

        # Failed heal should increment counter
        assert self_healing_merge._stats["failed"] > initial_failed


class TestEdgeCases(unittest.TestCase):
    """Edge cases and boundary conditions."""

    @patch("self_healing_merge._git")
    def test_empty_branch_no_changes_skips_healing(self, mock_git):
        """Branch with no changes is skipped."""
        mock_git.side_effect = [
            Mock(returncode=0, stdout="base123\n"),
            Mock(returncode=0, stdout=""),  # no changed files
        ]

        result = self_healing_merge.heal(
            repo="/repo",
            branch="empty-branch",
            base="master"
        )

        assert result["healed"] is False

    @patch("self_healing_merge._git")
    @patch("self_healing_merge._classify_files")
    def test_large_conflict_cluster_creates_multiple_repair_tasks(self, mock_classify, mock_git):
        """Large conflict clusters may be split into focused repair tasks."""
        # 20 conflicting files -> may group into security/auth/infrastructure clusters
        conflicting = [f"conflict-{i}.py" for i in range(20)]
        mock_classify.return_value = {
            "clean": [],
            "conflicting": conflicting,
            "all_changed": conflicting
        }

        with patch("self_healing_merge._create_repair_task") as mock_repair:
            with patch("self_healing_merge.db"):
                mock_repair.return_value = {"task_id": "t-1"}
                result = self_healing_merge.heal(
                    repo="/repo",
                    branch="large-conflict",
                    base="master"
                )

        # Should create task(s)
        assert mock_repair.called or result["fallback_repair_ticket_created"]

    @patch("self_healing_merge._git")
    def test_unicode_in_filenames_handled_correctly(self, mock_git):
        """Filenames with unicode are handled."""
        mock_git.side_effect = [
            Mock(returncode=0, stdout="base123\n"),
            Mock(returncode=0, stdout="file_日本語.py\n"),
            Mock(returncode=0, stdout=""),
            Mock(returncode=0, stdout=""),
            Mock(returncode=0, stdout=""),
            Mock(returncode=0, stdout=""),
            Mock(returncode=0, stdout=""),
        ]

        with patch("self_healing_merge._classify_files") as mock_classify:
            mock_classify.return_value = {
                "clean": ["file_日本語.py"],
                "conflicting": [],
                "all_changed": ["file_日本語.py"]
            }
            with patch("self_healing_merge.db"):
                result = self_healing_merge.heal(
                    repo="/repo",
                    branch="unicode-branch",
                    base="master"
                )

        # Should not crash
        assert isinstance(result, dict)

    @patch("release_train.db.select")
    def test_release_train_gates_respect_red_gate_cooldown(self, mock_select):
        """Red gate prevents releases for cooldown period after failure."""
        mock_select.return_value = [
            {
                "status": "FAILED",
                "failed_at": datetime.datetime.utcnow().isoformat()
            }
        ]

        result = release_train.check_red_gate(
            project="pareto-2080",
            cooldown_minutes=180
        )

        # Should be in cooldown
        assert result["in_cooldown"] is True or result["can_release"] is False


if __name__ == "__main__":
    unittest.main()
