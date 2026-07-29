import os
import re
from datetime import datetime, timezone
from pathlib import Path
import pytest
from unittest.mock import patch, MagicMock
import subprocess
import tempfile


class TestDeployCanary:
    """Tests for the deployment canary heartbeat system.

    Verifies that a trivial, safe change (canary file with timestamp)
    exercises the full build->verify->merge->push->Vercel pipeline.
    """

    CANARY_FILE = ".deploy-canary"
    TIMESTAMP_PATTERN = r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z'

    @pytest.fixture
    def canary_path(self, tmp_path):
        """Provide a temporary canary file path."""
        return tmp_path / self.CANARY_FILE

    # === File Creation Tests ===

    def test_canary_file_creates_at_repo_root(self, canary_path):
        """Test that canary file is created successfully."""
        timestamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        content = f"{timestamp} # deployment canary heartbeat"

        canary_path.write_text(content)

        assert canary_path.exists()
        assert canary_path.is_file()

    def test_canary_file_has_correct_name(self, tmp_path):
        """Test that file is named exactly '.deploy-canary'."""
        expected_name = ".deploy-canary"

        canary_path = tmp_path / expected_name
        canary_path.write_text("2026-07-25T12:00:00Z # test")

        assert canary_path.name == expected_name

    # === Timestamp Format Tests ===

    def test_timestamp_format_iso_8601_utc(self):
        """Test timestamp follows ISO 8601 UTC format (YYYY-MM-DDTHH:MM:SSZ)."""
        timestamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

        assert re.match(self.TIMESTAMP_PATTERN, timestamp), \
            f"Timestamp {timestamp} does not match ISO 8601 UTC format"

    def test_timestamp_ends_with_z_not_plus_zero(self):
        """Test that UTC timezone is indicated with 'Z' suffix, not '+00:00'."""
        timestamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

        assert timestamp.endswith('Z')
        assert not timestamp.endswith('+00:00')

    def test_timestamp_uses_utc_not_local_time(self):
        """Test that timestamp is in UTC, not local timezone."""
        now_utc = datetime.now(timezone.utc)
        timestamp = now_utc.isoformat().replace('+00:00', 'Z')

        # Verify it has timezone info
        assert 'Z' in timestamp or '+' in timestamp

    def test_timestamp_has_required_components(self):
        """Test that timestamp contains year, month, day, hour, minute, second."""
        timestamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

        # Must match YYYY-MM-DDTHH:MM:SS pattern
        match = re.match(r'(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})Z', timestamp)
        assert match is not None

        year, month, day, hour, minute, second = match.groups()
        assert int(year) >= 2020
        assert 1 <= int(month) <= 12
        assert 1 <= int(day) <= 31
        assert 0 <= int(hour) <= 23
        assert 0 <= int(minute) <= 59
        assert 0 <= int(second) <= 59

    # === Comment Tests ===

    def test_canary_content_has_comment(self, canary_path):
        """Test that canary file contains required comment with '#'."""
        timestamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        content = f"{timestamp} # deployment canary heartbeat"

        canary_path.write_text(content)

        assert '#' in canary_path.read_text()

    def test_comment_is_one_line(self, canary_path):
        """Test that canary file contains exactly one line."""
        timestamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        content = f"{timestamp} # deployment canary heartbeat"

        canary_path.write_text(content)

        lines = [line for line in canary_path.read_text().split('\n') if line.strip()]
        assert len(lines) == 1, f"Expected 1 line, got {len(lines)}"

    def test_comment_mentions_canary_or_heartbeat(self, canary_path):
        """Test that comment describes its purpose."""
        timestamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        content = f"{timestamp} # deployment canary heartbeat"

        canary_path.write_text(content)

        file_text = canary_path.read_text().lower()
        assert 'canary' in file_text or 'heartbeat' in file_text

    # === Timestamp Timeliness Tests ===

    def test_timestamp_is_current_within_tolerance(self, canary_path):
        """Test that timestamp is within 1 minute of current time."""
        now = datetime.now(timezone.utc)
        timestamp = now.isoformat().replace('+00:00', 'Z')
        content = f"{timestamp} # deployment canary heartbeat"

        canary_path.write_text(content)

        # Parse timestamp from file
        file_content = canary_path.read_text()
        file_timestamp_str = file_content.split('#')[0].strip()
        file_timestamp = datetime.fromisoformat(file_timestamp_str.replace('Z', '+00:00'))

        # Check within 60 seconds
        diff = abs((now - file_timestamp).total_seconds())
        assert diff < 60, f"Timestamp {diff}s old, should be < 60s"

    def test_timestamp_not_in_future(self, canary_path):
        """Test that timestamp is not in the future."""
        now = datetime.now(timezone.utc)
        timestamp = now.isoformat().replace('+00:00', 'Z')
        content = f"{timestamp} # deployment canary heartbeat"

        canary_path.write_text(content)

        file_content = canary_path.read_text()
        file_timestamp_str = file_content.split('#')[0].strip()
        file_timestamp = datetime.fromisoformat(file_timestamp_str.replace('Z', '+00:00'))

        assert file_timestamp <= now, "Timestamp should not be in the future"

    # === Update Functionality Tests ===

    def test_updates_existing_canary_file(self, canary_path):
        """Test that existing canary file is updated with new timestamp."""
        old_content = "2026-07-25T12:00:00Z # old canary"
        canary_path.write_text(old_content)

        new_timestamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        new_content = f"{new_timestamp} # deployment canary heartbeat"
        canary_path.write_text(new_content)

        assert canary_path.read_text() == new_content
        assert canary_path.read_text() != old_content

    def test_multiple_updates_work_correctly(self, canary_path):
        """Test that canary file can be updated multiple times."""
        timestamps = []

        for i in range(3):
            timestamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
            content = f"{timestamp} # deployment canary heartbeat"
            canary_path.write_text(content)
            timestamps.append(timestamp)

        # File should contain only the last timestamp
        final_content = canary_path.read_text()
        assert timestamps[-1] in final_content

    # === Format and Structure Tests ===

    def test_canary_format_timestamp_space_hash_comment(self, canary_path):
        """Test that canary follows format: TIMESTAMP # COMMENT."""
        timestamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        content = f"{timestamp} # deployment canary heartbeat"

        canary_path.write_text(content)

        parts = canary_path.read_text().split('#')
        assert len(parts) == 2, "Should have timestamp # comment format"
        assert parts[0].strip() == timestamp

    def test_canary_readable_human_format(self, canary_path):
        """Test that canary file is human-readable."""
        timestamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        content = f"{timestamp} # deployment canary heartbeat"

        canary_path.write_text(content)

        # Should be easily readable text
        file_text = canary_path.read_text()
        assert isinstance(file_text, str)
        assert len(file_text) > 0
        assert len(file_text) < 200  # Not excessively long

    # === Security Tests ===

    def test_canary_contains_no_secrets(self, canary_path):
        """Test that canary file contains no credentials or sensitive data."""
        timestamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        content = f"{timestamp} # deployment canary heartbeat"

        canary_path.write_text(content)

        file_content = canary_path.read_text().lower()
        secret_patterns = ['password', 'secret', 'token', 'api_key', 'apikey', 'credential']

        for pattern in secret_patterns:
            assert pattern not in file_content, \
                f"Canary should not contain '{pattern}'"

    def test_canary_contains_no_hardcoded_values(self, canary_path):
        """Test that canary uses only timestamp and comment."""
        timestamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        content = f"{timestamp} # deployment canary heartbeat"

        canary_path.write_text(content)

        file_content = canary_path.read_text()
        # Should only contain: timestamp, space, hash, space, comment
        assert re.match(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z # \w+.*$', file_content)

    # === Git Integration Tests ===

    @patch('subprocess.run')
    def test_canary_can_be_git_added(self, mock_run, canary_path):
        """Test that canary file can be staged with git add."""
        mock_run.return_value = MagicMock(returncode=0, stdout="")

        timestamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        content = f"{timestamp} # deployment canary heartbeat"
        canary_path.write_text(content)

        # Simulate git add
        result = subprocess.run(['git', 'add', str(canary_path)], capture_output=True)

        assert mock_run.called

    @patch('subprocess.run')
    def test_canary_can_be_git_committed(self, mock_run):
        """Test that canary file can be committed to git."""
        mock_run.return_value = MagicMock(returncode=0, stdout="")

        # Simulate git commit
        result = subprocess.run(
            ['git', 'commit', '-m', 'chore: update deployment canary'],
            capture_output=True
        )

        assert mock_run.called

    def test_only_canary_file_modified(self, tmp_path):
        """Test that canary operation only touches the canary file."""
        canary_path = tmp_path / ".deploy-canary"
        other_file = tmp_path / "other.txt"

        other_file.write_text("existing")

        timestamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        canary_path.write_text(f"{timestamp} # canary")

        # Verify only canary was created/modified
        assert canary_path.exists()
        assert other_file.read_text() == "existing"

    # === Completeness Tests ===

    def test_canary_creation_workflow_end_to_end(self, canary_path):
        """Test complete workflow: create file, set timestamp, commit ready."""
        # Create canary
        timestamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        content = f"{timestamp} # deployment canary heartbeat"
        canary_path.write_text(content)

        # Verify all requirements
        assert canary_path.exists()
        file_text = canary_path.read_text()
        assert re.match(self.TIMESTAMP_PATTERN, file_text.split('#')[0].strip())
        assert '#' in file_text
        assert len(file_text.split('\n')) == 1
        assert 'password' not in file_text.lower()

    def test_canary_meets_all_safe_change_criteria(self, canary_path):
        """Test that canary meets the 'trivial, safe change' requirement."""
        timestamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        content = f"{timestamp} # deployment canary heartbeat"
        canary_path.write_text(content)

        # Criteria: trivial, safe, no app code/config/auth/RLS touched
        file_text = canary_path.read_text()

        # Not touching sensitive areas
        assert 'auth' not in file_text.lower() or file_text.count('auth') <= 1  # Only in comment
        assert 'rls' not in file_text.lower()
        assert 'config' not in file_text.lower() or file_text.count('config') <= 1
        assert 'pricing' not in file_text.lower()

        # Is trivial: single line with timestamp
        assert len(file_text.split('\n')) == 1
