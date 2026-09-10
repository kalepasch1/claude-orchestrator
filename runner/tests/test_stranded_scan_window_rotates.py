#!/usr/bin/env python3
"""The stranded-branch reconciler's scan window must move, or the tail is never seen.

THE BUG
-------
`inventory()` selected branches with `sorted(heads.items())[:limit]` — the alphabetically
FIRST `limit` branches, the identical set on every run. Measured on beethoven 2026-09-09:

    agent/* branches on origin   1,618
    already merged into master   1,252
    stranded                       366
    default limit                  500

so roughly 1,118 branches (69%) could never be classified, never be carded, and would
stay stranded no matter how often the reconciler ran. The checkpoint did not help: it
records branches that were CARDED, and a merged/conflicting/unknown branch is never
added to it, so it could never advance the window past one.

This is the same scan-window starvation the tool exists to remedy — the parent task's
confirmed root cause was `_pick_cards()` scanning only the newest 3,000 of 238,177
approved cards. The recovery path was blind in exactly the way the thing it recovers
from was blind.

`inventory` also reported `total` (the whole population) beside counts that described
only the window, so a report that had seen under a third of the branches read as if it
had seen all of them. `scanned` is now separate from `total`.
"""
import os
import sys
import unittest

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RUNNER)

import reconcile_stranded_branches as rsb  # noqa: E402


class SelectWindowTests(unittest.TestCase):
    def setUp(self):
        self.branches = [f"agent/b{i:04d}" for i in range(1000)]

    def test_first_run_takes_the_head_of_the_list(self):
        window = rsb.select_window(self.branches, 100)
        self.assertEqual(window, self.branches[:100])

    def test_second_run_resumes_after_the_cursor(self):
        first = rsb.select_window(self.branches, 100)
        second = rsb.select_window(self.branches, 100, start_after=first[-1])
        self.assertEqual(second, self.branches[100:200])
        self.assertEqual(set(first) & set(second), set())

    def test_the_whole_population_is_covered_in_ceil_n_over_limit_runs(self):
        """The property that matters: nothing is structurally excluded."""
        seen, cursor = set(), ""
        for _ in range(10):                      # 1000 / 100
            window = rsb.select_window(self.branches, 100, start_after=cursor)
            seen.update(window)
            cursor = window[-1]
        self.assertEqual(seen, set(self.branches))

    def test_the_window_wraps_at_the_end(self):
        window = rsb.select_window(self.branches, 100, start_after=self.branches[-50])
        self.assertEqual(len(window), 100)
        self.assertEqual(window[:49], self.branches[-49:])
        self.assertEqual(window[49:], self.branches[:51])

    def test_a_cursor_past_the_end_restarts(self):
        window = rsb.select_window(self.branches, 10, start_after="agent/zzzz")
        self.assertEqual(window, self.branches[:10])

    def test_a_deleted_cursor_branch_still_resumes_in_the_right_place(self):
        """The cursor names a branch that may have been merged and pruned since."""
        window = rsb.select_window(self.branches, 5, start_after="agent/b0099x")
        self.assertEqual(window, self.branches[100:105])

    def test_a_limit_at_or_above_the_population_returns_everything(self):
        for limit in (1000, 5000, 0, -1, None):
            with self.subTest(limit=limit):
                self.assertEqual(len(rsb.select_window(self.branches, limit)), 1000)

    def test_empty_population_is_not_an_error(self):
        self.assertEqual(rsb.select_window([], 100), [])
        self.assertEqual(rsb.select_window([], 100, start_after="agent/x"), [])

    def test_ordering_is_stable_so_the_cursor_means_something(self):
        shuffled = list(reversed(self.branches))
        self.assertEqual(rsb.select_window(shuffled, 10),
                         rsb.select_window(self.branches, 10))


class InventoryCoverageTests(unittest.TestCase):
    """`scanned` must not be conflated with `total`."""

    def setUp(self):
        self.heads = {f"agent/b{i:04d}": f"{i:040x}" for i in range(300)}
        self._real_list = rsb.list_agent_branches
        self._real_base = rsb._base_sha
        self._real_classify = rsb.classify_branch
        self._real_isdir = rsb.os.path.isdir
        rsb.list_agent_branches = lambda _repo, prefix=rsb.BRANCH_PREFIX: self.heads
        rsb._base_sha = lambda _repo, _base: "base0000"
        rsb.classify_branch = lambda _repo, _sha, _base: rsb.MERGED
        rsb.os.path.isdir = lambda _p: True
        self.addCleanup(self._restore)

    def _restore(self):
        rsb.list_agent_branches = self._real_list
        rsb._base_sha = self._real_base
        rsb.classify_branch = self._real_classify
        rsb.os.path.isdir = self._real_isdir

    def _inv(self, **kw):
        return rsb.inventory({"name": "beethoven", "repo_path": "/tmp/x",
                              "default_base": "master"}, **kw)

    def test_total_is_the_population_and_scanned_is_the_window(self):
        inv = self._inv(limit=100)
        self.assertEqual(inv["total"], 300)
        self.assertEqual(inv["scanned"], 100)
        self.assertEqual(inv["merged"], 100,
                         "the classification counts describe the window, not the total")

    def test_cursor_is_returned_so_the_next_run_can_resume(self):
        inv = self._inv(limit=100)
        self.assertEqual(inv["cursor"], "agent/b0099")
        nxt = self._inv(limit=100, start_after=inv["cursor"])
        self.assertEqual(nxt["cursor"], "agent/b0199")

    def test_successive_inventories_cover_everything(self):
        seen, cursor = set(), ""
        for _ in range(3):
            inv = self._inv(limit=100, start_after=cursor)
            seen.update(b["branch"] for b in inv["branches"])
            cursor = inv["cursor"]
        self.assertEqual(len(seen), 300)

    def test_scanned_equals_total_when_the_limit_covers_the_population(self):
        inv = self._inv(limit=500)
        self.assertEqual(inv["scanned"], inv["total"])


class CursorPersistenceTests(unittest.TestCase):
    def setUp(self):
        import tempfile

        self.tmp = tempfile.mkdtemp(prefix="rsb-ckpt-")
        self._real = rsb.CHECKPOINT
        rsb.CHECKPOINT = os.path.join(self.tmp, "ckpt.json")
        self.addCleanup(lambda: setattr(rsb, "CHECKPOINT", self._real))

    def test_cursors_round_trip(self):
        rsb._save_checkpoint({"agent/a"}, scan_cursors={"beethoven": "agent/b0099"})
        self.assertEqual(rsb._load_cursors(), {"beethoven": "agent/b0099"})
        self.assertEqual(rsb._load_checkpoint(), {"agent/a"})

    def test_saving_done_branches_preserves_existing_cursors(self):
        """The two halves of the file are written by different code paths."""
        rsb._save_checkpoint(set(), scan_cursors={"beethoven": "agent/b0099"})
        rsb._save_checkpoint({"agent/a"})            # no cursors passed
        self.assertEqual(rsb._load_cursors(), {"beethoven": "agent/b0099"})

    def test_missing_checkpoint_is_not_an_error(self):
        rsb.CHECKPOINT = os.path.join(self.tmp, "nope.json")
        self.assertEqual(rsb._load_cursors(), {})
        self.assertEqual(rsb._load_checkpoint(), set())

    def test_corrupt_checkpoint_is_not_an_error(self):
        with open(rsb.CHECKPOINT, "w") as fh:
            fh.write("{ truncated")
        self.assertEqual(rsb._load_cursors(), {})
        self.assertEqual(rsb._load_checkpoint(), set())


if __name__ == "__main__":
    unittest.main()
