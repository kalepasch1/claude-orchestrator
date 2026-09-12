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
        """.claude/settings.local.json must not be RE-ADDED after its removal.

        WHAT THIS USED TO DO, AND WHY IT COULD NOT PASS. It ran
        `git log --all --full-history --name-only --pretty=format:` — every path
        of every commit on every ref — with a 10-second timeout, then filtered in
        Python. On this repo that command takes ~13s, so the test's usual outcome
        was TimeoutExpired rather than an assertion. And when it did finish it
        asserted zero occurrences in ALL history, which is false and will stay
        false: the file was committed in June 2026 and removed on 2026-08-06 by
        5eebf131 ("fix(security): .gitignore never untracked the allowlist it
        lists"). Sixteen commits across all refs still touch it.

        Purging those needs `git filter-repo`, which rewrites every SHA in the
        repository — breaking every clone, every recorded build/test proof and
        every branch on the fleet. That is an operator decision, not something a
        unit test can assert into existence, so this test no longer pretends it
        has happened.

        What it asserts instead is the regression that CAN recur and that the
        removal was for: nothing has added the file back since. Its companion
        test_settings_local_json_not_tracked covers the state at HEAD; this covers
        the interval. Scoped with a pathspec so git does the filtering, which also
        takes it from ~13s to under a second.
        """
        result = subprocess.run(
            ["git", "log", "--diff-filter=A", "--format=%H",
             "5eebf131..HEAD", "--", ".claude/settings.local.json"],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
            timeout=60,
        )
        readded = [line for line in result.stdout.splitlines() if line.strip()]

        self.assertEqual(
            readded,
            [],
            ".claude/settings.local.json was added back after 5eebf131 removed it "
            "(security regression). This file carries an overly permissive allowlist "
            "with kill commands and database access, and must stay untracked. "
            f"Re-added by: {', '.join(readded)}",
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
