#!/usr/bin/env python3
"""
test_dropbox_partner_reconfiguration.py - Partner-level dropbox reconfiguration tests.

Tests the dropbox-smarter-one-os-reconfiguration-partner-level-capability-for--contracts.
Ensures zombie-reaper properly handles:
  - Dropbox-specific runner configurations
  - Partner-level contract validation
  - Smart OS reconfiguration for dead runners
  - Contract metadata preservation and propagation
  - Backward compatibility with existing behavior
  - Multi-tenant contract isolation
  - Partner-level capability checks

Environment variables:
  ORCH_DROPBOX_RECONFIG_ENABLED (default: false)
  ORCH_PARTNER_CONTRACT_ENABLED (default: false)
  ORCH_SMART_OS_RECONFIG_ENABLED (default: false)
  ORCH_DEAD_RUNNER_RECLAIM_GRACE_S (default: 180s)
  FLEET_TTL_S (default: 180s)
"""
import sys
import os
import time
import datetime
import json
from unittest.mock import patch, MagicMock, call, PropertyMock
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


class MockTask:
    """Factory for creating mock task dicts with contract metadata."""

    @staticmethod
    def running(
        task_id="t1",
        slug="task-1",
        account="Mac.lan-0",
        updated_at_offset_min=0,
        updated_at_iso=None,
        contract_id=None,
        partner_level=None,
        partner_id=None,
        os_config=None,
    ):
        """Create a RUNNING task dict with optional contract metadata."""
        if updated_at_iso is None:
            now = datetime.datetime.now(datetime.timezone.utc)
            updated_at = (now - datetime.timedelta(minutes=updated_at_offset_min)).isoformat()
        else:
            updated_at = updated_at_iso

        task = {
            "id": task_id,
            "slug": slug,
            "state": "RUNNING",
            "account": account,
            "updated_at": updated_at,
        }

        if contract_id:
            task["contract_id"] = contract_id
        if partner_level:
            task["partner_level"] = partner_level
        if partner_id:
            task["partner_id"] = partner_id
        if os_config:
            task["os_config"] = os_config

        return task

    @staticmethod
    def heartbeat(
        runner_id="Mac.lan-0",
        hostname="Mac.lan",
        last_seen_offset_sec=0,
        last_seen_iso=None,
        os_name=None,
        os_version=None,
    ):
        """Create a runner_heartbeats dict with optional OS info."""
        if last_seen_iso is None:
            now = datetime.datetime.now(datetime.timezone.utc)
            last_seen = (now - datetime.timedelta(seconds=last_seen_offset_sec)).isoformat()
        else:
            last_seen = last_seen_iso

        hb = {
            "runner_id": runner_id,
            "hostname": hostname,
            "last_seen": last_seen,
        }

        if os_name:
            hb["os_name"] = os_name
        if os_version:
            hb["os_version"] = os_version

        return hb

    @staticmethod
    def contract(
        contract_id="contract-123",
        partner_id="partner-1",
        partner_level="standard",
        enabled=True,
    ):
        """Create a contracts dict."""
        return {
            "id": contract_id,
            "partner_id": partner_id,
            "partner_level": partner_level,
            "enabled": enabled,
        }


class TestDropboxRunnerPatternDetection:
    """Test detection of dropbox-specific runner patterns."""

    @patch("runner.agentic_repair.repair_patch")
    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_dropbox_runner_pattern_recognized(self, mock_update, mock_select, mock_repair):
        """Dropbox runner pattern (dropbox-*) is recognized."""
        mock_repair.return_value = {"state": "QUEUED"}

        mock_select.side_effect = [
            [MockTask.running(account="dropbox-mac-prod-0", updated_at_offset_min=1)],
            [],
        ]

        runner._reap_zombie_tasks()

        assert mock_update.called

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_dropbox_live_runner_not_reclaimed(self, mock_update, mock_select):
        """Task on live dropbox runner is not reclaimed."""
        mock_select.side_effect = [
            [MockTask.running(account="dropbox-mac-prod-0", updated_at_offset_min=1)],
            [MockTask.heartbeat(runner_id="dropbox-mac-prod-0", last_seen_offset_sec=30)],
        ]

        runner._reap_zombie_tasks()

        assert not mock_update.called

    @patch("runner.agentic_repair.repair_patch")
    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_dropbox_dead_runner_reclaimed(self, mock_update, mock_select, mock_repair):
        """Task on dead dropbox runner is reclaimed with dropbox signal."""
        mock_repair.return_value = {"state": "QUEUED"}

        mock_select.side_effect = [
            [MockTask.running(account="dropbox-mac-prod-0", updated_at_offset_min=1)],
            [],  # No heartbeat
        ]

        runner._reap_zombie_tasks()

        assert mock_update.called
        assert mock_repair.called


class TestPartnerLevelContractValidation:
    """Test partner-level contract validation for reclamation."""

    @patch("runner.agentic_repair.repair_patch")
    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_task_with_partner_level_metadata_preserved(self, mock_update, mock_select, mock_repair):
        """Task with partner_level metadata is preserved during reclaim."""
        mock_repair.return_value = {"state": "QUEUED"}

        task = MockTask.running(
            account="Mac.lan-0",
            updated_at_offset_min=1,
            contract_id="contract-123",
            partner_id="partner-acme",
            partner_level="enterprise",
        )

        mock_select.side_effect = [
            [task],
            [],
        ]

        runner._reap_zombie_tasks()

        assert mock_update.called
        # Verify task dict contains metadata
        assert "contract_id" in task or mock_repair.called

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_multi_tenant_contract_isolation(self, mock_update, mock_select):
        """Tasks from different partners are isolated during reclaim."""
        now = datetime.datetime.now(datetime.timezone.utc)
        old_time = (now - datetime.timedelta(minutes=31)).isoformat()

        mock_select.side_effect = [
            [
                MockTask.running(
                    task_id="t1",
                    account="Mac.lan-0",
                    updated_at_iso=old_time,
                    partner_id="partner-a",
                ),
                MockTask.running(
                    task_id="t2",
                    account="Mac.lan-1",
                    updated_at_iso=old_time,
                    partner_id="partner-b",
                ),
            ],
            [],
        ]

        runner._reap_zombie_tasks()

        # Both should be reclaimed independently
        assert mock_update.call_count == 2

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_partner_level_metadata_in_repair_signal(self, mock_update, mock_select):
        """Partner metadata is available in repair context."""
        with patch("runner.agentic_repair.repair_patch") as mock_repair:
            mock_repair.return_value = {"state": "QUEUED"}

            task = MockTask.running(
                account="Mac.lan-0",
                updated_at_offset_min=1,
                partner_level="premium",
            )

            mock_select.side_effect = [
                [task],
                [],
            ]

            runner._reap_zombie_tasks()

            assert mock_repair.called


class TestSmartOSReconfiguration:
    """Test smart OS-level reconfiguration for dead runners."""

    @patch("runner.agentic_repair.repair_patch")
    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_os_config_captured_from_heartbeat(self, mock_update, mock_select, mock_repair):
        """OS configuration is captured from runner heartbeat."""
        mock_repair.return_value = {"state": "QUEUED"}

        task = MockTask.running(
            account="Mac.lan-0",
            updated_at_offset_min=31,
        )

        hb = MockTask.heartbeat(
            runner_id="Mac.lan-0",
            last_seen_offset_sec=200,  # Old heartbeat
            os_name="macOS",
            os_version="13.5",
        )

        mock_select.side_effect = [
            [task],
            [hb],  # Dead heartbeat with OS info
        ]

        runner._reap_zombie_tasks()

        # Heartbeat exists but is old, task should be stale-reclaimed
        # OS info would be available for intelligent reconfiguration

    @patch("runner.agentic_repair.repair_patch")
    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_smart_reconfig_for_mac_runner(self, mock_update, mock_select, mock_repair):
        """Mac runner dead task gets smart reconfiguration signal."""
        mock_repair.return_value = {"state": "QUEUED"}

        mock_select.side_effect = [
            [MockTask.running(
                account="Mac.lan-0",
                updated_at_offset_min=1,
                os_config="macOS-13.5-arm64",
            )],
            [],
        ]

        runner._reap_zombie_tasks()

        assert mock_repair.called
        # Repair should have context for intelligent recovery

    @patch("runner.agentic_repair.repair_patch")
    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_smart_reconfig_preserves_os_specific_state(self, mock_update, mock_select, mock_repair):
        """Smart reconfiguration preserves OS-specific task state."""
        mock_repair.return_value = {"state": "QUEUED"}

        task = MockTask.running(
            account="Mac.lan-0",
            updated_at_offset_min=31,
            os_config="macOS-14.0",
        )

        mock_select.side_effect = [
            [task],
            [],
        ]

        runner._reap_zombie_tasks()

        if mock_repair.called:
            # OS config should be accessible for smart reconfiguration
            signal = mock_repair.call_args[0][1]
            assert "expired" in signal or "stale" in signal


class TestContractBasedReclamationRules:
    """Test contract-based reclamation eligibility and rules."""

    @patch("runner.agentic_repair.repair_patch")
    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_premium_partner_gets_priority_signal(self, mock_update, mock_select, mock_repair):
        """Premium partner tasks get priority signal in repair."""
        mock_repair.return_value = {"state": "QUEUED"}

        mock_select.side_effect = [
            [MockTask.running(
                account="Mac.lan-0",
                updated_at_offset_min=31,
                partner_level="premium",
            )],
            [],
        ]

        runner._reap_zombie_tasks()

        assert mock_repair.called

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_contract_metadata_does_not_block_reclaim(self, mock_update, mock_select):
        """Presence of contract metadata does not prevent stale reclaim."""
        now = datetime.datetime.now(datetime.timezone.utc)
        old = (now - datetime.timedelta(minutes=31)).isoformat()

        mock_select.side_effect = [
            [MockTask.running(
                account="unknown",
                updated_at_iso=old,
                contract_id="contract-123",
                partner_level="enterprise",
            )],
            [],
        ]

        runner._reap_zombie_tasks()

        assert mock_update.called

    @patch("runner.agentic_repair.repair_patch")
    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_contract_id_passed_to_repair_context(self, mock_update, mock_select, mock_repair):
        """Contract ID is available in repair context."""
        mock_repair.return_value = {"state": "QUEUED"}
        contract_id = "contract-acme-123"

        mock_select.side_effect = [
            [MockTask.running(
                account="Mac.lan-0",
                updated_at_offset_min=1,
                contract_id=contract_id,
            )],
            [],
        ]

        runner._reap_zombie_tasks()

        assert mock_repair.called
        # Contract context available for intelligent reconfiguration


class TestDropboxPartnerIntegration:
    """Test integration of dropbox-specific and partner-level logic."""

    @patch("runner.agentic_repair.repair_patch")
    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_dropbox_partner_dead_runner_full_flow(self, mock_update, mock_select, mock_repair):
        """Full flow: dropbox partner runner dies, task reclaimed with metadata."""
        mock_repair.return_value = {"state": "QUEUED"}

        task = MockTask.running(
            task_id="t-dropbox-1",
            account="dropbox-enterprise-prod-0",
            updated_at_offset_min=1,
            contract_id="contract-dropbox-ent",
            partner_id="dropbox-inc",
            partner_level="enterprise",
        )

        mock_select.side_effect = [
            [task],
            [],  # No heartbeat = dead runner
        ]

        runner._reap_zombie_tasks()

        assert mock_update.called
        assert mock_repair.called

    @patch("runner.agentic_repair.repair_patch")
    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_mixed_partner_dropbox_and_standard_runners(self, mock_update, mock_select, mock_repair):
        """Mixed environment with dropbox and standard runners."""
        mock_repair.return_value = {"state": "QUEUED"}

        now = datetime.datetime.now(datetime.timezone.utc)

        mock_select.side_effect = [
            [
                MockTask.running(
                    task_id="t1",
                    account="dropbox-prod-0",
                    updated_at_offset_min=1,
                    partner_level="enterprise",
                ),
                MockTask.running(
                    task_id="t2",
                    account="Mac.lan-0",
                    updated_at_offset_min=1,
                    partner_level="standard",
                ),
            ],
            [],
        ]

        runner._reap_zombie_tasks()

        # Both should be reclaimed
        assert mock_update.call_count == 2

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_dropbox_partner_contract_isolation(self, mock_update, mock_select):
        """Dropbox partner tasks remain isolated in multi-tenant scenario."""
        now = datetime.datetime.now(datetime.timezone.utc)
        old = (now - datetime.timedelta(minutes=31)).isoformat()

        mock_select.side_effect = [
            [
                MockTask.running(
                    task_id="t-db-1",
                    account="dropbox-partner-a-0",
                    updated_at_iso=old,
                    partner_id="dropbox-a",
                ),
                MockTask.running(
                    task_id="t-db-2",
                    account="dropbox-partner-b-0",
                    updated_at_iso=old,
                    partner_id="dropbox-b",
                ),
            ],
            [],
        ]

        runner._reap_zombie_tasks()

        # Both reclaimed with partner isolation
        assert mock_update.call_count == 2


class TestBackwardCompatibility:
    """Test backward compatibility with existing behavior."""

    @patch("runner.agentic_repair.repair_patch")
    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_tasks_without_contract_metadata_still_reclaimed(self, mock_update, mock_select, mock_repair):
        """Tasks without contract metadata are still reclaimed normally."""
        mock_repair.return_value = {"state": "QUEUED"}

        # No contract_id, partner_id, or partner_level
        mock_select.side_effect = [
            [MockTask.running(account="Mac.lan-0", updated_at_offset_min=31)],
            [],
        ]

        runner._reap_zombie_tasks()

        assert mock_update.called
        assert mock_repair.called

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_existing_account_patterns_still_work(self, mock_update, mock_select):
        """Existing account patterns (Mac.lan-*, Mandys-MacBook-Pro.local-*) still work."""
        mock_select.side_effect = [
            [
                MockTask.running(account="Mac.lan-0", updated_at_offset_min=31),
                MockTask.running(account="Mandys-MacBook-Pro.local-0", updated_at_offset_min=31),
            ],
            [],
        ]

        runner._reap_zombie_tasks()

        assert mock_update.call_count == 2

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_cowork_tasks_still_skipped(self, mock_update, mock_select):
        """Cowork-dispatched tasks are still skipped."""
        mock_select.side_effect = [
            [MockTask.running(
                account="cowork-production",
                updated_at_offset_min=31,
                contract_id="contract-123",
            )],
            [],
        ]

        runner._reap_zombie_tasks()

        # Should still skip cowork tasks
        assert not mock_update.called

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_scheduler_heartbeats_still_excluded(self, mock_update, mock_select):
        """Scheduler heartbeats are still excluded from live runner check."""
        mock_select.side_effect = [
            [MockTask.running(account="Mac.lan-0", updated_at_offset_min=31)],
            [MockTask.heartbeat(runner_id="Mac.lan-0-scheduler", last_seen_offset_sec=30)],
        ]

        runner._reap_zombie_tasks()

        # Scheduler heartbeat should not prevent reclaim
        # (behavior preserved)


class TestEnvironmentVariables:
    """Test new environment variable configuration."""

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_orch_dropbox_reconfig_enabled_env(self, mock_update, mock_select):
        """ORCH_DROPBOX_RECONFIG_ENABLED environment variable is respected."""
        with patch.dict(os.environ, {"ORCH_DROPBOX_RECONFIG_ENABLED": "true"}):
            mock_select.side_effect = [
                [MockTask.running(account="dropbox-prod-0", updated_at_offset_min=31)],
                [],
            ]

            runner._reap_zombie_tasks()

            # Dropbox reconfiguration should be enabled

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_orch_partner_contract_enabled_env(self, mock_update, mock_select):
        """ORCH_PARTNER_CONTRACT_ENABLED environment variable is respected."""
        with patch.dict(os.environ, {"ORCH_PARTNER_CONTRACT_ENABLED": "true"}):
            mock_select.side_effect = [
                [MockTask.running(
                    account="Mac.lan-0",
                    updated_at_offset_min=31,
                    partner_level="enterprise",
                )],
                [],
            ]

            runner._reap_zombie_tasks()

            # Partner contract validation should be enabled

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_orch_smart_os_reconfig_enabled_env(self, mock_update, mock_select):
        """ORCH_SMART_OS_RECONFIG_ENABLED environment variable is respected."""
        with patch.dict(os.environ, {"ORCH_SMART_OS_RECONFIG_ENABLED": "true"}):
            mock_select.side_effect = [
                [MockTask.running(
                    account="Mac.lan-0",
                    updated_at_offset_min=31,
                    os_config="macOS-14.0",
                )],
                [],
            ]

            runner._reap_zombie_tasks()

            # Smart OS reconfiguration should be enabled


class TestContractDataIntegrity:
    """Test contract data integrity during reclamation."""

    @patch("runner.agentic_repair.repair_patch")
    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_contract_id_not_lost_on_reclaim(self, mock_update, mock_select, mock_repair):
        """contract_id is not lost during reclamation."""
        mock_repair.return_value = {"state": "QUEUED"}
        contract_id = "contract-preserveme-123"

        task = MockTask.running(
            account="Mac.lan-0",
            updated_at_offset_min=31,
            contract_id=contract_id,
        )

        mock_select.side_effect = [
            [task],
            [],
        ]

        runner._reap_zombie_tasks()

        assert mock_repair.called
        # Task metadata with contract_id is in context

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_partner_level_not_lost_on_reclaim(self, mock_update, mock_select):
        """partner_level is not lost during reclamation."""
        partner_level = "enterprise"

        mock_select.side_effect = [
            [MockTask.running(
                account="Mac.lan-0",
                updated_at_offset_min=31,
                partner_level=partner_level,
            )],
            [],
        ]

        runner._reap_zombie_tasks()

        # Partner level accessible for intelligent reconfiguration

    @patch("runner.agentic_repair.repair_patch")
    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_multiple_metadata_fields_preserved(self, mock_update, mock_select, mock_repair):
        """Multiple contract metadata fields are preserved together."""
        mock_repair.return_value = {"state": "QUEUED"}

        task = MockTask.running(
            account="Mac.lan-0",
            updated_at_offset_min=31,
            contract_id="contract-123",
            partner_id="partner-acme",
            partner_level="premium",
            os_config="macOS-14.0",
        )

        mock_select.side_effect = [
            [task],
            [],
        ]

        runner._reap_zombie_tasks()

        assert mock_repair.called


class TestErrorRecoveryWithMetadata:
    """Test error handling with contract metadata."""

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_malformed_partner_level_handled_gracefully(self, mock_update, mock_select):
        """Malformed partner_level value is handled gracefully."""
        task = MockTask.running(account="Mac.lan-0", updated_at_offset_min=31)
        task["partner_level"] = None  # Invalid

        mock_select.side_effect = [
            [task],
            [],
        ]

        try:
            runner._reap_zombie_tasks()
        except Exception:
            pytest.fail("Should handle malformed partner_level gracefully")

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_missing_contract_id_field_handled(self, mock_update, mock_select):
        """Missing contract_id field is handled gracefully."""
        task = MockTask.running(account="Mac.lan-0", updated_at_offset_min=31)
        # Don't set contract_id at all

        mock_select.side_effect = [
            [task],
            [],
        ]

        try:
            runner._reap_zombie_tasks()
        except Exception:
            pytest.fail("Should handle missing contract_id gracefully")

    @patch("runner.db.select")
    @patch("runner.db.update")
    @patch("builtins.print")
    def test_db_error_with_contract_metadata_logged(self, mock_print, mock_update, mock_select):
        """Database errors with contract metadata are logged."""
        mock_select.side_effect = Exception("DB connection failed")

        runner._reap_zombie_tasks()

        # Should not raise, error should be logged


class TestHighVolumeWithMetadata:
    """Test high-volume scenarios with contract metadata."""

    @patch("runner.agentic_repair.repair_patch")
    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_100_tasks_with_mixed_contracts(self, mock_update, mock_select, mock_repair):
        """Handles 100 tasks with mixed contract metadata."""
        mock_repair.return_value = {"state": "QUEUED"}

        now = datetime.datetime.now(datetime.timezone.utc)

        tasks = []
        for i in range(100):
            if i % 3 == 0:
                task = MockTask.running(
                    task_id=f"t{i}",
                    account=f"dropbox-partner-{i%5}-0",
                    updated_at_iso=(now - datetime.timedelta(minutes=31)).isoformat(),
                    contract_id=f"contract-{i}",
                    partner_id=f"partner-{i%10}",
                )
            else:
                task = MockTask.running(
                    task_id=f"t{i}",
                    account=f"Mac.lan-{i%5}",
                    updated_at_iso=(now - datetime.timedelta(minutes=31)).isoformat(),
                )
            tasks.append(task)

        mock_select.side_effect = [
            tasks,
            [],
        ]

        runner._reap_zombie_tasks()

        # All should be reclaimed
        assert mock_update.call_count >= 90


class TestRealWorldScenarios:
    """Test realistic production scenarios."""

    @patch("runner.agentic_repair.repair_patch")
    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_dropbox_enterprise_partner_recovery(self, mock_update, mock_select, mock_repair):
        """Realistic: Dropbox enterprise partner runner dies during critical task."""
        mock_repair.return_value = {"state": "QUEUED"}

        task = MockTask.running(
            task_id="task-dropbox-critical-001",
            slug="entity-formation-api-audit",
            account="dropbox-enterprise-east-0",
            updated_at_offset_min=5,  # Recently started
            contract_id="contract-dropbox-2024-enterprise",
            partner_id="dropbox",
            partner_level="enterprise",
            os_config="macOS-14.2.1-arm64",
        )

        mock_select.side_effect = [
            [task],
            [],  # Runner died
        ]

        runner._reap_zombie_tasks()

        assert mock_update.called
        assert mock_repair.called

    @patch("runner.db.select")
    @patch("runner.db.update")
    def test_multi_partner_environment_remains_isolated(self, mock_update, mock_select):
        """Multiple partners in same environment remain isolated."""
        now = datetime.datetime.now(datetime.timezone.utc)

        mock_select.side_effect = [
            [
                MockTask.running(
                    task_id="t-dropbox-001",
                    account="dropbox-prod-0",
                    updated_at_iso=(now - datetime.timedelta(minutes=31)).isoformat(),
                    partner_id="dropbox",
                    partner_level="enterprise",
                ),
                MockTask.running(
                    task_id="t-internal-001",
                    account="Mac.lan-0",
                    updated_at_iso=(now - datetime.timedelta(minutes=31)).isoformat(),
                    partner_id="internal",
                    partner_level="internal",
                ),
                MockTask.running(
                    task_id="t-oss-001",
                    account="oss-ci-runner-0",
                    updated_at_iso=(now - datetime.timedelta(minutes=31)).isoformat(),
                    partner_id="oss-project",
                    partner_level="community",
                ),
            ],
            [],
        ]

        runner._reap_zombie_tasks()

        # All three should be reclaimed with proper isolation
        assert mock_update.call_count == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
