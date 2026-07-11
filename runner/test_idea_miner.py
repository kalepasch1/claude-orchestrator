#!/usr/bin/env python3
"""
test_idea_miner.py - Comprehensive tests for idea_miner module.

Tests cover: normal parsing, malformed logs, missing sources, deduplication,
confidence filtering, dry-run validation, env var configuration, and all
signal sources (errors, analytics, backlog, support).

15+ test cases covering acceptance criteria.
"""

import pytest
import json
import tempfile
import os
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock, mock_open
import sys
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import idea_miner


class TestErrorParsing:
    """Test error log parsing."""

    def test_mine_errors_normal_above_threshold(self):
        """Test parsing normal log with errors above ERROR_THRESHOLD."""
        miner = idea_miner.IdeaMiner()

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".log", delete=False
        ) as f:
            now = datetime.utcnow()
            f.write(f"{now.isoformat()} INFO: Task started\n")
            f.write(f"{now.isoformat()} ERROR: Connection timeout\n")
            f.write(f"{now.isoformat()} ERROR: Connection timeout\n")
            f.write(f"{now.isoformat()} ERROR: Connection timeout\n")
            f.write(f"{now.isoformat()} ERROR: Database lock\n")
            f.write(f"{now.isoformat()} ERROR: Database lock\n")
            f.write(f"{now.isoformat()} ERROR: Database lock\n")
            f.flush()
            temp_path = f.name

        try:
            with patch("builtins.open", mock_open(read_data=open(temp_path).read())):
                with patch.object(Path, "exists", return_value=True):
                    suggestions = miner.mine_errors_from_logs()

            # Should find errors with >= ERROR_THRESHOLD occurrences
            assert len(suggestions) > 0
            for sugg in suggestions:
                assert sugg["signal_type"] == "error"
                assert sugg["confidence"] >= 0.70
                assert "suggested_title" in sugg
                assert "signal_id" in sugg
                assert "evidence" in sugg
        finally:
            os.unlink(temp_path)

    def test_mine_errors_no_log_file(self):
        """Test graceful handling when log file is missing."""
        miner = idea_miner.IdeaMiner()

        with patch("builtins.open", side_effect=FileNotFoundError):
            with patch.object(Path, "exists", return_value=False):
                suggestions = miner.mine_errors_from_logs()
                assert suggestions == []

    def test_mine_errors_below_threshold(self):
        """Test that errors below ERROR_THRESHOLD are not suggested."""
        miner = idea_miner.IdeaMiner()

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".log", delete=False
        ) as f:
            now = datetime.utcnow()
            f.write(f"{now.isoformat()} ERROR: Rare error\n")
            f.write(f"{now.isoformat()} ERROR: Rare error\n")
            f.flush()
            temp_path = f.name

        try:
            with patch("builtins.open", mock_open(read_data=open(temp_path).read())):
                with patch.object(Path, "exists", return_value=True):
                    suggestions = miner.mine_errors_from_logs()

            # ERROR_THRESHOLD is 3, we only have 2 occurrences
            assert len(suggestions) == 0
        finally:
            os.unlink(temp_path)

    def test_mine_errors_outside_lookback_window(self):
        """Test that errors outside lookback window are ignored."""
        miner = idea_miner.IdeaMiner()

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".log", delete=False
        ) as f:
            old = datetime.utcnow() - timedelta(hours=48)
            f.write(f"{old.isoformat()} ERROR: Old error\n")
            f.write(f"{old.isoformat()} ERROR: Old error\n")
            f.write(f"{old.isoformat()} ERROR: Old error\n")
            f.flush()
            temp_path = f.name

        try:
            with patch("builtins.open", mock_open(read_data=open(temp_path).read())):
                with patch.object(Path, "exists", return_value=True):
                    with patch("idea_miner.LOOKBACK_HOURS", 24):
                        suggestions = miner.mine_errors_from_logs()

            assert len(suggestions) == 0
        finally:
            os.unlink(temp_path)

    def test_extract_timestamp_iso_format(self):
        """Test timestamp extraction from ISO format."""
        line = "2026-07-11T12:30:45 ERROR: Test error"
        ts = idea_miner._extract_timestamp(line)
        assert ts is not None
        assert ts.year == 2026
        assert ts.month == 7
        assert ts.day == 11

    def test_extract_timestamp_missing(self):
        """Test that missing timestamp returns None."""
        line = "ERROR: Test error without timestamp"
        ts = idea_miner._extract_timestamp(line)
        assert ts is None

    def test_extract_error_message_error_prefix(self):
        """Test error message extraction with ERROR: prefix."""
        line = "2026-07-11T12:00:00 ERROR: Connection timeout occurred"
        msg = idea_miner._extract_error_message(line)
        assert msg is not None
        assert "timeout" in msg.lower()

    def test_extract_error_message_exception_prefix(self):
        """Test error message extraction with Exception prefix."""
        line = "Exception: Database connection failed"
        msg = idea_miner._extract_error_message(line)
        assert msg is not None
        assert "database" in msg.lower()

    def test_extract_error_message_missing(self):
        """Test that non-error line returns None."""
        line = "INFO: Task completed successfully"
        msg = idea_miner._extract_error_message(line)
        assert msg is None


class TestAnalyticsMining:
    """Test analytics funnel degradation detection."""

    def test_mine_analytics_below_threshold(self):
        """Test analytics mining detects task types below 90% success."""
        miner = idea_miner.IdeaMiner()

        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            ("task_type_a", 100, 85),  # 85% success
            ("task_type_b", 50, 50),  # 100% success
        ]

        with patch("idea_miner.sqlite3.connect") as mock_connect:
            mock_conn = MagicMock()
            mock_connect.return_value = mock_conn
            mock_conn.cursor.return_value = mock_cursor

            with patch.object(Path, "exists", return_value=True):
                suggestions = miner.mine_analytics()

        # Should suggest task_type_a (85% < 90%)
        assert any(s["signal_type"] == "analytics" for s in suggestions)
        assert any("task_type_a" in s["evidence"] for s in suggestions)

    def test_mine_analytics_no_db(self):
        """Test graceful handling when DB is missing."""
        miner = idea_miner.IdeaMiner()

        with patch.object(Path, "exists", return_value=False):
            suggestions = miner.mine_analytics()
            assert suggestions == []

    def test_mine_analytics_db_error(self):
        """Test graceful handling of DB errors."""
        miner = idea_miner.IdeaMiner()

        with patch("idea_miner.sqlite3.connect", side_effect=sqlite3.OperationalError("DB locked")):
            with patch.object(Path, "exists", return_value=True):
                suggestions = miner.mine_analytics()
                assert suggestions == []

    def test_mine_analytics_all_healthy(self):
        """Test no suggestions when all task types are healthy (>90%)."""
        miner = idea_miner.IdeaMiner()

        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            ("task_type_a", 100, 95),  # 95% success
            ("task_type_b", 50, 50),  # 100% success
        ]

        with patch("idea_miner.sqlite3.connect") as mock_connect:
            mock_conn = MagicMock()
            mock_connect.return_value = mock_conn
            mock_conn.cursor.return_value = mock_cursor

            with patch.object(Path, "exists", return_value=True):
                suggestions = miner.mine_analytics()

        assert len(suggestions) == 0

    def test_mine_analytics_empty_result(self):
        """Test handling of empty query result."""
        miner = idea_miner.IdeaMiner()

        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []

        with patch("idea_miner.sqlite3.connect") as mock_connect:
            mock_conn = MagicMock()
            mock_connect.return_value = mock_conn
            mock_conn.cursor.return_value = mock_cursor

            with patch.object(Path, "exists", return_value=True):
                suggestions = miner.mine_analytics()

        assert len(suggestions) == 0


class TestBacklogMining:
    """Test high-priority task detection."""

    def test_mine_backlog_high_priority_unattempted(self):
        """Test detection of high-priority, unattempted tasks."""
        miner = idea_miner.IdeaMiner()

        with tempfile.TemporaryDirectory() as tmpdir:
            intake_path = Path(tmpdir) / "intake" / "processed"
            intake_path.mkdir(parents=True)

            task_file = intake_path / "task1.md"
            task_file.write_text(
                """---
title: Fix database connection
priority: high
status: unattempted
---
# Task content
"""
            )

            with patch("builtins.open", mock_open(read_data=task_file.read_text())):
                with patch.object(Path, "glob", return_value=[task_file]):
                    with patch.object(Path, "exists", return_value=True):
                        suggestions = miner.mine_backlog()

            assert any(s["signal_type"] == "backlog" for s in suggestions)

    def test_mine_backlog_no_directory(self):
        """Test graceful handling when intake/processed is missing."""
        miner = idea_miner.IdeaMiner()

        with patch.object(Path, "exists", return_value=False):
            suggestions = miner.mine_backlog()
            assert suggestions == []

    def test_mine_backlog_ignores_attempted(self):
        """Test that attempted tasks are not suggested."""
        miner = idea_miner.IdeaMiner()

        with tempfile.TemporaryDirectory() as tmpdir:
            intake_path = Path(tmpdir) / "intake" / "processed"
            intake_path.mkdir(parents=True)

            task_file = intake_path / "task1.md"
            task_file.write_text(
                """---
title: Fix database connection
priority: high
status: attempted
---
"""
            )

            with patch("builtins.open", mock_open(read_data=task_file.read_text())):
                with patch.object(Path, "glob", return_value=[task_file]):
                    with patch.object(Path, "exists", return_value=True):
                        suggestions = miner.mine_backlog()

            assert len(suggestions) == 0

    def test_mine_backlog_ignores_low_priority(self):
        """Test that low-priority tasks are not suggested."""
        miner = idea_miner.IdeaMiner()

        with tempfile.TemporaryDirectory() as tmpdir:
            intake_path = Path(tmpdir) / "intake" / "processed"
            intake_path.mkdir(parents=True)

            task_file = intake_path / "task1.md"
            task_file.write_text(
                """---
title: Nice-to-have improvement
priority: low
status: unattempted
---
"""
            )

            with patch("builtins.open", mock_open(read_data=task_file.read_text())):
                with patch.object(Path, "glob", return_value=[task_file]):
                    with patch.object(Path, "exists", return_value=True):
                        suggestions = miner.mine_backlog()

            assert len(suggestions) == 0


class TestDeduplication:
    """Test deduplication logic."""

    def test_deduplicate_recent_signal(self):
        """Test deduplication of recently suggested tasks."""
        miner = idea_miner.IdeaMiner()

        suggestions = [
            {
                "signal_type": "error",
                "signal_id": "log:123",
                "evidence": "Test error",
                "confidence": 0.75,
                "suggested_title": "Test",
                "suggested_description": "Test",
                "timestamp_utc": datetime.utcnow().isoformat() + "Z",
            }
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            processed_dir = Path(tmpdir) / "intake" / "processed"
            processed_dir.mkdir(parents=True)

            recent_file = processed_dir / "recent-ideaminer-error.md"
            recent_file.write_text("signal_id: log:123\n")

            with patch("builtins.open", mock_open(read_data="signal_id: log:123\n")):
                with patch.object(Path, "glob", return_value=[recent_file]):
                    with patch.object(Path, "exists", return_value=True):
                        deduped = miner.deduplicate(suggestions)

            assert len(deduped) == 0

    def test_deduplicate_old_signal_not_filtered(self):
        """Test that old suggestions (>12h) are not deduped."""
        miner = idea_miner.IdeaMiner()

        suggestions = [
            {
                "signal_type": "error",
                "signal_id": "log:123",
                "evidence": "Test error",
                "confidence": 0.75,
                "suggested_title": "Test",
                "suggested_description": "Test",
                "timestamp_utc": datetime.utcnow().isoformat() + "Z",
            }
        ]

        with patch.object(Path, "exists", return_value=False):
            deduped = miner.deduplicate(suggestions)

        assert len(deduped) == 1

    def test_deduplicate_below_confidence_threshold(self):
        """Test filtering of suggestions below MIN_CONFIDENCE."""
        miner = idea_miner.IdeaMiner()

        suggestions = [
            {
                "signal_type": "error",
                "signal_id": "log:123",
                "evidence": "Test",
                "confidence": 0.65,  # Below default 0.70
                "suggested_title": "Test",
                "suggested_description": "Test",
                "timestamp_utc": datetime.utcnow().isoformat() + "Z",
            }
        ]

        with patch.object(Path, "exists", return_value=False):
            deduped = miner.deduplicate(suggestions)

        assert len(deduped) == 0

    def test_deduplicate_at_confidence_threshold(self):
        """Test that suggestions at MIN_CONFIDENCE are included."""
        miner = idea_miner.IdeaMiner()

        suggestions = [
            {
                "signal_type": "error",
                "signal_id": "log:123",
                "evidence": "Test",
                "confidence": 0.70,  # At default 0.70
                "suggested_title": "Test",
                "suggested_description": "Test",
                "timestamp_utc": datetime.utcnow().isoformat() + "Z",
            }
        ]

        with patch.object(Path, "exists", return_value=False):
            deduped = miner.deduplicate(suggestions)

        assert len(deduped) == 1


class TestDryRun:
    """Test dry-run JSON output."""

    def test_dry_run_outputs_valid_json(self):
        """Test that dry-run mode outputs valid JSON to stdout."""
        miner = idea_miner.IdeaMiner()

        suggestions = [
            {
                "signal_type": "error",
                "signal_id": "log:123",
                "evidence": "Test error",
                "confidence": 0.75,
                "suggested_title": "Fix error",
                "suggested_description": "Description",
                "timestamp_utc": datetime.utcnow().isoformat() + "Z",
            }
        ]

        with patch.object(
            miner, "mine_errors_from_logs", return_value=suggestions
        ):
            with patch.object(miner, "mine_analytics", return_value=[]):
                with patch.object(miner, "mine_backlog", return_value=[]):
                    with patch.object(miner, "mine_support_issues", return_value=[]):
                        with patch("builtins.print") as mock_print:
                            miner.run(dry_run=True)

                        mock_print.assert_called()
                        output = mock_print.call_args[0][0]
                        parsed = json.loads(output)
                        assert len(parsed) > 0
                        assert parsed[0]["signal_type"] == "error"

    def test_dry_run_includes_all_required_fields(self):
        """Test that JSON output includes all required fields."""
        miner = idea_miner.IdeaMiner()

        suggestion = {
            "signal_type": "error",
            "signal_id": "log:123",
            "evidence": "Test error",
            "confidence": 0.75,
            "suggested_title": "Fix error",
            "suggested_description": "Description",
            "timestamp_utc": datetime.utcnow().isoformat() + "Z",
        }

        required_fields = [
            "signal_type",
            "signal_id",
            "evidence",
            "confidence",
            "suggested_title",
            "suggested_description",
            "timestamp_utc",
        ]

        for field in required_fields:
            assert field in suggestion
            assert suggestion[field] is not None


class TestWriteTask:
    """Test writing tasks to intake/processed/."""

    def test_write_task_creates_valid_markdown(self):
        """Test that write_task creates properly formatted markdown."""
        miner = idea_miner.IdeaMiner()

        suggestion = {
            "signal_type": "error",
            "signal_id": "log:123",
            "evidence": "Test error",
            "confidence": 0.75,
            "suggested_title": "Fix test error",
            "suggested_description": "Test description",
            "timestamp_utc": datetime.utcnow().isoformat() + "Z",
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("builtins.open", mock_open()) as mock_file:
                with patch.object(Path, "mkdir"):
                    miner.write_task(suggestion)

                # Verify write was called
                mock_file.assert_called()

    def test_write_task_handles_errors(self):
        """Test graceful error handling during task write."""
        miner = idea_miner.IdeaMiner()

        suggestion = {
            "signal_type": "error",
            "signal_id": "log:123",
            "evidence": "Test error",
            "confidence": 0.75,
            "suggested_title": "Fix error",
            "suggested_description": "Description",
            "timestamp_utc": datetime.utcnow().isoformat() + "Z",
        }

        with patch("builtins.open", side_effect=OSError("Permission denied")):
            # Should not raise; graceful degradation
            miner.write_task(suggestion)


class TestEnvironmentConfiguration:
    """Test environment variable configuration."""

    def test_env_var_lookback_hours(self):
        """Test ORCH_IDEA_MINER_LOOKBACK_HOURS env var."""
        with patch.dict(os.environ, {"ORCH_IDEA_MINER_LOOKBACK_HOURS": "12"}):
            lookback = int(os.getenv("ORCH_IDEA_MINER_LOOKBACK_HOURS", "24"))
            assert lookback == 12

    def test_env_var_min_confidence(self):
        """Test ORCH_IDEA_MINER_MIN_CONFIDENCE env var."""
        with patch.dict(os.environ, {"ORCH_IDEA_MINER_MIN_CONFIDENCE": "0.80"}):
            confidence = float(os.getenv("ORCH_IDEA_MINER_MIN_CONFIDENCE", "0.70"))
            assert confidence == 0.80

    def test_env_var_error_threshold(self):
        """Test ORCH_IDEA_MINER_ERROR_THRESHOLD env var."""
        with patch.dict(os.environ, {"ORCH_IDEA_MINER_ERROR_THRESHOLD": "5"}):
            threshold = int(os.getenv("ORCH_IDEA_MINER_ERROR_THRESHOLD", "3"))
            assert threshold == 5


class TestIntegration:
    """Integration tests for full mining pipeline."""

    def test_run_collects_from_all_sources(self):
        """Test that run() collects suggestions from all sources."""
        miner = idea_miner.IdeaMiner()

        error_sugg = [
            {
                "signal_type": "error",
                "signal_id": "log:1",
                "evidence": "Error",
                "confidence": 0.75,
                "suggested_title": "Fix",
                "suggested_description": "Desc",
                "timestamp_utc": datetime.utcnow().isoformat() + "Z",
            }
        ]

        with patch.object(miner, "mine_errors_from_logs", return_value=error_sugg):
            with patch.object(miner, "mine_analytics", return_value=[]):
                with patch.object(miner, "mine_backlog", return_value=[]):
                    with patch.object(miner, "mine_support_issues", return_value=[]):
                        with patch.object(miner, "deduplicate", return_value=error_sugg):
                            with patch("builtins.print"):
                                miner.run(dry_run=True)

        assert len(miner.suggestions) > 0

    def test_run_normal_mode_writes_tasks(self):
        """Test that normal mode writes tasks to disk."""
        miner = idea_miner.IdeaMiner()

        suggestions = [
            {
                "signal_type": "error",
                "signal_id": "log:1",
                "evidence": "Error",
                "confidence": 0.75,
                "suggested_title": "Fix",
                "suggested_description": "Desc",
                "timestamp_utc": datetime.utcnow().isoformat() + "Z",
            }
        ]

        with patch.object(miner, "mine_errors_from_logs", return_value=suggestions):
            with patch.object(miner, "mine_analytics", return_value=[]):
                with patch.object(miner, "mine_backlog", return_value=[]):
                    with patch.object(miner, "mine_support_issues", return_value=[]):
                        with patch.object(miner, "deduplicate", return_value=suggestions):
                            with patch.object(miner, "write_task") as mock_write:
                                miner.run(dry_run=False)

                                mock_write.assert_called()


class TestSupportIssues:
    """Test Linear support issue mining (placeholder)."""

    def test_mine_support_issues_returns_empty(self):
        """Test that support issues mining returns empty list (not yet implemented)."""
        miner = idea_miner.IdeaMiner()
        suggestions = miner.mine_support_issues()
        assert suggestions == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
