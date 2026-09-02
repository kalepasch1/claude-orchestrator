#!/usr/bin/env python3
"""
test_contract_validator.py - Tests for smart contract validation and legal gating.

Tests cover:
- detect_legal_trigger: Identifies licensing/registration/custody/transmission/advice keys and credential markers
- validate_contract_change: Validates configuration change rules and dangerous transitions
- legal_gate_required: Determines if a change dict requires legal gate approval
- Fail-soft error handling: All functions return sensible defaults on bad input
- Integration with fleet_config validation
"""

import pytest
import sys
import os
from typing import Dict, Any, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from contract_validator import (
    detect_legal_trigger,
    validate_contract_change,
    legal_gate_required,
)


class TestDetectLegalTrigger:
    """Tests for detect_legal_trigger function."""

    def test_detect_license_key(self):
        """Detect LICENSE and related keys."""
        assert detect_legal_trigger("ORCH_LICENSE_KEY") is True
        assert detect_legal_trigger("LICENSE") is True
        assert detect_legal_trigger("license_key") is True

    def test_detect_registration_key(self):
        """Detect REGISTRATION and related keys."""
        assert detect_legal_trigger("ORCH_REGISTRATION_ID") is True
        assert detect_legal_trigger("registration") is True
        assert detect_legal_trigger("enroll_enabled") is True

    def test_detect_custody_key(self):
        """Detect CUSTODY and related keys."""
        assert detect_legal_trigger("CUSTODY_PROVIDER") is True
        assert detect_legal_trigger("owner_id") is True
        assert detect_legal_trigger("steward_config") is True

    def test_detect_transmission_key(self):
        """Detect TRANSMISSION and related keys."""
        assert detect_legal_trigger("TRANSMISSION_ENABLED") is True
        assert detect_legal_trigger("transfer_config") is True
        assert detect_legal_trigger("migration_path") is True

    def test_detect_advice_key(self):
        """Detect ADVICE and related keys."""
        assert detect_legal_trigger("ADVICE_MODE") is True
        assert detect_legal_trigger("recommendation_engine") is True
        assert detect_legal_trigger("guidance_config") is True

    def test_detect_password_marker(self):
        """Detect PASSWORD credential marker."""
        assert detect_legal_trigger("DB_PASSWORD") is True
        assert detect_legal_trigger("api_password") is True
        assert detect_legal_trigger("password") is True

    def test_detect_token_marker(self):
        """Detect TOKEN credential marker."""
        assert detect_legal_trigger("AUTH_TOKEN") is True
        assert detect_legal_trigger("github_token") is True
        assert detect_legal_trigger("api_token") is True

    def test_detect_secret_marker(self):
        """Detect SECRET credential marker."""
        assert detect_legal_trigger("OPENAI_SECRET") is True
        assert detect_legal_trigger("jwt_secret") is True
        assert detect_legal_trigger("secret_key") is True

    def test_detect_key_marker(self):
        """Detect KEY credential marker."""
        assert detect_legal_trigger("API_KEY") is True
        assert detect_legal_trigger("encryption_key") is True
        assert detect_legal_trigger("signing_key") is True

    def test_detect_pat_marker(self):
        """Detect PAT (Personal Access Token) marker."""
        assert detect_legal_trigger("GITHUB_PAT") is True
        assert detect_legal_trigger("pat_token") is True

    def test_detect_credential_marker(self):
        """Detect CREDENTIAL marker."""
        assert detect_legal_trigger("AWS_CREDENTIAL") is True
        assert detect_legal_trigger("credential") is True

    def test_safe_config_keys_not_triggered(self):
        """Safe config keys should not trigger legal gate."""
        assert detect_legal_trigger("ORCH_MAX_PARALLEL") is False
        assert detect_legal_trigger("MAX_THREADS") is False
        assert detect_legal_trigger("PER_TASK_GB") is False
        assert detect_legal_trigger("ORCH_AUTO_PULL") is False
        assert detect_legal_trigger("ENABLE_LOGGING") is False

    def test_empty_string_returns_false(self):
        """Empty string should return False (fail-soft)."""
        assert detect_legal_trigger("") is False

    def test_none_returns_false(self):
        """None input should return False (fail-soft)."""
        assert detect_legal_trigger(None) is False

    def test_non_string_returns_false(self):
        """Non-string input should return False (fail-soft)."""
        assert detect_legal_trigger(123) is False
        assert detect_legal_trigger(12.34) is False
        assert detect_legal_trigger([]) is False
        assert detect_legal_trigger({}) is False

    def test_case_insensitive_detection(self):
        """Trigger detection is case-insensitive."""
        assert detect_legal_trigger("orch_LICENSE_key") is True
        assert detect_legal_trigger("ORCH_license_KEY") is True
        assert detect_legal_trigger("api_PASSWORD") is True
        assert detect_legal_trigger("API_password") is True


class TestValidateContractChange:
    """Tests for validate_contract_change function."""

    def test_non_trigger_key_always_valid(self):
        """Non-trigger keys should always return (True, '')."""
        is_valid, reason = validate_contract_change(10, 20, "ORCH_MAX_PARALLEL")
        assert is_valid is True
        assert reason == ""

    def test_clear_license_key_invalid(self):
        """Clearing a license key should be invalid."""
        is_valid, reason = validate_contract_change("ABC123", None, "ORCH_LICENSE_KEY")
        assert is_valid is False
        assert "license" in reason.lower() or "revoke" in reason.lower()

    def test_clear_registration_invalid(self):
        """Clearing registration should be invalid."""
        is_valid, reason = validate_contract_change("REG123", None, "REGISTRATION_ID")
        assert is_valid is False

    def test_add_transmission_without_old_value_invalid(self):
        """Enabling transmission from unset state should be invalid."""
        is_valid, reason = validate_contract_change(None, True, "TRANSMISSION_ENABLED")
        assert is_valid is False
        assert "transmission" in reason.lower()

    def test_clear_owner_invalid(self):
        """Clearing owner should be invalid (audit trail required)."""
        is_valid, reason = validate_contract_change("owner1", None, "OWNER_ID")
        assert is_valid is False
        assert "owner" in reason.lower()

    def test_modify_license_with_old_value_valid(self):
        """Modifying a license (replacing one with another) should be valid."""
        is_valid, reason = validate_contract_change("LICENSE1", "LICENSE2", "ORCH_LICENSE_KEY")
        assert is_valid is True

    def test_modify_registration_with_old_value_valid(self):
        """Modifying registration with existing value should be valid."""
        is_valid, reason = validate_contract_change("REG1", "REG2", "REGISTRATION_ID")
        assert is_valid is True

    def test_error_handling_invalid_values(self):
        """Should handle invalid value types gracefully (fail-soft)."""
        is_valid, reason = validate_contract_change("old", "new", "ORCH_LICENSE_KEY")
        # Should not raise, should return sensible default
        assert isinstance(is_valid, bool)
        assert isinstance(reason, str)

    def test_error_handling_non_string_key(self):
        """Should handle non-string key gracefully (fail-soft)."""
        is_valid, reason = validate_contract_change("old", "new", None)
        assert isinstance(is_valid, bool)
        assert reason == ""

    def test_error_in_validation_returns_true(self):
        """On internal error, should return (True, '') - fail-soft."""
        # Pass invalid types to trigger potential errors
        is_valid, reason = validate_contract_change({}, [], "ORCH_LICENSE_KEY")
        assert is_valid is True
        assert reason == ""


class TestLegalGateRequired:
    """Tests for legal_gate_required function."""

    def test_no_legal_triggers_returns_false(self):
        """Config with no legal triggers should return False."""
        changes = {
            "ORCH_MAX_PARALLEL": 20,
            "PER_TASK_GB": 1.5,
            "ENABLE_LOGGING": "true",
        }
        assert legal_gate_required(changes) is False

    def test_one_legal_trigger_returns_true(self):
        """Config with one legal trigger should return True."""
        changes = {
            "ORCH_MAX_PARALLEL": 20,
            "ORCH_LICENSE_KEY": "ABC123",
        }
        assert legal_gate_required(changes) is True

    def test_multiple_legal_triggers_returns_true(self):
        """Config with multiple legal triggers should return True."""
        changes = {
            "ORCH_LICENSE_KEY": "ABC123",
            "REGISTRATION_ID": "REG123",
            "ORCH_MAX_PARALLEL": 20,
        }
        assert legal_gate_required(changes) is True

    def test_credential_marker_triggers_gate(self):
        """Config with credential marker should trigger gate."""
        changes = {
            "ORCH_MAX_PARALLEL": 20,
            "API_KEY": "secret",
        }
        assert legal_gate_required(changes) is True

    def test_password_triggers_gate(self):
        """Password in config should trigger gate."""
        changes = {"DB_PASSWORD": "pass123"}
        assert legal_gate_required(changes) is True

    def test_token_triggers_gate(self):
        """Token in config should trigger gate."""
        changes = {"AUTH_TOKEN": "token123"}
        assert legal_gate_required(changes) is True

    def test_empty_dict_returns_false(self):
        """Empty dict should return False."""
        assert legal_gate_required({}) is False

    def test_none_returns_false(self):
        """None input should return False (fail-soft)."""
        assert legal_gate_required(None) is False

    def test_non_dict_returns_false(self):
        """Non-dict input should return False (fail-soft)."""
        assert legal_gate_required([]) is False
        assert legal_gate_required("string") is False
        assert legal_gate_required(123) is False

    def test_dict_with_non_string_keys_handled(self):
        """Dict with non-string keys should be handled gracefully."""
        changes = {
            "ORCH_MAX_PARALLEL": 20,
            123: "value",  # Non-string key
        }
        # Should not raise, should process string keys
        result = legal_gate_required(changes)
        assert isinstance(result, bool)

    def test_all_safe_keys_returns_false(self):
        """Dict with only safe keys should return False."""
        changes = {
            "ORCH_MAX_PARALLEL": 20,
            "ORCH_AUTO_PULL": True,
            "ORCH_QUEUE_MODE": "normal",
            "MAX_THREADS": 8,
            "ENABLE_LOGGING": True,
        }
        assert legal_gate_required(changes) is False


class TestIntegrationScenarios:
    """Integration tests for real-world scenarios."""

    def test_fleet_safe_config_update_no_gate(self):
        """Safe fleet config update should not require gate."""
        changes = {
            "ORCH_MAX_PARALLEL": 15,
            "ORCH_AUTO_PULL": True,
            "PER_TASK_GB": 1.2,
        }
        assert legal_gate_required(changes) is False

        # All changes should validate
        for key, value in changes.items():
            is_valid, reason = validate_contract_change(None, value, key)
            assert is_valid is True

    def test_license_config_update_requires_gate(self):
        """License config update should require gate."""
        changes = {"ORCH_LICENSE_KEY": "NEW_LICENSE"}
        assert legal_gate_required(changes) is True

    def test_registration_config_update_requires_gate(self):
        """Registration config update should require gate."""
        changes = {"ORCH_REGISTRATION_ID": "CUST_12345"}
        assert legal_gate_required(changes) is True

    def test_custody_change_requires_gate(self):
        """Custody change should require gate."""
        changes = {"CUSTODY_PROVIDER": "provider_new"}
        assert legal_gate_required(changes) is True

    def test_transmission_change_requires_gate(self):
        """Transmission change should require gate."""
        changes = {"TRANSMISSION_ENABLED": True}
        assert legal_gate_required(changes) is True

    def test_secret_key_requires_gate(self):
        """Secret key in config should require gate."""
        changes = {"EXTERNAL_API_SECRET": "secret123"}
        assert legal_gate_required(changes) is True

    def test_mixed_safe_and_legal_requires_gate(self):
        """Mixed safe and legal changes should require gate."""
        changes = {
            "ORCH_MAX_PARALLEL": 20,
            "PER_TASK_GB": 1.5,
            "ORCH_LICENSE_KEY": "LICENSE123",
            "ENABLE_LOGGING": True,
        }
        assert legal_gate_required(changes) is True

    def test_dangerous_license_clear_invalid(self):
        """Clearing license key should be invalid."""
        changes = {"ORCH_LICENSE_KEY": None}
        assert legal_gate_required(changes) is True
        # Validate the change
        is_valid, reason = validate_contract_change("LICENSE123", None, "ORCH_LICENSE_KEY")
        assert is_valid is False

    def test_dangerous_owner_clear_invalid(self):
        """Clearing owner should be invalid."""
        changes = {"OWNER_ID": None}
        assert legal_gate_required(changes) is True
        # Validate the change
        is_valid, reason = validate_contract_change("owner1", None, "OWNER_ID")
        assert is_valid is False

    def test_normal_registration_update_valid(self):
        """Updating registration with existing value should be valid."""
        changes = {"REGISTRATION_ID": "NEW_REG_ID"}
        assert legal_gate_required(changes) is True
        # Validate the change (with old value)
        is_valid, reason = validate_contract_change("OLD_REG_ID", "NEW_REG_ID", "REGISTRATION_ID")
        assert is_valid is True


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_very_long_key_name(self):
        """Handle very long key names."""
        long_key = "A" * 1000 + "_LICENSE"
        assert detect_legal_trigger(long_key) is True

    def test_special_characters_in_key(self):
        """Handle special characters in key name."""
        assert detect_legal_trigger("ORCH-LICENSE-KEY") is True
        assert detect_legal_trigger("ORCH_LICENSE_KEY-2") is True

    def test_unicode_in_key(self):
        """Handle unicode characters in key name."""
        assert detect_legal_trigger("ORCH_LICENSE_KEY_™") is True

    def test_numeric_only_key(self):
        """Numeric-only key should be safe."""
        assert detect_legal_trigger("12345") is False

    def test_empty_change_dict(self):
        """Empty change dict should not require gate."""
        assert legal_gate_required({}) is False

    def test_none_values_in_dict(self):
        """Dict with None values should be handled."""
        changes = {"ORCH_MAX_PARALLEL": None, "MAX_THREADS": None}
        assert legal_gate_required(changes) is False

    def test_multiple_credential_markers_in_key(self):
        """Key with multiple credential markers."""
        assert detect_legal_trigger("API_KEY_SECRET_TOKEN") is True

    def test_trigger_keyword_as_substring(self):
        """Trigger keyword as substring of larger word."""
        # "license" in "unlicensed"
        assert detect_legal_trigger("UNLICENSED_MODE") is True
        # "owner" in "homeowner"
        assert detect_legal_trigger("HOMEOWNER_POLICY") is True


class TestCaseInsensitivity:
    """Test case-insensitive behavior."""

    def test_lowercase_triggers_detected(self):
        """Lowercase trigger keywords detected."""
        assert detect_legal_trigger("orch_license_key") is True
        assert detect_legal_trigger("registration_id") is True
        assert detect_legal_trigger("api_token") is True

    def test_uppercase_triggers_detected(self):
        """Uppercase trigger keywords detected."""
        assert detect_legal_trigger("ORCH_LICENSE_KEY") is True
        assert detect_legal_trigger("REGISTRATION_ID") is True
        assert detect_legal_trigger("API_TOKEN") is True

    def test_mixed_case_triggers_detected(self):
        """Mixed case trigger keywords detected."""
        assert detect_legal_trigger("Orch_License_Key") is True
        assert detect_legal_trigger("Registration_ID") is True
        assert detect_legal_trigger("Api_Token") is True
