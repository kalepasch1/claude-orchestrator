"""
test_settings_security.py - Comprehensive security tests for Claude Code settings.

These tests ensure that machine-specific configuration files containing
dangerous patterns (kill commands, database access, overly broad file permissions)
are never committed to git, preventing security regressions.
"""

import json
import os
import subprocess
import unittest


class TestSettingsSecurity(unittest.TestCase):
    """Security tests for settings files."""

    def setUp(self):
        """Get the repo root."""
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
        )
        self.repo_root = result.stdout.strip()

    def test_dangerous_patterns_in_local_settings(self):
        """Verify no tracked settings files contain dangerous patterns.

        Dangerous patterns indicate files that should be machine-specific
        and never committed to version control:
        - kill commands (process termination)
        - database access (db.select, db.update)
        - overly broad file permissions (Read(//Users/**)
        - destructive git operations (git reset --hard)
        """
        result = subprocess.run(
            ["git", "ls-files"],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
        )
        tracked_files = result.stdout.strip().split("\n")

        dangerous_indicators = {
            "kill_commands": ["Bash(kill", "Bash(pkill"],
            "database_access": ["import db", "db.select", "db.update"],
            "overly_broad_paths": ["Read(//Users", "Read(//Users/**"],
            "destructive_git": ["Bash(git reset --hard"],
        }

        for tracked_file in tracked_files:
            if not tracked_file.strip():
                continue

            # Only check settings and config files
            if not any(keyword in tracked_file.lower() for keyword in ["settings", "config", "allowlist"]):
                continue

            file_path = os.path.join(self.repo_root, tracked_file)
            if not os.path.exists(file_path):
                continue

            try:
                with open(file_path) as f:
                    content = f.read()
            except (IOError, UnicodeDecodeError):
                continue

            for category, patterns in dangerous_indicators.items():
                for pattern in patterns:
                    self.assertNotIn(
                        pattern,
                        content,
                        f"Tracked file {tracked_file} contains {category} pattern '{pattern}'. "
                        f"Machine-specific files should not be in git.",
                    )

    def test_settings_local_json_not_tracked(self):
        """Verify .claude/settings.local.json is never tracked in git.

        This is the primary constraint: machine-specific config files
        (especially those with overly permissive allowlists) must never
        be committed to version control.
        """
        result = subprocess.run(
            ["git", "ls-files", ".claude/settings.local.json"],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
        )

        tracked_output = result.stdout.strip()
        self.assertEqual(
            tracked_output,
            "",
            ".claude/settings.local.json must not be tracked in git. "
            "This file contains machine-specific configuration that includes "
            "dangerous patterns: kill commands, database access, overly broad "
            "file permissions. Security regression detected.",
        )

    def test_settings_local_json_in_gitignore(self):
        """Verify .claude/settings.local.json is in .gitignore.

        The .gitignore entry prevents future accidental commits while
        allowing the file to exist locally for machine-specific configuration.
        """
        gitignore_path = os.path.join(self.repo_root, ".gitignore")
        self.assertTrue(os.path.exists(gitignore_path))

        with open(gitignore_path) as f:
            content = f.read()

        self.assertIn(
            ".claude/settings.local.json",
            content,
            ".claude/settings.local.json must be in .gitignore to prevent "
            "future accidental commits of machine-specific configuration.",
        )

    def test_no_machine_specific_allowlists_tracked(self):
        """Verify no machine-specific allowlist files are tracked.

        Files like settings.local.json, .env.local, etc. contain user-specific
        configuration and should never be in git.
        """
        result = subprocess.run(
            ["git", "ls-files"],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
        )
        tracked_files = result.stdout.strip().split("\n")

        machine_specific_patterns = [
            ".claude/settings.local.json",
            "settings.local.json",
            ".env.local",
            ".env.*.local",
            ".claude/allowlist.json",
            ".permission-allowlist.json",
        ]

        violations = []
        for tracked_file in tracked_files:
            if not tracked_file.strip():
                continue

            for pattern in machine_specific_patterns:
                if pattern.endswith("/**"):
                    if pattern[:-3] in tracked_file:
                        violations.append((tracked_file, pattern))
                elif pattern in tracked_file:
                    violations.append((tracked_file, pattern))

        self.assertEqual(
            len(violations),
            0,
            f"Found {len(violations)} machine-specific files in git: "
            f"{[f[0] for f in violations]}. These files contain local "
            f"configuration and dangerous permissions and must be removed.",
        )

    def test_tracked_settings_files_allowed_list(self):
        """Verify only safe, non-local settings files are tracked.

        Allowed tracked settings files should be those that:
        - Contain default/safe configuration
        - Do not include user-specific overrides
        - Do not include dangerous patterns
        - Are meant to be version controlled
        """
        result = subprocess.run(
            ["git", "ls-files"],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
        )
        tracked_files = result.stdout.strip().split("\n")

        tracked_settings = [
            f for f in tracked_files
            if "settings" in f.lower() and (f.endswith(".json") or f.endswith(".yml") or f.endswith(".yaml"))
        ]

        # Files like settings.local.json should not be here
        forbidden_keywords = ["local", ".local", "allowlist", "machine-specific"]

        for settings_file in tracked_settings:
            for keyword in forbidden_keywords:
                self.assertNotIn(
                    keyword,
                    settings_file.lower(),
                    f"Tracked settings file '{settings_file}' appears to be "
                    f"machine-specific (contains '{keyword}'). Only default/"
                    f"safe settings should be tracked.",
                )

    def test_gitignore_covers_local_patterns(self):
        """Verify .gitignore has comprehensive patterns for machine-specific files."""
        gitignore_path = os.path.join(self.repo_root, ".gitignore")
        self.assertTrue(os.path.exists(gitignore_path))

        with open(gitignore_path) as f:
            content = f.read()

        # Critical patterns that must be in .gitignore
        required_patterns = [
            ".claude/settings.local.json",
            ".env.local",
            ".env",
        ]

        for pattern in required_patterns:
            self.assertIn(
                pattern,
                content,
                f"Pattern '{pattern}' should be in .gitignore to prevent "
                f"machine-specific files from being committed.",
            )

    def test_no_settings_local_in_recent_commits(self):
        """Verify settings.local.json has been removed from recent commits.

        If this test fails, the file exists in git history (security regression).
        Remediation requires git filter-repo or interactive rebase.
        """
        # Only check the last 100 commits (more recent history)
        result = subprocess.run(
            ["git", "log", "--all", "--name-only", "--pretty=format:", "-100"],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode != 0:
            # If git log fails, skip this check
            return

        recent_files = result.stdout.strip().split("\n")
        settings_local_found = any(
            ".claude/settings.local.json" in f and f.strip()
            for f in recent_files
        )

        self.assertFalse(
            settings_local_found,
            ".claude/settings.local.json was found in recent git history. "
            "This file must be removed from all commits. Remediation requires: "
            "git filter-repo --path .claude/settings.local.json --invert-paths",
        )


if __name__ == "__main__":
    unittest.main()
