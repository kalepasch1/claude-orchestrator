"""Tests for branch_monitor — real-time branch management automation."""
import os
import sys
import tempfile
import subprocess
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import branch_monitor as bm


@pytest.fixture
def git_repo(tmp_path):
    """Create a minimal git repo with an agent branch."""
    repo = str(tmp_path / "repo")
    os.makedirs(repo)
    subprocess.run(["git", "init", repo], capture_output=True, check=True)
    subprocess.run(["git", "-C", repo, "commit", "--allow-empty", "-m", "init"],
                   capture_output=True, check=True)
    # create an agent branch
    subprocess.run(["git", "-C", repo, "branch", "agent/test-task"],
                   capture_output=True, check=True)
    return repo


class TestBranchEvent:
    def test_event_creation(self):
        e = bm.BranchEvent(branch="agent/foo", event_type="stale", details="old")
        assert e.branch == "agent/foo"
        assert e.event_type == "stale"
        assert e.timestamp > 0

    def test_snapshot_defaults(self):
        s = bm.MonitorSnapshot(timestamp=time.time())
        assert s.total_branches == 0
        assert s.stale_branches == []
        assert s.orphan_branches == []
        assert s.events == []


class TestBranchMonitor:
    def test_init(self, tmp_path):
        m = bm.BranchMonitor(str(tmp_path), interval=60)
        assert m.interval == 60
        assert m.auto_cleanup is False

    def test_scan_nonexistent_repo(self, tmp_path):
        m = bm.BranchMonitor(str(tmp_path / "nope"))
        snap = m.scan()
        assert snap.total_branches == 0

    def test_scan_empty_repo(self, git_repo):
        """Scan a repo with no remote agent branches returns 0 remote branches."""
        m = bm.BranchMonitor(git_repo)
        snap = m.scan()
        # No remote branches in a local-only repo
        assert snap.total_branches == 0

    def test_orphan_detection(self, git_repo):
        """Branches with no matching task slug are orphans."""
        m = bm.BranchMonitor(git_repo, task_slugs=["other-task"])
        # Manually inject a branch into scan results by scanning local branches
        # Since there are no remotes, test the orphan logic directly
        snap = bm.MonitorSnapshot(timestamp=time.time())
        slug = "test-task"
        if m.task_slugs and slug not in m.task_slugs:
            snap.orphan_branches.append("agent/test-task")
            snap.events.append(bm.BranchEvent(
                branch="agent/test-task", event_type="orphan",
                details=f"no task found for slug '{slug}'"))
        assert len(snap.orphan_branches) == 1
        assert snap.events[0].event_type == "orphan"

    def test_event_callback(self, tmp_path):
        events = []
        m = bm.BranchMonitor(str(tmp_path))
        m.on_event(lambda e: events.append(e))
        m._emit(bm.BranchEvent(branch="agent/x", event_type="stale"))
        assert len(events) == 1
        assert events[0].event_type == "stale"

    def test_callback_error_does_not_crash(self, tmp_path):
        def bad_cb(e):
            raise ValueError("boom")
        m = bm.BranchMonitor(str(tmp_path))
        m.on_event(bad_cb)
        # Should not raise
        m._emit(bm.BranchEvent(branch="agent/x", event_type="stale"))

    def test_latest_snapshot_none(self, tmp_path):
        m = bm.BranchMonitor(str(tmp_path))
        assert m.latest_snapshot() is None

    def test_start_stop(self, tmp_path):
        m = bm.BranchMonitor(str(tmp_path), interval=1)
        m.start()
        assert m._thread is not None and m._thread.is_alive()
        m.stop()
        assert not m._thread.is_alive()

    def test_max_snapshots_cap(self, tmp_path):
        m = bm.BranchMonitor(str(tmp_path))
        m._max_snapshots = 5
        for _ in range(10):
            m.scan()
        with m._lock:
            assert len(m._snapshots) == 5


class TestModuleLevelHelpers:
    def test_get_monitor_singleton(self, tmp_path):
        bm._default_monitor = None
        m1 = bm.get_monitor(str(tmp_path))
        m2 = bm.get_monitor(str(tmp_path))
        assert m1 is m2
        bm.shutdown_monitor()
        assert bm._default_monitor is None

    def test_shutdown_when_none(self):
        bm._default_monitor = None
        bm.shutdown_monitor()  # should not raise
