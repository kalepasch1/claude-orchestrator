#!/usr/bin/env python3
"""`local_evidence_reconciler` batched fast paths — and one that was measured and rejected.

CONTEXT (2026-09-09)
--------------------
The reconcile-evidence tasks kept timing out and re-queueing (attempt 3 and climbing on
some). The cause is not the evidence, it is the traversal: the live evidence sets are two
orders of magnitude larger than the samples carried in the task prompts.

    beethoven   11,894 evidence items  (10,716 distinct rescue commits)
    tomorrow    27,033 evidence items  (~26,345 rescue refs)

A full unpatched run on beethoven produced no output in 22 minutes and was killed. An
unwritten ledger is indistinguishable from unreconciled work, so "too slow to finish" is
a correctness problem here, not a performance nicety.

WHAT IS PINNED HERE
-------------------
1. `contained_refs` — a batched containment pass — agrees exactly with the per-ref
   `rev-list base..ref` it short-circuits. The hazard of any containment fast path is a
   false ALREADY_PRESENT, which writes off live work, so that direction is pinned
   explicitly.
2. Per-commit verdict sharing is sound: two refs on the same sha cannot classify
   differently.

WHAT IS *NOT* HERE, DELIBERATELY
--------------------------------
The obvious next optimisation — collapsing `_superseded`'s per-path `git log` loop into a
single `git log --since --name-only` pass — was implemented, measured, and reverted. See
the block comment on `_superseded`. It was 3x SLOWER (112.8s vs 38.5s on a fixed 200-item
sample) and it CHANGED VERDICTS. There is no test for it because it is not in the tree;
this note exists so the next reader does not re-derive it from first principles and ship
it on the strength of how obviously correct it looks.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

RUNNER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner")
sys.path.insert(0, RUNNER)

import local_evidence_reconciler as ler  # noqa: E402


def _run(repo, *args):
    return subprocess.run(list(args), cwd=repo, capture_output=True, text=True, timeout=60)


class ContainedRefsTests(unittest.TestCase):
    """The batched containment pass must agree with `rev-list base..ref` being empty."""

    def setUp(self):
        self.repo = tempfile.mkdtemp(prefix="ler-contained-")
        self.addCleanup(shutil.rmtree, self.repo, ignore_errors=True)
        _run(self.repo, "git", "init", "-q", "-b", "master")
        _run(self.repo, "git", "config", "user.name", "kalepasch1")
        _run(self.repo, "git", "config", "user.email", "kalepasch@gmail.com")
        _run(self.repo, "git", "config", "commit.gpgsign", "false")

        self._write("a.py", "1\n")
        _run(self.repo, "git", "add", "-A")
        _run(self.repo, "git", "commit", "-qm", "base")
        self.merged = _run(self.repo, "git", "rev-parse", "HEAD").stdout.strip()
        _run(self.repo, "git", "update-ref",
             "refs/orch-rescue/20260101T000000-merged", self.merged)

        _run(self.repo, "git", "checkout", "-q", "-b", "side")
        self._write("a.py", "2\n")
        _run(self.repo, "git", "add", "-A")
        _run(self.repo, "git", "commit", "-qm", "side work")
        self.unmerged = _run(self.repo, "git", "rev-parse", "HEAD").stdout.strip()
        _run(self.repo, "git", "update-ref",
             "refs/orch-rescue/20260101T000001-unmerged", self.unmerged)
        _run(self.repo, "git", "checkout", "-q", "master")

    def _write(self, rel, text):
        path = os.path.join(self.repo, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)

    def test_contained_matches_empty_rev_list(self):
        """Same question, one traversal instead of n — so it must give the same answer."""
        contained = ler.contained_refs(self.repo, "master")
        for ref in ("refs/orch-rescue/20260101T000000-merged",
                    "refs/orch-rescue/20260101T000001-unmerged"):
            unique = _run(self.repo, "git", "rev-list", f"master..{ref}").stdout.split()
            self.assertEqual(ref in contained, not unique,
                             f"{ref}: batched containment disagrees with rev-list")

    def test_unmerged_evidence_is_not_written_off_as_already_present(self):
        """The one hazard of a containment fast path, pinned in the dangerous direction."""
        self.assertNotIn("refs/orch-rescue/20260101T000001-unmerged",
                         ler.contained_refs(self.repo, "master"))

    def test_merged_evidence_is_recognised(self):
        self.assertIn("refs/orch-rescue/20260101T000000-merged",
                      ler.contained_refs(self.repo, "master"))

    def test_classify_fast_path_agrees_with_the_slow_path(self):
        """`contained_refs` short-circuits step 1; the verdict must be unchanged."""
        item = {"kind": "rescue-ref", "ref": "refs/orch-rescue/20260101T000000-merged",
                "name": "20260101T000000-merged"}
        ctx = ler.build_context(self.repo, base="master", live_task_slugs=set())

        ctx["contained_refs"] = set()
        slow = ler.classify(self.repo, item, ctx)
        ctx["contained_refs"] = ler.contained_refs(self.repo, ctx["base_ref"])
        fast = ler.classify(self.repo, item, ctx)

        self.assertEqual(slow["classification"], "ALREADY_PRESENT")
        self.assertEqual(fast["classification"], slow["classification"])

    def test_a_ref_that_no_longer_resolves_is_not_reported_unknown(self):
        """Zero-UNKNOWN is the completion bar; a vanished ref must still classify."""
        ctx = ler.build_context(self.repo, base="master", live_task_slugs=set())
        ctx["contained_refs"] = ler.contained_refs(self.repo, ctx["base_ref"])
        record = ler.classify(self.repo, {"kind": "rescue-ref",
                                          "ref": "refs/orch-rescue/gone", "name": "gone"}, ctx)
        self.assertEqual(record["classification"], "ALREADY_PRESENT")


class PerCommitSharingTests(unittest.TestCase):
    """Two refs on the same commit cannot classify differently — so share the verdict."""

    def setUp(self):
        self.repo = tempfile.mkdtemp(prefix="ler-share-")
        self.addCleanup(shutil.rmtree, self.repo, ignore_errors=True)
        _run(self.repo, "git", "init", "-q", "-b", "master")
        _run(self.repo, "git", "config", "user.name", "kalepasch1")
        _run(self.repo, "git", "config", "user.email", "kalepasch@gmail.com")
        _run(self.repo, "git", "config", "commit.gpgsign", "false")
        with open(os.path.join(self.repo, "a.py"), "w") as f:
            f.write("1\n")
        _run(self.repo, "git", "add", "-A")
        _run(self.repo, "git", "commit", "-qm", "base")
        sha = _run(self.repo, "git", "rev-parse", "HEAD").stdout.strip()
        # A periodic sweep that ran twice with nothing new to capture writes two refs at
        # the same commit. This is the common shape, not a corner case.
        for name in ("20260101T000000-sweep", "20260101T000030-sweep"):
            _run(self.repo, "git", "update-ref", f"refs/orch-rescue/{name}", sha)

    def test_duplicate_refs_each_get_their_own_record(self):
        """Sharing the VERDICT must not collapse the ledger — it is per evidence item."""
        report = ler.reconcile(self.repo, "test-fingerprint", base="master", write=False)
        sources = [r["source"] for r in report["records"]]
        self.assertIn("refs/orch-rescue/20260101T000000-sweep", sources)
        self.assertIn("refs/orch-rescue/20260101T000030-sweep", sources)

    def test_shared_verdicts_are_reported(self):
        """If a refactor silently reverts the sharing, this number drops to zero."""
        report = ler.reconcile(self.repo, "test-fingerprint", base="master", write=False)
        self.assertIn("prefilter", report)
        self.assertGreaterEqual(report["prefilter"]["verdicts_shared"], 1)

    def test_reconcile_reaches_zero_unknown(self):
        """Completion bar for the reconcile tasks this module serves."""
        report = ler.reconcile(self.repo, "test-fingerprint", base="master", write=False)
        self.assertEqual(report["unknown"], [])


if __name__ == "__main__":
    unittest.main()
