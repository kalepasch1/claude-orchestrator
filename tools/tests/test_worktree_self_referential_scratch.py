"""A reconcile task's own report is not recovered work.

Run: python3 -m pytest tools/tests/test_worktree_self_referential_scratch.py

Agent worktrees live at {repo}-wt/{slug}. A task that writes a report about
itself names the file after its own slug, leaves it untracked, and the next
sweep finds a dirty worktree carrying a non-generated file the base does not
have -- RECOVERABLE_VALUE, file a recovery task, which opens a worktree, writes
its own report, and so on. Three worktrees in this checkout were dirty with
nothing but their own report when this was written.

The matcher is keyed on the worktree's own directory name, so these tests care
most about what it must NOT swallow: a file named after a different task is
somebody's recovered work.
"""

import os
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import reconcile_worktree_evidence as r  # noqa: E402


def run(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], check=True,
                          capture_output=True, text=True).stdout.strip()


def write(root, rel, body):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path) or root, exist_ok=True)
    with open(path, "w") as fh:
        fh.write(body)


SLUG = "chatgpt-local-reconcile-beethoven-2829958769f3"


class TestMatcher(unittest.TestCase):
    """Unit-level: what counts as a worktree's own scratch."""

    def setUp(self):
        self.root = "/tmp/repo-wt/" + SLUG

    def test_report_named_after_the_worktree_matches(self):
        self.assertTrue(
            r.is_own_task_scratch("docs/%s.md" % SLUG, self.root))

    def test_report_for_a_different_task_does_not_match(self):
        self.assertFalse(
            r.is_own_task_scratch(
                "docs/chatgpt-local-reconcile-beethoven-f7b45f3f90ad.md",
                self.root))

    def test_ordinary_source_does_not_match(self):
        for path in ("runner/economic_scheduler.py", "tools/thing.py",
                     "docs/recovery/ledger.json", "README.md"):
            self.assertFalse(r.is_own_task_scratch(path, self.root), path)

    def test_a_directory_named_like_the_slug_does_not_match_by_itself(self):
        # Only the basename is considered, so an unrelated file sitting under a
        # slug-named directory stays classifiable.
        self.assertFalse(
            r.is_own_task_scratch("%s/runner/real_work.py" % SLUG, self.root))

    def test_missing_or_short_root_never_matches(self):
        self.assertFalse(r.is_own_task_scratch("docs/x.md", ""))
        self.assertFalse(r.is_own_task_scratch("docs/wt.md", "/tmp/wt"))

    def test_trailing_separator_on_the_root_is_tolerated(self):
        self.assertTrue(
            r.is_own_task_scratch("docs/%s.md" % SLUG, self.root + "/"))


class ScratchWorktreeTestCase(unittest.TestCase):
    """Integration: a worktree named like a real agent worktree."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.join(self.tmp.name, "repo")
        os.makedirs(self.repo)
        run(self.repo, "init", "-q", "-b", "main")
        write(self.repo, "app.py", "X = 1\n")
        # docs/ must already be tracked, as it is in the real repo. git status
        # collapses an entirely-untracked directory to "docs/" and never names
        # the file inside it, which is not the shape this matcher sees live.
        write(self.repo, "docs/README.md", "docs\n")
        run(self.repo, "add", "-A")
        run(self.repo, "-c", "user.name=t", "-c", "user.email=t@t",
            "commit", "-qm", "base")
        run(self.repo, "checkout", "-q", "-b", "agent/" + SLUG)

        wt_parent = os.path.join(self.tmp.name, "repo-wt")
        os.makedirs(wt_parent)
        self.wt = os.path.join(wt_parent, SLUG)
        run(self.repo, "worktree", "add", "-q", "--force", self.wt,
            "agent/" + SLUG)
        self.addCleanup(self.tmp.cleanup)

    def classify(self):
        item = r.Item(ref=self.wt, created_at=int(time.time()) + 60)
        head = run(self.wt, "rev-parse", "HEAD")
        r.classify_worktree(item, self.wt, head, "refs/heads/agent/" + SLUG,
                            "main", self.repo, set())
        return item


class TestSelfReferentialScratch(ScratchWorktreeTestCase):
    def test_own_report_only_is_not_recoverable_value(self):
        write(self.wt, "docs/%s.md" % SLUG, "# Reconciliation report\n")
        item = self.classify()
        self.assertEqual(item.classification, "ALREADY_PRESENT")
        self.assertEqual(item.evidence, "self-referential task scratch")

    def test_the_file_is_still_enumerated_not_dropped(self):
        write(self.wt, "docs/%s.md" % SLUG, "# Reconciliation report\n")
        item = self.classify()
        self.assertIn("docs/%s.md" % SLUG, item.files)

    def test_the_source_is_left_untouched(self):
        report = os.path.join(self.wt, "docs", "%s.md" % SLUG)
        write(self.wt, "docs/%s.md" % SLUG, "# Reconciliation report\n")
        self.classify()
        self.assertTrue(os.path.isfile(report))
        with open(report) as fh:
            self.assertEqual(fh.read(), "# Reconciliation report\n")

    def test_real_work_alongside_the_report_is_still_recoverable(self):
        write(self.wt, "docs/%s.md" % SLUG, "# Reconciliation report\n")
        write(self.wt, "runner/genuinely_new.py", "VALUE = 1\n")
        item = self.classify()
        self.assertEqual(item.classification, "RECOVERABLE_VALUE")

    def test_a_report_for_another_task_is_still_recoverable(self):
        write(self.wt, "docs/chatgpt-local-reconcile-beethoven-f7b45f3f90ad.md",
              "# Somebody else's report\n")
        item = self.classify()
        self.assertEqual(item.classification, "RECOVERABLE_VALUE")


if __name__ == "__main__":
    unittest.main()
