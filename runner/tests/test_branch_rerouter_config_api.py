#!/usr/bin/env python3
"""
Tests for branch_rerouter config API — set_branch_config / get_branch_config for model keys.

Covers the programmatic configuration interface for branch rerouting, with emphasis on:
  - Model-key configuration via API (not env vars)
  - In-memory config persistence and thread safety
  - Interaction with reroute() using API-set config
  - Mock scenarios with programmatically configured model keys
  - Config validation and fail-soft behavior
"""
import os
import sys
import pytest
import subprocess
import tempfile
import shutil
import threading
from unittest.mock import patch, MagicMock
from collections import namedtuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import branch_rerouter

CompletedProcessMock = namedtuple('CompletedProcessMock', ['returncode', 'stdout', 'stderr'])


@pytest.fixture
def temp_repo():
    """Create a temporary git repository."""
    tmpdir = tempfile.mkdtemp()
    repo = os.path.join(tmpdir, "test_repo")
    os.makedirs(repo)

    subprocess.run(["git", "init"], cwd=repo, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, capture_output=True)

    with open(os.path.join(repo, "README.md"), "w") as f:
        f.write("# Test Repo\n")

    subprocess.run(["git", "add", "README.md"], cwd=repo, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, capture_output=True)
    subprocess.run(["git", "checkout", "-b", "main"], cwd=repo, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    yield repo

    shutil.rmtree(tmpdir, ignore_errors=True)
    branch_rerouter.invalidate_repo()


@pytest.fixture(autouse=True)
def _reset_state():
    """Reset environment and state before/after each test."""
    old_env = dict(os.environ)
    branch_rerouter.invalidate()
    branch_rerouter.reset_stats()
    os.environ["ORCH_BRANCH_REROUTE_ENABLED"] = "true"
    yield
    os.environ.clear()
    os.environ.update(old_env)
    branch_rerouter.invalidate()
    branch_rerouter.reset_stats()


def git_branch_exists_response(exists=True):
    """Create a mock response for git show-ref --verify --quiet."""
    return CompletedProcessMock(returncode=0 if exists else 1, stdout="", stderr="")


def git_get_commit_response(commit_sha="abc123def456"):
    """Create a mock response for git rev-parse --verify --quiet."""
    return CompletedProcessMock(returncode=0, stdout=f"{commit_sha}\n", stderr="")


def git_is_ancestor_response(is_ancestor=True):
    """Create a mock response for git merge-base --is-ancestor."""
    return CompletedProcessMock(returncode=0 if is_ancestor else 1, stdout="", stderr="")


def mock_git_state_missing():
    """Mock git state: branch does not exist."""
    def side_effect(repo, *args, **kwargs):
        if len(args) >= 2 and "show-ref" in args:
            return git_branch_exists_response(exists=False)
        return None
    return side_effect


class TestSetBranchConfig:
    """Tests for set_branch_config() function."""

    def test_set_valid_branch_config(self, temp_repo):
        """set_branch_config with valid ORCH_BRANCH_REROUTE_ key."""
        result = branch_rerouter.set_branch_config("ORCH_BRANCH_REROUTE_agent/test", "main")
        assert result == True

    def test_set_model_key_config(self, temp_repo):
        """set_branch_config with model-specific key."""
        result = branch_rerouter.set_branch_config("ORCH_BRANCH_REROUTE_model/claude", "main")
        assert result == True

    def test_set_config_with_nested_model_key(self, temp_repo):
        """set_branch_config with nested model key (model/provider/name)."""
        result = branch_rerouter.set_branch_config("ORCH_BRANCH_REROUTE_model/anthropic/claude", "main")
        assert result == True

    def test_set_config_invalid_key_prefix(self, temp_repo):
        """set_branch_config rejects key without ORCH_BRANCH_REROUTE_ prefix."""
        result = branch_rerouter.set_branch_config("INVALID_KEY", "main")
        assert result == False

    def test_set_config_empty_value(self, temp_repo):
        """set_branch_config with empty value (stored as empty string)."""
        result = branch_rerouter.set_branch_config("ORCH_BRANCH_REROUTE_agent/test", "")
        assert result == True

    def test_set_config_none_value(self, temp_repo):
        """set_branch_config with None value (stored as empty string)."""
        result = branch_rerouter.set_branch_config("ORCH_BRANCH_REROUTE_agent/test", None)
        assert result == True

    def test_set_config_non_string_key(self, temp_repo):
        """set_branch_config rejects non-string key."""
        result = branch_rerouter.set_branch_config(123, "main")
        assert result == False

    def test_set_config_multiple_keys(self, temp_repo):
        """set_branch_config can store multiple keys."""
        result1 = branch_rerouter.set_branch_config("ORCH_BRANCH_REROUTE_agent/a", "main")
        result2 = branch_rerouter.set_branch_config("ORCH_BRANCH_REROUTE_agent/b", "develop")
        assert result1 == True
        assert result2 == True

    def test_set_config_overwrites_existing(self, temp_repo):
        """set_branch_config overwrites existing value."""
        branch_rerouter.set_branch_config("ORCH_BRANCH_REROUTE_agent/test", "main")
        result = branch_rerouter.set_branch_config("ORCH_BRANCH_REROUTE_agent/test", "develop")
        assert result == True


class TestGetBranchConfig:
    """Tests for get_branch_config() function."""

    def test_get_unset_config_returns_empty(self, temp_repo):
        """get_branch_config returns empty string for unset key."""
        result = branch_rerouter.get_branch_config("ORCH_BRANCH_REROUTE_nonexistent")
        assert result == ""

    def test_get_valid_config(self, temp_repo):
        """get_branch_config returns stored value."""
        branch_rerouter.set_branch_config("ORCH_BRANCH_REROUTE_agent/test", "main")
        result = branch_rerouter.get_branch_config("ORCH_BRANCH_REROUTE_agent/test")
        assert result == "main"

    def test_get_model_key_config(self, temp_repo):
        """get_branch_config retrieves model-specific config."""
        branch_rerouter.set_branch_config("ORCH_BRANCH_REROUTE_model/claude", "feature/test")
        result = branch_rerouter.get_branch_config("ORCH_BRANCH_REROUTE_model/claude")
        assert result == "feature/test"

    def test_get_invalid_key_prefix_returns_empty(self, temp_repo):
        """get_branch_config returns empty for key without ORCH_BRANCH_REROUTE_ prefix."""
        result = branch_rerouter.get_branch_config("INVALID_KEY")
        assert result == ""

    def test_get_non_string_key_returns_empty(self, temp_repo):
        """get_branch_config returns empty for non-string key."""
        result = branch_rerouter.get_branch_config(123)
        assert result == ""

    def test_get_multiple_configs(self, temp_repo):
        """get_branch_config can retrieve multiple stored keys."""
        branch_rerouter.set_branch_config("ORCH_BRANCH_REROUTE_agent/a", "main")
        branch_rerouter.set_branch_config("ORCH_BRANCH_REROUTE_agent/b", "develop")
        assert branch_rerouter.get_branch_config("ORCH_BRANCH_REROUTE_agent/a") == "main"
        assert branch_rerouter.get_branch_config("ORCH_BRANCH_REROUTE_agent/b") == "develop"

    def test_get_empty_value_config(self, temp_repo):
        """get_branch_config returns empty string for empty-value config."""
        branch_rerouter.set_branch_config("ORCH_BRANCH_REROUTE_agent/test", "")
        result = branch_rerouter.get_branch_config("ORCH_BRANCH_REROUTE_agent/test")
        assert result == ""


class TestConfigAPIWithReroute:
    """Tests for reroute() using API-set configuration."""

    def test_reroute_uses_api_set_config(self, temp_repo):
        """reroute() honors config set via set_branch_config()."""
        os.chdir(temp_repo)
        branch_rerouter.invalidate_repo()

        with patch("branch_rerouter._git", side_effect=mock_git_state_missing()):
            branch_rerouter.set_branch_config("ORCH_BRANCH_REROUTE_model/test", "main")
            result = branch_rerouter.reroute("model/test")
            assert result == "main"

    def test_reroute_model_key_from_api_config(self, temp_repo):
        """reroute() applies model-specific config from API."""
        os.chdir(temp_repo)
        branch_rerouter.invalidate_repo()

        with patch("branch_rerouter._git", side_effect=mock_git_state_missing()):
            branch_rerouter.set_branch_config("ORCH_BRANCH_REROUTE_model/claude/opus", "feature/test")
            result = branch_rerouter.reroute("model/claude/opus")
            assert result == "feature/test"

    def test_reroute_stats_incremented_with_api_config(self, temp_repo):
        """reroute() stats increment when using API-set config."""
        os.chdir(temp_repo)
        branch_rerouter.invalidate_repo()
        branch_rerouter.reset_stats()

        with patch("branch_rerouter._git", side_effect=mock_git_state_missing()):
            branch_rerouter.set_branch_config("ORCH_BRANCH_REROUTE_agent/task", "main")
            branch_rerouter.reroute("agent/task")
            stats = branch_rerouter.stats()
            assert stats["rerouted"] == 1

    def test_reroute_api_config_takes_precedence_over_fallback(self, temp_repo):
        """Explicit API config overrides fallback."""
        os.chdir(temp_repo)
        os.environ["ORCH_BRANCH_REROUTE_FALLBACK"] = "develop"
        branch_rerouter.invalidate_repo()

        with patch("branch_rerouter._git", side_effect=mock_git_state_missing()):
            branch_rerouter.set_branch_config("ORCH_BRANCH_REROUTE_agent/test", "main")
            result = branch_rerouter.reroute("agent/test")
            assert result == "main"

    def test_reroute_multiple_api_model_keys(self, temp_repo):
        """reroute() handles multiple model keys from API config."""
        os.chdir(temp_repo)
        branch_rerouter.invalidate_repo()

        with patch("branch_rerouter._git", side_effect=mock_git_state_missing()):
            branch_rerouter.set_branch_config("ORCH_BRANCH_REROUTE_model/opus", "main")
            branch_rerouter.set_branch_config("ORCH_BRANCH_REROUTE_model/sonnet", "develop")

            assert branch_rerouter.reroute("model/opus") == "main"
            assert branch_rerouter.reroute("model/sonnet") == "develop"


class TestConfigAPIWithMocking:
    """Tests for config API with git command mocking."""

    def test_mock_model_key_from_api_config(self, temp_repo):
        """Mock test: model key configured via API."""
        os.chdir(temp_repo)
        branch_rerouter.invalidate_repo()

        def git_side_effect(repo, *args, **kwargs):
            if len(args) >= 2 and "show-ref" in args:
                return git_branch_exists_response(exists=False)
            return None

        with patch("branch_rerouter._git", side_effect=git_side_effect):
            branch_rerouter.set_branch_config("ORCH_BRANCH_REROUTE_model/claude", "main")
            result = branch_rerouter.reroute("model/claude")
            assert result == "main"

    def test_mock_model_key_event_emission_from_api_config(self, temp_repo):
        """Mock test: event emitted when model key from API config is rerouted."""
        os.chdir(temp_repo)
        branch_rerouter.invalidate_repo()

        with patch("branch_rerouter._git", side_effect=mock_git_state_missing()), \
             patch("events.emit") as mock_emit:
            branch_rerouter.set_branch_config("ORCH_BRANCH_REROUTE_model/test", "main")
            result = branch_rerouter.reroute("model/test")
            assert result == "main"
            mock_emit.assert_called()

    def test_mock_api_config_override_env_var(self, temp_repo):
        """Mock test: API config and env var both present."""
        os.chdir(temp_repo)
        os.environ["ORCH_BRANCH_REROUTE_agent/test"] = "develop"
        branch_rerouter.invalidate_repo()

        with patch("branch_rerouter._git", side_effect=mock_git_state_missing()):
            branch_rerouter.set_branch_config("ORCH_BRANCH_REROUTE_agent/test", "main")
            result = branch_rerouter.reroute("agent/test")
            # Both env var and API config apply; exact key lookup should find the mapping
            assert result == "main"

    def test_mock_many_api_model_keys(self, temp_repo):
        """Mock test: 50 model keys from API config."""
        os.chdir(temp_repo)
        branch_rerouter.invalidate_repo()

        with patch("branch_rerouter._git", side_effect=mock_git_state_missing()):
            for i in range(50):
                branch_rerouter.set_branch_config(f"ORCH_BRANCH_REROUTE_model/v{i}", "main")

            for i in range(50):
                result = branch_rerouter.reroute(f"model/v{i}")
                assert result == "main"


class TestConfigAPIConcurrency:
    """Tests for thread-safe config API access."""

    def test_concurrent_set_config(self, temp_repo):
        """Concurrent set_branch_config calls are thread-safe."""
        errors = []
        results = []

        def set_config(i):
            try:
                result = branch_rerouter.set_branch_config(
                    f"ORCH_BRANCH_REROUTE_model/v{i}",
                    f"target_{i}"
                )
                results.append(result)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=set_config, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert len(errors) == 0
        assert all(results)
        assert len(results) == 20

    def test_concurrent_get_config(self, temp_repo):
        """Concurrent get_branch_config calls are thread-safe."""
        # Pre-populate config
        for i in range(20):
            branch_rerouter.set_branch_config(
                f"ORCH_BRANCH_REROUTE_model/v{i}",
                f"target_{i}"
            )

        errors = []
        results = []

        def get_config(i):
            try:
                result = branch_rerouter.get_branch_config(f"ORCH_BRANCH_REROUTE_model/v{i}")
                results.append(result)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=get_config, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert len(errors) == 0
        assert len(results) == 20
        for i, result in enumerate(results):
            assert result == f"target_{i}"

    def test_concurrent_set_and_reroute(self, temp_repo):
        """Concurrent config setting and rerouting are thread-safe."""
        os.chdir(temp_repo)
        branch_rerouter.invalidate_repo()

        errors = []

        def set_and_reroute(i):
            try:
                branch_rerouter.set_branch_config(
                    f"ORCH_BRANCH_REROUTE_model/task_{i}",
                    "main"
                )
                with patch("branch_rerouter._git", side_effect=mock_git_state_missing()):
                    result = branch_rerouter.reroute(f"model/task_{i}")
                    assert result == "main"
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=set_and_reroute, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert len(errors) == 0

    def test_concurrent_invalidate_and_access(self, temp_repo):
        """Concurrent invalidate() and config access are thread-safe."""
        # Pre-populate config
        for i in range(10):
            branch_rerouter.set_branch_config(
                f"ORCH_BRANCH_REROUTE_model/v{i}",
                f"target_{i}"
            )

        errors = []

        def access():
            try:
                branch_rerouter.get_branch_config("ORCH_BRANCH_REROUTE_model/v0")
            except Exception as e:
                errors.append(e)

        def invalidate_state():
            try:
                branch_rerouter.invalidate()
            except Exception as e:
                errors.append(e)

        threads = []
        for i in range(5):
            if i % 2 == 0:
                threads.append(threading.Thread(target=access))
            else:
                threads.append(threading.Thread(target=invalidate_state))

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert len(errors) == 0


class TestConfigAPIInvalidation:
    """Tests for invalidate() clearing API-set config."""

    def test_invalidate_clears_api_config(self, temp_repo):
        """invalidate() clears in-memory config."""
        branch_rerouter.set_branch_config("ORCH_BRANCH_REROUTE_model/test", "main")
        branch_rerouter.invalidate()
        result = branch_rerouter.get_branch_config("ORCH_BRANCH_REROUTE_model/test")
        assert result == ""

    def test_invalidate_clears_multiple_configs(self, temp_repo):
        """invalidate() clears all in-memory configs."""
        for i in range(10):
            branch_rerouter.set_branch_config(f"ORCH_BRANCH_REROUTE_model/v{i}", "main")

        branch_rerouter.invalidate()

        for i in range(10):
            result = branch_rerouter.get_branch_config(f"ORCH_BRANCH_REROUTE_model/v{i}")
            assert result == ""

    def test_reroute_after_invalidate_uses_fallback(self, temp_repo):
        """reroute() falls back to ORCH_BRANCH_REROUTE_FALLBACK after invalidate()."""
        os.chdir(temp_repo)
        branch_rerouter.invalidate_repo()

        with patch("branch_rerouter._git", side_effect=mock_git_state_missing()):
            branch_rerouter.set_branch_config("ORCH_BRANCH_REROUTE_model/test", "feature/test")
            result = branch_rerouter.reroute("model/test")
            assert result == "feature/test"

            branch_rerouter.invalidate()
            # After invalidate, config is cleared, should use fallback
            os.environ["ORCH_BRANCH_REROUTE_FALLBACK"] = "develop"
            result = branch_rerouter.reroute("model/test")
            assert result == "develop"


class TestConfigAPIEdgeCases:
    """Tests for edge cases in config API."""

    def test_config_key_with_special_characters(self, temp_repo):
        """Config key with special characters in branch name."""
        result = branch_rerouter.set_branch_config(
            "ORCH_BRANCH_REROUTE_model/claude-v1.5-sonnet",
            "main"
        )
        assert result == True
        value = branch_rerouter.get_branch_config(
            "ORCH_BRANCH_REROUTE_model/claude-v1.5-sonnet"
        )
        assert value == "main"

    def test_config_value_with_spaces(self, temp_repo):
        """Config value is stored as-is (including spaces)."""
        result = branch_rerouter.set_branch_config(
            "ORCH_BRANCH_REROUTE_agent/test",
            "branch with spaces"
        )
        assert result == True
        value = branch_rerouter.get_branch_config("ORCH_BRANCH_REROUTE_agent/test")
        assert value == "branch with spaces"

    def test_config_value_numeric_string(self, temp_repo):
        """Config value stored as string even if numeric."""
        result = branch_rerouter.set_branch_config(
            "ORCH_BRANCH_REROUTE_agent/test",
            "123"
        )
        assert result == True
        value = branch_rerouter.get_branch_config("ORCH_BRANCH_REROUTE_agent/test")
        assert value == "123"

    def test_config_overwrite_with_different_value(self, temp_repo):
        """Config key can be overwritten with different value."""
        branch_rerouter.set_branch_config("ORCH_BRANCH_REROUTE_agent/test", "main")
        branch_rerouter.set_branch_config("ORCH_BRANCH_REROUTE_agent/test", "develop")
        value = branch_rerouter.get_branch_config("ORCH_BRANCH_REROUTE_agent/test")
        assert value == "develop"

    def test_config_overwrite_with_empty_value(self, temp_repo):
        """Config key can be overwritten with empty value."""
        branch_rerouter.set_branch_config("ORCH_BRANCH_REROUTE_agent/test", "main")
        branch_rerouter.set_branch_config("ORCH_BRANCH_REROUTE_agent/test", "")
        value = branch_rerouter.get_branch_config("ORCH_BRANCH_REROUTE_agent/test")
        assert value == ""


class TestGetRerouteConfigIncludesAPI:
    """Tests for _get_reroute_config() including API-set keys."""

    def test_get_reroute_config_includes_api_keys(self, temp_repo):
        """_get_reroute_config() includes keys set via set_branch_config()."""
        branch_rerouter.set_branch_config("ORCH_BRANCH_REROUTE_model/test", "main")
        mappings = branch_rerouter._get_reroute_config()
        assert "model/test" in mappings
        assert mappings["model/test"] == "main"

    def test_get_reroute_config_multiple_api_keys(self, temp_repo):
        """_get_reroute_config() includes multiple API-set keys."""
        for i in range(10):
            branch_rerouter.set_branch_config(f"ORCH_BRANCH_REROUTE_model/v{i}", f"target_{i}")

        mappings = branch_rerouter._get_reroute_config()
        for i in range(10):
            assert f"model/v{i}" in mappings
            assert mappings[f"model/v{i}"] == f"target_{i}"

    def test_get_reroute_config_excludes_special_keys(self, temp_repo):
        """_get_reroute_config() excludes special ORCH_BRANCH_REROUTE_* keys."""
        os.environ["ORCH_BRANCH_REROUTE_FALLBACK"] = "dev"
        os.environ["ORCH_BRANCH_REROUTE_ENABLED"] = "true"
        os.environ["ORCH_BRANCH_REROUTE_TIMEOUT_SEC"] = "60"

        mappings = branch_rerouter._get_reroute_config()
        # These special keys should not appear in the mappings
        assert "FALLBACK" not in mappings
        assert "ENABLED" not in mappings
        assert "TIMEOUT_SEC" not in mappings


class TestConfigAPIFailSoft:
    """Tests for fail-soft behavior in config API."""

    def test_set_config_with_none_key(self, temp_repo):
        """set_branch_config with None key returns False (fail-soft)."""
        result = branch_rerouter.set_branch_config(None, "main")
        assert result == False

    def test_get_config_with_none_key(self, temp_repo):
        """get_branch_config with None key returns empty string (fail-soft)."""
        result = branch_rerouter.get_branch_config(None)
        assert result == ""

    def test_set_config_internal_exception(self, temp_repo):
        """set_branch_config returns False on internal exception."""
        # Mock threading.Lock to raise exception
        with patch("branch_rerouter._lock") as mock_lock:
            mock_lock.__enter__.side_effect = Exception("lock failed")
            result = branch_rerouter.set_branch_config("ORCH_BRANCH_REROUTE_test", "main")
            assert result == False

    def test_get_config_internal_exception(self, temp_repo):
        """get_branch_config returns empty string on internal exception."""
        # Mock threading.Lock to raise exception
        with patch("branch_rerouter._lock") as mock_lock:
            mock_lock.__enter__.side_effect = Exception("lock failed")
            result = branch_rerouter.get_branch_config("ORCH_BRANCH_REROUTE_test")
            assert result == ""


class TestConfigAPIIntegration:
    """Integration tests for config API with reroute workflow."""

    def test_workflow_api_config_then_reroute(self, temp_repo):
        """Typical workflow: configure via API, then reroute."""
        os.chdir(temp_repo)
        branch_rerouter.invalidate_repo()
        branch_rerouter.reset_stats()

        with patch("branch_rerouter._git", side_effect=mock_git_state_missing()):
            # Configure model keys
            branch_rerouter.set_branch_config("ORCH_BRANCH_REROUTE_model/opus", "main")
            branch_rerouter.set_branch_config("ORCH_BRANCH_REROUTE_model/sonnet", "develop")

            # Reroute based on config
            assert branch_rerouter.reroute("model/opus") == "main"
            assert branch_rerouter.reroute("model/sonnet") == "develop"

            # Verify stats
            stats = branch_rerouter.stats()
            assert stats["rerouted"] == 2

    def test_workflow_mixed_api_and_env_config(self, temp_repo):
        """Workflow mixing API-set and env-var config."""
        os.chdir(temp_repo)
        os.environ["ORCH_BRANCH_REROUTE_agent/env"] = "main"
        branch_rerouter.invalidate_repo()

        with patch("branch_rerouter._git", side_effect=mock_git_state_missing()):
            branch_rerouter.set_branch_config("ORCH_BRANCH_REROUTE_agent/api", "develop")

            # Both should work
            assert branch_rerouter.reroute("agent/env") == "main"
            assert branch_rerouter.reroute("agent/api") == "develop"

    def test_workflow_config_update_then_reroute(self, temp_repo):
        """Workflow: update config, then reroute uses new value."""
        os.chdir(temp_repo)
        branch_rerouter.invalidate_repo()

        with patch("branch_rerouter._git", side_effect=mock_git_state_missing()):
            # Initial config
            branch_rerouter.set_branch_config("ORCH_BRANCH_REROUTE_model/test", "main")
            assert branch_rerouter.reroute("model/test") == "main"

            # Update config
            branch_rerouter.set_branch_config("ORCH_BRANCH_REROUTE_model/test", "develop")
            assert branch_rerouter.reroute("model/test") == "develop"

    def test_workflow_large_model_fleet_config(self, temp_repo):
        """Workflow: configure large fleet of model keys via API."""
        os.chdir(temp_repo)
        branch_rerouter.invalidate_repo()

        # Configure 100 model instances
        for i in range(100):
            branch_rerouter.set_branch_config(
                f"ORCH_BRANCH_REROUTE_model/instance_{i}",
                f"target_{i % 10}"
            )

        with patch("branch_rerouter._git", side_effect=mock_git_state_missing()):
            # Reroute all instances
            for i in range(100):
                result = branch_rerouter.reroute(f"model/instance_{i}")
                assert result == f"target_{i % 10}"
