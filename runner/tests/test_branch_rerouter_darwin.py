#!/usr/bin/env python3
"""
Darwin (macOS)-specific tests for branch_rerouter.py — isolated platform-gated tests.

Test coverage: Darwin-specific behaviors, oversized scenarios, model key routing, and mock-based testing:
  - Platform detection and identification
  - Symlink repository detection (common on macOS)
  - Darwin-specific timeout handling
  - Thread safety with Darwin-specific patterns
  - Oversized model key routing (100+ keys, 50+ concurrent threads)
  - Model key hierarchies (provider/family/variant) and version suffixes
  - Mock-based git operations with CompletedProcess simulation
  - Large-scale concurrent access and stats accuracy under stress
  - Complex real-world model family tree routing and multi-version rollouts

4 consolidated test classes: platform determination, oversized routing, mock-based routing,
and complex model scenarios.

These tests are marked with @pytest.mark.skipif to skip on non-Darwin platforms.
Run with: pytest tests/test_branch_rerouter_darwin.py -v
"""
import os
import sys
import pytest
import subprocess
import tempfile
import shutil
import threading
import time
from unittest.mock import patch, MagicMock
from collections import namedtuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import branch_rerouter

CompletedProcessMock = namedtuple('CompletedProcessMock', ['returncode', 'stdout', 'stderr'])


def git_branch_exists_response(exists=True):
    """Create a mock response for git show-ref --verify --quiet (checking branch existence)."""
    return CompletedProcessMock(returncode=0 if exists else 1, stdout="", stderr="")


def git_get_commit_response(commit_sha="abc123def456"):
    """Create a mock response for git rev-parse --verify --quiet (getting commit SHA)."""
    return CompletedProcessMock(returncode=0, stdout=f"{commit_sha}\n", stderr="")


def git_is_ancestor_response(is_ancestor=True):
    """Create a mock response for git merge-base --is-ancestor (checking stale status)."""
    return CompletedProcessMock(returncode=0 if is_ancestor else 1, stdout="", stderr="")


@pytest.fixture
def temp_repo():
    """Create a temporary git repository with main and feature branches."""
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

    with open(os.path.join(repo, "feature.txt"), "w") as f:
        f.write("feature work\n")
    subprocess.run(["git", "add", "feature.txt"], cwd=repo, capture_output=True)
    subprocess.run(["git", "commit", "-m", "feature work"], cwd=repo, capture_output=True)
    subprocess.run(["git", "checkout", "-b", "feature/test"], cwd=repo, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    yield repo

    shutil.rmtree(tmpdir, ignore_errors=True)
    branch_rerouter.invalidate_repo()


@pytest.fixture(autouse=True)
def _reset_env_and_state():
    """Reset environment and state before/after each test."""
    old_env = dict(os.environ)
    branch_rerouter.invalidate_repo()
    branch_rerouter.reset_stats()
    os.environ["ORCH_BRANCH_REROUTE_ENABLED"] = "true"
    yield
    os.environ.clear()
    os.environ.update(old_env)
    branch_rerouter.invalidate_repo()
    branch_rerouter.reset_stats()


@pytest.fixture
def mock_git_state_missing():
    """Mock git state: branch does not exist."""
    def side_effect(repo, *args, **kwargs):
        if len(args) >= 2 and "show-ref" in args:
            return git_branch_exists_response(exists=False)
        return None
    return side_effect


class TestDarwinPlatformDetermination:
    """Tests for Darwin/macOS-specific branch rerouting behavior."""

    @pytest.mark.skipif(sys.platform != 'darwin', reason="Darwin-specific test")
    def test_darwin_repo_detection_with_home_dir(self, temp_repo):
        """Repo detection works with Darwin home directory paths."""
        os.chdir(temp_repo)
        branch_rerouter.invalidate_repo()
        repo = branch_rerouter._load_repo()
        assert repo is not None
        assert os.path.exists(os.path.join(repo, ".git"))

    @pytest.mark.skipif(sys.platform != 'darwin', reason="Darwin-specific test")
    def test_darwin_symlink_repo_detection(self, temp_repo):
        """Repo detection follows symlinks (common on Darwin)."""
        real_repo = temp_repo
        symlink_repo = os.path.join(tempfile.gettempdir(), f"symlink_{os.getpid()}")
        try:
            os.symlink(real_repo, symlink_repo)
            os.chdir(symlink_repo)
            branch_rerouter.invalidate_repo()
            repo = branch_rerouter._load_repo()
            assert repo is not None
        finally:
            if os.path.exists(symlink_repo):
                os.remove(symlink_repo)

    @pytest.mark.skipif(sys.platform != 'darwin', reason="Darwin-specific test")
    def test_darwin_timeout_handling(self, temp_repo):
        """Git timeout handling on Darwin systems."""
        os.chdir(temp_repo)
        os.environ["ORCH_BRANCH_REROUTE_TIMEOUT_SEC"] = "5"
        branch_rerouter.invalidate_repo()
        timeout = branch_rerouter._get_timeout_sec()
        assert timeout == 5

    @pytest.mark.skipif(sys.platform != 'darwin', reason="Darwin-specific test")
    def test_darwin_thread_safety_macos_specifics(self, temp_repo):
        """Thread safety works with Darwin-specific patterns."""
        os.chdir(temp_repo)
        os.environ["ORCH_BRANCH_REROUTE_model/darwin"] = "main"
        branch_rerouter.invalidate_repo()

        results = []
        errors = []

        def reroute_darwin():
            try:
                result = branch_rerouter.reroute("model/darwin")
                results.append(result)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=reroute_darwin) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert len(errors) == 0
        assert all(r == "main" for r in results)


class TestOversizedModelKeyRouting:
    """Darwin-specific tests for oversized model key routing scenarios (100+ keys, concurrent access)."""

    @pytest.mark.skipif(sys.platform != 'darwin', reason="Darwin-specific test")
    def test_model_key_routing_with_darwin_symlinks(self, temp_repo):
        """Model key routing with Darwin symlink repositories."""
        real_repo = temp_repo
        symlink_path = os.path.join(tempfile.gettempdir(), f"model_test_{os.getpid()}")

        try:
            os.symlink(real_repo, symlink_path)
            os.chdir(symlink_path)
            branch_rerouter.invalidate_repo()

            os.environ["ORCH_BRANCH_REROUTE_model/test"] = "main"
            branch_rerouter.invalidate_repo()

            result = branch_rerouter.reroute("model/test")
            assert result == "main"
        finally:
            if os.path.exists(symlink_path):
                os.remove(symlink_path)

    @pytest.mark.skipif(sys.platform != 'darwin', reason="Darwin-specific test")
    def test_concurrent_model_threads_darwin_safe(self, temp_repo):
        """Concurrent model key threads on Darwin are safe (50 threads, 5 operations each)."""
        os.chdir(temp_repo)

        for i in range(50):
            os.environ[f"ORCH_BRANCH_REROUTE_model/m{i}"] = "main"

        branch_rerouter.invalidate_repo()
        results = []
        errors = []

        def model_reroute_worker(model_id):
            try:
                for _ in range(5):
                    result = branch_rerouter.reroute(f"model/m{model_id}")
                    results.append(result)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=model_reroute_worker, args=(i,))
            for i in range(50)
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert len(errors) == 0
        assert len(results) == 250  # 50 threads * 5 calls

    @pytest.mark.skipif(sys.platform != 'darwin', reason="Darwin-specific test")
    def test_darwin_100_model_keys_independent_routing(self, temp_repo):
        """100 model keys route independently on Darwin without conflicts."""
        os.chdir(temp_repo)

        # Create multiple target branches
        for i in range(5):
            subprocess.run(
                ["git", "checkout", "-b", f"target_{i}"],
                cwd=temp_repo,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            subprocess.run(
                ["git", "checkout", "main"],
                cwd=temp_repo,
                capture_output=True
            )

        # Map 100 models to different targets
        for i in range(100):
            target = f"target_{i % 5}"
            os.environ[f"ORCH_BRANCH_REROUTE_model/v{i}"] = target

        branch_rerouter.invalidate_repo()
        branch_rerouter.reset_stats()

        # Verify mappings
        for i in range(100):
            expected = f"target_{i % 5}"
            result = branch_rerouter.reroute(f"model/v{i}")
            assert result == expected

    @pytest.mark.skipif(sys.platform != 'darwin', reason="Darwin-specific test")
    def test_darwin_model_key_provider_hierarchy(self, temp_repo):
        """Model keys with multi-level provider hierarchy on Darwin."""
        os.chdir(temp_repo)

        hierarchies = {
            "model/anthropic/claude/opus": "main",
            "model/anthropic/claude/sonnet": "main",
            "model/anthropic/claude/haiku": "main",
            "model/openai/gpt/4": "main",
            "model/openai/gpt/3.5": "main",
            "model/google/gemini/pro": "main",
        }

        for key, target in hierarchies.items():
            os.environ[f"ORCH_BRANCH_REROUTE_{key}"] = target

        branch_rerouter.invalidate_repo()

        for key, expected in hierarchies.items():
            result = branch_rerouter.reroute(key)
            assert result == expected

    @pytest.mark.skipif(sys.platform != 'darwin', reason="Darwin-specific test")
    def test_darwin_model_key_version_suffixes(self, temp_repo):
        """Model keys with version suffixes on Darwin."""
        os.chdir(temp_repo)

        versions = [
            "model/v1.0.0",
            "model/v1.1.0",
            "model/v2.0.0-beta",
            "model/v2.0.0-rc1",
            "model/v2.0.0",
        ]

        for version in versions:
            os.environ[f"ORCH_BRANCH_REROUTE_{version}"] = "main"

        branch_rerouter.invalidate_repo()

        for version in versions:
            result = branch_rerouter.reroute(version)
            assert result == "main"

    @pytest.mark.skipif(sys.platform != 'darwin', reason="Darwin-specific test")
    def test_darwin_model_key_stats_aggregation_oversized(self, temp_repo):
        """Stats correctly aggregate reroutes for many model keys on Darwin."""
        os.chdir(temp_repo)

        for i in range(50):
            os.environ[f"ORCH_BRANCH_REROUTE_model/v{i}"] = "main"

        branch_rerouter.invalidate_repo()
        branch_rerouter.reset_stats()

        # Reroute 50 missing model branches
        for i in range(50):
            branch_rerouter.reroute(f"model/v{i}")

        stats = branch_rerouter.stats()
        assert stats["rerouted"] == 50


class TestDarwinMockModelKeyRouting:
    """Mock-based tests for model key routing on Darwin with CompletedProcess simulation."""

    @pytest.mark.skipif(sys.platform != 'darwin', reason="Darwin-specific test")
    def test_mock_darwin_model_key_explicit_mapping(self, temp_repo, mock_git_state_missing):
        """Mock test for model-specific explicit mapping on Darwin."""
        os.chdir(temp_repo)
        os.environ["ORCH_BRANCH_REROUTE_model/claude3"] = "feature/test"
        branch_rerouter.invalidate_repo()

        with patch("branch_rerouter._git", side_effect=mock_git_state_missing):
            result = branch_rerouter.reroute("model/claude3")
            assert result == "feature/test"

    @pytest.mark.skipif(sys.platform != 'darwin', reason="Darwin-specific test")
    def test_mock_darwin_multiple_model_keys_independent(self, temp_repo, mock_git_state_missing):
        """Mock test for multiple model keys with independent mappings on Darwin."""
        os.chdir(temp_repo)
        os.environ["ORCH_BRANCH_REROUTE_model/opus"] = "main"
        os.environ["ORCH_BRANCH_REROUTE_model/sonnet"] = "feature/test"
        branch_rerouter.invalidate_repo()

        with patch("branch_rerouter._git", side_effect=mock_git_state_missing):
            assert branch_rerouter.reroute("model/opus") == "main"
            assert branch_rerouter.reroute("model/sonnet") == "feature/test"

    @pytest.mark.skipif(sys.platform != 'darwin', reason="Darwin-specific test")
    def test_mock_darwin_model_key_missing_uses_fallback(self, temp_repo, mock_git_state_missing):
        """Mock test for model key without explicit mapping uses fallback on Darwin."""
        os.chdir(temp_repo)
        os.environ["ORCH_BRANCH_REROUTE_FALLBACK"] = "develop"
        branch_rerouter.invalidate_repo()

        with patch("branch_rerouter._git", side_effect=mock_git_state_missing):
            result = branch_rerouter.reroute("model/unknown")
            assert result == "develop"

    @pytest.mark.skipif(sys.platform != 'darwin', reason="Darwin-specific test")
    def test_mock_darwin_model_key_nested_paths(self, temp_repo, mock_git_state_missing):
        """Mock test for model keys with nested paths on Darwin."""
        os.chdir(temp_repo)
        os.environ["ORCH_BRANCH_REROUTE_model/anthropic/claude"] = "main"
        branch_rerouter.invalidate_repo()

        with patch("branch_rerouter._git", side_effect=mock_git_state_missing):
            result = branch_rerouter.reroute("model/anthropic/claude")
            assert result == "main"

    @pytest.mark.skipif(sys.platform != 'darwin', reason="Darwin-specific test")
    def test_mock_darwin_model_key_stats_tracked(self, temp_repo, mock_git_state_missing):
        """Mock test for model key reroutes tracked in stats on Darwin."""
        os.chdir(temp_repo)
        os.environ["ORCH_BRANCH_REROUTE_model/test"] = "feature/test"
        branch_rerouter.invalidate_repo()
        branch_rerouter.reset_stats()

        with patch("branch_rerouter._git", side_effect=mock_git_state_missing):
            branch_rerouter.reroute("model/test")
            stats = branch_rerouter.stats()
            assert stats["rerouted"] == 1

    @pytest.mark.skipif(sys.platform != 'darwin', reason="Darwin-specific test")
    def test_mock_darwin_100_branches_mixed_states(self, temp_repo):
        """Mock test: 100 branches with mixed exist/missing states on Darwin."""
        def git_side_effect(repo, *args, **kwargs):
            for arg in args:
                if "agent/task_" in arg:
                    task_num = int(arg.split("_")[-1])
                    if "show-ref" in args:
                        return git_branch_exists_response(exists=task_num % 2 == 0)
            return None

        with patch("branch_rerouter._git", side_effect=git_side_effect):
            os.chdir(temp_repo)
            branch_rerouter.reset_stats()

            for i in range(100):
                branch = f"agent/task_{i}"
                result = branch_rerouter.reroute(branch)
                if i % 2 == 0:
                    assert result == branch
                else:
                    assert result == "main"

    @pytest.mark.skipif(sys.platform != 'darwin', reason="Darwin-specific test")
    def test_mock_darwin_large_batch_model_keys_reroute(self, temp_repo, mock_git_state_missing):
        """Mock test: batch processing of 100+ model keys on Darwin."""
        os.chdir(temp_repo)

        # Set up 100 model mappings
        for i in range(100):
            os.environ[f"ORCH_BRANCH_REROUTE_model/batch_{i}"] = f"target_{i % 10}"

        branch_rerouter.invalidate_repo()
        branch_rerouter.reset_stats()

        with patch("branch_rerouter._git", side_effect=mock_git_state_missing):
            for i in range(100):
                result = branch_rerouter.reroute(f"model/batch_{i}")
                assert result == f"target_{i % 10}"

        stats = branch_rerouter.stats()
        assert stats["rerouted"] == 100

    @pytest.mark.skipif(sys.platform != 'darwin', reason="Darwin-specific test")
    def test_mock_darwin_concurrent_model_key_access_with_mocks(self, temp_repo, mock_git_state_missing):
        """Mock test: concurrent model key access on Darwin with mocked git."""
        os.chdir(temp_repo)
        os.environ["ORCH_BRANCH_REROUTE_model/a"] = "main"
        os.environ["ORCH_BRANCH_REROUTE_model/b"] = "feature/test"
        branch_rerouter.invalidate_repo()

        results = []
        errors = []

        def reroute_model(model_key):
            try:
                result = branch_rerouter.reroute(model_key)
                results.append(result)
            except Exception as e:
                errors.append(e)

        with patch("branch_rerouter._git", side_effect=mock_git_state_missing):
            threads = []
            for i in range(10):
                model_key = "model/a" if i % 2 == 0 else "model/b"
                t = threading.Thread(target=reroute_model, args=(model_key,))
                threads.append(t)
                t.start()

            for t in threads:
                t.join(timeout=5)

        assert len(errors) == 0
        assert len(results) == 10

    @pytest.mark.skipif(sys.platform != 'darwin', reason="Darwin-specific test")
    def test_mock_darwin_model_key_config_parsing_oversized(self, temp_repo, mock_git_state_missing):
        """Mock test: config parsing with many ORCH_* keys on Darwin."""
        os.chdir(temp_repo)

        # Add many non-reroute ORCH_* keys
        for i in range(50):
            os.environ[f"ORCH_OTHER_KEY_{i}"] = f"value_{i}"

        # Add branch reroute keys
        for i in range(50):
            os.environ[f"ORCH_BRANCH_REROUTE_agent/task_{i}"] = "main"

        branch_rerouter.invalidate_repo()
        mappings = branch_rerouter._get_reroute_config()

        # Should only have the branch reroute keys, not the other ORCH_* keys
        assert len(mappings) == 50

    @pytest.mark.skipif(sys.platform != 'darwin', reason="Darwin-specific test")
    def test_mock_darwin_model_key_prefix_matching_priority(self, temp_repo, mock_git_state_missing):
        """Mock test: exact model key match takes priority over prefix matches on Darwin."""
        os.chdir(temp_repo)

        os.environ["ORCH_BRANCH_REROUTE_model/claude"] = "main"
        os.environ["ORCH_BRANCH_REROUTE_model/claude/v1"] = "feature/test"

        branch_rerouter.invalidate_repo()

        with patch("branch_rerouter._git", side_effect=mock_git_state_missing):
            # Exact match should be used
            result = branch_rerouter.reroute("model/claude/v1")
            assert result == "feature/test"

            # Prefix without exact match should use fallback
            result = branch_rerouter.reroute("model/claude/v2")
            assert result == "main"


class TestDarwinComplexModelKeyScenarios:
    """Complex real-world model key scenarios on Darwin."""

    @pytest.mark.skipif(sys.platform != 'darwin', reason="Darwin-specific test")
    def test_darwin_model_family_tree_routing(self, temp_repo):
        """Model family tree routing: anthropic/claude with multiple variants on Darwin."""
        os.chdir(temp_repo)

        # Create family tree of models
        models = [
            ("model/anthropic/claude/opus/v1", "main"),
            ("model/anthropic/claude/opus/v2", "main"),
            ("model/anthropic/claude/sonnet/v1", "feature/test"),
            ("model/anthropic/claude/sonnet/v2", "feature/test"),
            ("model/anthropic/claude/haiku/v1", "develop"),
            ("model/anthropic/claude/haiku/v2", "develop"),
        ]

        for model_key, target in models:
            os.environ[f"ORCH_BRANCH_REROUTE_{model_key}"] = target

        branch_rerouter.invalidate_repo()

        for model_key, expected_target in models:
            result = branch_rerouter.reroute(model_key)
            assert result == expected_target

    @pytest.mark.skipif(sys.platform != 'darwin', reason="Darwin-specific test")
    def test_darwin_multiversion_model_rollout(self, temp_repo):
        """Multi-version model rollout scenario on Darwin (canary to stable)."""
        os.chdir(temp_repo)

        # Simulate rolling out a new model version: canary → staging → production
        versions = {
            "model/claude-3.5-canary": "canary-branch",
            "model/claude-3.5-staging": "staging-branch",
            "model/claude-3.5-production": "main",
            "model/claude-4-canary": "canary-branch",
            "model/claude-4-staging": "staging-branch",
            "model/claude-4-production": "main",
        }

        for model_key, target in versions.items():
            os.environ[f"ORCH_BRANCH_REROUTE_{model_key}"] = target

        branch_rerouter.invalidate_repo()

        for model_key, expected_target in versions.items():
            result = branch_rerouter.reroute(model_key)
            assert result == expected_target

    @pytest.mark.skipif(sys.platform != 'darwin', reason="Darwin-specific test")
    def test_darwin_region_specific_model_routing(self, temp_repo):
        """Region-specific model routing on Darwin (EU/US/APAC regions)."""
        os.chdir(temp_repo)

        # Create multiple target branches for regions
        regions = ["eu", "us", "apac"]
        for region in regions:
            subprocess.run(
                ["git", "checkout", "-b", f"region-{region}"],
                cwd=temp_repo,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            subprocess.run(["git", "checkout", "main"], cwd=temp_repo, capture_output=True)

        # Map models to regions
        models_by_region = {
            "eu": [f"model/claude/eu/v{i}" for i in range(5)],
            "us": [f"model/claude/us/v{i}" for i in range(5)],
            "apac": [f"model/claude/apac/v{i}" for i in range(5)],
        }

        for region, models in models_by_region.items():
            for model_key in models:
                os.environ[f"ORCH_BRANCH_REROUTE_{model_key}"] = f"region-{region}"

        branch_rerouter.invalidate_repo()
        branch_rerouter.reset_stats()

        # Verify routing
        for region, models in models_by_region.items():
            for model_key in models:
                result = branch_rerouter.reroute(model_key)
                assert result == f"region-{region}"

        stats = branch_rerouter.stats()
        assert stats["rerouted"] == 15  # 5 + 5 + 5

    @pytest.mark.skipif(sys.platform != 'darwin', reason="Darwin-specific test")
    def test_darwin_high_concurrency_model_key_rerouting(self, temp_repo):
        """High-concurrency model key rerouting on Darwin (100 threads, 1000 operations)."""
        os.chdir(temp_repo)

        for i in range(100):
            os.environ[f"ORCH_BRANCH_REROUTE_model/m{i}"] = "main"

        branch_rerouter.invalidate_repo()
        results = []
        errors = []

        def high_load_worker(worker_id):
            try:
                for _ in range(10):
                    model_id = worker_id % 100
                    result = branch_rerouter.reroute(f"model/m{model_id}")
                    results.append(result)
            except Exception as e:
                errors.append(str(e))

        threads = [
            threading.Thread(target=high_load_worker, args=(i,))
            for i in range(100)
        ]

        start_time = time.time()
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)
        elapsed = time.time() - start_time

        assert len(errors) == 0
        assert len(results) == 1000  # 100 threads * 10 operations
        assert elapsed < 60  # Should complete within 60 seconds

    @pytest.mark.skipif(sys.platform != 'darwin', reason="Darwin-specific test")
    def test_darwin_stress_test_stats_accuracy(self, temp_repo):
        """Stats remain accurate under stress on Darwin (concurrent reroutes with stats checks)."""
        os.chdir(temp_repo)

        for i in range(50):
            os.environ[f"ORCH_BRANCH_REROUTE_model/v{i}"] = "main"

        branch_rerouter.invalidate_repo()
        branch_rerouter.reset_stats()

        errors = []

        def stress_test_worker():
            try:
                for i in range(50):
                    branch_rerouter.reroute(f"model/v{i}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=stress_test_worker) for _ in range(10)]

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert len(errors) == 0
        stats = branch_rerouter.stats()
        assert stats["rerouted"] == 500  # 10 threads * 50 operations
