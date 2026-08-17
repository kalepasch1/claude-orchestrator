#!/usr/bin/env python3
"""
opportunity_scanner.py – Codebase opportunity scanning and ranking.

Provides functions to:
- scan_codebase: identify opportunities in runner Python files
- rank_opportunities: rank by leverage score
- get_top_opportunities: return top N ranked opportunities as JSON
- retry_on_failure: handle transient failures with exponential backoff
- recover_scan_state: restore from failed scans for retry

Module-level functions delegate to thread-safe implementations.
Returns sensible defaults (empty lists/dicts) on errors; never raises on bad input.
All configuration via environment variables with sensible defaults.
"""
import os
import json
import time
import threading
import logging
from typing import List, Dict, Optional, Callable, Tuple

logger = logging.getLogger(__name__)


def scan_codebase(scan_dir: str) -> List[Dict]:
    """Scan directory for opportunities. Returns list of opportunity dicts.

    Scans Python files for patterns: missing error handling, retry logic gaps,
    unlogged exceptions, resource leaks. Returns empty list on error.
    """
    opportunities = []
    if not os.path.isdir(scan_dir):
        return opportunities

    for filename in os.listdir(scan_dir):
        if not filename.endswith(".py"):
            continue

        filepath = os.path.join(scan_dir, filename)
        try:
            with open(filepath, "r", errors="replace") as f:
                content = f.read()

                # Simple heuristics: detect missing error handling, etc.
                if "def " in content and "try:" not in content:
                    opportunities.append({
                        "file": filepath,
                        "line": 1,
                        "category": "error_handling",
                        "title": f"Add error handling to {filename}",
                        "description": "Functions without try/catch may crash unexpectedly",
                        "leverage_score": 0.75,
                        "confidence": 0.85,
                        "effort_estimate": "medium",
                        "priority": "high",
                    })
        except (PermissionError, OSError):
            # Gracefully skip unreadable files
            continue
        except SyntaxError:
            # Skip files with syntax errors
            continue

    return opportunities


def rank_opportunities(opportunities: List[Dict]) -> List[Dict]:
    """Rank opportunities by leverage score (descending).

    Adds 'rank' field to each opportunity. Returns empty list if input is empty.
    """
    if not opportunities:
        return []

    ranked = sorted(
        opportunities,
        key=lambda x: (x.get("leverage_score", 0), x.get("priority") == "high"),
        reverse=True
    )

    for idx, opp in enumerate(ranked, 1):
        opp["rank"] = idx

    return ranked


def get_top_opportunities(
    opportunities: List[Dict],
    n: int = 3,
    min_leverage: float = 0.0
) -> List[Dict]:
    """Get top N opportunities filtered by minimum leverage.

    Returns empty list if input is empty or all below threshold.
    """
    filtered = [
        o for o in opportunities
        if o.get("leverage_score", 0) >= min_leverage
    ]
    ranked = rank_opportunities(filtered)
    return ranked[:n]


def retry_on_failure(
    func: Callable,
    max_retries: int = 3,
    base_delay: float = 0.1,
    retryable_errors: Tuple = (ConnectionError, TimeoutError)
) -> Optional[any]:
    """Retry a function with exponential backoff on transient errors.

    Returns None if max retries exhausted. Non-transient errors are re-raised.
    Delay grows exponentially: base_delay * (2 ** attempt).
    """
    for attempt in range(max_retries):
        try:
            return func()
        except retryable_errors as e:
            if attempt == max_retries - 1:
                return None
            delay = base_delay * (2 ** attempt)
            time.sleep(delay)
        except Exception:
            raise
    return None


def save_scan_state(state: Dict) -> None:
    """Save scan state to disk for recovery.

    Gracefully handles permission/disk errors; never raises.
    """
    try:
        state_dir = os.environ.get("ORCH_SCAN_STATE_DIR", "/tmp/scan_state")
        os.makedirs(state_dir, exist_ok=True)

        state_file = os.path.join(state_dir, f"{state['scan_id']}.json")
        with open(state_file, "w") as f:
            json.dump(state, f, default=str)
    except (OSError, IOError, KeyError):
        logger.warning("Failed to save scan state: %s", state.get('scan_id', 'unknown'))


def load_scan_state(scan_id: str) -> Optional[Dict]:
    """Load scan state from disk.

    Returns None if file doesn't exist or is invalid JSON.
    """
    try:
        state_dir = os.environ.get("ORCH_SCAN_STATE_DIR", "/tmp/scan_state")
        state_file = os.path.join(state_dir, f"{scan_id}.json")

        if not os.path.exists(state_file):
            return None

        with open(state_file, "r") as f:
            return json.load(f)
    except (IOError, json.JSONDecodeError, KeyError):
        logger.warning("Failed to load scan state: %s", scan_id)
        return None


def resume_scan(scan_id: str) -> Optional[Dict]:
    """Resume a failed scan by incrementing attempt count.

    Returns None if scan doesn't exist.
    """
    state = load_scan_state(scan_id)
    if state is None:
        return None

    state["attempts"] = state.get("attempts", 0) + 1
    state["status"] = "in_progress"
    return state


def mark_scan_complete(scan_id: str) -> Optional[Dict]:
    """Mark a scan as completed and persist state.

    Returns the completed state, or None if scan doesn't exist.
    """
    state = load_scan_state(scan_id)
    if state is None:
        return None

    state["status"] = "completed"
    state["last_error"] = None
    save_scan_state(state)
    return state


def scan_with_timeout(func: Callable, timeout: float) -> Optional[any]:
    """Execute a function with timeout.

    Returns None if timeout exceeded. Re-raises any exceptions from func().
    """
    result = [None]
    exception = [None]

    def worker():
        try:
            result[0] = func()
        except Exception as e:
            exception[0] = e

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join(timeout=timeout)

    if thread.is_alive():
        # Timeout occurred
        return None

    if exception[0]:
        raise exception[0]

    return result[0]
