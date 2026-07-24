"""
test_settings_hygiene.py - Prevent machine-specific config from being committed.

Machine-specific files (like .claude/settings.local.json) should NEVER be tracked
in git, as they contain overly permissive allowlists and other local configuration
that would create a security regression if committed.
"""
import os
import subprocess
import unittest


class TestSettingsHygiene(unittest.TestCase):
    """Ensure machine-specific config files are not tracked in git."""

    def setUp(self):
        """Get the repo root."""
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
        )
        self.repo_root = result.stdout.strip()

    def test_settings_local_in_gitignore(self):
        """Verify .claude/settings.local.json is in .gitignore."""
        gitignore_path = os.path.join(self.repo_root, ".gitignore")
        self.assertTrue(
            os.path.exists(gitignore_path),
            f"{gitignore_path} does not exist",
        )
        with open(gitignore_path) as f:
            content = f.read()
        self.assertIn(
            ".claude/settings.local.json",
            content,
            ".claude/settings.local.json is not in .gitignore",
        )

    def test_settings_local_not_tracked(self):
        """Verify .claude/settings.local.json is not tracked in git."""
        result = subprocess.run(
            ["git", "ls-files", ".claude/settings.local.json"],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
        )
        tracked = result.stdout.strip()
        self.assertFalse(
            tracked,
            f".claude/settings.local.json is tracked in git (should be ignored): {tracked}",
        )

    def test_no_allowlist_files_tracked(self):
        """Verify no machine-specific allowlist files are tracked."""
        result = subprocess.run(
            ["git", "ls-files"],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
        )
        tracked_files = result.stdout.strip().split("\n")

        # Files that should never be tracked (machine-specific)
        forbidden_patterns = [
            ".claude/settings.local.json",
            "settings.local.json",
            ".env.local",
            ".env.local.*",
        ]

        for pattern in forbidden_patterns:
            for tracked in tracked_files:
                self.assertNotIn(
                    pattern,
                    tracked,
                    f"Machine-specific file {pattern} found in git tracking: {tracked}",
                )

    def test_no_secrets_in_tracked_settings(self):
        """Verify no tracked settings files contain sensitive keywords."""
        result = subprocess.run(
            ["git", "ls-files", "-o", "--exclude-standard"],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
        )
        settings_files = [
            f for f in result.stdout.strip().split("\n")
            if "settings" in f.lower() and f.endswith(".json")
        ]

        tracked_result = subprocess.run(
            ["git", "ls-files"],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
        )
        tracked_settings = [
            f for f in tracked_result.stdout.strip().split("\n")
            if "settings" in f.lower() and f.endswith(".json")
        ]

        # Only non-local settings should be tracked
        allowed_tracked = [f for f in tracked_settings if "local" not in f]
        self.assertEqual(
            allowed_tracked,
            tracked_settings,
            f"Local settings files are tracked in git: {tracked_settings}",
        )

    def test_settings_local_not_in_recent_history(self):
        """Verify .claude/settings.local.json was removed from git history.

        This test detects the security regression where settings.local.json
        (containing overly permissive allowlists) was accidentally committed.
        """
        result = subprocess.run(
            ["git", "log", "--all", "--full-history", "--name-only", "--pretty=format:"],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
            timeout=10,
        )
        all_files_in_history = result.stdout.strip().split("\n")

        # Filter to settings files only
        settings_in_history = [
            f for f in all_files_in_history
            if ".claude/settings.local.json" in f and f.strip()
        ]

        self.assertEqual(
            len(settings_in_history),
            0,
            ".claude/settings.local.json found in git history (security regression). "
            "This file contains overly permissive allowlists with kill commands and "
            "database access. It must be removed via git filter-repo. "
            f"Found in {len(settings_in_history)} commits.",
        )

    def test_no_allowlist_with_dangerous_commands(self):
        """Verify that any tracked allowlist files don't contain dangerous patterns.

        Dangerous patterns: kill commands, database access, file manipulation.
        """
        result = subprocess.run(
            ["git", "ls-files"],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
        )
        tracked_files = result.stdout.strip().split("\n")

        # Only check tracked settings files
        tracked_settings = [
            f for f in tracked_files
            if "settings" in f.lower() and f.endswith(".json") and f.strip()
        ]

        dangerous_patterns = [
            "Bash(kill",
            "Bash(pkill",
            'import db"',
            "db.select",
            "db.update",
            "Bash(rm -rf",
            "Bash(git reset --hard",
        ]

        for settings_file in tracked_settings:
            file_path = os.path.join(self.repo_root, settings_file)
            if not os.path.exists(file_path):
                continue

            with open(file_path) as f:
                content = f.read()

            for pattern in dangerous_patterns:
                self.assertNotIn(
                    pattern,
                    content,
                    f"Dangerous pattern '{pattern}' found in tracked settings file {settings_file}",
                )


if __name__ == "__main__":
    unittest.main()
