#!/usr/bin/env python3
"""
auto_filer.py — HTTP 409 Conflict handler for concurrent file writes.

Detects HTTP 409 Conflict responses when writing files to concurrent streams,
logs conflicts with timestamp and context, and implements exponential backoff
retry before escalating. Preserves all existing file I/O behavior in non-409 paths.

Environment:
    ORCH_CONFLICT_BACKOFF_MAX_RETRIES   Max retry attempts (default: 3)
    ORCH_CONFLICT_BACKOFF_BASE_DELAY    Initial backoff in seconds (default: 2)
"""
import os
import sys
import time
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import log as _log_mod
    _log = _log_mod.get("auto_filer")
except Exception:
    import logging
    _log = logging.getLogger("auto_filer")


# ── Configuration ─────────────────────────────────────────────────────────────
CONFLICT_BACKOFF_MAX_RETRIES = int(os.environ.get("ORCH_CONFLICT_BACKOFF_MAX_RETRIES", "3"))
CONFLICT_BACKOFF_BASE_DELAY = float(os.environ.get("ORCH_CONFLICT_BACKOFF_BASE_DELAY", "2"))
CONFLICT_BACKOFF_MAX_DELAY = float(os.environ.get("ORCH_CONFLICT_BACKOFF_MAX_DELAY", "8"))


# ── Singleton state ───────────────────────────────────────────────────────────
_lock = threading.Lock()
_stats = {
    "conflicts_detected": 0,
    "retries_succeeded": 0,
    "retries_exhausted": 0,
    "last_conflict_path": "",
    "last_conflict_time": 0.0,
}


def _exponential_backoff(attempt: int) -> float:
    """Calculate backoff delay for attempt N (0-indexed).

    Returns delay clamped to [base_delay, max_delay].
    Formula: base_delay * 2^attempt, clamped to max_delay.
    """
    if attempt < 0:
        return 0.0
    delay = CONFLICT_BACKOFF_BASE_DELAY * (2 ** attempt)
    return min(delay, CONFLICT_BACKOFF_MAX_DELAY)


def _record_conflict(filepath: str, competing_process_hint: str = ""):
    """Record conflict metadata for logging and metrics."""
    with _lock:
        _stats["conflicts_detected"] += 1
        _stats["last_conflict_path"] = filepath
        _stats["last_conflict_time"] = time.time()

    hint_msg = f" (competing process: {competing_process_hint})" if competing_process_hint else ""
    _log.warning(
        "HTTP 409 Conflict on file write: path=%s%s",
        filepath, hint_msg
    )


def write_with_conflict_retry(filepath: str, content: bytes, mode: str = "wb",
                              on_409_hint: callable = None) -> tuple[bool, str]:
    """Write file content with automatic retry on 409 Conflict.

    Args:
        filepath: Path to file to write
        content: Bytes to write
        mode: File open mode (default: 'wb' for binary write)
        on_409_hint: Optional callable that returns a competing process hint
                    when 409 is detected. Signature: on_409_hint(filepath) -> str

    Returns:
        (success: bool, error_msg: str)
        - On success: (True, "")
        - On 409 after retries: (False, "exhausted retries after 409 conflict")
        - On other errors: (False, error description)
    """
    if not filepath:
        return (False, "filepath is empty")

    attempt = 0
    last_error = ""

    while attempt <= CONFLICT_BACKOFF_MAX_RETRIES:
        try:
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            with open(filepath, mode) as fh:
                if 'b' in mode:
                    # Binary mode: write bytes as-is
                    fh.write(content if isinstance(content, bytes) else content.encode('utf-8'))
                else:
                    # Text mode: write string
                    fh.write(content if isinstance(content, str) else content.decode('utf-8', errors='replace'))

            # Success
            if attempt > 0:
                with _lock:
                    _stats["retries_succeeded"] += 1
                _log.info("File write succeeded after %d retry(ies): %s", attempt, filepath)
            return (True, "")

        except PermissionError as e:
            # Permission errors are not 409 conflicts; return immediately
            last_error = str(e)
            _log.error("File write failed (permission denied): path=%s, error=%s", filepath, last_error)
            return (False, last_error)

        except OSError as e:
            # Detect 409-like conflicts: "resource busy" or concurrent write errors
            # NOTE: "permission denied" and "file exists" are NOT auto-filed; only resource busy
            error_str = str(e).lower()
            is_conflict = any(phrase in error_str for phrase in [
                "resource busy",
                "text file busy",
                "device or resource busy",
                "conflict",
            ])

            last_error = str(e)

            if is_conflict and attempt < CONFLICT_BACKOFF_MAX_RETRIES:
                # Record conflict and prepare for retry
                hint = ""
                if on_409_hint:
                    try:
                        hint = on_409_hint(filepath)
                    except Exception:
                        hint = ""

                _record_conflict(filepath, hint)

                # Exponential backoff before retry
                delay = _exponential_backoff(attempt)
                _log.debug(
                    "409-like conflict detected on write: %s; "
                    "retrying in %.1f seconds (attempt %d/%d)",
                    filepath, delay, attempt + 1, CONFLICT_BACKOFF_MAX_RETRIES
                )
                time.sleep(delay)
                attempt += 1
                continue

            # Not a conflict, or exhausted retries
            if is_conflict:
                with _lock:
                    _stats["retries_exhausted"] += 1
                _log.error(
                    "Exhausted retries after 409 conflict: path=%s, "
                    "attempts=%d, last_error=%s",
                    filepath, CONFLICT_BACKOFF_MAX_RETRIES, last_error
                )
                return (False, "exhausted retries after 409 conflict")
            else:
                # Not a conflict; return the error immediately
                _log.error("File write failed (non-conflict): path=%s, error=%s", filepath, last_error)
                return (False, last_error)

        except Exception as e:
            # Unexpected error; fail-soft and return immediately
            last_error = str(e)
            _log.error("Unexpected error during file write: path=%s, error=%s", filepath, last_error)
            return (False, last_error)

    # Should not reach here, but fail-soft just in case
    return (False, "write failed after retries: " + last_error)


def stats() -> dict:
    """Return current conflict handler statistics."""
    with _lock:
        return dict(_stats)


def reset_stats():
    """Reset all statistics counters."""
    with _lock:
        _stats["conflicts_detected"] = 0
        _stats["retries_succeeded"] = 0
        _stats["retries_exhausted"] = 0
        _stats["last_conflict_path"] = ""
        _stats["last_conflict_time"] = 0.0


# ── Standalone mode ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    if "--stats" in sys.argv:
        import json
        print(json.dumps(stats(), indent=2))
    else:
        print("Usage: python3 auto_filer.py [--stats]")
