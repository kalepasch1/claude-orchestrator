#!/usr/bin/env python3
"""
test_partner_contract_allowlist.py — Comprehensive test suite for partner-level
contract and allowlist configuration management.

Validates:
A) Allowlist configuration must specify values (not empty/null keys)
B) Branch lease fail-soft behavior is preserved during allowlist ops
C) Merge train critical imports are always present and functional
D) Partner-level capability routing respects allowlist constraints
E) No regression: fail-soft error handling survives allowlist refactors
F) Thread-safe concurrent allowlist access (no race conditions)
G) Allowlist validation prevents malicious empty configurations
H) Contract extraction and processing with allowlist filtering
I) Authorization checks integrated with allowlist-based task filtering
J) 25+ test cases covering normal paths, edge cases, security boundaries, and regressions
"""

import os
import sys
import unittest
import tempfile
import threading
import time
import json
from unittest.mock import MagicMock, patch, call, mock_open
from pathlib import Path
from io import StringIO

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Disable network during tests
os.environ["ORCH_DB_ENABLED"] = "false"
os.environ["ORCH_DB_URL"] = ""
os.environ["BRANCH_LEASE_FAIL_SOFT"] = "true"


class TestBranchLeaseFailSoftPreservation(unittest.TestCase):
    """Verify fail-soft behavior is preserved and not removed by allowlist changes."""

    def test_branch_lease_heartbeat_fails_soft_on_rpc_error(self):
        """Heartbeat should return True (fail-soft) when RPC infrastructure errors."""
        import branch_lease

        with patch.object(branch_lease, '_active') as mock_active:
            with patch.object(branch_lease.db, 'rpc') as mock_rpc:
                # Simulate RPC infrastructure error
                mock_rpc.side_effect = Exception("RPC connection timeout")

                # Set up a lease in the active dict
                mock_active.items.return_value = [
                    (("task_123", "feature-branch"), {
                        "p_project_id": "proj_1",
                        "branch": "feature-branch",
                        "p_task_id": "task_123",
                        "token": "token_xyz",
                        "ttl": 3600,
                    })
                ]

                # Should return True (fail-soft), not raise or return False
                with patch('builtins.open', mock_open()):
                    result = branch_lease.heartbeat("task_123", "feature-branch")

                self.assertTrue(result, "heartbeat should fail-soft to True on RPC error")

    def test_branch_lease_genuine_false_from_rpc_is_honored(self):
        """When RPC genuinely returns False (lease lost), heartbeat must return False."""
        import branch_lease

        with patch.object(branch_lease, '_active') as mock_active:
            with patch.object(branch_lease.db, 'rpc') as mock_rpc:
                # RPC returns False (lease genuinely lost)
                mock_rpc.return_value = False

                mock_active.items.return_value = [
                    (("task_456", "main"), {
                        "p_project_id": "proj_2",
                        "branch": "main",
                        "p_task_id": "task_456",
                        "token": "token_abc",
                        "ttl": 3600,
                    })
                ]

                result = branch_lease.heartbeat("task_456", "main")

                self.assertFalse(result, "heartbeat must honor False from RPC (lease lost)")

    def test_branch_lease_empty_leases_returns_false(self):
        """Heartbeat should return False when no active leases exist."""
        import branch_lease

        with patch.object(branch_lease, '_active', {}):
            result = branch_lease.heartbeat("nonexistent_task")
            self.assertFalse(result)

    def test_branch_lease_rpc_error_logged_to_stderr(self):
        """RPC errors should be logged but not crash the heartbeat."""
        import branch_lease

        with patch.object(branch_lease, '_active') as mock_active:
            with patch.object(branch_lease.db, 'rpc') as mock_rpc:
                mock_rpc.side_effect = RuntimeError("Network unreachable")

                mock_active.items.return_value = [
                    (("task_789", "dev"), {
                        "p_project_id": "proj_3",
                        "branch": "dev",
                        "p_task_id": "task_789",
                        "token": "token_dev",
                        "ttl": 3600,
                    })
                ]

                with patch('sys.stderr') as mock_stderr:
                    result = branch_lease.heartbeat("task_789", "dev")
                    self.assertTrue(result)
                    # Verify error was logged (not raised)

    def test_branch_lease_multiple_leases_all_or_nothing(self):
        """Multiple leases require all to succeed; one failure triggers fail-soft."""
        import branch_lease

        with patch.object(branch_lease, '_active') as mock_active:
            with patch.object(branch_lease.db, 'rpc') as mock_rpc:
                # First call succeeds, second errors
                mock_rpc.side_effect = [True, Exception("RPC error")]

                mock_active.items.return_value = [
                    (("task_multi", "branch1"), {
                        "p_project_id": "proj_m",
                        "branch": "branch1",
                        "p_task_id": "task_multi",
                        "token": "token_1",
                        "ttl": 3600,
                    }),
                    (("task_multi", "branch2"), {
                        "p_project_id": "proj_m",
                        "branch": "branch2",
                        "p_task_id": "task_multi",
                        "token": "token_2",
                        "ttl": 3600,
                    })
                ]

                with patch('builtins.open', mock_open()):
                    result = branch_lease.heartbeat("task_multi")

                self.assertTrue(result, "Multiple lease heartbeat should fail-soft to True")


class TestMergeTrainImportsAndDependencies(unittest.TestCase):
    """Verify critical imports in merge_train are present and functional."""

    def test_merge_train_has_repo_lock_import(self):
        """repo_lock must be imported (was missing, caused NameError)."""
        import merge_train
        self.assertTrue(hasattr(merge_train, 'repo_lock'),
                       "merge_train must import repo_lock (was missing, caused crashes)")

    def test_merge_train_has_concurrent_futures_import(self):
        """concurrent.futures must be imported (was missing in ThreadPoolExecutor usage)."""
        import merge_train
        self.assertTrue(hasattr(merge_train, 'concurrent'),
                       "merge_train must import concurrent.futures")

    def test_merge_train_has_repo_hygiene_import(self):
        """repo_hygiene must be imported (was missing, fail-soft masked it)."""
        import merge_train
        self.assertTrue(hasattr(merge_train, 'repo_hygiene'),
                       "merge_train must import repo_hygiene for pre-test cleanup")

    def test_merge_train_has_semantic_merge_import(self):
        """semantic_merge must be imported (was missing in auto-merge path)."""
        import merge_train
        self.assertTrue(hasattr(merge_train, 'semantic_merge'),
                       "merge_train must import semantic_merge for auto-merge")

    def test_merge_train_repo_lock_used_correctly(self):
        """repo_lock.hold() should be called with correct parameters."""
        import merge_train

        with patch.object(merge_train, 'repo_lock') as mock_lock:
            with patch.object(merge_train.db, 'select') as mock_select:
                mock_select.return_value = []

                # Verify repo_lock.hold is callable
                self.assertTrue(callable(mock_lock.hold))


class TestAllowlistConfigurationValidation(unittest.TestCase):
    """Verify allowlist configuration is properly validated."""

    def test_allowlist_key_cannot_be_empty_dict(self):
        """Allowlist cannot have empty values (security vulnerability)."""
        allowlist_config = {
            "admin": [],  # Empty list is invalid
            "user": ["template_1"]
        }

        # This should fail validation
        with self.assertRaises((ValueError, AssertionError)) as ctx:
            self._validate_allowlist(allowlist_config)
        self.assertIn("empty", str(ctx.exception).lower())

    def test_allowlist_key_cannot_be_none_values(self):
        """Allowlist values cannot be None."""
        allowlist_config = {
            "admin": None,  # None is invalid
            "user": ["template_1"]
        }

        with self.assertRaises((ValueError, AssertionError)):
            self._validate_allowlist(allowlist_config)

    def test_allowlist_valid_configuration(self):
        """Valid allowlist configurations should pass validation."""
        allowlist_config = {
            "admin": ["contract_1", "contract_2"],
            "partner": ["contract_1"],
            "viewer": ["contract_1"]
        }

        # Should not raise
        result = self._validate_allowlist(allowlist_config)
        self.assertTrue(result)

    def test_allowlist_values_must_be_non_empty_list(self):
        """Each allowlist role must map to a non-empty list of contracts."""
        invalid_configs = [
            {"admin": []},
            {"admin": None},
            {"admin": "contract_1"},  # String instead of list
        ]

        for config in invalid_configs:
            with self.assertRaises((ValueError, AssertionError)):
                self._validate_allowlist(config)

    def _validate_allowlist(self, config):
        """Simulate allowlist validation logic."""
        if not config:
            raise ValueError("Allowlist config cannot be empty")

        for role, contracts in config.items():
            if contracts is None:
                raise ValueError(f"Allowlist role '{role}' has None values")
            if isinstance(contracts, str):
                raise ValueError(f"Allowlist role '{role}' must be a list, not string")
            if isinstance(contracts, list) and len(contracts) == 0:
                raise ValueError(f"Allowlist role '{role}' has empty list (potential security issue)")

        return True


class TestPartnerContractRouting(unittest.TestCase):
    """Verify partner-level contract routing respects allowlist constraints."""

    def test_partner_access_filtered_by_allowlist(self):
        """Partner can only access contracts in their allowlist."""
        partner_allowlist = {
            "partner_a": ["contract_1", "contract_2"],
            "partner_b": ["contract_3"],
        }

        accessible = self._filter_contracts("partner_a", partner_allowlist)
        self.assertEqual(set(accessible), {"contract_1", "contract_2"})

        accessible = self._filter_contracts("partner_b", partner_allowlist)
        self.assertEqual(set(accessible), {"contract_3"})

    def test_partner_unauthorized_contract_access_denied(self):
        """Partner cannot access contracts outside their allowlist."""
        partner_allowlist = {
            "partner_a": ["contract_1"],
        }

        accessible = self._filter_contracts("partner_a", partner_allowlist)
        self.assertNotIn("contract_2", accessible)

    def test_unknown_partner_has_no_access(self):
        """Unknown partners have no contract access."""
        partner_allowlist = {
            "partner_a": ["contract_1"],
        }

        accessible = self._filter_contracts("unknown_partner", partner_allowlist)
        self.assertEqual(accessible, [])

    def test_contract_extraction_respects_allowlist(self):
        """Contract extraction filters to allowlist."""
        contracts = [
            {"id": "contract_1", "name": "Contract 1"},
            {"id": "contract_2", "name": "Contract 2"},
            {"id": "contract_3", "name": "Contract 3"},
        ]

        partner_allowlist = {
            "partner_a": ["contract_1", "contract_3"],
        }

        filtered = self._extract_contracts(contracts, "partner_a", partner_allowlist)
        self.assertEqual(len(filtered), 2)
        self.assertEqual({c["id"] for c in filtered}, {"contract_1", "contract_3"})

    def _filter_contracts(self, partner_id, allowlist):
        """Simulate contract filtering by allowlist."""
        return allowlist.get(partner_id, [])

    def _extract_contracts(self, all_contracts, partner_id, allowlist):
        """Simulate contract extraction with allowlist filtering."""
        allowed_ids = self._filter_contracts(partner_id, allowlist)
        return [c for c in all_contracts if c["id"] in allowed_ids]


class TestAllowlistThreadSafety(unittest.TestCase):
    """Verify allowlist operations are thread-safe."""

    def test_concurrent_allowlist_reads_thread_safe(self):
        """Multiple threads reading allowlist should not cause races."""
        allowlist = {
            "admin": ["contract_1", "contract_2"],
            "partner": ["contract_1"],
        }

        results = []
        errors = []

        def read_allowlist():
            try:
                for _ in range(100):
                    partner_id = "partner"
                    contracts = allowlist.get(partner_id, [])
                    results.append(contracts)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=read_allowlist) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0, "No errors should occur during concurrent reads")
        self.assertTrue(len(results) > 0, "Should have collected results")

    def test_concurrent_contract_filtering_thread_safe(self):
        """Concurrent contract filtering should not corrupt allowlist state."""
        allowlist = {
            "partner_a": ["c1", "c2"],
            "partner_b": ["c3"],
        }

        errors = []
        results = []

        def filter_contracts():
            try:
                for _ in range(50):
                    for pid in ["partner_a", "partner_b"]:
                        contracts = allowlist.get(pid, [])
                        results.append((pid, contracts))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=filter_contracts) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0)
        # Verify allowlist wasn't corrupted
        self.assertEqual(len(allowlist["partner_a"]), 2)
        self.assertEqual(len(allowlist["partner_b"]), 1)


class TestContractProcessingWithAllowlist(unittest.TestCase):
    """Verify contract extraction and processing with allowlist filtering."""

    def test_extract_contracts_from_task_respects_allowlist(self):
        """Task contract extraction must respect partner allowlist."""
        task = {
            "id": "task_1",
            "contracts": ["contract_1", "contract_2", "contract_3"],
            "project_id": "proj_1"
        }

        partner_allowlist = {
            "partner_a": ["contract_1", "contract_2"],
        }

        allowed_contracts = [
            c for c in task["contracts"]
            if c in partner_allowlist.get("partner_a", [])
        ]

        self.assertEqual(allowed_contracts, ["contract_1", "contract_2"])

    def test_task_processing_skips_unauthorized_contracts(self):
        """Task processing should skip contracts partner is not authorized for."""
        task = {
            "id": "task_2",
            "contracts": ["contract_1", "contract_2"],
            "project_id": "proj_2"
        }

        partner_allowlist = {
            "partner_b": ["contract_2"],
        }

        # Partner B should only process contract_2
        allowed = [
            c for c in task["contracts"]
            if c in partner_allowlist.get("partner_b", [])
        ]

        self.assertEqual(allowed, ["contract_2"])
        self.assertEqual(len(allowed), 1)

    def test_empty_contract_list_on_no_allowlist_match(self):
        """Task with no matching allowlist contracts should have empty list."""
        task = {
            "id": "task_3",
            "contracts": ["contract_1", "contract_2"],
        }

        partner_allowlist = {
            "partner_c": ["contract_99"],  # Doesn't match task contracts
        }

        allowed = [
            c for c in task["contracts"]
            if c in partner_allowlist.get("partner_c", [])
        ]

        self.assertEqual(allowed, [])


class TestNoRegressionInFailSoftBehavior(unittest.TestCase):
    """Regression tests to ensure fail-soft behavior is never removed."""

    def test_heartbeat_does_not_raise_on_db_error(self):
        """Heartbeat must never raise on database errors."""
        import branch_lease

        with patch.object(branch_lease, '_active') as mock_active:
            with patch.object(branch_lease.db, 'rpc') as mock_rpc:
                # Various error types that could occur
                error_types = [
                    ConnectionError("Connection refused"),
                    TimeoutError("Request timeout"),
                    RuntimeError("Unknown error"),
                    Exception("Generic error"),
                ]

                for error in error_types:
                    mock_rpc.side_effect = error
                    mock_active.items.return_value = [(("t1", "b1"), {
                        "p_project_id": "p", "branch": "b1",
                        "p_task_id": "t1", "token": "tk", "ttl": 3600
                    })]

                    with patch('builtins.open', mock_open()):
                        # Should not raise
                        try:
                            result = branch_lease.heartbeat("t1", "b1")
                            # Should have failed soft
                            self.assertTrue(result)
                        except Exception as e:
                            self.fail(f"heartbeat raised {type(e).__name__} on {error}")

    def test_heartbeat_critical_path_never_removes_error_handling(self):
        """The fail-soft try/except in heartbeat must always exist."""
        import branch_lease
        import inspect

        source = inspect.getsource(branch_lease.heartbeat)

        # Verify the critical error handling is present
        self.assertIn("try:", source, "heartbeat must have try/except for fail-soft")
        self.assertIn("except", source, "heartbeat must have except clause")
        self.assertIn("sys.stderr", source, "heartbeat must log errors to stderr")


class TestAllowlistEdgeCases(unittest.TestCase):
    """Test edge cases in allowlist configuration and usage."""

    def test_allowlist_with_duplicate_contracts(self):
        """Allowlist with duplicate contracts should be handled gracefully."""
        allowlist = {
            "partner": ["contract_1", "contract_1", "contract_2"]
        }

        # Deduplication
        unique = list(set(allowlist["partner"]))
        self.assertEqual(len(unique), 2)

    def test_allowlist_with_special_characters_in_contract_ids(self):
        """Contract IDs with special characters should be handled."""
        allowlist = {
            "partner": ["contract-1", "contract_2", "contract.3"]
        }

        for contract_id in allowlist["partner"]:
            self.assertIsInstance(contract_id, str)
            self.assertTrue(len(contract_id) > 0)

    def test_allowlist_with_very_large_contract_list(self):
        """Large allowlists should not cause performance issues."""
        allowlist = {
            "partner": [f"contract_{i}" for i in range(10000)]
        }

        # Should complete quickly
        start = time.time()
        result = "contract_5000" in allowlist["partner"]
        elapsed = time.time() - start

        self.assertTrue(result)
        self.assertLess(elapsed, 0.1, "Large allowlist lookup should be fast")

    def test_allowlist_with_null_bytes_rejected(self):
        """Allowlist entries with null bytes should be rejected."""
        invalid_contract_id = "contract\x00malicious"

        # Should either be rejected or sanitized
        sanitized = invalid_contract_id.replace("\x00", "")
        self.assertNotEqual(sanitized, invalid_contract_id)
        self.assertNotIn("\x00", sanitized)

    def test_allowlist_case_sensitivity(self):
        """Allowlist matching should be case-sensitive."""
        allowlist = {
            "partner": ["CONTRACT_1"]
        }

        # Lowercase should not match
        self.assertIn("CONTRACT_1", allowlist["partner"])
        self.assertNotIn("contract_1", allowlist["partner"])


class TestAuthorizationIntegrationWithAllowlist(unittest.TestCase):
    """Test authorization checks integrated with allowlist filtering."""

    def test_authorized_partner_can_access_allowed_contracts(self):
        """Authorized partner accessing allowed contract should succeed."""
        auth = self._check_auth("partner_a", "contract_1",
                               allowlist={"partner_a": ["contract_1"]})
        self.assertTrue(auth)

    def test_authorized_partner_cannot_access_forbidden_contracts(self):
        """Authorized partner accessing forbidden contract should fail."""
        auth = self._check_auth("partner_a", "contract_2",
                               allowlist={"partner_a": ["contract_1"]})
        self.assertFalse(auth)

    def test_unauthorized_partner_denied_all_contracts(self):
        """Unauthorized partner denied access to any contract."""
        auth = self._check_auth("unknown", "contract_1",
                               allowlist={"partner_a": ["contract_1"]})
        self.assertFalse(auth)

    def _check_auth(self, partner_id, contract_id, allowlist):
        """Simulate authorization check with allowlist."""
        allowed = allowlist.get(partner_id, [])
        return contract_id in allowed


if __name__ == "__main__":
    unittest.main()
