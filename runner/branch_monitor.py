#!/usr/bin/env python3
"""
branch_monitor.py — real-time branch management automation.

Provides continuous monitoring of agent branches, detecting stale/orphan
branches and triggering automated recovery or cleanup actions without
manual intervention.

Env vars:
    ORCH_BRANCH_MONITOR_INTERVAL   seconds between scans (default 300)
    ORCH_BRANCH_MONITOR_ENABLED    "true" to enable (default "true")
    ORCH_BRANCH_AUTO_CLEANUP       "true" to auto-delete stale merged branches (default "false")
"""
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log as _log_mod
import branch_lifecycle as bl

_log = _log_mod.get("branch_monitor")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
MONITOR_INTERVAL = int(os.environ.get("ORCH_BRANCH_MONITOR_INTERVAL", "300"))
MONITOR_ENABLED = os.environ.get("ORCH_BRANCH_MONITOR_ENABLED", "true").lower() in ("1", "true", "yes")
AUTO_CLEANUP = os.environ.get("ORCH_BRANCH_AUTO_CLEANUP", "false").lower() in ("1", "true", "yes")


@dataclass
class BranchEvent:
    """Represents a detected branch event."""
    branch: str
    event_type: str  # "stale", "orphan", "recovered", "cleaned"
    details: str = ""
    timestamp: float = field(default_factory=time.time)


@dataclass
class MonitorSnapshot:
    """Point-in-time snapshot of branch health."""
    timestamp: float
    total_branches: int = 0
    stale_branches: List[str] = field(default_factory=list)
    orphan_branches: List[str] = field(default_factory=list)
    healthy_branches: List[str] = field(default_factory=list)
    events: List[BranchEvent] = field(default_factory=list)


EventCallback = Callable[[BranchEvent], None]


class BranchMonitor:
    """Continuously monitors agent branches for staleness and orphans.

    Usage:
        monitor = BranchMonitor("/path/to/repo")
        monitor.on_event(my_callback)
        monitor.start()       # background thread
        ...
        monitor.stop()
    """

    def __init__(self, repo_path: str, interval: int = None,
                 task_slugs: Optional[List[str]] = None,
                 auto_cleanup: bool = None):
        self.repo_path = repo_path
        self.interval = interval if interval is not None else MONITOR_INTERVAL
        self.task_slugs = set(task_slugs or [])
        self.auto_cleanup = auto_cleanup if auto_cleanup is not None else AUTO_CLEANUP
        self._callbacks: List[EventCallback] = []
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._snapshots: List[MonitorSnapshot] = []
        self._max_snapshots = 100

    def on_event(self, callback: EventCallback):
        """Register a callback for branch events."""
        self._callbacks.append(callback)

    def _emit(self, event: BranchEvent):
        for cb in self._callbacks:
            try:
                cb(event)
            except Exception as e:
                _log.warning("event callback error: %s", e)

    def scan(self) -> MonitorSnapshot:
        """Run a single scan and return a snapshot."""
        snap = MonitorSnapshot(timestamp=time.time())

        try:
            r = subprocess.run(
                ["git", "branch", "-r", "--list", "origin/agent/*"],
                cwd=self.repo_path, capture_output=True, text=True, timeout=30,
            )
            if r.returncode != 0:
                branches = []
            else:
                branches = [b.strip() for b in r.stdout.splitlines() if b.strip()]
        except Exception as e:
            _log.error("scan failed: %s", e)
            branches = []

        snap.total_branches = len(branches)

        for branch in branches:
            local_name = branch.replace("origin/", "", 1) if branch.startswith("origin/") else branch
            slug = local_name.replace("agent/", "", 1) if local_name.startswith("agent/") else local_name

            # Check staleness
            stale = bl.is_stale(self.repo_path, branch)
            if stale:
                snap.stale_branches.append(local_name)
                event = BranchEvent(branch=local_name, event_type="stale",
                                    details=f"branch {local_name} exceeds stale threshold")
                snap.events.append(event)
                self._emit(event)
                continue

            # Check orphan (no matching task slug)
            if self.task_slugs and slug not in self.task_slugs:
                snap.orphan_branches.append(local_name)
                event = BranchEvent(branch=local_name, event_type="orphan",
                                    details=f"no task found for slug '{slug}'")
                snap.events.append(event)
                self._emit(event)
                continue

            snap.healthy_branches.append(local_name)

        with self._lock:
            self._snapshots.append(snap)
            if len(self._snapshots) > self._max_snapshots:
                self._snapshots = self._snapshots[-self._max_snapshots:]

        return snap

    def latest_snapshot(self) -> Optional[MonitorSnapshot]:
        """Return the most recent snapshot, or None."""
        with self._lock:
            return self._snapshots[-1] if self._snapshots else None

    def start(self):
        """Start background monitoring thread."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="branch-monitor")
        self._thread.start()
        _log.info("branch monitor started (interval=%ds)", self.interval)

    def stop(self):
        """Stop background monitoring."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=10)
        _log.info("branch monitor stopped")

    def _run(self):
        while not self._stop_event.is_set():
            try:
                self.scan()
            except Exception as e:
                _log.error("monitor scan error: %s", e)
            self._stop_event.wait(self.interval)


# ---------------------------------------------------------------------------
# Module-level convenience
# ---------------------------------------------------------------------------
_default_monitor: Optional[BranchMonitor] = None
_default_lock = threading.Lock()


def get_monitor(repo_path: str, **kwargs) -> BranchMonitor:
    """Get or create a singleton monitor for the given repo."""
    global _default_monitor
    with _default_lock:
        if _default_monitor is None or _default_monitor.repo_path != repo_path:
            _default_monitor = BranchMonitor(repo_path, **kwargs)
        return _default_monitor


def shutdown_monitor():
    """Stop the singleton monitor."""
    global _default_monitor
    with _default_lock:
        if _default_monitor:
            _default_monitor.stop()
            _default_monitor = None
