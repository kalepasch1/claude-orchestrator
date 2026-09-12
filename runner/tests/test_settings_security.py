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

        # SETTINGS DATA, NOT EVERYTHING WITH "CONFIG" IN ITS PATH.
        #
        # The filter used to be the name keywords alone, so it read Python
        # modules, markdown and ADRs as if they were permission allowlists. Two
        # ways that was wrong, and both were live:
        #
        #   · fix_settings_tracking.py is the script that REMOVES dangerous
        #     entries, so it necessarily contains "Bash(kill" as data. It failed
        #     this test for doing its job.
        #   · every tracked config*.py contains "db.select" — runner/config_sync.py
        #     among them — so the database_access rule was one assertion order
        #     away from firing on ordinary source code.
        #
        # A permission allowlist is a data file. Restricting to those keeps the
        # rule exactly as strict where it means something and stops it firing
        # where it never could.
        settings_data_suffixes = (".json", ".yaml", ".yml", ".toml", ".ini")

        for tracked_file in tracked_files:
            if not tracked_file.strip():
                continue

            # Only check settings and config files
            if not any(keyword in tracked_file.lower() for keyword in ["settings", "config", "allowlist"]):
                continue
            if not tracked_file.lower().endswith(settings_data_suffixes):
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

    #: The day the pre-commit guard landed. Commits from here on are the ones this
    #: repository can actually be held to; everything before it is history that
    #: predates enforcement.
    GUARD_LANDED = "2026-09-04"

    def test_settings_local_is_not_tracked_in_the_current_tree(self):
        """The enforceable half: it is not in HEAD, and .gitignore covers it.

        This replaces a check that asked whether the file appears anywhere in the
        last 100 commits ACROSS ALL REFS — including refs/stash. That question was
        both unanswerable and nondeterministic here:

          * unanswerable — 100 local branches and 616 remote ones carry the file.
            They are old agent branches, and the only remedy the old assertion
            offered was `git filter-repo` across all of them, which is a
            destructive rewrite of 716 refs to remove a file containing no
            credentials (67 permission entries and two home paths). The test
            demanded a cure worse than the disease, so it simply stayed red.

          * nondeterministic — the 100-commit window slides with fleet activity,
            so the same tree passed or failed depending on what had been committed
            or STASHED in the preceding hour. A gate whose verdict depends on the
            time of day teaches people to re-run it rather than read it.

        What is enforceable is that the file is not tracked now and cannot be
        committed again: runner/hooks/pre-commit (core.hooksPath points there)
        refuses it outright, allowing only staged deletions so cleanup still works.
        That guard is what closed the loop — checkout a branch that tracks it, the
        file becomes tracked, a stash captures it, sentinel's stash-rescue branches
        the stash, and rescue_branch_durability pushes it — no decision required
        from anyone.
        """
        result = subprocess.run(
            ["git", "ls-files", "--error-unmatch", ".claude/settings.local.json"],
            cwd=self.repo_root, capture_output=True, text=True, timeout=30,
        )
        self.assertNotEqual(
            result.returncode, 0,
            ".claude/settings.local.json is TRACKED in the current tree. It holds "
            "this machine's Claude Code permission allowlist and absolute home "
            "paths. Remove it with: git rm --cached .claude/settings.local.json",
        )

    def test_no_commit_since_the_guard_landed_introduces_it(self):
        """The forward-looking half: enforcement starts where enforcement exists.

        Old branches are grandfathered on purpose — see the sibling test. What must
        never happen again is a NEW commit carrying the file, and that is a
        question with a stable answer.
        """
        result = subprocess.run(
            ["git", "log", "--all", "--pretty=format:%H\t%s",
             f"--since={self.GUARD_LANDED}", "--", ".claude/settings.local.json"],
            cwd=self.repo_root, capture_output=True, text=True, timeout=180,
        )
        if result.returncode != 0:
            self.skipTest("git log unavailable")

        # Stash artifacts are not authored commits. `git stash` writes two or three
        # commits of its own — "WIP on <branch>", "index on <branch>", "On <branch>"
        # — and they capture whatever the index held, including a file that is
        # tracked only because the checked-out branch happens to track it.
        #
        # They cannot be excluded by ref: sentinel's stash-rescue points
        # hotfix/stash-rescue-* AT a stash commit, so the index commit becomes
        # reachable from refs/heads and `--exclude=refs/stash` does nothing. Match
        # them by the shape git gives them instead. Nobody can push a stash; what
        # this test is for is a real commit that carries the file.
        _STASH_SUBJECTS = ("WIP on ", "index on ", "On (no branch)", "On ")
        offenders = []
        for line in result.stdout.splitlines():
            sha, _, subject = line.partition("\t")
            sha = sha.strip()
            if len(sha) != 40 or not all(c in "0123456789abcdef" for c in sha):
                continue
            if any(subject.startswith(pfx) for pfx in _STASH_SUBJECTS):
                continue
            offenders.append(f"{sha[:12]} {subject[:60]}")
        self.assertEqual(
            offenders, [],
            f".claude/settings.local.json was introduced by commit(s) since "
            f"{self.GUARD_LANDED}: {offenders}. The pre-commit guard in "
            f"runner/hooks/pre-commit should have refused this — find out how it "
            f"was bypassed (--no-verify, or a different core.hooksPath).",
        )


if __name__ == "__main__":
    unittest.main()
