#!/usr/bin/env python3
"""Regenerable artifacts must not be tracked in git.

regenerable_artifacts.REGENERABLE_PATTERNS is the repo's declaration of "machine output the
fleet can rebuild on demand". `.recovery-intent-*.txt` was on that list, but nothing ever put
it in .gitignore — so patch_recovery.py wrote a stub per failed recovery, the fleet committed
them, and 67 accumulated in the repo root on master.

They carry no work. landed_evidence.py and merge_reconciliation.py both grep commit messages
for exactly this shape (SCAFFOLD_RE / SCAFFOLD = "recovery-intent", "placeholder commit",
"intent stub") specifically to reject such commits as not-real-work. Tracking their output
contradicts that.

This test locks the invariant so the next stub is ignored instead of committed.
"""
import subprocess
import unittest
from pathlib import Path

import regenerable_artifacts

REPO = Path(__file__).resolve().parents[2]

# Patterns that are genuinely fleet-local disposable output and must never be tracked.
# Deliberately a subset of REGENERABLE_PATTERNS: some entries there (lockfile-adjacent or
# vendored paths) are legitimately committed in some repos, so this asserts only the
# unambiguous ones rather than the whole list.
MUST_BE_IGNORED = (
    ".recovery-intent-*.txt",
    ".orch-context-cache.json",
)


def _tracked(pattern):
    out = subprocess.run(
        ["git", "ls-files", "--", pattern],
        cwd=str(REPO), capture_output=True, text=True, timeout=60)
    return [line for line in out.stdout.splitlines() if line.strip()]


class TestRegenerableArtifactsNotTracked(unittest.TestCase):

    def test_recovery_intent_stubs_are_not_tracked(self):
        """The 67 committed stubs are gone and no new one is tracked."""
        tracked = _tracked(".recovery-intent-*.txt")
        self.assertEqual(
            tracked, [],
            f"{len(tracked)} recovery-intent stub(s) tracked in git; "
            f"they are declared regenerable and must be gitignored: {tracked[:5]}")

    def test_declared_disposable_artifacts_are_not_tracked(self):
        for pattern in MUST_BE_IGNORED:
            with self.subTest(pattern=pattern):
                tracked = _tracked(pattern)
                self.assertEqual(
                    tracked, [],
                    f"{pattern} is in REGENERABLE_PATTERNS but {len(tracked)} "
                    f"matching file(s) are tracked: {tracked[:5]}")

    def test_patterns_are_actually_declared_regenerable(self):
        """Guard the premise: this test is only correct if the repo agrees they're disposable."""
        for pattern in MUST_BE_IGNORED:
            with self.subTest(pattern=pattern):
                self.assertIn(pattern, regenerable_artifacts.REGENERABLE_PATTERNS)

    def test_gitignore_covers_recovery_intent_stubs(self):
        """git check-ignore is the real contract — not a substring match on .gitignore."""
        probe = ".recovery-intent-some-future-slug.txt"
        result = subprocess.run(
            ["git", "check-ignore", "-q", probe],
            cwd=str(REPO), capture_output=True, timeout=60)
        self.assertEqual(
            result.returncode, 0,
            f"{probe} is not gitignored; the next failed recovery will be committed again")

    def test_is_regenerable_agrees(self):
        """The helper the merge guard consults must classify a stub as regenerable."""
        self.assertTrue(
            regenerable_artifacts.is_regenerable(".recovery-intent-any-slug.txt"))


if __name__ == "__main__":
    unittest.main()
