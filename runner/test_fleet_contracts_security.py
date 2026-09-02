"""Comprehensive security tests for fleet_contracts.py

Tests the critical security predicate is_safe_config_key() that prevents credential
leakage in fleet-wide config. This module's correctness is load-bearing for the entire
orchestrator's security model — the 2026-08-02 incident where credentials were stored
in plaintext in fleet_config happened because this guard did not exist and validation
logic was duplicated across modules.

Test strategy:
- All deny markers must block, regardless of prefix
- All safe prefixes must allow, if no deny markers present
- Explicit exclusions must block even with a safe prefix
- Case insensitivity must work both ways
- Whitespace, None, non-strings must fail closed
- fail_soft decorator must return defaults on any error
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fleet_contracts


class TestIsSafeConfigKey:
    """Security tests for the is_safe_config_key() predicate."""

    def test_none_fails_closed(self):
        """None input must return False, never raise."""
        assert fleet_contracts.is_safe_config_key(None) is False

    def test_empty_string_fails_closed(self):
        """Empty string must return False."""
        assert fleet_contracts.is_safe_config_key("") is False

    def test_whitespace_only_fails_closed(self):
        """Whitespace-only strings must fail closed."""
        assert fleet_contracts.is_safe_config_key("   ") is False
        assert fleet_contracts.is_safe_config_key("\t") is False
        assert fleet_contracts.is_safe_config_key("\n") is False

    def test_non_string_fails_closed(self):
        """Non-string types must fail closed."""
        assert fleet_contracts.is_safe_config_key(123) is False
        assert fleet_contracts.is_safe_config_key([]) is False
        assert fleet_contracts.is_safe_config_key({}) is False
        assert fleet_contracts.is_safe_config_key(True) is False

    def test_deny_marker_key_blocks(self):
        """Any deny marker must block, regardless of prefix."""
        for marker in fleet_contracts.DENY_MARKERS:
            # Exact match
            assert fleet_contracts.is_safe_config_key(marker) is False
            # With safe prefix (should still block due to deny marker)
            assert fleet_contracts.is_safe_config_key(f"ORCH_{marker}") is False
            # Case insensitive
            assert fleet_contracts.is_safe_config_key(marker.lower()) is False

    def test_safe_prefix_allows_when_no_deny_markers(self):
        """Safe prefixes must allow config when no deny markers present."""
        for prefix in fleet_contracts.SAFE_PREFIXES:
            test_key = f"{prefix}TUNING_PARAM"
            assert fleet_contracts.is_safe_config_key(test_key) is True

    def test_case_insensitive_matching(self):
        """Matching must be case insensitive."""
        # Safe prefix in lowercase should work
        assert fleet_contracts.is_safe_config_key("orch_safe_param") is True
        assert fleet_contracts.is_safe_config_key("max_parallel") is True
        # Deny marker in lowercase should block
        assert fleet_contracts.is_safe_config_key("my_secret_key") is False
        assert fleet_contracts.is_safe_config_key("password_hash") is False

    def test_whitespace_stripped_before_check(self):
        """Leading/trailing whitespace must be stripped."""
        assert fleet_contracts.is_safe_config_key("  ORCH_PARAM  ") is True
        assert fleet_contracts.is_safe_config_key("\tMAX_PARALLEL\t") is True
        assert fleet_contracts.is_safe_config_key("  \n  MY_SECRET_KEY  ") is False

    def test_explicit_exclusion_blocks_despite_safe_prefix(self):
        """Explicit exclusions must block even with safe prefix."""
        for excl in fleet_contracts.FLEET_CONFIG_SCHEMA["explicit_exclusions"]:
            assert fleet_contracts.is_safe_config_key(excl) is False
            assert fleet_contracts.is_safe_config_key(excl.lower()) is False

    def test_all_deny_markers_block(self):
        """Every marker in DENY_MARKERS must individually block."""
        expected_blockers = {
            "MY_API_KEY",
            "SECRET_PASSWORD",
            "BEARER_TOKEN",
            "AUTH_TOKEN",
            "SESSION_ID_VALUE",
            "COOKIE_JAR",
            "PRIVATE_CERT",
            "GITHUB_PAT",
            "OPENAI_API_KEY",
            "VERCEL_TOKEN",
        }
        for blocker in expected_blockers:
            assert fleet_contracts.is_safe_config_key(blocker) is False, f"Failed to block {blocker}"

    def test_all_safe_prefixes_allow(self):
        """Every prefix in SAFE_PREFIXES must allow clean keys."""
        for prefix in fleet_contracts.SAFE_PREFIXES:
            key = f"{prefix}EXAMPLE_PARAM"
            assert fleet_contracts.is_safe_config_key(key) is True, f"Failed to allow {key}"

    def test_prefix_match_requires_full_prefix_boundary(self):
        """Prefix matching must respect word boundaries or prefix start."""
        assert fleet_contracts.is_safe_config_key("MY_ORCH_SAFE") is False  # ORCH not at start
        assert fleet_contracts.is_safe_config_key("ORCH_PARAM") is True      # ORCH at start is ok
        assert fleet_contracts.is_safe_config_key("MAX_PARALLEL_CEILING") is True
        assert fleet_contracts.is_safe_config_key("XMAX_PARALLEL") is False  # MAX_PARALLEL not at start

    def test_marker_substring_anywhere_blocks(self):
        """Deny markers can appear anywhere in key, not just start."""
        assert fleet_contracts.is_safe_config_key("ORCH_MY_SECRET_PARAM") is False  # SECRET in middle
        assert fleet_contracts.is_safe_config_key("ORCH_PASSWORD_RESET") is False   # PASSWORD in middle
        assert fleet_contracts.is_safe_config_key("CUSTOM_AUTH_TOKEN") is False      # TOKEN in middle

    def test_exception_during_check_fails_closed(self):
        """An exception while checking must return False, not raise."""
        # This is a regression test for the except Exception: return False pattern
        # Create an object that might cause issues during string operations
        class BadString:
            def upper(self):
                raise RuntimeError("Intentional error in upper()")
        # Manually pass it through the validation path
        result = fleet_contracts.is_safe_config_key(BadString())
        assert result is False

    def test_schema_consistency(self):
        """FLEET_CONFIG_SCHEMA must match implementation."""
        schema = fleet_contracts.FLEET_CONFIG_SCHEMA
        assert schema["version"] == 1
        assert schema["fail_closed"] is True
        assert schema["safe_prefixes"] == fleet_contracts.SAFE_PREFIXES
        assert schema["deny_markers"] == fleet_contracts.DENY_MARKERS
        assert "explicit_exclusions" in schema
        assert len(schema["explicit_exclusions"]) > 0


class TestAssertSafeConfigKey:
    """Tests for assert_safe_config_key() which raises on invalid keys."""

    def test_safe_key_passes(self):
        """Safe keys must not raise."""
        try:
            fleet_contracts.assert_safe_config_key("ORCH_MAX_PARALLEL")
            fleet_contracts.assert_safe_config_key("MAX_PARALLEL")
            fleet_contracts.assert_safe_config_key("RAM_FLOOR_GB")
        except ValueError:
            assert False, "assert_safe_config_key raised on a safe key"

    def test_unsafe_key_raises(self):
        """Unsafe keys must raise ValueError."""
        unsafe_keys = [
            "ORCH_API_KEY",
            "MY_SECRET",
            "GITHUB_PAT",
            "VERCEL_TOKEN",
            "OPENAI_API_KEY",
        ]
        for key in unsafe_keys:
            try:
                fleet_contracts.assert_safe_config_key(key)
                assert False, f"assert_safe_config_key did not raise for {key}"
            except ValueError as e:
                assert "fleet-contracts" in str(e).lower()
                assert key in str(e) or "refusing" in str(e).lower()

    def test_error_message_mentions_contract(self):
        """Error message must reference the contract."""
        try:
            fleet_contracts.assert_safe_config_key("ORCH_SECRET_KEY")
        except ValueError as e:
            msg = str(e)
            assert "fleet-contracts" in msg.lower() or "refusing" in msg.lower()


class TestFailSoftDecorator:
    """Tests for the fail_soft() decorator."""

    def test_decorator_returns_default_on_error(self):
        """Decorator must return default value on exception."""
        @fleet_contracts.fail_soft(default="DEFAULT_VALUE")
        def failing_function():
            raise RuntimeError("Intentional error")

        result = failing_function()
        assert result == "DEFAULT_VALUE"

    def test_decorator_returns_none_by_default(self):
        """Decorator must return None if no default specified."""
        @fleet_contracts.fail_soft()
        def failing_function():
            raise RuntimeError("Intentional error")

        result = failing_function()
        assert result is None

    def test_decorator_preserves_success_case(self):
        """Decorator must pass through successful results."""
        @fleet_contracts.fail_soft(default="DEFAULT")
        def working_function():
            return "SUCCESS"

        result = working_function()
        assert result == "SUCCESS"

    def test_decorator_calls_on_error_callback(self):
        """Decorator must call on_error callback if provided."""
        callback_called = []

        def error_handler(exc):
            callback_called.append(str(exc))

        @fleet_contracts.fail_soft(default="DEFAULT", on_error=error_handler)
        def failing_function():
            raise RuntimeError("Test error")

        result = failing_function()
        assert result == "DEFAULT"
        assert len(callback_called) == 1
        assert "Test error" in callback_called[0]

    def test_decorator_silently_swallows_callback_errors(self):
        """Decorator must not raise even if on_error callback fails."""
        def bad_callback(exc):
            raise RuntimeError("Callback error")

        @fleet_contracts.fail_soft(default="DEFAULT", on_error=bad_callback)
        def failing_function():
            raise RuntimeError("Original error")

        result = failing_function()
        assert result == "DEFAULT"  # Did not raise despite callback error

    def test_decorator_preserves_function_metadata(self):
        """Decorator must preserve original function name."""
        @fleet_contracts.fail_soft(default="DEFAULT")
        def named_function():
            return "result"

        assert named_function.__name__ == "named_function"

    def test_decorator_accepts_args_and_kwargs(self):
        """Decorator must preserve args and kwargs."""
        @fleet_contracts.fail_soft(default="DEFAULT")
        def parametrized_function(a, b, c=None):
            if c is None:
                raise RuntimeError("c not provided")
            return f"{a}-{b}-{c}"

        # Test success case with args and kwargs
        result = parametrized_function(1, 2, c=3)
        assert result == "1-2-3"

        # Test error case (c not provided)
        result = parametrized_function(1, 2)
        assert result == "DEFAULT"


class TestDescribeFunction:
    """Tests for describe() which returns the contract."""

    def test_describe_returns_dict(self):
        """describe() must return a dictionary."""
        contract = fleet_contracts.describe()
        assert isinstance(contract, dict)

    def test_describe_includes_schema_fields(self):
        """describe() must include all schema fields."""
        contract = fleet_contracts.describe()
        required_fields = {"version", "table", "description", "safe_prefixes",
                          "deny_markers", "fail_closed", "explicit_exclusions", "incident"}
        assert required_fields.issubset(contract.keys())

    def test_describe_is_copyable(self):
        """describe() must return a copy, not reference to mutable schema."""
        contract1 = fleet_contracts.describe()
        contract2 = fleet_contracts.describe()
        # Modify one copy
        contract1["safe_prefixes"] = []
        # Other copy should be unchanged
        assert len(contract2["safe_prefixes"]) > 0


class TestIntegrationScenarios:
    """Integration tests for realistic config validation scenarios."""

    def test_machine_scaling_config_allowed(self):
        """Machine scaling params must be allowed fleet-wide."""
        allowed = [
            "MAX_PARALLEL",
            "PER_TASK_GB",
            "RAM_FLOOR_GB",
            "ORCH_MAX_QUEUED_TASKS",
        ]
        for key in allowed:
            assert fleet_contracts.is_safe_config_key(key) is True

    def test_model_selection_config_allowed(self):
        """Model selection must be allowed fleet-wide."""
        allowed = [
            "OLLAMA_MODEL",
            "OLLAMA_ENDPOINT",
        ]
        for key in allowed:
            assert fleet_contracts.is_safe_config_key(key) is True

    def test_2026_08_02_incident_vectors_blocked(self):
        """Keys that caused the 2026-08-02 incident must be blocked."""
        blocked = [
            "VERCEL_TOKEN",
            "GITHUB_PAT",
            "OPENAI_API_KEY",
            "GEMINI_API_KEY",
        ]
        for key in blocked:
            assert fleet_contracts.is_safe_config_key(key) is False

    def test_git_pat_value_exclusion(self):
        """ORCH_GIT_PAT value must be in env only, never fleet_config."""
        # The value lives in local env
        # Only ORCH_GIT_AUTH_REQUIRED signal is fleet-wide
        assert fleet_contracts.is_safe_config_key("ORCH_GIT_PAT") is False
        assert fleet_contracts.is_safe_config_key("ORCH_GIT_AUTH_REQUIRED") is True

    def test_deployment_config_allowed(self):
        """Deployment control signals must be allowed."""
        allowed = [
            "DEPLOY_SKIP_TESTS",
            "DEPLOY_STRATEGY",
            "DEPLOY_TIMEOUT",
        ]
        for key in allowed:
            assert fleet_contracts.is_safe_config_key(key) is True


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "--tb=short"])
