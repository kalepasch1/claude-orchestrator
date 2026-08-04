#!/usr/bin/env python3
"""Reproduction of the self-certifying phantom-merge loop, in executable form.

Builds a REAL git repo that reproduces the exact production sequence:

    1. agent commits work on agent/<slug>
    2. the branch is GC'd before promotion (work is gone)
    3. a recovery task files `recovery-intent-stub: <slug>` on the integration branch
    4. the recovery branch is merged  ->  `Merge branch 'agent/recover-missing-branch-<slug>'`
    5. the sweeper asks "did <slug> land?"

Historically step 5 answered YES by matching its own scaffolding, and the original task
closed MERGED with zero code. These tests pin all three unsound behaviours that produced
10,584 phantom merges, plus the true-positive case so the fix cannot be "always say no".

Run: python3 -m pytest tests/test_phantom_merge_loop.py -q
"""
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner"))

import landed_evidence  # noqa: E402


def git(repo, *args):
    r = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    assert r.returncode == 0, f"git {args} failed: {r.stderr}"
    return r.stdout.strip()


def write(repo, name, text):
    with open(os.path.join(repo, name), "w") as f:
        f.write(text)


class PhantomMergeLoop(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="phantomrepo-")
        r = cls.tmp
        git(r, "init", "-q", "-b", "master")
        git(r, "config", "user.email", "t@t")
        git(r, "config", "user.name", "t")
        write(r, "README", "base\n")
        git(r, "add", "-A")
        git(r, "commit", "-qm", "base")

        cls.slug = "improve-enhanced-testing-suite-for-configuration-slice-2"

        # --- (1) agent does real work on its branch -------------------------
        git(r, "checkout", "-q", "-b", f"agent/{cls.slug}")
        write(r, "feature.py", "def feature():\n    return 42\n")
        git(r, "add", "-A")
        git(r, "commit", "-qm", f"feat: implement {cls.slug}")
        # --- (2) branch GC'd before promotion: work never reaches master ----
        git(r, "checkout", "-q", "master")
        git(r, "branch", "-qD", f"agent/{cls.slug}")

        # --- (3)+(4) recovery files a stub and merges it --------------------
        rec = f"recover-missing-branch-{cls.slug}"
        git(r, "checkout", "-q", "-b", f"agent/{rec}")
        write(r, f"INTENT-{rec}.md", "intent only, no implementation\n")
        git(r, "add", "-A")
        git(r, "commit", "-qm", f"recovery-intent-stub: {cls.slug}\n\nintent: rebuild the lost work")
        git(r, "commit", "-q", "--allow-empty", "-m", f"agent: {rec}")
        git(r, "checkout", "-q", "master")
        git(r, "merge", "-q", "--no-ff", f"agent/{rec}", "-m",
            f"Merge branch 'agent/{rec}' (auto-resolved)")

        # --- a SIBLING slice that really did land (48-char prefix collision) -
        cls.sibling = "improve-enhanced-testing-suite-for-configuration-slice-1"
        git(r, "checkout", "-q", "-b", f"agent/{cls.sibling}")
        write(r, "sibling.py", "def sibling():\n    return 1\n")
        git(r, "add", "-A")
        git(r, "commit", "-qm", f"feat: implement {cls.sibling}")
        git(r, "checkout", "-q", "master")
        git(r, "merge", "-q", "--no-ff", f"agent/{cls.sibling}", "-m",
            f"Merge branch 'agent/{cls.sibling}'")

        # --- an EMPTY merge that names a slug but delivers nothing -----------
        cls.empty_slug = "hive-ops-empty-delivery-slice-9"
        git(r, "commit", "-q", "--allow-empty", "-m",
            f"Merge branch 'agent/{cls.empty_slug}' (auto-resolved)")

        # --- publish to an 'origin' so integration_sweeper (which only consults
        #     origin/<target>) is exercised for real rather than trivially returning False.
        cls.origin = tempfile.mkdtemp(prefix="phantomorigin-")
        git(cls.origin, "init", "-q", "--bare", "-b", "master")
        git(r, "remote", "add", "origin", cls.origin)
        git(r, "push", "-q", "origin", "master")
        git(r, "fetch", "-q", "origin")

        cls.refs = ["master"]

    def test_1_stub_and_recovery_merge_do_not_certify(self):
        """THE BUG: recovery scaffolding must never prove the original landed."""
        ev = landed_evidence.find_evidence(self.tmp, self.slug, refs=self.refs)
        self.assertIsNone(
            ev, f"phantom merge reproduced: recovery scaffolding certified {self.slug} as {ev}")
        self.assertFalse(landed_evidence.has_landed(self.tmp, self.slug, refs=self.refs))

    def test_2_sibling_slice_does_not_certify_via_48char_prefix(self):
        """slice-1 landing must not certify slice-2 (both share a 48-char prefix)."""
        self.assertEqual(self.slug[:48], self.sibling[:48],
                         "test precondition: the two slugs must collide under truncation")
        self.assertIsNone(landed_evidence.find_evidence(self.tmp, self.slug, refs=self.refs))

    def test_3_empty_commit_is_not_evidence(self):
        """A merge that changes no files delivered nothing, whatever it says."""
        self.assertIsNone(
            landed_evidence.find_evidence(self.tmp, self.empty_slug, refs=self.refs))

    def test_4_real_work_is_still_recognised(self):
        """Guard against 'fix' by always answering no."""
        ev = landed_evidence.find_evidence(self.tmp, self.sibling, refs=self.refs)
        self.assertIsNotNone(ev, "genuinely merged work must still be recognised")
        sha, ref, subject = ev
        self.assertTrue(sha)
        # the evidence sha must really change the tree. Compare against the FIRST PARENT:
        # `git show` on a merge commit prints no file list, which is exactly why the audit
        # compares tree OIDs instead of diffing.
        files = git(self.tmp, "diff", "--name-only", f"{sha}^1", sha)
        self.assertIn("sibling.py", files)

    def test_5_sweeper_does_not_write_MERGED_for_the_phantom(self):
        """End-to-end: the sweeper's decision function must refuse to close the task."""
        import integration_sweeper as isw
        decided = isw._already_integrated(self.tmp, self.slug)
        self.assertFalse(
            decided,
            "integration_sweeper still self-certifies: it would set state=MERGED for a task "
            "whose only trace in git is its own recovery stub")
        # ...and it still says yes to the real one
        self.assertTrue(isw._already_integrated(self.tmp, self.sibling))


if __name__ == "__main__":
    unittest.main(verbosity=2)
