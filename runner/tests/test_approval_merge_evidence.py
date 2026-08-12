"""approval_merge must not write MERGED without the sha that proves it.

Batch 1 of the stranded-branch recovery (ops/stranded-recovery-batch-1-report.md)
found 20 branches whose task row said MERGED while the branch was not an ancestor
of master -- created AFTER the 2026-08-04 audit, so the writer was still live.
Every other MERGED writer in the fleet already routes through merge_truth;
approval_merge's terminal write was a bare db.update carrying no artifact_commit,
and `_integrate` only moves a LOCAL ref unless ORCH_PUSH_ON_MERGE is set. That
combination is the phantom-merge factory these tests close.
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import approval_merge

REPO = "/fake/repo"
SHA = "a" * 40


def _proc(returncode=0, stdout="", stderr=""):
    p = MagicMock()
    p.returncode = returncode
    p.stdout = stdout
    p.stderr = stderr
    return p


class SplitResultTest(unittest.TestCase):
    """The DB state must never be the raw return string of _integrate()."""

    def test_merged_carries_its_sha(self):
        self.assertEqual(approval_merge._split_result(f"MERGED:{SHA}"), ("MERGED", SHA))

    def test_bare_merged_still_works_but_carries_no_evidence(self):
        # Backwards compatible: an old-style bare "MERGED" is not rejected, it simply
        # arrives without a sha -- merge_truth then treats it as unverifiable.
        self.assertEqual(approval_merge._split_result("MERGED"), ("MERGED", ""))

    def test_pushfail_detail_never_leaks_into_the_state_column(self):
        state, sha = approval_merge._split_result("PUSHFAIL:remote rejected (non-fast-forward)")
        self.assertEqual(state, "PUSHFAIL")
        self.assertEqual(sha, "")

    def test_conflict_passes_through(self):
        self.assertEqual(approval_merge._split_result("CONFLICT"), ("CONFLICT", ""))

    def test_none_and_empty_are_survivable(self):
        # Fail-soft: bad input returns a value, it does not raise.
        self.assertEqual(approval_merge._split_result(None), ("", ""))
        self.assertEqual(approval_merge._split_result(""), ("", ""))


class MergedShaTest(unittest.TestCase):
    def test_returns_tip_of_base(self):
        with patch("subprocess.run", return_value=_proc(0, SHA + "\n")):
            self.assertEqual(approval_merge.merged_sha(REPO, "main"), SHA)

    def test_git_failure_returns_empty_not_garbage(self):
        with patch("subprocess.run", return_value=_proc(1, "", "fatal: bad revision")):
            self.assertEqual(approval_merge.merged_sha(REPO, "main"), "")

    def test_exception_is_fail_soft(self):
        with patch("subprocess.run", side_effect=OSError("boom")):
            self.assertEqual(approval_merge.merged_sha(REPO, "main"), "")


class IntegrateReturnsEvidenceTest(unittest.TestCase):
    """A successful integration must hand back the sha, not a bare word."""

    def test_success_returns_merged_with_sha(self):
        calls = {"n": 0}

        def fake_run(cmd, *a, **kw):
            calls["n"] += 1
            if cmd[:2] == ["git", "rev-parse"]:
                return _proc(0, SHA + "\n")
            return _proc(0)

        with patch("approval_merge._free_branch"), \
             patch("approval_merge.subprocess.run", side_effect=fake_run), \
             patch("subprocess.run", side_effect=fake_run), \
             patch.dict(os.environ, {"ORCH_PUSH_ON_MERGE": "false"}), \
             patch("auto_conflict_resolver.verify_merge", return_value=""):
            result = approval_merge._integrate(REPO, "agent/x", "main", test_cmd="true")

        self.assertTrue(result.startswith("MERGED:"), result)
        state, sha = approval_merge._split_result(result)
        self.assertEqual(state, "MERGED")
        self.assertEqual(sha, SHA)


if __name__ == "__main__":
    unittest.main()
