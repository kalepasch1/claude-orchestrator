#!/usr/bin/env python3
"""Tests for batch_fusion.py — task fusion for same-repo mechanical work."""
import os, sys, unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import batch_fusion


def _task(tid="t1", project="p1", kind="mechanical", prompt="fix runner/foo.py", slug=None):
    return {"id": tid, "project_id": project, "kind": kind, "prompt": prompt, "slug": slug or tid}


class TestKindsCompatible(unittest.TestCase):
    def test_same_kind(self):
        self.assertTrue(batch_fusion._kinds_compatible("mechanical", "mechanical"))
    def test_compatible_group(self):
        self.assertTrue(batch_fusion._kinds_compatible("mechanical", "config"))
    def test_incompatible(self):
        self.assertFalse(batch_fusion._kinds_compatible("mechanical", "feature"))
    def test_feature_self(self):
        self.assertTrue(batch_fusion._kinds_compatible("feature", "feature"))


class TestExtractTargetFiles(unittest.TestCase):
    def test_extracts_paths(self):
        t = _task(prompt="Fix runner/foo.py and runner/bar.js")
        files = batch_fusion._extract_target_files(t)
        self.assertIn("runner/foo.py", files)
        self.assertIn("runner/bar.js", files)
    def test_empty_prompt(self):
        t = _task(prompt="")
        files = batch_fusion._extract_target_files(t)
        self.assertIsInstance(files, list)


class TestFileOverlap(unittest.TestCase):
    def test_full_overlap(self):
        self.assertAlmostEqual(batch_fusion._file_overlap(["a.py"], ["a.py"]), 1.0)
    def test_no_overlap(self):
        self.assertAlmostEqual(batch_fusion._file_overlap(["a.py"], ["b.py"]), 0.0)
    def test_partial_overlap(self):
        v = batch_fusion._file_overlap(["a.py", "b.py"], ["b.py", "c.py"])
        self.assertGreater(v, 0)
        self.assertLess(v, 1)
    def test_empty_lists(self):
        self.assertEqual(batch_fusion._file_overlap([], []), 0)
    def test_one_empty(self):
        self.assertEqual(batch_fusion._file_overlap(["a.py"], []), 0)


class TestFindFusible(unittest.TestCase):
    def test_batch_size_bounds(self):
        tasks = [_task(tid=f"t{i}", project="p1", kind="mechanical",
                       prompt=f"fix runner/shared.py line {i}") for i in range(10)]
        batches = batch_fusion.find_fusible(tasks)
        for b in batches:
            self.assertLessEqual(len(b), batch_fusion.MAX_BATCH_SIZE)
    def test_cross_project_isolation(self):
        tasks = [
            _task(tid="a1", project="proj-A", prompt="fix runner/x.py"),
            _task(tid="a2", project="proj-A", prompt="fix runner/x.py"),
            _task(tid="b1", project="proj-B", prompt="fix runner/x.py"),
        ]
        batches = batch_fusion.find_fusible(tasks)
        for b in batches:
            projects = set(t["project_id"] for t in b)
            self.assertEqual(len(projects), 1, "batch must not cross projects")
    def test_single_task_no_batch(self):
        tasks = [_task()]
        batches = batch_fusion.find_fusible(tasks)
        self.assertEqual(len(batches), 0)
    def test_incompatible_kinds_not_fused(self):
        tasks = [
            _task(tid="t1", kind="mechanical", prompt="fix runner/a.py"),
            _task(tid="t2", kind="feature", prompt="fix runner/a.py"),
        ]
        batches = batch_fusion.find_fusible(tasks)
        for b in batches:
            kinds = set(t["kind"] for t in b)
            self.assertFalse({"mechanical", "feature"}.issubset(kinds))


class TestFusePrompts(unittest.TestCase):
    def test_fuse_output(self):
        batch = [_task(tid="t1", slug="fix-a"), _task(tid="t2", slug="fix-b")]
        result = batch_fusion.fuse_prompts(batch)
        self.assertIn("FUSED BATCH", result)
        self.assertIn("fix-a", result)
        self.assertIn("fix-b", result)
    def test_fuse_truncation(self):
        long_prompt = "x" * (batch_fusion.MAX_FUSED_PROMPT_LEN + 100)
        batch = [_task(prompt=long_prompt)]
        result = batch_fusion.fuse_prompts(batch)
        self.assertLessEqual(len(result), batch_fusion.MAX_FUSED_PROMPT_LEN + 100)


class TestDistributeOutcome(unittest.TestCase):
    def test_distribute_does_not_raise(self):
        batch = [_task(tid="t1"), _task(tid="t2")]
        batch_fusion.distribute_outcome(batch, "output", merged=False, cost={"usd": 0.01})
    def test_distribute_merged(self):
        batch = [_task(tid="t1")]
        batch_fusion.distribute_outcome(batch, "ok", merged=True, cost=None)


class TestIdempotency(unittest.TestCase):
    def test_find_fusible_idempotent(self):
        tasks = [_task(tid=f"t{i}", prompt=f"fix runner/x.py #{i}") for i in range(4)]
        b1 = batch_fusion.find_fusible(tasks)
        b2 = batch_fusion.find_fusible(tasks)
        self.assertEqual(len(b1), len(b2))


class TestPriorityOrdering(unittest.TestCase):
    def test_ordering_preserved_in_batch(self):
        tasks = [
            _task(tid="first", prompt="fix runner/a.py first"),
            _task(tid="second", prompt="fix runner/a.py second"),
            _task(tid="third", prompt="fix runner/a.py third"),
        ]
        batches = batch_fusion.find_fusible(tasks)
        if batches:
            ids = [t["id"] for t in batches[0]]
            self.assertEqual(ids[0], "first")


class TestMechanicalBatching(unittest.TestCase):
    """The unpause contract: N same-repo mechanical tasks must actually fuse.

    Before this, fusion required a non-empty file-set overlap for every pair, so a
    run of small mechanical tasks touching different files produced zero batches —
    enabled in config, inert in practice. These assertions pin the batch-count
    envelope the scheduler is sized against: ceil(N/10) .. ceil(N/5)."""

    @staticmethod
    def _mech(n, project="p1"):
        return [_task(tid=f"m{i}", project=project, kind="mechanical",
                      prompt=f"fix runner/mod_{i}.py") for i in range(n)]

    def _assert_envelope(self, n):
        batches = batch_fusion.find_fusible(self._mech(n))
        lo = -(-n // 10)
        hi = -(-n // 5)
        self.assertGreaterEqual(len(batches), lo,
                                f"N={n} produced {len(batches)} batches, expected >= {lo}")
        self.assertLessEqual(len(batches), hi,
                             f"N={n} produced {len(batches)} batches, expected <= {hi}")
        self.assertEqual(sum(len(b) for b in batches), n, "every task must land in a batch")

    def test_batch_count_envelope(self):
        for n in (6, 10, 11, 17, 20, 23, 40):
            with self.subTest(n=n):
                self._assert_envelope(n)

    def test_batch_size_capped_at_ten(self):
        batches = batch_fusion.find_fusible(self._mech(37))
        self.assertTrue(batches)
        for b in batches:
            self.assertLessEqual(len(b), 10)
            self.assertGreaterEqual(len(b), 2, "a 1-task batch saves nothing")

    def test_batches_never_cross_projects(self):
        tasks = self._mech(12, project="A") + self._mech(12, project="B")
        for b in batch_fusion.find_fusible(tasks):
            self.assertEqual(len(set(t["project_id"] for t in b)), 1)

    def test_no_task_appears_twice(self):
        batches = batch_fusion.find_fusible(self._mech(23))
        ids = [t["id"] for b in batches for t in b]
        self.assertEqual(len(ids), len(set(ids)))

    def test_mechanical_not_mixed_with_feature(self):
        tasks = self._mech(8) + [_task(tid="f1", kind="feature", prompt="add runner/x.py")]
        for b in batch_fusion.find_fusible(tasks):
            kinds = set(t["kind"] for t in b)
            self.assertFalse({"mechanical", "feature"}.issubset(kinds))


class TestFailSoft(unittest.TestCase):
    """Fusion is an optimization. A malformed row must cost a tick, not the scheduler."""

    def test_malformed_tasks_return_empty_not_raise(self):
        for bad in ([None, None], ["not-a-dict", 42], [{}, {}], [{"id": None}, {"id": ""}]):
            with self.subTest(bad=bad):
                self.assertEqual(batch_fusion.find_fusible(bad), [])

    def test_non_iterable_input_returns_empty(self):
        self.assertEqual(batch_fusion.find_fusible(None), [])
        self.assertEqual(batch_fusion.find_fusible(12345), [])

    def test_missing_fields_do_not_raise(self):
        tasks = [{"id": "a"}, {"id": "b"}, {"id": "c", "prompt": None, "kind": None}]
        self.assertIsInstance(batch_fusion.find_fusible(tasks), list)

    def test_good_tasks_survive_alongside_malformed(self):
        good = [_task(tid=f"g{i}", kind="mechanical", prompt=f"fix runner/g{i}.py")
                for i in range(6)]
        batches = batch_fusion.find_fusible(good + [None, {}, "junk"])
        self.assertTrue(batches)
        self.assertEqual(sum(len(b) for b in batches), 6)

    def test_fuse_prompts_tolerates_malformed_entries(self):
        out = batch_fusion.fuse_prompts([_task(tid="ok", slug="ok-slug"), None, {}])
        self.assertIn("ok-slug", out)


if __name__ == "__main__":
    unittest.main()
