"""Recovery-intent stub markers must not accumulate in the repo.

patch_recovery.regenerate_from_intent() writes .recovery-intent-<slug>.txt as a
last-resort placeholder for a missing branch. It is a marker, not work -- that is the
whole premise of runner/recovery_stub_detector.py. 188 of them had nonetheless been
committed to repo root on master, swept in by agent worktrees running `git add -A`.

Each one is a permanent conflict source: repo root is shared by every branch, so two
branches that each drop a marker collide there forever. relfix-beethoven-299c6b3c3bc6
failed four consecutive redo attempts on exactly that, conflicting on .gitignore plus
two .recovery-intent-*.txt files.

These tests pin both halves of the fix, because they can silently cancel each other:
ignoring the pattern without `git add -f` would quietly turn the recovery path into a
no-op commit, and `git add -f` without the ignore rule leaves the accumulation running.
"""
import os
import re
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
RUNNER = os.path.dirname(HERE)
REPO = os.path.dirname(RUNNER)
sys.path.insert(0, RUNNER)


class GitignoreCoversMarkersTest(unittest.TestCase):
    def test_gitignore_has_the_marker_pattern(self):
        with open(os.path.join(REPO, ".gitignore")) as fh:
            body = fh.read()
        self.assertIn(".recovery-intent-*.txt", body)

    def test_no_marker_file_is_tracked(self):
        out = subprocess.run(["git", "ls-files"], cwd=REPO,
                             capture_output=True, text=True).stdout
        tracked = [p for p in out.splitlines() if "recovery-intent" in p and p.endswith(".txt")]
        self.assertEqual(tracked, [], f"{len(tracked)} stub marker(s) tracked again")

    def test_pattern_actually_ignores_a_marker(self):
        """The rule must work in a real repo, not just look right in the file."""
        tmp = tempfile.mkdtemp(prefix="ri-ignore-")
        try:
            subprocess.run(["git", "init", "-q", tmp], capture_output=True)
            with open(os.path.join(tmp, ".gitignore"), "w") as fh:
                fh.write(".recovery-intent-*.txt\n")
            marker = os.path.join(tmp, ".recovery-intent-some-slug.txt")
            with open(marker, "w") as fh:
                fh.write("recovery-intent: some-slug\n")
            out = subprocess.run(["git", "status", "--porcelain"], cwd=tmp,
                                 capture_output=True, text=True).stdout
            self.assertNotIn("recovery-intent", out)
            # ...and -f still overrides it, which patch_recovery depends on.
            subprocess.run(["git", "add", "-f", marker], cwd=tmp, capture_output=True)
            staged = subprocess.run(["git", "diff", "--cached", "--name-only"], cwd=tmp,
                                    capture_output=True, text=True).stdout
            self.assertIn("recovery-intent-some-slug.txt", staged)
        finally:
            subprocess.run(["rm", "-rf", tmp], capture_output=True)


class PatchRecoveryStillCommitsItsMarkerTest(unittest.TestCase):
    def test_stub_add_uses_force(self):
        """Without -f the ignore rule would make the stub commit a silent no-op."""
        with open(os.path.join(RUNNER, "patch_recovery.py")) as fh:
            src = fh.read()
        self.assertIsNotNone(
            re.search(r'"git",\s*"add",\s*"-f",\s*stub_path', src),
            "patch_recovery must stage its intent marker with `git add -f`",
        )


if __name__ == "__main__":
    unittest.main()
