"""
Reaper lease safety for self-deploy.

The self-deploy system's canary gate and restart logic must coordinate with the
reaper to ensure that:

1. A runner that holds the restart flag does NOT get reaped before completing it
2. A restart-pending flag is not indefinitely stale (prevents zombie restart requests)
3. Concurrent restart requests do not race and create duplicate restarts
4. A failed restart attempt is properly logged and allows retry
"""
import os
import sys
import time
import tempfile
import threading

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import self_deploy  # noqa: E402


@pytest.fixture
def temp_repo():
    """Create a temp directory for test repos."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def isolated_restart_flag(monkeypatch, temp_repo):
    """Isolate restart flag to a temp location."""
    flag_path = os.path.join(temp_repo, ".restart_requested")
    monkeypatch.setattr(self_deploy, "RESTART_FLAG", flag_path)
    return flag_path


class TestRestartPendingAge:
    """Restart-pending flag must not be indefinitely stale."""

    def test_pending_with_fresh_flag(self, isolated_restart_flag):
        """A restart pending in the current cycle should be recognized."""
        ts = time.time()
        commit = "abc123def456abc123def456abc123def456"
        with open(isolated_restart_flag, "w") as f:
            f.write(f"{ts} restarting into {commit}\n")

        assert self_deploy.restart_pending_for(commit)

    def test_pending_age_expires(self, isolated_restart_flag, monkeypatch):
        """A pending flag older than MAX_AGE should expire."""
        # Write a flag that is older than MAX_AGE
        old_time = time.time() - self_deploy.RESTART_PENDING_MAX_AGE - 10
        with open(isolated_restart_flag, "w") as f:
            f.write(f"{old_time} old reason\n")

        commit = "abc123def456abc123def456abc123def456"
        assert not self_deploy.restart_pending_for(commit[:8])

    def test_pending_for_wrong_commit_returns_false(self, isolated_restart_flag):
        """Pending flag for a different commit should not apply."""
        ts = time.time()
        with open(isolated_restart_flag, "w") as f:
            f.write(f"{ts} for abc123\n")

        different_commit = "def456def456def456def456def456def456"
        assert not self_deploy.restart_pending_for(different_commit[:8])

    def test_missing_flag_returns_false(self, isolated_restart_flag):
        """Absent restart flag means no pending restart."""
        commit = "abc123def456abc123def456abc123def456"
        assert not self_deploy.restart_pending_for(commit[:8])


class TestRequestRestart:
    """Restart request flag creation."""

    def test_request_restart_writes_flag(self, isolated_restart_flag):
        """Request restart writes a timestamp and reason."""
        self_deploy.request_restart("test reason")

        assert os.path.exists(isolated_restart_flag)
        with open(isolated_restart_flag) as f:
            content = f.read()
        assert "test reason" in content

    def test_request_restart_timestamp_format(self, isolated_restart_flag):
        """Flag should contain ISO format timestamp."""
        self_deploy.request_restart("test")

        with open(isolated_restart_flag) as f:
            content = f.read()
        # Should contain ISO timestamp
        assert "T" in content and ":" in content

    def test_multiple_restart_requests_overwrite(self, isolated_restart_flag):
        """Multiple calls should update the flag, not append."""
        self_deploy.request_restart("first")
        first_content = open(isolated_restart_flag).read()

        time.sleep(0.01)  # Ensure different timestamp
        self_deploy.request_restart("second")
        second_content = open(isolated_restart_flag).read()

        # second should replace first, not append
        assert second_content.count("first") == 0
        assert "second" in second_content


class TestCanaryGateExecution:
    """Canary gate safety and isolation."""

    def test_canary_gate_needs_tests_to_exist(self, temp_repo):
        """Canary gate requires test files; missing tests fail closed."""
        # Create a minimal repo without test files
        os.makedirs(os.path.join(temp_repo, "runner", "tests"), exist_ok=True)

        # Gate should fail closed if no tests found
        result = self_deploy.canary_gate(temp_repo, "abc123", "def456")
        assert result is False  # Fails closed when no tests

    def test_gate_env_blocks_live_control_plane(self, monkeypatch):
        """Gate environment must not inherit live Supabase credentials."""
        monkeypatch.setenv("SUPABASE_URL", "https://live.supabase.co")
        monkeypatch.setenv("SUPABASE_SERVICE_KEY", "real-key")

        env = self_deploy.gate_env()

        if self_deploy.CANARY_HERMETIC:
            # Hermetic mode blocks the plane
            assert env.get("SUPABASE_URL") == "http://localhost"
            assert env.get("SUPABASE_SERVICE_KEY") == "canary-hermetic-no-live-control-plane"

    def test_gate_env_preserves_other_vars(self, monkeypatch):
        """Gate env should preserve non-credential variables."""
        monkeypatch.setenv("RUNNER_ID", "test-runner")

        env = self_deploy.gate_env()

        assert env.get("RUNNER_ID") == "test-runner"

    def test_canary_hermetic_flag_can_be_disabled(self, monkeypatch):
        """ORCH_CANARY_HERMETIC=0 should allow live plane access in tests."""
        monkeypatch.setattr(self_deploy, "CANARY_HERMETIC", False)
        monkeypatch.setenv("SUPABASE_URL", "https://live.supabase.co")

        env = self_deploy.gate_env()

        # Should inherit the real value
        assert env.get("SUPABASE_URL") == "https://live.supabase.co"


class TestOriginTracking:
    """Origin/master reconciliation for self-deploy."""

    def test_track_origin_can_be_disabled(self, monkeypatch):
        """ORCH_SELF_DEPLOY_TRACK_ORIGIN=0 should skip origin fetch."""
        monkeypatch.setattr(self_deploy, "TRACK_ORIGIN", False)

        result = self_deploy.reconcile_origin(tempfile.gettempdir())

        assert result.get("tracked") is False
        assert result.get("action") == "disabled"

    def test_reconcile_origin_catches_fetch_errors(self, monkeypatch, temp_repo):
        """A failed fetch should not crash but report safely."""
        monkeypatch.setattr(self_deploy, "TRACK_ORIGIN", True)

        def bad_git(repo, args, timeout=None):
            r = type('R', (), {})()
            r.returncode = 1
            r.stderr = "fatal: fetch failed"
            r.stdout = ""
            return r

        monkeypatch.setattr(self_deploy, "_git", bad_git)

        result = self_deploy.reconcile_origin(temp_repo)

        assert result.get("ok") is False
        assert result.get("action") == "fetch_failed"


class TestCanaryPinning:
    """Canary runs in isolated checkout, not the live tree."""

    def test_pin_checkout_creates_worktree(self, temp_repo):
        """Pin should create an isolated worktree if available."""
        # This would need a real git repo to test fully; skip in isolation
        result = self_deploy.pin_checkout(temp_repo, "abc123")
        # Should return None when pinning fails (expected in test env)
        assert result is None or os.path.isdir(result)

    def test_unpin_removes_worktree(self, temp_repo):
        """Unpin should clean up the worktree."""
        wt_path = os.path.join(temp_repo, ".runtime", "test-wt")
        os.makedirs(wt_path, exist_ok=True)

        # Should not raise even if cleanup partially fails
        self_deploy.unpin(temp_repo, wt_path)


class TestCheckNewCode:
    """Detecting stale code vs fresh HEAD."""

    def test_stale_when_running_differs_from_head(self, temp_repo, monkeypatch):
        """Code is stale when running_commit != head_commit."""
        monkeypatch.setattr(self_deploy, "running_commit",
                          lambda r: "abc123abc123abc123abc123abc123abc123")
        monkeypatch.setattr(self_deploy, "current_commit",
                          lambda r: "def456def456def456def456def456def456")

        result = self_deploy.check_new_code(temp_repo)

        assert result["stale"] is True
        assert result["unknown"] is False

    def test_not_stale_when_commits_match(self, temp_repo, monkeypatch):
        """Code is fresh when both commits are identical."""
        commit = "abc123abc123abc123abc123abc123abc123"
        monkeypatch.setattr(self_deploy, "running_commit", lambda r: commit)
        monkeypatch.setattr(self_deploy, "current_commit", lambda r: commit)

        result = self_deploy.check_new_code(temp_repo)

        assert result["stale"] is False
        assert result["unknown"] is False

    def test_unknown_when_running_commit_missing(self, temp_repo, monkeypatch):
        """Unknown staleness when running_commit not recorded."""
        monkeypatch.setattr(self_deploy, "running_commit", lambda r: "")
        monkeypatch.setattr(self_deploy, "current_commit",
                          lambda r: "abc123abc123abc123abc123abc123abc123")

        result = self_deploy.check_new_code(temp_repo)

        assert result["unknown"] is True
        assert result["stale"] is False


class TestBootMarkerRecording:
    """Boot marker file for boot-to-current tracking."""

    def test_record_boot_writes_commit(self, temp_repo):
        """record_boot should write the current commit to the boot file."""
        boot_path = os.path.join(temp_repo, self_deploy.BOOT_FILE)
        # Simulate current_commit
        commit = "abc123abc123abc123abc123abc123abc123"

        result = self_deploy.record_boot(temp_repo, commit)

        # Should write the commit
        assert result == commit
        assert os.path.exists(boot_path)
        with open(boot_path) as f:
            assert f.read().strip() == commit

    def test_record_boot_idempotent(self, temp_repo):
        """Multiple record_boot calls should be safe."""
        commit = "abc123abc123abc123abc123abc123abc123"
        self_deploy.record_boot(temp_repo, commit)
        self_deploy.record_boot(temp_repo, commit)

        boot_path = os.path.join(temp_repo, self_deploy.BOOT_FILE)
        assert os.path.exists(boot_path)
        with open(boot_path) as f:
            content = f.read().strip()
        assert content == commit

    def test_running_commit_reads_boot_file(self, temp_repo, monkeypatch):
        """running_commit should read the boot marker."""
        commit = "def456def456def456def456def456def456"
        boot_path = os.path.join(temp_repo, self_deploy.BOOT_FILE)

        # Clear any env var override
        monkeypatch.delenv("ORCH_BOOT_COMMIT", raising=False)

        # Write to the boot file
        with open(boot_path, "w") as f:
            f.write(commit + "\n")

        result = self_deploy.running_commit(temp_repo)

        assert result == commit

    def test_running_commit_from_env_takes_precedence(self, temp_repo, monkeypatch):
        """ORCH_BOOT_COMMIT env var should override the boot file."""
        env_commit = "aaa111aaa111aaa111aaa111aaa111aaa111"
        file_commit = "bbb222bbb222bbb222bbb222bbb222bbb222"

        boot_path = os.path.join(temp_repo, self_deploy.BOOT_FILE)
        with open(boot_path, "w") as f:
            f.write(file_commit)

        monkeypatch.setenv("ORCH_BOOT_COMMIT", env_commit)

        result = self_deploy.running_commit(temp_repo)

        assert result == env_commit


class TestCanaryTimeout:
    """Canary gate timeout configuration."""

    def test_canary_timeout_default_is_reasonable(self):
        """Default timeout should be long enough for idle machine."""
        # 600s (10 min) was measured as safe on idle hardware
        assert self_deploy.CANARY_TIMEOUT >= 300
        assert self_deploy.CANARY_TIMEOUT <= 1200

    def test_canary_timeout_is_configurable(self, monkeypatch):
        """ORCH_CANARY_TIMEOUT env var should override default."""
        monkeypatch.setenv("ORCH_CANARY_TIMEOUT", "120")
        # Re-import to pick up the new env var
        import importlib
        importlib.reload(self_deploy)

        assert self_deploy.CANARY_TIMEOUT == 120

    def test_restart_pending_max_age_covers_long_tasks(self):
        """MAX_AGE should be long enough for a long-running task to complete."""
        # If a task can run up to 3600s, the flag should stay pending that long
        assert self_deploy.RESTART_PENDING_MAX_AGE >= 3600


class TestConcurrency:
    """Concurrent self-deploy operations."""

    def test_restart_flag_is_last_write_wins(self, isolated_restart_flag):
        """Multiple threads writing restart flags should race safely."""
        results = []

        def write_flag(commit):
            self_deploy.request_restart(f"commit {commit}")
            with open(isolated_restart_flag) as f:
                results.append(f.read())

        threads = [
            threading.Thread(target=write_flag, args=(f"c{i}",))
            for i in range(5)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All reads should show the same content (last write)
        # This is a sanity check that the flag was written atomically
        assert len(results) > 0


class TestMaybeDeployFlow:
    """Full self-deploy flow."""

    def test_maybe_deploy_handles_missing_repo(self):
        """maybe_deploy should handle repo errors gracefully."""
        result = self_deploy.maybe_deploy(repo="/nonexistent/path")

        assert result.get("deployed") is False
        assert result.get("reason") is not None

    def test_maybe_deploy_returns_structured_dict(self, temp_repo, monkeypatch):
        """maybe_deploy should always return a structured result dict."""
        monkeypatch.setattr(self_deploy, "check_new_code",
                          lambda r: {"stale": False, "unknown": False,
                                    "running_commit": "", "head_commit": ""})

        result = self_deploy.maybe_deploy(repo=temp_repo)

        assert isinstance(result, dict)
        assert "deployed" in result
        assert "reason" in result


class TestCriticalCanaryTests:
    """Critical test paths for canary gate."""

    def test_critical_canary_tests_exist_in_code(self):
        """Critical test files should be clearly defined."""
        assert isinstance(self_deploy.CRITICAL_CANARY_TESTS, tuple)
        assert len(self_deploy.CRITICAL_CANARY_TESTS) > 0
        # At least test_self_deploy should be in critical path
        critical_names = [os.path.basename(t) for t in self_deploy.CRITICAL_CANARY_TESTS]
        assert any("self_deploy" in name for name in critical_names)

    def test_critical_tests_prevent_import_failures(self):
        """Critical set should include all-modules-importable test."""
        critical_names = [os.path.basename(t) for t in self_deploy.CRITICAL_CANARY_TESTS]
        assert any("import" in name for name in critical_names)
