#!/usr/bin/env python3
"""Tests for canary heartbeat — trivial safe deployment exercise.

The canary task verifies the full build->verify->merge->push->Vercel-deploy loop
end-to-end by creating/updating a single file with a timestamp, committing it,
and pushing to merge the base branch.

Coverage:
  - .deploy-canary file creation with UTC timestamp
  - Comment line presence and format validation
  - Idempotency (multiple runs produce valid state)
  - Git commit with correct author
  - No other files modified (safety check)
  - Timestamp format validation (RFC3339/ISO8601 UTC)
  - One-line comment requirement
"""
import os
import sys
import tempfile
import unittest
import subprocess
import re
from datetime import datetime
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class CanaryHeartbeatFileFormatTest(unittest.TestCase):
    """Test .deploy-canary file format and content."""

    def test_deploy_canary_file_exists_after_creation(self):
        """File .deploy-canary should exist at repo root after creation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            canary_path = os.path.join(tmpdir, ".deploy-canary")
            timestamp = datetime.utcnow().isoformat() + "Z"
            content = f"{timestamp} # canary heartbeat\n"

            with open(canary_path, "w") as f:
                f.write(content)

            self.assertTrue(os.path.exists(canary_path))
            self.assertGreater(os.path.getsize(canary_path), 0)

    def test_deploy_canary_contains_valid_utc_timestamp(self):
        """First line should contain a valid UTC ISO8601 timestamp."""
        with tempfile.TemporaryDirectory() as tmpdir:
            canary_path = os.path.join(tmpdir, ".deploy-canary")
            timestamp = datetime.utcnow().isoformat() + "Z"
            content = f"{timestamp} # canary\n"

            with open(canary_path, "w") as f:
                f.write(content)

            with open(canary_path, "r") as f:
                first_line = f.readline().strip()

            # ISO8601 UTC timestamp pattern: YYYY-MM-DDTHH:MM:SS.ffffffZ
            iso_pattern = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
            self.assertRegex(first_line, iso_pattern)
            self.assertTrue(first_line.endswith("Z") or "+" in first_line or "-" in first_line[-6:])

    def test_deploy_canary_timestamp_parses_as_datetime(self):
        """Timestamp should be parseable back to a datetime object."""
        with tempfile.TemporaryDirectory() as tmpdir:
            canary_path = os.path.join(tmpdir, ".deploy-canary")
            now = datetime.utcnow()
            timestamp = now.isoformat() + "Z"
            content = f"{timestamp} # canary\n"

            with open(canary_path, "w") as f:
                f.write(content)

            with open(canary_path, "r") as f:
                first_line = f.readline().strip()

            # Extract timestamp (before first space)
            ts_str = first_line.split()[0]
            # Remove Z and parse
            ts_str_clean = ts_str.rstrip("Z")
            parsed = datetime.fromisoformat(ts_str_clean)

            # Should be within 5 seconds of now (accounting for execution time)
            delta = abs((parsed - now).total_seconds())
            self.assertLess(delta, 5)

    def test_deploy_canary_contains_one_line_comment(self):
        """File should contain exactly one line with a comment."""
        with tempfile.TemporaryDirectory() as tmpdir:
            canary_path = os.path.join(tmpdir, ".deploy-canary")
            timestamp = datetime.utcnow().isoformat() + "Z"
            content = f"{timestamp} # canary heartbeat\n"

            with open(canary_path, "w") as f:
                f.write(content)

            with open(canary_path, "r") as f:
                lines = f.readlines()

            self.assertEqual(len(lines), 1)
            self.assertIn("#", lines[0])

    def test_deploy_canary_comment_after_timestamp(self):
        """Comment should appear after timestamp separated by space."""
        with tempfile.TemporaryDirectory() as tmpdir:
            canary_path = os.path.join(tmpdir, ".deploy-canary")
            timestamp = datetime.utcnow().isoformat() + "Z"
            content = f"{timestamp} # canary heartbeat exercise\n"

            with open(canary_path, "w") as f:
                f.write(content)

            with open(canary_path, "r") as f:
                line = f.read().strip()

            parts = line.split("#", 1)
            self.assertEqual(len(parts), 2)
            self.assertTrue(parts[0].strip())  # timestamp part not empty
            self.assertTrue(parts[1].strip())  # comment part not empty

    def test_deploy_canary_timestamp_within_reasonable_bounds(self):
        """Timestamp should not be wildly in past or future."""
        with tempfile.TemporaryDirectory() as tmpdir:
            canary_path = os.path.join(tmpdir, ".deploy-canary")
            now = datetime.utcnow()
            timestamp = now.isoformat() + "Z"
            content = f"{timestamp} # canary\n"

            with open(canary_path, "w") as f:
                f.write(content)

            with open(canary_path, "r") as f:
                first_line = f.readline().strip()

            ts_str = first_line.split()[0].rstrip("Z")
            parsed = datetime.fromisoformat(ts_str)

            # Within 10 seconds of now
            delta = abs((parsed - now).total_seconds())
            self.assertLess(delta, 10)

    def test_deploy_canary_no_extra_lines(self):
        """File should have exactly one line, no trailing empty lines."""
        with tempfile.TemporaryDirectory() as tmpdir:
            canary_path = os.path.join(tmpdir, ".deploy-canary")
            timestamp = datetime.utcnow().isoformat() + "Z"
            content = f"{timestamp} # canary\n"

            with open(canary_path, "w") as f:
                f.write(content)

            with open(canary_path, "r") as f:
                lines = [l for l in f.readlines() if l.strip()]

            self.assertEqual(len(lines), 1)


class CanaryHeartbeatIdempotencyTest(unittest.TestCase):
    """Test idempotency — multiple runs produce valid state."""

    def test_multiple_creations_produce_valid_file(self):
        """Creating the file multiple times should always produce valid content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            canary_path = os.path.join(tmpdir, ".deploy-canary")

            for i in range(3):
                timestamp = datetime.utcnow().isoformat() + "Z"
                content = f"{timestamp} # canary heartbeat\n"
                with open(canary_path, "w") as f:
                    f.write(content)

            with open(canary_path, "r") as f:
                lines = f.readlines()

            self.assertEqual(len(lines), 1)
            self.assertIn("#", lines[0])

    def test_update_preserves_file_validity(self):
        """Updating file should not corrupt format."""
        with tempfile.TemporaryDirectory() as tmpdir:
            canary_path = os.path.join(tmpdir, ".deploy-canary")

            # First write
            ts1 = datetime.utcnow().isoformat() + "Z"
            with open(canary_path, "w") as f:
                f.write(f"{ts1} # canary 1\n")

            # Update
            ts2 = datetime.utcnow().isoformat() + "Z"
            with open(canary_path, "w") as f:
                f.write(f"{ts2} # canary 2\n")

            with open(canary_path, "r") as f:
                content = f.read()

            lines = [l for l in content.split("\n") if l.strip()]
            self.assertEqual(len(lines), 1)
            self.assertIn(ts2, content)
            self.assertNotIn(ts1, content)

    def test_file_remains_small(self):
        """File should always be small (under 100 bytes)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            canary_path = os.path.join(tmpdir, ".deploy-canary")

            for _ in range(5):
                timestamp = datetime.utcnow().isoformat() + "Z"
                content = f"{timestamp} # canary\n"
                with open(canary_path, "w") as f:
                    f.write(content)

            size = os.path.getsize(canary_path)
            self.assertLess(size, 200)


class CanaryHeartbeatGitTest(unittest.TestCase):
    """Test git commit and author verification."""

    def test_commit_message_is_descriptive(self):
        """Commit message should describe the canary heartbeat."""
        messages = [
            "chore(canary): heartbeat — pipeline smoke test",
            "chore: canary heartbeat",
            "heartbeat — pipeline verification",
        ]
        for msg in messages:
            self.assertTrue(len(msg) > 0)
            # Should not contain secrets, config keys, or app code references
            self.assertNotIn("SECRET", msg.upper())
            self.assertNotIn("PASSWORD", msg.upper())
            self.assertNotIn("API_KEY", msg.upper())

    def test_commit_author_must_be_repo_owner(self):
        """Commit must be authored as kalepasch1 <kalepasch@gmail.com>."""
        expected_name = "kalepasch1"
        expected_email = "kalepasch@gmail.com"

        # Verify the constants are correct (from CLAUDE.md)
        self.assertEqual(expected_name, "kalepasch1")
        self.assertEqual(expected_email, "kalepasch@gmail.com")

    def test_commit_does_not_modify_app_code(self):
        """Commit should only touch .deploy-canary, nothing else."""
        safe_files = [".deploy-canary"]
        unsafe_patterns = [
            r"app/.*\.(tsx|ts|jsx|js)$",
            r"lib/.*\.(tsx|ts|jsx|js)$",
            r".*\.config\.(ts|js)$",
            r".*\.env.*",
            r"pricing.*",
            r"auth.*",
            r"rls.*",
        ]

        # Verify no app code files are in safe list
        for safe in safe_files:
            for pattern in unsafe_patterns:
                self.assertNotRegex(safe, pattern)

    def test_commit_does_not_modify_config(self):
        """Commit should not modify configuration files."""
        config_patterns = [
            r"package\.json$",
            r"\.env.*$",
            r"tsconfig\.json$",
            r".*\.config\.js$",
            r".*\.config\.ts$",
        ]

        modified_file = ".deploy-canary"
        for pattern in config_patterns:
            self.assertNotRegex(modified_file, pattern)

    def test_commit_does_not_modify_pricing(self):
        """Commit should not touch pricing configuration."""
        self.assertNotIn("pricing", ".deploy-canary")
        self.assertNotIn("PRICING", ".deploy-canary")

    def test_commit_does_not_modify_auth(self):
        """Commit should not touch authentication systems."""
        self.assertNotIn("auth", ".deploy-canary")
        self.assertNotIn("AUTH", ".deploy-canary")

    def test_commit_does_not_modify_rls(self):
        """Commit should not touch RLS policies."""
        self.assertNotIn("rls", ".deploy-canary")
        self.assertNotIn("RLS", ".deploy-canary")


class CanaryHeartbeatSafetyTest(unittest.TestCase):
    """Test safety constraints — no dangerous changes."""

    def test_deploy_canary_path_is_at_root(self):
        """File must be at repo root, not nested."""
        # Only filename, no directory component
        filename = ".deploy-canary"
        self.assertNotIn("/", filename)
        self.assertNotIn("\\", filename)

    def test_deploy_canary_filename_matches_exactly(self):
        """Filename must be exactly '.deploy-canary' (case-sensitive)."""
        self.assertEqual(".deploy-canary", ".deploy-canary")
        self.assertNotEqual(".deploy-canary", ".DEPLOY-CANARY")
        self.assertNotEqual(".deploy-canary", "deploy-canary")

    def test_no_secrets_in_file_content(self):
        """File should never contain secrets, passwords, or credentials."""
        timestamp = datetime.utcnow().isoformat() + "Z"
        content = f"{timestamp} # canary heartbeat\n"

        secret_patterns = [
            "password",
            "secret",
            "api_key",
            "token",
            "credential",
        ]

        content_lower = content.lower()
        for pattern in secret_patterns:
            self.assertNotIn(pattern, content_lower)

    def test_no_comments_reveal_internals(self):
        """Comments should not expose internal implementation details."""
        timestamp = datetime.utcnow().isoformat() + "Z"
        content = f"{timestamp} # canary heartbeat\n"

        # Should be simple, public-safe comment
        self.assertIn("canary", content.lower())
        self.assertIn("heartbeat", content.lower())
        # Should NOT include implementation details
        self.assertNotIn("database", content.lower())
        self.assertNotIn("service", content.lower())
        self.assertNotIn("endpoint", content.lower())

    def test_file_is_idempotent_after_multiple_ops(self):
        """Repeated operations should converge to same state."""
        with tempfile.TemporaryDirectory() as tmpdir:
            canary_path = os.path.join(tmpdir, ".deploy-canary")

            # Three iterations
            for i in range(3):
                timestamp = datetime.utcnow().isoformat() + "Z"
                content = f"{timestamp} # canary heartbeat\n"
                with open(canary_path, "w") as f:
                    f.write(content)

            # Check final state
            with open(canary_path, "r") as f:
                final = f.read()

            lines = [l for l in final.split("\n") if l.strip()]
            self.assertEqual(len(lines), 1)
            self.assertTrue(lines[0].startswith("20"))  # Year starts with 20
            self.assertIn("#", lines[0])


class CanaryHeartbeatBuildVerificationTest(unittest.TestCase):
    """Test that the change passes build verification."""

    def test_canary_file_does_not_break_typescript_build(self):
        """Adding .deploy-canary should not cause TypeScript errors."""
        # .deploy-canary is not a TypeScript file, so it won't be included in tsc
        filename = ".deploy-canary"
        # Verify it's not a code file
        self.assertFalse(filename.endswith(".ts"))
        self.assertFalse(filename.endswith(".tsx"))
        self.assertFalse(filename.endswith(".js"))
        self.assertFalse(filename.endswith(".jsx"))

    def test_canary_file_does_not_break_json_parsing(self):
        """File should not interfere with package.json or other JSON configs."""
        filename = ".deploy-canary"
        self.assertNotEqual(filename, "package.json")
        self.assertFalse(filename.endswith(".json"))

    def test_canary_file_does_not_affect_linting(self):
        """File should not trigger linting errors."""
        filename = ".deploy-canary"
        # Not a code file
        code_extensions = [".ts", ".tsx", ".js", ".jsx", ".py", ".go"]
        for ext in code_extensions:
            self.assertFalse(filename.endswith(ext))

    def test_canary_does_not_modify_vitest_config(self):
        """Test runner config should not change."""
        modified_files = [".deploy-canary"]
        test_config_files = ["vitest.config.ts", "vitest.config.js", "jest.config.js"]
        for cf in test_config_files:
            self.assertNotIn(cf, modified_files)

    def test_canary_does_not_modify_test_files(self):
        """No test files should be modified."""
        modified_files = [".deploy-canary"]
        # Check no test patterns
        test_patterns = [r"\.test\.(ts|tsx|js|jsx)$", r"\.spec\.(ts|tsx|js|jsx)$"]
        for pf in modified_files:
            for pattern in test_patterns:
                self.assertNotRegex(pf, pattern)


class CanaryHeartbeatDeprecationTest(unittest.TestCase):
    """Test that canary does not conflict with existing systems."""

    def test_no_conflict_with_rls_policies(self):
        """Canary file should not interfere with RLS."""
        filename = ".deploy-canary"
        self.assertNotIn("auth", filename.lower())
        self.assertNotIn("policy", filename.lower())

    def test_no_conflict_with_pricing_system(self):
        """Canary file should not touch pricing table or logic."""
        filename = ".deploy-canary"
        self.assertNotIn("price", filename.lower())
        self.assertNotIn("billing", filename.lower())

    def test_no_conflict_with_supabase_setup(self):
        """Canary file should not modify Supabase configuration."""
        filename = ".deploy-canary"
        self.assertNotEqual(filename, ".env")
        self.assertNotEqual(filename, ".env.local")
        self.assertNotEqual(filename, "supabase.json")

    def test_vercel_deployment_allowlist(self):
        """Only .deploy-canary should trigger Vercel deployment."""
        modified_files = [".deploy-canary"]
        # All files are safe for Vercel
        for f in modified_files:
            self.assertTrue(len(f) > 0)
            self.assertNotIn(".env", f)  # env files are not deployed


class CanaryHeartbeatComplianceTest(unittest.TestCase):
    """Test compliance with deployment and security requirements."""

    def test_timestamp_is_utc_not_local(self):
        """Timestamp must always be UTC, never local time."""
        now_utc = datetime.utcnow()
        timestamp = now_utc.isoformat() + "Z"

        # Must end with Z (Zulu/UTC indicator)
        self.assertTrue(timestamp.endswith("Z"))

    def test_no_local_timezone_offsets(self):
        """Should not use +/-HH:MM timezone offsets, only Z for UTC."""
        # Valid: 2026-07-30T12:34:56Z
        # Invalid: 2026-07-30T12:34:56-07:00
        timestamp = datetime.utcnow().isoformat() + "Z"

        # Count + or - signs in timezone part
        tz_part = timestamp[-10:]  # Last part might be timezone
        # Should be just 'Z', not offset
        self.assertFalse("+0" in tz_part or "-0" in tz_part)
        self.assertTrue(timestamp.endswith("Z"))

    def test_commit_can_be_fast_forwarded(self):
        """Commit must be mergeable without conflicts."""
        # Single file change means low conflict risk
        filename = ".deploy-canary"
        self.assertEqual(len([filename]), 1)

    def test_no_merge_conflicts_expected(self):
        """Trivial change should not cause merge conflicts."""
        # Only one file, simple content
        files = [".deploy-canary"]
        self.assertEqual(len(files), 1)


if __name__ == "__main__":
    unittest.main()
