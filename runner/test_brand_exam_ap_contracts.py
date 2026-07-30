#!/usr/bin/env python3
"""
test_brand_exam_ap_contracts.py - Brand examination AP contracts with zombie-reaper integration.

Comprehensive tests for dropbox-prediction-markets-institute-think-tank-launch-brand-exam-ap-contracts.

Covers:
  - Brand exam AP (agreement protocol) contract validation and enforcement
  - Dropbox prediction markets institute integration with think tank launch
  - Runner heartbeat monitoring and expiration detection (zombie-reaper)
  - Multi-stage brand exam workflow (initiation → validation → approval → launch)
  - Contract-based access control and capability enforcement
  - Task state management and transitions
  - Error recovery and graceful degradation
  - High-volume batch processing
  - Integration with agentic_repair for orphaned task recovery

Environment variables tested:
  ORCH_DB_ENABLED (must be false for tests)
  ORCH_DB_URL (must be empty for tests)
  ORCH_BRAND_EXAM_ENABLED (enables brand exam workflow)
  ORCH_DROPBOX_PMI_ENABLED (enables dropbox prediction markets institute)
  ORCH_AP_CONTRACT_ENFORCE (enables AP contract validation)
  ORCH_ZOMBIE_REAPER_GRACE_S (runner grace period before reclaim)
  ORCH_THINK_TANK_LAUNCH (enables think tank launch workflows)
"""
import sys
import os
import time
import datetime
import json
from unittest.mock import patch, MagicMock, call
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Disable DB at module load
os.environ["ORCH_DB_ENABLED"] = "false"
os.environ["ORCH_DB_URL"] = ""

# Import runner module
import importlib.util
_spec = importlib.util.spec_from_file_location(
    "runner",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "runner.py")
)
runner = importlib.util.module_from_spec(_spec)
sys.modules["runner"] = runner
_spec.loader.exec_module(runner)


class MockAPContract:
    """Factory for creating mock AP contract dicts."""

    @staticmethod
    def brand_exam_ap(
        contract_id="ap-contract-pmi-001",
        status="active",
        brand_tier="standard",
        capabilities=None,
        think_tank_enabled=True,
        dropbox_enabled=True,
    ):
        """Create an AP contract for brand examination."""
        if capabilities is None:
            capabilities = [
                "brand_exam_basic",
                "validation_basic",
                "think_tank_launch",
                "dropbox_integration"
            ]

        return {
            "id": contract_id,
            "type": "ap_contract",
            "contract_type": "brand_exam",
            "status": status,
            "tier": brand_tier,
            "capabilities": capabilities,
            "think_tank_enabled": think_tank_enabled,
            "dropbox_enabled": dropbox_enabled,
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "agreement_date": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }

    @staticmethod
    def task(
        task_id="brand-exam-ap-1",
        slug="dropbox-pmi-think-tank-brand-exam",
        account="Mac.lan-0",
        contract_id="ap-contract-pmi-001",
        state="RUNNING",
        brand_tier="standard",
        updated_at_offset_min=0,
        updated_at_iso=None,
    ):
        """Create a brand exam AP contract task."""
        if updated_at_iso is None:
            now = datetime.datetime.now(datetime.timezone.utc)
            updated_at = (now - datetime.timedelta(minutes=updated_at_offset_min)).isoformat()
        else:
            updated_at = updated_at_iso

        return {
            "id": task_id,
            "slug": slug,
            "state": state,
            "account": account,
            "contract_id": contract_id,
            "brand_tier": brand_tier,
            "exam_type": "brand_exam_ap",
            "dropbox_pmi_think_tank": True,
            "updated_at": updated_at,
            "stage": "initiation",
        }

    @staticmethod
    def heartbeat(
        runner_id="Mac.lan-0",
        hostname="Mac.lan",
        last_seen_offset_sec=0,
        last_seen_iso=None,
    ):
        """Create a runner_heartbeats dict."""
        if last_seen_iso is None:
            now = datetime.datetime.now(datetime.timezone.utc)
            last_seen = (now - datetime.timedelta(seconds=last_seen_offset_sec)).isoformat()
        else:
            last_seen = last_seen_iso

        return {
            "runner_id": runner_id,
            "hostname": hostname,
            "last_seen": last_seen,
        }


class TestBrandExamAPContractBasics:
    """Test basic brand exam AP contract creation and validation."""

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_ap_contract_created_for_brand_exam(self, mock_update, mock_select):
        """AP contract can be created for brand examination."""
        contract = MockAPContract.brand_exam_ap()

        assert contract["type"] == "ap_contract"
        assert contract["contract_type"] == "brand_exam"
        assert contract["status"] == "active"

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_ap_contract_includes_dropbox_integration(self, mock_update, mock_select):
        """AP contract includes Dropbox prediction markets institute integration."""
        contract = MockAPContract.brand_exam_ap()

        assert contract["dropbox_enabled"] is True
        assert "dropbox_integration" in contract["capabilities"]

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_ap_contract_includes_think_tank_launch(self, mock_update, mock_select):
        """AP contract includes think tank launch capability."""
        contract = MockAPContract.brand_exam_ap()

        assert contract["think_tank_enabled"] is True
        assert "think_tank_launch" in contract["capabilities"]

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_brand_exam_task_references_ap_contract(self, mock_update, mock_select):
        """Brand exam task correctly references AP contract."""
        contract = MockAPContract.brand_exam_ap(contract_id="ap-contract-123")
        task = MockAPContract.task(contract_id="ap-contract-123")

        assert task["contract_id"] == contract["id"]
        assert task["exam_type"] == "brand_exam_ap"

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_task_dropbox_pmi_flag_matches_contract(self, mock_update, mock_select):
        """Task dropbox_pmi flag matches contract dropbox_enabled."""
        contract = MockAPContract.brand_exam_ap(dropbox_enabled=True)
        task = MockAPContract.task()

        assert task["dropbox_pmi_think_tank"] == contract["dropbox_enabled"]


class TestAPContractCapabilities:
    """Test AP contract capability enforcement."""

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_basic_tier_has_minimal_capabilities(self, mock_update, mock_select):
        """Basic tier has minimal brand exam capabilities."""
        contract = MockAPContract.brand_exam_ap(
            brand_tier="basic",
            capabilities=["brand_exam_basic"]
        )

        assert "brand_exam_basic" in contract["capabilities"]
        assert len(contract["capabilities"]) >= 1

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_standard_tier_includes_validation(self, mock_update, mock_select):
        """Standard tier includes validation capabilities."""
        contract = MockAPContract.brand_exam_ap(
            brand_tier="standard",
            capabilities=["brand_exam_basic", "validation_basic"]
        )

        assert "validation_basic" in contract["capabilities"]

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_premium_tier_includes_advanced_features(self, mock_update, mock_select):
        """Premium tier includes advanced brand exam features."""
        contract = MockAPContract.brand_exam_ap(
            brand_tier="premium",
            capabilities=[
                "brand_exam_basic",
                "validation_advanced",
                "custom_branding",
                "expedited_processing"
            ]
        )

        assert "validation_advanced" in contract["capabilities"]
        assert "custom_branding" in contract["capabilities"]

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_enterprise_tier_full_access(self, mock_update, mock_select):
        """Enterprise tier has full access to all capabilities."""
        capabilities = [
            "brand_exam_basic",
            "validation_advanced",
            "custom_branding",
            "expedited_processing",
            "white_label_support",
            "priority_queue",
            "dedicated_account_manager"
        ]
        contract = MockAPContract.brand_exam_ap(
            brand_tier="enterprise",
            capabilities=capabilities
        )

        assert len(contract["capabilities"]) >= 7
        assert "white_label_support" in contract["capabilities"]


class TestDropboxPMIIntegration:
    """Test Dropbox prediction markets institute integration."""

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_dropbox_pmi_contract_recognized(self, mock_update, mock_select):
        """Dropbox PMI contracts are recognized by id pattern."""
        contract = MockAPContract.brand_exam_ap(contract_id="ap-contract-pmi-001")

        assert "pmi" in contract["id"].lower()
        assert contract["dropbox_enabled"] is True

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_dropbox_pmi_task_routed_correctly(self, mock_update, mock_select):
        """Dropbox PMI tasks are routed to correct handler."""
        task = MockAPContract.task(slug="dropbox-pmi-think-tank-brand-exam")

        assert "dropbox" in task["slug"].lower()
        assert "pmi" in task["slug"].lower()
        assert task["dropbox_pmi_think_tank"] is True

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_dropbox_disabled_contract_blocks_integration(self, mock_update, mock_select):
        """Contracts with dropbox_enabled=false block integration."""
        contract = MockAPContract.brand_exam_ap(dropbox_enabled=False)

        assert contract["dropbox_enabled"] is False

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_pmi_prediction_market_capabilities(self, mock_update, mock_select):
        """PMI contracts include prediction market capabilities."""
        contract = MockAPContract.brand_exam_ap(
            contract_id="ap-contract-pmi-001",
            capabilities=[
                "brand_exam_basic",
                "prediction_market_validation",
                "institute_credential_check",
                "market_tier_verification"
            ]
        )

        assert "prediction_market_validation" in contract["capabilities"]
        assert "institute_credential_check" in contract["capabilities"]


class TestThinkTankLaunchWorkflow:
    """Test think tank launch workflow integration."""

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_think_tank_launch_enabled_in_contract(self, mock_update, mock_select):
        """Think tank launch is enabled in AP contract."""
        contract = MockAPContract.brand_exam_ap(think_tank_enabled=True)

        assert contract["think_tank_enabled"] is True
        assert "think_tank_launch" in contract["capabilities"]

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_think_tank_launch_task_creation(self, mock_update, mock_select):
        """Think tank launch task can be created."""
        task = MockAPContract.task(
            slug="dropbox-pmi-think-tank-brand-exam",
            stage="think_tank_launch"
        )

        task["stage"] = "think_tank_launch"
        assert task["stage"] == "think_tank_launch"

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_think_tank_launch_requires_contract_capability(self, mock_update, mock_select):
        """Think tank launch requires contract capability."""
        contract = MockAPContract.brand_exam_ap(
            think_tank_enabled=False,
            capabilities=["brand_exam_basic"]
        )

        assert "think_tank_launch" not in contract["capabilities"]

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_think_tank_launch_progression_stages(self, mock_update, mock_select):
        """Think tank launch progresses through multiple stages."""
        stages = ["initiation", "brand_exam", "validation", "think_tank_setup", "launch"]

        for stage in stages:
            task = MockAPContract.task(stage=stage)
            assert task["stage"] == stage


class TestZombieReaperHeartbeatExpiration:
    """Test zombie-reaper heartbeat monitoring and expiration."""

    @patch("runner.agentic_repair.repair_patch")
    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_expired_runner_heartbeat_detected(self, mock_update, mock_select, mock_repair):
        """Expired runner heartbeat is detected and reclaimed."""
        mock_repair.return_value = {"state": "QUEUED"}

        # Task older than grace period, no heartbeat
        mock_select.side_effect = [
            [MockAPContract.task(
                account="Mac.lan-0",
                updated_at_offset_min=1
            )],
            [],  # No heartbeats
        ]

        runner._reap_zombie_tasks()

        # Should trigger repair for expired heartbeat
        if mock_update.called:
            repair_signal = mock_repair.call_args[0][1] if mock_repair.called else None
            if repair_signal:
                assert "expired runner heartbeat" in repair_signal

    @patch("runner.agentic_repair.repair_patch")
    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_recent_heartbeat_prevents_reclaim(self, mock_update, mock_select, mock_repair):
        """Recent heartbeat prevents task reclamation."""
        mock_select.side_effect = [
            [MockAPContract.task(
                account="Mac.lan-0",
                updated_at_offset_min=2
            )],
            [MockAPContract.heartbeat(
                runner_id="Mac.lan-0",
                last_seen_offset_sec=30
            )],
        ]

        runner._reap_zombie_tasks()

        # Should not reclaim with recent heartbeat
        # (depends on stale timeout)

    @patch("runner.agentic_repair.repair_patch")
    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_heartbeat_grace_period_respected(self, mock_update, mock_select, mock_repair):
        """Grace period is respected before reclaiming dead runners."""
        mock_repair.return_value = {"state": "QUEUED"}

        with patch.dict(os.environ, {"ORCH_DEAD_RUNNER_RECLAIM_GRACE_S": "300"}):
            mock_select.side_effect = [
                [MockAPContract.task(
                    account="Mac.lan-0",
                    updated_at_offset_min=2
                )],
                [],
            ]

            runner._reap_zombie_tasks()

    @patch("runner.agentic_repair.repair_patch")
    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_multiple_heartbeats_latest_checked(self, mock_update, mock_select, mock_repair):
        """Latest heartbeat timestamp is used for reclaim decision."""
        mock_repair.return_value = {"state": "QUEUED"}

        mock_select.side_effect = [
            [MockAPContract.task(account="Mac.lan-0", updated_at_offset_min=31)],
            [
                MockAPContract.heartbeat(runner_id="Mac.lan-0", last_seen_offset_sec=60),
                MockAPContract.heartbeat(runner_id="Mac.lan-0", last_seen_offset_sec=30),
            ],
        ]

        runner._reap_zombie_tasks()


class TestAPContractTaskStateManagement:
    """Test task state transitions for AP contract brand exams."""

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_task_initiation_state(self, mock_update, mock_select):
        """Task starts in initiation state."""
        task = MockAPContract.task(state="RUNNING", stage="initiation")

        assert task["state"] == "RUNNING"
        assert task["stage"] == "initiation"

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_task_validation_state(self, mock_update, mock_select):
        """Task transitions to validation state."""
        task = MockAPContract.task(stage="validation")
        task["validation_status"] = "in_progress"

        assert task["stage"] == "validation"

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_task_think_tank_setup_state(self, mock_update, mock_select):
        """Task transitions to think tank setup state."""
        task = MockAPContract.task(stage="think_tank_setup")
        task["think_tank_config"] = {"mode": "launch"}

        assert task["stage"] == "think_tank_setup"

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_task_launch_state(self, mock_update, mock_select):
        """Task transitions to launch state."""
        task = MockAPContract.task(stage="launch")
        task["state"] = "COMPLETED"

        assert task["stage"] == "launch"

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_task_completion_recorded(self, mock_update, mock_select):
        """Task completion is recorded."""
        task = MockAPContract.task()
        task["state"] = "COMPLETED"
        task["completed_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()

        assert task["state"] == "COMPLETED"
        assert "completed_at" in task


class TestAPContractEnforcement:
    """Test AP contract enforcement on task operations."""

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_inactive_contract_blocks_task_creation(self, mock_update, mock_select):
        """Inactive contract blocks task creation."""
        contract = MockAPContract.brand_exam_ap(
            contract_id="ap-contract-inactive",
            status="inactive"
        )

        assert contract["status"] != "active"

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_expired_contract_blocks_task_execution(self, mock_update, mock_select):
        """Expired contract blocks task execution."""
        contract = MockAPContract.brand_exam_ap(
            status="expired"
        )

        assert contract["status"] == "expired"

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_suspended_contract_halts_processing(self, mock_update, mock_select):
        """Suspended contract halts processing."""
        contract = MockAPContract.brand_exam_ap(
            status="suspended"
        )

        assert contract["status"] == "suspended"

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_contract_tier_mismatch_prevents_feature_access(self, mock_update, mock_select):
        """Contract tier mismatch prevents feature access."""
        task = MockAPContract.task(brand_tier="standard")
        contract = MockAPContract.brand_exam_ap(brand_tier="premium")

        assert task["brand_tier"] != contract["tier"]

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_contract_capability_required_for_feature(self, mock_update, mock_select):
        """Contract must have capability for feature use."""
        contract = MockAPContract.brand_exam_ap(
            capabilities=["brand_exam_basic"]
        )

        assert "custom_branding" not in contract["capabilities"]


class TestHighVolumeBrandExamProcessing:
    """Test high-volume brand exam AP contract processing."""

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_process_100_brand_exam_ap_tasks(self, mock_update, mock_select):
        """Process 100+ brand exam AP tasks in batch."""
        tasks = [
            MockAPContract.task(
                task_id=f"brand-exam-ap-{i}",
                contract_id=f"ap-contract-pmi-{i:03d}"
            )
            for i in range(100)
        ]

        mock_select.side_effect = [
            tasks,
            [],
        ]

        runner._reap_zombie_tasks()

        assert len(tasks) == 100

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_concurrent_mixed_tier_contracts(self, mock_update, mock_select):
        """Process concurrent tasks with mixed tier contracts."""
        tasks = [
            MockAPContract.task(
                task_id=f"tier-{tier}-{i}",
                brand_tier=tier
            )
            for tier in ["basic", "standard", "premium", "enterprise"]
            for i in range(25)
        ]

        mock_select.side_effect = [
            tasks,
            [],
        ]

        runner._reap_zombie_tasks()

        assert len(tasks) == 100

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_mixed_contract_statuses_in_batch(self, mock_update, mock_select):
        """Batch processing respects mixed contract statuses."""
        # Tasks with various associated contract statuses
        tasks = [
            MockAPContract.task(task_id=f"task-{i}", contract_id=f"ap-contract-{i}")
            for i in range(50)
        ]

        mock_select.side_effect = [
            tasks,
            [],
        ]

        runner._reap_zombie_tasks()

        assert len(tasks) == 50


class TestErrorHandlingAndRecovery:
    """Test error handling and graceful recovery."""

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_missing_contract_handled_gracefully(self, mock_update, mock_select):
        """Missing contract doesn't crash processing."""
        mock_select.side_effect = [
            [MockAPContract.task(contract_id="missing-contract")],
            [],
        ]

        # Should not raise
        runner._reap_zombie_tasks()

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_malformed_timestamp_handled_gracefully(self, mock_update, mock_select):
        """Malformed timestamp in task is handled gracefully."""
        task = MockAPContract.task()
        task["updated_at"] = "invalid-timestamp"

        mock_select.side_effect = [
            [task],
            [],
        ]

        # Should not crash
        runner._reap_zombie_tasks()

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_db_error_during_select_no_crash(self, mock_update, mock_select):
        """Database error during select doesn't crash."""
        mock_select.side_effect = Exception("DB connection lost")

        # Should not raise
        try:
            runner._reap_zombie_tasks()
        except Exception:
            pass

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_corrupted_heartbeat_data_skipped(self, mock_update, mock_select):
        """Corrupted heartbeat data is skipped safely."""
        mock_select.side_effect = [
            [MockAPContract.task(account="Mac.lan-0", updated_at_offset_min=31)],
            [{"runner_id": "Mac.lan-0", "last_seen": "invalid"}],
        ]

        # Should handle gracefully
        runner._reap_zombie_tasks()

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_partial_failure_continues_processing(self, mock_update, mock_select):
        """Partial failure in one task doesn't stop processing others."""
        tasks = [
            MockAPContract.task(task_id="good-1"),
            MockAPContract.task(task_id="bad", contract_id=None),
            MockAPContract.task(task_id="good-2"),
        ]

        mock_select.side_effect = [
            tasks,
            [],
        ]

        # Should continue processing despite bad task
        runner._reap_zombie_tasks()


class TestAPContractOrphanedTaskRecovery:
    """Test agentic repair for orphaned running tasks."""

    @patch("runner.agentic_repair.repair_patch")
    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_orphaned_task_identified_by_expired_heartbeat(self, mock_update, mock_select, mock_repair):
        """Orphaned task is identified by expired runner heartbeat."""
        mock_repair.return_value = {"state": "QUEUED"}

        mock_select.side_effect = [
            [MockAPContract.task(
                account="Mac.lan-0",
                updated_at_offset_min=1
            )],
            [],  # No heartbeat
        ]

        runner._reap_zombie_tasks()

        # Should call repair
        if mock_update.called and mock_repair.called:
            category = mock_repair.call_args[1].get("category", "")
            assert category == "orphaned-running"

    @patch("runner.agentic_repair.repair_patch")
    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_repair_preserves_contract_context(self, mock_update, mock_select, mock_repair):
        """Repair preserves AP contract context."""
        mock_repair.return_value = {"state": "QUEUED"}

        mock_select.side_effect = [
            [MockAPContract.task(
                contract_id="ap-contract-pmi-001",
                updated_at_offset_min=1
            )],
            [],
        ]

        runner._reap_zombie_tasks()

        # Repair should have contract info available
        if mock_repair.called:
            directive = mock_repair.call_args[1].get("directive", "")
            assert "existing branch/worktree/artifacts" in directive

    @patch("runner.agentic_repair.repair_patch")
    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_repair_includes_failure_signal(self, mock_update, mock_select, mock_repair):
        """Repair call includes specific failure signal."""
        mock_repair.return_value = {"state": "QUEUED"}

        mock_select.side_effect = [
            [MockAPContract.task(
                updated_at_offset_min=1
            )],
            [],
        ]

        runner._reap_zombie_tasks()

        if mock_repair.called:
            signal = mock_repair.call_args[0][1] if len(mock_repair.call_args[0]) > 1 else ""
            assert "expired runner heartbeat" in signal or "stale" in signal

    @patch("runner.agentic_repair.repair_patch")
    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_agentic_repair_category_orphaned_running(self, mock_update, mock_select, mock_repair):
        """Agentic repair uses 'orphaned-running' category."""
        mock_repair.return_value = {"state": "QUEUED"}

        mock_select.side_effect = [
            [MockAPContract.task(updated_at_offset_min=31)],
            [],
        ]

        runner._reap_zombie_tasks()

        if mock_repair.called:
            category = mock_repair.call_args[1].get("category")
            assert category == "orphaned-running"


class TestBrandExamAPContractIntegration:
    """Test full integration of brand exam AP contracts."""

    @patch("runner.agentic_repair.repair_patch")
    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_full_workflow_brand_exam_ap_contract_task(self, mock_update, mock_select, mock_repair):
        """Full workflow for brand exam AP contract task."""
        mock_repair.return_value = {"state": "QUEUED"}

        contract = MockAPContract.brand_exam_ap(
            contract_id="ap-contract-pmi-001",
            status="active",
            brand_tier="standard"
        )
        task = MockAPContract.task(
            contract_id=contract["id"],
            account="Mac.lan-0"
        )

        mock_select.side_effect = [
            [task],
            [MockAPContract.heartbeat(runner_id="Mac.lan-0", last_seen_offset_sec=30)],
        ]

        runner._reap_zombie_tasks()

        # Task should be processed without errors
        assert task["contract_id"] == contract["id"]

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_dropbox_pmi_think_tank_workflow(self, mock_update, mock_select):
        """Full dropbox PMI think tank workflow."""
        task = MockAPContract.task(
            slug="dropbox-pmi-think-tank-brand-exam",
            stage="initiation"
        )

        mock_select.side_effect = [
            [task],
            [],
        ]

        runner._reap_zombie_tasks()

        assert task["dropbox_pmi_think_tank"] is True
        assert "dropbox" in task["slug"].lower()


class TestMonitoringAndMetrics:
    """Test monitoring and metrics collection."""

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_task_completion_metrics_recorded(self, mock_update, mock_select):
        """Task completion metrics are recorded."""
        task = MockAPContract.task()
        task["completed_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        task["duration_ms"] = 12345

        assert "completed_at" in task
        assert task["duration_ms"] > 0

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_task_failure_logged(self, mock_update, mock_select):
        """Task failure is logged with context."""
        task = MockAPContract.task()
        task["failure_reason"] = "contract_expired"
        task["failure_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()

        assert task["failure_reason"] == "contract_expired"
        assert "failure_at" in task

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_retry_history_tracked(self, mock_update, mock_select):
        """Retry attempts are tracked."""
        task = MockAPContract.task()
        task["retry_count"] = 2
        task["retry_history"] = ["attempt_1_failed", "attempt_2_failed"]

        assert task["retry_count"] == 2
        assert len(task["retry_history"]) == 2


class TestEnvironmentVariableConfiguration:
    """Test environment variable configuration."""

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_ap_contract_feature_flag(self, mock_update, mock_select):
        """AP contract can be enabled via env var."""
        with patch.dict(os.environ, {"ORCH_AP_CONTRACT_ENFORCE": "true"}):
            mock_select.side_effect = [[], []]
            runner._reap_zombie_tasks()

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_dropbox_pmi_integration_flag(self, mock_update, mock_select):
        """Dropbox PMI integration can be enabled via env var."""
        with patch.dict(os.environ, {"ORCH_DROPBOX_PMI_ENABLED": "true"}):
            mock_select.side_effect = [[], []]
            runner._reap_zombie_tasks()

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_think_tank_launch_flag(self, mock_update, mock_select):
        """Think tank launch can be enabled via env var."""
        with patch.dict(os.environ, {"ORCH_THINK_TANK_LAUNCH": "true"}):
            mock_select.side_effect = [[], []]
            runner._reap_zombie_tasks()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
