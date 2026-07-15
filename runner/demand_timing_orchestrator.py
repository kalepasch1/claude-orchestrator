#!/usr/bin/env python3
"""
demand_timing_orchestrator.py - Orchestrate when demand mining runs.

Manages timing decisions for periodic demand signal mining. Tracks state across runs
to prevent redundant scans, enforce cooldown windows, and apply backoff strategies
based on recency and success history. Persists state to a JSON file.

Strategies:
  - fixed_interval: run if cooldown_hours elapsed since last run
  - exponential_backoff: extend cooldown if no new signals found
  - demand_responsive: shorten window if recent high-demand signals
"""
import os
import sys
import json
import time
from typing import Dict, Optional, Tuple
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

HOME = os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator"))
TIMING_STATE_FILE = os.path.join(HOME, "demand_timing_state.json")

# Default timing configuration (in hours)
DEFAULT_COOLDOWN_HOURS = int(os.environ.get("ORCH_DEMAND_COOLDOWN_HOURS", "6"))
DEFAULT_MIN_INTERVAL = int(os.environ.get("ORCH_DEMAND_MIN_INTERVAL", "1"))
DEFAULT_MAX_BACKOFF = int(os.environ.get("ORCH_DEMAND_MAX_BACKOFF", "24"))

# Strategy selection
TIMING_STRATEGY = os.environ.get("ORCH_DEMAND_TIMING_STRATEGY", "fixed_interval")

# High-demand threshold (number of demand proposals in last run)
HIGH_DEMAND_THRESHOLD = int(os.environ.get("ORCH_DEMAND_HIGH_THRESHOLD", "3"))
HIGH_DEMAND_WINDOW_HOURS = int(os.environ.get("ORCH_DEMAND_HIGH_WINDOW_HOURS", "2"))


class DemandTimingState:
    """Tracks timing state for demand mining orchestration."""

    def __init__(self, state_file: str = TIMING_STATE_FILE):
        self.state_file = state_file if state_file else TIMING_STATE_FILE
        self.state: Dict = {
            "last_run_timestamp": None,
            "last_run_count": 0,
            "consecutive_empty": 0,
            "current_backoff_hours": DEFAULT_COOLDOWN_HOURS,
            "created_at": datetime.now().isoformat(),
        }
        self._load()

    def _load(self) -> None:
        """Load state from file if it exists."""
        if not os.path.isfile(self.state_file):
            return
        try:
            with open(self.state_file, "r") as f:
                persisted = json.load(f)
                if isinstance(persisted, dict):
                    self.state.update(persisted)
        except Exception:
            pass

    def save(self) -> None:
        """Persist state to file."""
        try:
            os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
            with open(self.state_file, "w") as f:
                json.dump(self.state, f, indent=2)
        except Exception:
            pass

    def record_run(self, signal_count: int) -> None:
        """Record a demand mining run with the number of signals found."""
        self.state["last_run_timestamp"] = datetime.now().isoformat()
        self.state["last_run_count"] = signal_count
        if signal_count == 0:
            self.state["consecutive_empty"] += 1
        else:
            self.state["consecutive_empty"] = 0
        self.save()

    def get_last_run_time(self) -> Optional[datetime]:
        """Get the timestamp of the last demand mining run."""
        ts = self.state.get("last_run_timestamp")
        if ts:
            try:
                return datetime.fromisoformat(ts)
            except (ValueError, TypeError):
                return None
        return None

    def get_last_run_count(self) -> int:
        """Get the number of demand signals from the last run."""
        return self.state.get("last_run_count", 0)

    def hours_since_last_run(self) -> Optional[float]:
        """Return hours elapsed since last run, or None if never run."""
        last = self.get_last_run_time()
        if last is None:
            return None
        return (datetime.now() - last).total_seconds() / 3600.0

    def set_backoff_hours(self, hours: float) -> None:
        """Update the current backoff window."""
        self.state["current_backoff_hours"] = min(
            max(hours, DEFAULT_MIN_INTERVAL), DEFAULT_MAX_BACKOFF
        )
        self.save()

    def get_backoff_hours(self) -> float:
        """Get the current backoff window in hours."""
        return self.state.get("current_backoff_hours", DEFAULT_COOLDOWN_HOURS)


def should_run_fixed_interval(state: DemandTimingState) -> Tuple[bool, str]:
    """
    Fixed interval strategy: run if cooldown elapsed since last run.

    Returns (should_run, reason).
    """
    hours_since = state.hours_since_last_run()
    if hours_since is None:
        return True, "never run before"

    cooldown = state.get_backoff_hours()
    if hours_since >= cooldown:
        return True, f"{hours_since:.1f}h since last run >= {cooldown}h cooldown"
    return False, f"in cooldown: {hours_since:.1f}h < {cooldown}h"


def should_run_exponential_backoff(state: DemandTimingState) -> Tuple[bool, str]:
    """
    Exponential backoff strategy: extend cooldown if recent runs found no signals.

    Shortens window if high demand recently detected.
    Returns (should_run, reason).
    """
    hours_since = state.hours_since_last_run()
    if hours_since is None:
        return True, "never run before"

    backoff = state.get_backoff_hours()
    consecutive_empty = state.state.get("consecutive_empty", 0)

    # Increase backoff if we've had multiple empty runs
    if consecutive_empty > 2:
        new_backoff = min(backoff * 1.5, DEFAULT_MAX_BACKOFF)
        state.set_backoff_hours(new_backoff)
        backoff = new_backoff

    if hours_since >= backoff:
        return True, f"exponential: {hours_since:.1f}h >= backoff {backoff:.1f}h"
    return False, f"exponential backoff: {hours_since:.1f}h < {backoff:.1f}h"


def should_run_demand_responsive(state: DemandTimingState) -> Tuple[bool, str]:
    """
    Demand-responsive strategy: adapt window based on recent signal volume.

    If high demand detected recently, shorten the window. Otherwise use standard backoff.
    Returns (should_run, reason).
    """
    hours_since = state.hours_since_last_run()
    if hours_since is None:
        return True, "never run before"

    last_count = state.get_last_run_count()

    # If last run found high demand, use shorter window
    if last_count >= HIGH_DEMAND_THRESHOLD:
        window = HIGH_DEMAND_WINDOW_HOURS
        if hours_since >= window:
            return True, f"high-demand mode: {hours_since:.1f}h >= {window}h"
        return False, f"high-demand backoff: {hours_since:.1f}h < {window}h"

    # Normal backoff
    backoff = state.get_backoff_hours()
    if hours_since >= backoff:
        return True, f"normal: {hours_since:.1f}h >= {backoff}h"
    return False, f"backoff: {hours_since:.1f}h < {backoff}h"


def should_run(
    strategy: Optional[str] = None,
    state_file: str = TIMING_STATE_FILE
) -> Tuple[bool, str]:
    """
    Determine if demand mining should run now.

    Args:
        strategy: Timing strategy (defaults to TIMING_STRATEGY env var)
        state_file: Path to state file

    Returns:
        (should_run, reason_message)
    """
    if strategy is None:
        strategy = TIMING_STRATEGY

    state = DemandTimingState(state_file)

    if strategy == "exponential_backoff":
        return should_run_exponential_backoff(state)
    elif strategy == "demand_responsive":
        return should_run_demand_responsive(state)
    else:  # fixed_interval
        return should_run_fixed_interval(state)


def record_mining_result(
    signal_count: int,
    state_file: str = TIMING_STATE_FILE
) -> None:
    """
    Record the outcome of a demand mining run.

    Args:
        signal_count: Number of demand signals found in this run
        state_file: Path to state file
    """
    state = DemandTimingState(state_file)
    state.record_run(signal_count)

    # Adjust backoff based on strategy
    strategy = os.environ.get("ORCH_DEMAND_TIMING_STRATEGY", "fixed_interval")
    if strategy == "exponential_backoff":
        consecutive_empty = state.state.get("consecutive_empty", 0)
        if consecutive_empty > 2:
            new_backoff = min(state.get_backoff_hours() * 1.5, DEFAULT_MAX_BACKOFF)
            state.set_backoff_hours(new_backoff)
    elif strategy == "demand_responsive":
        if signal_count >= HIGH_DEMAND_THRESHOLD:
            state.set_backoff_hours(HIGH_DEMAND_WINDOW_HOURS)
        else:
            state.set_backoff_hours(DEFAULT_COOLDOWN_HOURS)


def get_next_run_time(
    strategy: Optional[str] = None,
    state_file: str = TIMING_STATE_FILE
) -> Optional[datetime]:
    """
    Calculate when the next demand mining should run.

    Returns None if should run immediately, or a datetime for the next scheduled run.
    """
    should, _ = should_run(strategy, state_file)
    if should:
        return None

    state = DemandTimingState(state_file)
    last_run = state.get_last_run_time()
    if last_run is None:
        return None

    backoff = state.get_backoff_hours()
    return last_run + timedelta(hours=backoff)


def reset_state(state_file: str = TIMING_STATE_FILE) -> None:
    """Reset timing state (useful for testing and recovery)."""
    state = DemandTimingState(state_file)
    state.state = {
        "last_run_timestamp": None,
        "last_run_count": 0,
        "consecutive_empty": 0,
        "current_backoff_hours": DEFAULT_COOLDOWN_HOURS,
        "created_at": datetime.now().isoformat(),
    }
    state.save()


if __name__ == "__main__":
    should, reason = should_run()
    print(f"Should run: {should}")
    print(f"Reason: {reason}")
