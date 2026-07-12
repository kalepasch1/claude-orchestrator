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


if __name__ == "__main__":
    unittest.main()
