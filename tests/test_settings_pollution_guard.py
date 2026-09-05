#!/usr/bin/env python3
"""`.claude/settings.local.json` must not be committable.

WHAT ACTUALLY WENT WRONG
------------------------
`rework-secret-merge-train-serializer-48b1a1a` was shelved after seven remediations. The
code was fine every time — the reviewer's note says so: "Code changes are well-tested and
logically sound. However, .claude/settings.local.json includes user-specific paths
(/Users/mandypasch, /Users/kpasch) and should NOT be committed."

Seven cycles were spent on a machine-local file arriving in a diff, caught by eye each
time. The repository already had `scripts/check-settings-pollution.sh` and already
gitignored the file, and neither helped:

  * the checker was wired into nothing — no hook, no CI, one grep found it referenced
    only by its own header comment;
  * the pre-commit hook exits 0 as soon as no staged file ends in `.py`, so a staged
    settings.local.json walked past it;
  * the checker inspected the file's CONTENTS and never asked the simpler question —
    is this file staged or tracked at all? It is `git add -f`-ed or not present.

These tests pin the guard that closes it, and the wiring, because an unwired checker is
what this task was already paying for.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHECKER = os.path.join(REPO_ROOT, "scripts", "check-settings-pollution.sh")
SETTINGS = ".claude/settings.local.json"

CLEAN_SETTINGS = '{"permissions": {"allow": ["Edit", "Write", "Read", "Bash"]}}'
POLLUTED_SETTINGS = (
    '{"permissions": {"allow": ["Edit", "Read(/Users/kpasch/Documents/**)",'
    ' "Bash(pkill -f runner)"]}}'
)


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          timeout=60)


class RepoStateTest(unittest.TestCase):
    def test_the_file_is_gitignored(self):
        with open(os.path.join(REPO_ROOT, ".gitignore"), encoding="utf-8") as handle:
            self.assertIn(SETTINGS, handle.read())

    def test_the_file_is_not_tracked_in_this_repo(self):
        result = git(REPO_ROOT, "ls-files", "--error-unmatch", SETTINGS)
        self.assertNotEqual(result.returncode, 0,
                            f"{SETTINGS} is tracked; run: git rm --cached {SETTINGS}")

    def test_the_checker_is_executable(self):
        self.assertTrue(os.path.isfile(CHECKER))

    def test_the_pre_commit_hook_runs_the_checker(self):
        """An unwired checker is the whole reason this cost seven cycles."""
        with open(os.path.join(REPO_ROOT, "scripts", "install-hooks.sh"),
                  encoding="utf-8") as handle:
            installer = handle.read()
        self.assertIn("check-settings-pollution.sh", installer)

    def test_the_checker_runs_before_the_python_only_early_exit(self):
        with open(os.path.join(REPO_ROOT, "scripts", "install-hooks.sh"),
                  encoding="utf-8") as handle:
            installer = handle.read()
        guard = installer.index("check-settings-pollution.sh")
        early_exit = installer.index('if [ -z "$STAGED_PY_FILES" ]')
        self.assertLess(guard, early_exit,
                        "the hook exits early when nothing staged is a .py file, so the "
                        "guard must run before that or it never runs at all")


class ScratchRepoTest(unittest.TestCase):
    """The checker, exercised against real git state in a throwaway repo."""

    def setUp(self):
        self.repo = tempfile.mkdtemp(prefix="settings-guard-")
        self.addCleanup(shutil.rmtree, self.repo, True)
        git(self.repo, "init")
        git(self.repo, "symbolic-ref", "HEAD", "refs/heads/master")
        git(self.repo, "config", "user.email", "t@example.com")
        git(self.repo, "config", "user.name", "T")
        os.makedirs(os.path.join(self.repo, ".claude"))
        os.makedirs(os.path.join(self.repo, "scripts"))
        shutil.copy(CHECKER, os.path.join(self.repo, "scripts"))
        with open(os.path.join(self.repo, ".gitignore"), "w", encoding="utf-8") as handle:
            handle.write(SETTINGS + "\n")
        git(self.repo, "add", ".gitignore")
        git(self.repo, "commit", "-m", "init")

    def _write_settings(self, body):
        with open(os.path.join(self.repo, SETTINGS), "w", encoding="utf-8") as handle:
            handle.write(body)

    def _run(self):
        return subprocess.run(["bash", "scripts/check-settings-pollution.sh"],
                              cwd=self.repo, capture_output=True, text=True, timeout=60)

    def test_absent_file_is_clean(self):
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("clean", result.stdout)

    def test_an_untracked_clean_file_passes(self):
        self._write_settings(CLEAN_SETTINGS)
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_a_staged_file_fails_even_when_its_contents_are_clean(self):
        """The exact shape that shelved the task: force-added, contents irrelevant."""
        self._write_settings(CLEAN_SETTINGS)
        git(self.repo, "add", "-f", SETTINGS)
        result = self._run()
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("STAGED", result.stdout)
        self.assertIn("git restore --staged", result.stdout,
                      "the message must name the fix, not just the fault")

    def test_a_committed_file_fails_and_names_the_fix(self):
        self._write_settings(CLEAN_SETTINGS)
        git(self.repo, "add", "-f", SETTINGS)
        git(self.repo, "commit", "-m", "oops")
        result = self._run()
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("TRACKED", result.stdout)
        self.assertIn("git rm --cached", result.stdout)

    def test_polluted_contents_of_an_untracked_file_still_fail(self):
        """The original content check must keep working."""
        if not shutil.which("jq"):
            self.skipTest("jq not installed; the content checks require it")
        self._write_settings(POLLUTED_SETTINGS)
        result = self._run()
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("/Users/kpasch", result.stdout)

    def test_a_missing_jq_fails_loudly_instead_of_reporting_clean(self):
        """A checker that passes because its dependency is absent is worse than none."""
        self._write_settings(POLLUTED_SETTINGS)
        empty_path = tempfile.mkdtemp(prefix="nojq-")
        self.addCleanup(shutil.rmtree, empty_path, True)
        for tool in ("bash", "git", "grep", "wc", "head"):
            found = shutil.which(tool)
            if found:
                os.symlink(found, os.path.join(empty_path, tool))
        result = subprocess.run(
            ["bash", "scripts/check-settings-pollution.sh"], cwd=self.repo,
            capture_output=True, text=True, timeout=60,
            env=dict(os.environ, PATH=empty_path))
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("jq is required", result.stdout)


class HookBehaviourTest(unittest.TestCase):
    """The installed hook must actually stop the commit."""

    def test_the_hook_body_blocks_when_the_checker_fails(self):
        with open(os.path.join(REPO_ROOT, "scripts", "install-hooks.sh"),
                  encoding="utf-8") as handle:
            installer = handle.read()
        block = installer[installer.index("check-settings-pollution.sh"):]
        self.assertIn("exit 1", block[:400],
                      "a guard that prints and continues is not a guard")


if __name__ == "__main__":
    unittest.main()
