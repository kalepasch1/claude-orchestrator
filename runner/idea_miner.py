#!/usr/bin/env python3
"""
idea_miner.py - Signal-to-task generator from runner error logs and support queue.

Reads runner error logs (JSON lines) and optional support queue to extract evidence-anchored
improvement tasks. Outputs to stdout (dry-run) or appends to runner/generated_tasks.jsonl.

Fail-soft: missing logs/queue → skip, log warning, continue.
Module-level singleton pattern with thread-safe state.
"""

import os
import sys
import json
import re
import csv
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional
import logging
import threading
import hashlib
from collections import defaultdict

# Configuration from environment
IDEA_MINER_MODE = os.getenv("IDEA_MINER_MODE", "dry-run")  # dry-run | generate
IDEA_MINER_LOG_PATH = os.getenv("IDEA_MINER_LOG_PATH", "runner/logs/runner.log")
IDEA_MINER_DEDUP_DAYS = int(os.getenv("IDEA_MINER_DEDUP_DAYS", "7"))
IDEA_MINER_MIN_CONFIDENCE = float(os.getenv("IDEA_MINER_MIN_CONFIDENCE", "0.5"))
IDEA_MINER_SUPPORT_QUEUE = os.getenv("IDEA_MINER_SUPPORT_QUEUE", "runner/support_queue.jsonl")

GENERATED_TASKS_PATH = "runner/generated_tasks.jsonl"
GENERATED_TASKS_CSV_PATH = "runner/generated_tasks.csv"

_lock = threading.Lock()
_logger = None
_state = None


def _get_logger():
    """Get or create logger."""
    global _logger
    if _logger is None:
        _logger = logging.getLogger("idea_miner")
        handler = logging.StreamHandler(sys.stderr)
        formatter = logging.Formatter("%(levelname)s: %(message)s")
        handler.setFormatter(formatter)
        _logger.addHandler(handler)
        _logger.setLevel(logging.WARNING)
    return _logger


def _log_warning(msg: str, exc: Optional[Exception] = None):
    """Log warning message, optionally with exception."""
    logger = _get_logger()
    if exc:
        logger.warning(f"{msg}: {exc}")
    else:
        logger.warning(msg)


def _extract_error_signature(error_msg: str) -> str:
    """Extract canonical error signature (strip timestamps, line numbers, variable values)."""
    # Remove common variable/value patterns
    sig = re.sub(r'\d{4}-\d{2}-\d{2}T[\d:\.]+Z?', 'TIMESTAMP', error_msg)
    sig = re.sub(r'line \d+', 'line N', sig)
    sig = re.sub(r'pid=\d+', 'pid=PID', sig)
    sig = re.sub(r'0x[0-9a-f]+', '0xADDR', sig)
    sig = re.sub(r'["\'][\w\-\.\/]+["\']', 'PATH', sig)
    return sig[:200]  # Cap signature length


def _compute_confidence(frequency: int, severity: float = 1.0) -> float:
    """Compute confidence from frequency and severity.

    Higher frequency → higher confidence.
    Confidence ∈ [0, 1].
    """
    # Base confidence: increase with frequency (diminishing returns)
    base = min(1.0, (frequency - 1) * 0.15)
    return min(1.0, base * severity)


def _compute_priority(confidence: float, frequency: int) -> int:
    """Compute priority 1-5 from confidence and frequency.

    Formula: min(5, 1 + ceil(4 * confidence) + min(4, frequency_count // 5))
    """
    return min(5, 1 + math.ceil(4 * confidence) + min(4, frequency // 5))


def _parse_iso_timestamp(ts_str: Optional[str]) -> Optional[str]:
    """Parse and normalize timestamp to ISO 8601 UTC."""
    if not ts_str:
        return None
    try:
        # Try parsing common formats
        for fmt in [
            "%Y-%m-%dT%H:%M:%S.%fZ",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%d %H:%M:%S",
        ]:
            try:
                dt = datetime.strptime(ts_str, fmt)
                # Assume UTC if no tzinfo
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.isoformat().replace('+00:00', 'Z')
            except ValueError:
                continue
        return None
    except Exception:
        return None


def _read_logs() -> List[Dict[str, Any]]:
    """Read runner logs and extract error entries.

    Returns list of dicts with keys: line_number, timestamp, error_msg, severity.
    Fail-soft: missing file → return [], log warning.
    """
    log_entries = []
    log_path = Path(IDEA_MINER_LOG_PATH)

    if not log_path.exists():
        _log_warning(f"Log file not found: {log_path}")
        return []

    try:
        with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
            for line_num, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue

                try:
                    # Try parsing as JSON
                    obj = json.loads(line)

                    # Extract fields
                    msg = obj.get('message', '') or obj.get('msg', '') or str(obj)
                    timestamp = obj.get('timestamp') or obj.get('time') or datetime.now(timezone.utc).isoformat()
                    level = obj.get('level', 'INFO').upper()

                    # Only extract errors/warnings
                    if level not in ['ERROR', 'CRITICAL', 'WARNING']:
                        continue

                    severity = 1.0 if level == 'CRITICAL' else (0.7 if level == 'ERROR' else 0.5)

                    log_entries.append({
                        'line_number': line_num,
                        'timestamp': _parse_iso_timestamp(timestamp),
                        'error_msg': msg[:500],  # Cap message length
                        'severity': severity,
                        'raw': obj,
                    })
                except json.JSONDecodeError:
                    # Try parsing as plain text error line
                    if any(kw in line.lower() for kw in ['error', 'exception', 'failed', 'traceback']):
                        log_entries.append({
                            'line_number': line_num,
                            'timestamp': datetime.now(timezone.utc).isoformat(),
                            'error_msg': line[:500],
                            'severity': 0.7,
                            'raw': {'message': line},
                        })
                except Exception:
                    # Skip malformed lines
                    continue
    except Exception as e:
        _log_warning(f"Error reading log file: {IDEA_MINER_LOG_PATH}", e)
        return []

    return log_entries


def _read_support_queue() -> List[Dict[str, Any]]:
    """Read support queue tickets.

    Returns list of dicts with keys: ticket_id, timestamp, title, frequency.
    Fail-soft: missing file → return [], log warning.
    """
    tickets = []
    queue_path = Path(IDEA_MINER_SUPPORT_QUEUE)

    if not queue_path.exists():
        _log_warning(f"Support queue not found: {queue_path}")
        return []

    try:
        with open(queue_path, 'r', encoding='utf-8', errors='replace') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue

                try:
                    obj = json.loads(line)
                    ticket_id = obj.get('id') or obj.get('ticket_id', '')
                    timestamp = obj.get('created_at') or obj.get('timestamp', datetime.now(timezone.utc).isoformat())
                    title = obj.get('title') or obj.get('summary', '')
                    freq = obj.get('frequency') or obj.get('count', 1)

                    tickets.append({
                        'ticket_id': ticket_id,
                        'timestamp': _parse_iso_timestamp(timestamp),
                        'title': title[:100],
                        'frequency': int(freq) if freq else 1,
                        'raw': obj,
                    })
                except json.JSONDecodeError:
                    continue
                except Exception:
                    continue
    except Exception as e:
        _log_warning(f"Error reading support queue: {queue_path}", e)

    return tickets


def _generate_tasks_from_errors(log_entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Group errors by signature and generate improvement tasks.

    Returns list of task dicts.
    """
    tasks = []
    error_groups = defaultdict(list)

    # Group by error signature
    for entry in log_entries:
        sig = _extract_error_signature(entry['error_msg'])
        error_groups[sig].append(entry)

    # Generate tasks for frequent error groups
    for sig, entries in error_groups.items():
        frequency = len(entries)
        if frequency < 1:
            continue

        # Use first entry's timestamp as source
        first_entry = entries[0]
        severity = max(e['severity'] for e in entries)
        confidence = _compute_confidence(frequency, severity)

        # Skip low-confidence signals
        if confidence < IDEA_MINER_MIN_CONFIDENCE:
            continue

        priority = _compute_priority(confidence, frequency)

        # Create task
        title = f"Fix recurring error: {sig[:60]}..."
        if len(sig) <= 60:
            title = f"Fix recurring error: {sig}"

        task = {
            'title': title[:100],
            'signal_type': 'error',
            'source_id': first_entry['line_number'],
            'source_timestamp': first_entry['timestamp'] or datetime.now(timezone.utc).isoformat(),
            'confidence': round(confidence, 2),
            'priority': priority,
            'frequency': frequency,
            'error_signature': sig,
            'generated_at': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        }

        tasks.append(task)

    return tasks


def _generate_tasks_from_tickets(tickets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert support tickets to improvement tasks.

    Returns list of task dicts.
    """
    tasks = []

    for ticket in tickets:
        frequency = ticket['frequency']
        confidence = _compute_confidence(frequency, 0.6)  # Support tickets have lower base severity

        if confidence < IDEA_MINER_MIN_CONFIDENCE:
            continue

        priority = _compute_priority(confidence, frequency)

        task = {
            'title': f"Address support issue: {ticket['title'][:70]}",
            'signal_type': 'ticket_pattern',
            'source_id': ticket['ticket_id'],
            'source_timestamp': ticket['timestamp'] or datetime.now(timezone.utc).isoformat(),
            'confidence': round(confidence, 2),
            'priority': priority,
            'frequency': frequency,
            'generated_at': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        }

        tasks.append(task)

    return tasks


def _load_existing_tasks() -> Dict[str, Dict[str, Any]]:
    """Load existing tasks from generated_tasks.jsonl for deduplication.

    Returns dict mapping task_hash → task_obj.
    Reads up to IDEA_MINER_DEDUP_DAYS in the past.
    Fail-soft: missing file → return {}.
    """
    tasks = {}
    path = Path(GENERATED_TASKS_PATH)

    if not path.exists():
        return {}

    cutoff = datetime.now(timezone.utc) - timedelta(days=IDEA_MINER_DEDUP_DAYS)

    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue

                try:
                    task = json.loads(line)

                    # Check if task is within dedup window
                    gen_at = task.get('generated_at')
                    if gen_at:
                        try:
                            task_dt = datetime.fromisoformat(gen_at.replace('Z', '+00:00'))
                            if task_dt < cutoff:
                                continue  # Outside dedup window
                        except (ValueError, AttributeError):
                            pass

                    # Compute hash for this task
                    sig = task.get('error_signature') or task.get('source_id', '')
                    ts = task.get('source_timestamp', '')
                    # Hash on signature + hour (not minute, to allow ~hour of drift)
                    if ts:
                        try:
                            ts_obj = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                            ts_hour = ts_obj.replace(minute=0, second=0, microsecond=0).isoformat()
                        except (ValueError, AttributeError):
                            ts_hour = ts
                    else:
                        ts_hour = ''

                    task_hash = hashlib.md5(f"{sig}:{ts_hour}".encode()).hexdigest()
                    tasks[task_hash] = task
                except json.JSONDecodeError:
                    continue
                except Exception:
                    continue
    except Exception as e:
        _log_warning(f"Error loading existing tasks for dedup", e)

    return tasks


def _compute_task_hash(task: Dict[str, Any]) -> str:
    """Compute dedup hash for a task."""
    sig = task.get('error_signature') or task.get('source_id', '')
    ts = task.get('source_timestamp', '')

    if ts:
        try:
            ts_obj = datetime.fromisoformat(ts.replace('Z', '+00:00'))
            ts_hour = ts_obj.replace(minute=0, second=0, microsecond=0).isoformat()
        except (ValueError, AttributeError):
            ts_hour = ts
    else:
        ts_hour = ''

    return hashlib.md5(f"{sig}:{ts_hour}".encode()).hexdigest()


class IdeaMinerState:
    """Singleton state holder for idea miner."""

    def __init__(self):
        self.tasks_generated = 0
        self.signals_read = 0
        self.duplicates_skipped = 0
        self.errors_encountered = 0

    def generate(self, mode: str = "dry-run", csv_export: bool = False) -> List[Dict[str, Any]]:
        """Generate tasks from all signal sources.

        Args:
            mode: "dry-run" (stdout) or "generate" (append to file)
            csv_export: also export to CSV

        Returns: list of generated task dicts
        """
        with _lock:
            try:
                # Read signals
                log_entries = _read_logs()
                tickets = _read_support_queue()

                self.signals_read = len(log_entries) + len(tickets)

                # Generate tasks
                error_tasks = _generate_tasks_from_errors(log_entries)
                ticket_tasks = _generate_tasks_from_tickets(tickets)
                all_tasks = error_tasks + ticket_tasks

                # Dedup if in generate mode
                if mode == "generate":
                    existing = _load_existing_tasks()
                    dedup_tasks = []

                    for task in all_tasks:
                        task_hash = _compute_task_hash(task)
                        if task_hash not in existing:
                            dedup_tasks.append(task)
                        else:
                            self.duplicates_skipped += 1

                    all_tasks = dedup_tasks

                    # Append to file
                    try:
                        path = Path(GENERATED_TASKS_PATH)
                        path.parent.mkdir(parents=True, exist_ok=True)
                        with open(path, 'a', encoding='utf-8') as f:
                            for task in all_tasks:
                                f.write(json.dumps(task) + '\n')
                    except Exception as e:
                        _log_warning(f"Error writing generated tasks", e)
                        self.errors_encountered += 1

                    # Export to CSV if requested
                    if csv_export and all_tasks:
                        try:
                            path = Path(GENERATED_TASKS_CSV_PATH)
                            path.parent.mkdir(parents=True, exist_ok=True)
                            with open(path, 'w', newline='', encoding='utf-8') as f:
                                writer = csv.DictWriter(f, fieldnames=[
                                    'title', 'signal_type', 'source_id', 'source_timestamp',
                                    'confidence', 'priority', 'frequency', 'generated_at'
                                ])
                                writer.writeheader()
                                for task in all_tasks:
                                    # Only include common fields for CSV
                                    row = {k: task.get(k, '') for k in writer.fieldnames}
                                    writer.writerow(row)
                        except Exception as e:
                            _log_warning(f"Error writing CSV export", e)
                            self.errors_encountered += 1

                self.tasks_generated = len(all_tasks)
                return all_tasks

            except Exception as e:
                _log_warning(f"Error in generate()", e)
                self.errors_encountered += 1
                return []

    def stats(self) -> Dict[str, int]:
        """Return execution statistics."""
        return {
            'tasks_generated': self.tasks_generated,
            'signals_read': self.signals_read,
            'duplicates_skipped': self.duplicates_skipped,
            'errors_encountered': self.errors_encountered,
        }


def acquire() -> IdeaMinerState:
    """Acquire the singleton state (thread-safe)."""
    global _state
    with _lock:
        if _state is None:
            _state = IdeaMinerState()
        return _state


def generate(signals: Optional[List[Dict]] = None, mode: str = "dry-run", dedup_days: Optional[int] = None) -> List[Dict[str, Any]]:
    """Generate tasks from signals (module-level convenience function).

    Args:
        signals: (unused, for API compatibility)
        mode: "dry-run" or "generate"
        dedup_days: (unused, uses env var IDEA_MINER_DEDUP_DAYS)

    Returns: list of task dicts
    """
    state = acquire()
    return state.generate(mode=mode)


def stats() -> Dict[str, int]:
    """Get execution statistics."""
    state = acquire()
    return state.stats()


def main():
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Auto-generate improvement tasks from runner signals.")
    parser.add_argument('--generate', action='store_true', help="Append to generated_tasks.jsonl")
    parser.add_argument('--csv', action='store_true', help="Export to CSV")
    parser.add_argument('--mode', default=IDEA_MINER_MODE, choices=['dry-run', 'generate'],
                        help="Execution mode (default: dry-run)")

    args = parser.parse_args()

    mode = args.mode
    if args.generate:
        mode = "generate"

    # Generate tasks
    state = acquire()
    tasks = state.generate(mode=mode, csv_export=args.csv)

    # Output
    if mode == "dry-run":
        # Output as JSON to stdout
        for task in tasks:
            print(json.dumps(task))
    else:
        # Print summary to stderr
        s = state.stats()
        print(f"Generated: {s['tasks_generated']}, Skipped: {s['duplicates_skipped']}, Errors: {s['errors_encountered']}", file=sys.stderr)


if __name__ == "__main__":
    main()
