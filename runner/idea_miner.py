#!/usr/bin/env python3
"""
idea_miner.py - Auto-generate evidence-anchored improvement tasks from runner metrics and logs.

Scans the orchestrator's own execution signals (logs, fleet_config DB, intake backlog)
and generates high-value task suggestions. Internal diagnostic tool for runner/master controller.

Signal sources (priority order, fail-soft if unavailable):
1. Top runtime errors from logs (last 24h)
2. Analytics funnel degradation from fleet_config DB
3. Known support issues from Linear INGEST project
4. Unexecuted high-priority tasks from intake/processed/

Output: JSON objects with evidence citations; dry-run to stdout or write to intake/processed/.
Deduplication: Do not suggest if matching Linear issue exists or same signal suggested <12h ago.
Graceful degradation: Skip unavailable sources, log warnings, do not crash.
"""

import os
import sys
import json
import re
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional
import logging
import threading
import hashlib
import sqlite3

HOME = os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator"))
LOOKBACK_HOURS = int(os.getenv("ORCH_IDEA_MINER_LOOKBACK_HOURS", "24"))
MIN_CONFIDENCE = float(os.getenv("ORCH_IDEA_MINER_MIN_CONFIDENCE", "0.70"))
ERROR_THRESHOLD = int(os.getenv("ORCH_IDEA_MINER_ERROR_THRESHOLD", "3"))

_lock = threading.Lock()
_logger = None


def _get_logger():
    global _logger
    if _logger is None:
        _logger = logging.getLogger("idea_miner")
        handler = logging.StreamHandler()
        formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
        handler.setFormatter(formatter)
        _logger.addHandler(handler)
        _logger.setLevel(logging.WARNING)
    return _logger


def _ensure_dirs():
    try:
        os.makedirs(HOME, exist_ok=True)
    except Exception:
        pass


def _log_warning(msg, context=""):
    logger = _get_logger()
    logger.warning(f"{msg} ({context})" if context else msg)


def _extract_timestamp(line: str) -> Optional[datetime]:
    """Extract ISO timestamp from log line. Returns None if not found."""
    iso_pattern = r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})"
    match = re.search(iso_pattern, line)
    if match:
        try:
            return datetime.fromisoformat(match.group(1))
        except (ValueError, AttributeError):
            pass
    return None


def _extract_error_message(line: str) -> Optional[str]:
    """Extract error message from log line. Returns None if not found."""
    patterns = [
        r"ERROR:\s*(.+?)(?:\n|$)",
        r"error:\s*(.+?)(?:\n|$)",
        r"Exception:\s*(.+?)(?:\n|$)",
        r"Traceback.*?:\s*(.+?)(?:\n|$)",
    ]

    for pattern in patterns:
        match = re.search(pattern, line, re.IGNORECASE)
        if match:
            return match.group(1).strip()

    return None


class IdeaMiner:
    """Mines high-value task suggestions from runner signals."""

    def __init__(self):
        self.suggestions = []

    def mine_errors_from_logs(self) -> List[Dict[str, Any]]:
        """
        Parse runner logs (last LOOKBACK_HOURS) and extract top errors (frequency >= ERROR_THRESHOLD).
        Returns list of suggestion dicts. Gracefully handles missing/malformed logs.
        """
        suggestions = []
        log_files = [
            Path("runner.log"),
            Path(HOME) / "runner.log",
            Path("/var/log/claude-orchestrator/runner.log"),
            Path.home() / ".claude" / "runner.log",
        ]

        log_path = None
        for lp in log_files:
            if lp.exists():
                log_path = lp
                break

        if not log_path:
            _log_warning("No runner log file found", "mine_errors_from_logs")
            return suggestions

        try:
            with open(log_path, "r", errors="replace") as f:
                lines = f.readlines()

            cutoff = datetime.utcnow() - timedelta(hours=LOOKBACK_HOURS)
            error_counts = {}
            error_lines = {}

            for i, line in enumerate(lines):
                if "ERROR" in line or "error" in line.lower():
                    timestamp = _extract_timestamp(line)
                    if timestamp and timestamp >= cutoff:
                        error_msg = _extract_error_message(line)
                        if error_msg:
                            if error_msg not in error_counts:
                                error_counts[error_msg] = 0
                                error_lines[error_msg] = i + 1
                            error_counts[error_msg] += 1

            # Top 5 errors with >= ERROR_THRESHOLD occurrences
            top_errors = sorted(
                [
                    (msg, count)
                    for msg, count in error_counts.items()
                    if count >= ERROR_THRESHOLD
                ],
                key=lambda x: x[1],
                reverse=True,
            )[:5]

            for error_msg, count in top_errors:
                confidence = min(0.95, 0.70 + (count - ERROR_THRESHOLD) * 0.05)
                line_num = error_lines[error_msg]

                suggestions.append(
                    {
                        "signal_type": "error",
                        "signal_id": f"log:{line_num}",
                        "evidence": error_msg[:100],
                        "confidence": round(confidence, 2),
                        "suggested_title": f"Fix: {error_msg[:50]}",
                        "suggested_description": f'Error "{error_msg}" occurred {count} times in last {LOOKBACK_HOURS}h (line {line_num})',
                        "timestamp_utc": datetime.utcnow().isoformat() + "Z",
                    }
                )

        except Exception as e:
            _log_warning(f"Error parsing logs: {e}", "mine_errors_from_logs")

        return suggestions

    def mine_analytics(self) -> List[Dict[str, Any]]:
        """
        Query fleet_config DB for task execution success rates (last 7 days).
        Flag task types with <90% success rate. Gracefully handles missing/locked DB.
        """
        suggestions = []

        try:
            db_paths = [
                Path("runner") / "fleet_config.db",
                Path(HOME) / "fleet_config.db",
                Path.home() / ".claude" / "fleet_config.db",
            ]

            db_path = None
            for dp in db_paths:
                if dp.exists():
                    db_path = dp
                    break

            if not db_path:
                _log_warning("fleet_config DB not found", "mine_analytics")
                return suggestions

            conn = sqlite3.connect(str(db_path), timeout=5)
            cursor = conn.cursor()

            query = """
            SELECT task_type, COUNT(*) as total,
                   SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) as successes
            FROM execution_log
            WHERE timestamp >= datetime('now', '-7 days')
            GROUP BY task_type
            HAVING total >= 10
            """

            cursor.execute(query)
            results = cursor.fetchall()
            conn.close()

            for task_type, total, successes in results:
                success_rate = (successes / total) * 100.0 if total > 0 else 0.0

                if success_rate < 90.0:
                    confidence = min(0.95, 0.70 + (90.0 - success_rate) * 0.01)

                    suggestions.append(
                        {
                            "signal_type": "analytics",
                            "signal_id": f"metric:{task_type}",
                            "evidence": f"{task_type}: {success_rate:.1f}% success rate ({int(successes)}/{int(total)})",
                            "confidence": round(confidence, 2),
                            "suggested_title": f"Improve {task_type} reliability",
                            "suggested_description": f'Task type "{task_type}" has {success_rate:.1f}% success rate in last 7 days (target: ≥90%)',
                            "timestamp_utc": datetime.utcnow().isoformat() + "Z",
                        }
                    )

        except sqlite3.OperationalError as e:
            _log_warning(f"DB lock or missing table: {e}", "mine_analytics")
        except Exception as e:
            _log_warning(f"Error querying analytics: {e}", "mine_analytics")

        return suggestions

    def mine_backlog(self) -> List[Dict[str, Any]]:
        """
        Scan intake/processed/ for high-priority, unexecuted tasks.
        Gracefully handles missing directory.
        """
        suggestions = []

        try:
            intake_path = Path("intake") / "processed"
            if not intake_path.exists():
                _log_warning("intake/processed directory not found", "mine_backlog")
                return suggestions

            for task_file in intake_path.glob("*.md"):
                try:
                    with open(task_file, "r", errors="replace") as f:
                        content = f.read()

                    if "priority: high" in content and "status: unattempted" in content:
                        title_match = re.search(
                            r"title:\s*(.+?)(?:\n|$)", content
                        )
                        title = (
                            title_match.group(1).strip()
                            if title_match
                            else task_file.stem
                        )

                        suggestions.append(
                            {
                                "signal_type": "backlog",
                                "signal_id": f"file:{task_file.name}",
                                "evidence": f"High-priority, unexecuted: {title}",
                                "confidence": 0.75,
                                "suggested_title": f"Execute: {title}",
                                "suggested_description": f'High-priority task "{title}" from {task_file.name} remains unexecuted',
                                "timestamp_utc": datetime.utcnow().isoformat() + "Z",
                            }
                        )

                except Exception as e:
                    _log_warning(f"Error reading {task_file.name}: {e}", "mine_backlog")

        except Exception as e:
            _log_warning(f"Error mining backlog: {e}", "mine_backlog")

        return suggestions

    def mine_support_issues(self) -> List[Dict[str, Any]]:
        """
        Query Linear INGEST project for open "runner" bugs (not yet implemented).
        Returns empty list gracefully.
        """
        return []

    def deduplicate(
        self, suggestions: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Filter suggestions: remove if same signal_id suggested in last 12h,
        or confidence < MIN_CONFIDENCE. Returns deduplicated list.
        """
        seen = set()
        deduped = []
        cutoff = datetime.utcnow() - timedelta(hours=12)

        processed_dir = Path("intake") / "processed"
        if processed_dir.exists():
            for file in processed_dir.glob("*ideaminer*.md"):
                try:
                    mtime = datetime.fromtimestamp(file.stat().st_mtime)
                    if mtime > cutoff:
                        with open(file, "r", errors="replace") as f:
                            content = f.read()
                            match = re.search(
                                r"signal_id:\s*(.+?)(?:\n|$)", content
                            )
                            if match:
                                signal_id = match.group(1).strip()
                                seen.add(signal_id)
                except Exception:
                    pass

        for sugg in suggestions:
            if (
                sugg["signal_id"] not in seen
                and sugg["confidence"] >= MIN_CONFIDENCE
            ):
                deduped.append(sugg)
                seen.add(sugg["signal_id"])

        return deduped

    def write_task(self, suggestion: Dict[str, Any]) -> None:
        """
        Write suggestion to intake/processed/<timestamp>-ideaminer-<type>.md
        in canonical YAML frontmatter + markdown format.
        """
        timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        signal_type = suggestion["signal_type"]
        filename = f"{timestamp}-ideaminer-{signal_type}.md"

        output_path = Path("intake") / "processed" / filename
        output_path.parent.mkdir(parents=True, exist_ok=True)

        content = f"""---
title: {suggestion['suggested_title']}
priority: high
status: unattempted
signal_type: {suggestion['signal_type']}
signal_id: {suggestion['signal_id']}
confidence: {suggestion['confidence']}
created_at: {suggestion['timestamp_utc']}
---

# {suggestion['suggested_title']}

## Evidence
{suggestion['evidence']}

## Description
{suggestion['suggested_description']}

## Signal ID
{suggestion['signal_id']}
"""

        try:
            with open(output_path, "w") as f:
                f.write(content)
        except Exception as e:
            _log_warning(f"Error writing task {filename}: {e}", "write_task")

    def run(self, dry_run: bool = False) -> None:
        """
        Run the idea miner: collect suggestions from all sources, deduplicate,
        output (dry-run: JSON to stdout; normal: write to intake/processed/).
        """
        _ensure_dirs()

        all_suggestions = []
        all_suggestions.extend(self.mine_errors_from_logs())
        all_suggestions.extend(self.mine_analytics())
        all_suggestions.extend(self.mine_backlog())
        all_suggestions.extend(self.mine_support_issues())

        suggestions = self.deduplicate(all_suggestions)

        if dry_run:
            print(json.dumps(suggestions, indent=2))
        else:
            for sugg in suggestions:
                self.write_task(sugg)

        self.suggestions = suggestions


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Mine high-value task suggestions from runner signals"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Output JSON to stdout instead of writing to disk",
    )
    args = parser.parse_args()

    miner = IdeaMiner()
    miner.run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
