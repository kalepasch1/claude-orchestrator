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


class TestMechanicalFusionBounds(unittest.TestCase):
    """Acceptance: N same-repo mechanical tasks fuse into
    ceil(N/MAX_BATCH_SIZE)..ceil(N/MIN_MECHANICAL_BATCH) batches."""

    def _bounds(self, n):
        lo = -(-n // batch_fusion.MAX_BATCH_SIZE)
        hi = -(-n // batch_fusion.MIN_MECHANICAL_BATCH)
        return lo, hi

    def test_batch_count_within_bounds(self):
        for n in (5, 6, 9, 10, 11, 17, 25, 40, 73):
            with self.subTest(n=n):
                tasks = [_task(tid=f"m{i}", project="p1", kind="mechanical",
                               prompt=f"bump version in runner/mod_{i}.py") for i in range(n)]
                batches = batch_fusion.find_fusible(tasks)
                lo, hi = self._bounds(n)
                self.assertGreaterEqual(len(batches), lo, f"N={n} under-fused")
                self.assertLessEqual(len(batches), hi, f"N={n} over-fused")

    def test_every_task_appears_exactly_once(self):
        n = 23
        tasks = [_task(tid=f"m{i}", kind="mechanical",
                       prompt=f"tidy runner/mod_{i}.py") for i in range(n)]
        batches = batch_fusion.find_fusible(tasks)
        seen = [t["id"] for b in batches for t in b]
        self.assertEqual(len(seen), len(set(seen)), "a task was fused into two batches")
        self.assertEqual(set(seen), {f"m{i}" for i in range(n)})

    def test_no_batch_exceeds_the_cap(self):
        tasks = [_task(tid=f"m{i}", kind="mechanical",
                       prompt=f"tidy runner/mod_{i}.py") for i in range(37)]
        for b in batch_fusion.find_fusible(tasks):
            self.assertLessEqual(len(b), batch_fusion.MAX_BATCH_SIZE)
            self.assertGreaterEqual(len(b), 2)

    def test_batches_are_near_equal(self):
        tasks = [_task(tid=f"m{i}", kind="mechanical",
                       prompt=f"tidy runner/mod_{i}.py") for i in range(25)]
        sizes = [len(b) for b in batch_fusion.find_fusible(tasks)]
        self.assertLessEqual(max(sizes) - min(sizes), 1, f"lopsided batches: {sizes}")

    def test_mechanical_fuses_without_file_overlap(self):
        """Same repo is enough for mechanical work — that is the un-pause."""
        tasks = [_task(tid=f"m{i}", kind="mechanical",
                       prompt=f"touch runner/unrelated_{i}.py") for i in range(6)]
        self.assertEqual(len(batch_fusion.find_fusible(tasks)), 1)

    def test_short_tail_still_fuses(self):
        tasks = [_task(tid=f"m{i}", kind="mechanical",
                       prompt=f"tidy runner/mod_{i}.py") for i in range(3)]
        batches = batch_fusion.find_fusible(tasks)
        self.assertEqual(len(batches), 1)
        self.assertEqual(len(batches[0]), 3)

    def test_mechanical_still_never_crosses_projects(self):
        tasks = ([_task(tid=f"a{i}", project="A", kind="mechanical") for i in range(8)]
                 + [_task(tid=f"b{i}", project="B", kind="mechanical") for i in range(8)])
        for b in batch_fusion.find_fusible(tasks):
            self.assertEqual(len({t["project_id"] for t in b}), 1)

    def test_non_mechanical_kinds_are_untouched_by_the_new_path(self):
        """Feature tasks with no shared files must not fuse on repo alone."""
        tasks = [_task(tid=f"f{i}", kind="feature",
                       prompt=f"build runner/unrelated_{i}.py") for i in range(8)]
        self.assertEqual(batch_fusion.find_fusible(tasks), [],
                         "feature tasks must still prove shared context")

    def test_feature_tasks_sharing_files_still_fuse(self):
        tasks = [_task(tid=f"f{i}", kind="feature",
                       prompt="extend runner/shared.py") for i in range(4)]
        self.assertTrue(batch_fusion.find_fusible(tasks))

    def test_prompt_cap_forces_more_batches_not_an_overstuffed_one(self):
        big = "y" * (batch_fusion.MAX_FUSED_PROMPT_LEN // 2)
        tasks = [_task(tid=f"m{i}", kind="mechanical", prompt=big) for i in range(6)]
        batches = batch_fusion.find_fusible(tasks)
        self.assertGreater(len(batches), 1)
        for b in batches:
            total = sum(len(t["prompt"]) for t in b)
            self.assertLessEqual(total, batch_fusion.MAX_FUSED_PROMPT_LEN * 1.5)


class TestSessionRouting(unittest.TestCase):
    def test_one_session_per_batch(self):
        tasks = [_task(tid=f"m{i}", kind="mechanical",
                       prompt=f"tidy runner/mod_{i}.py") for i in range(14)]
        batches = batch_fusion.find_fusible(tasks)
        sessions = batch_fusion.plan_sessions(tasks)
        self.assertEqual(len(sessions), len(batches))
        self.assertTrue(all(s["prompt"] for s in sessions))

    def test_session_key_is_stable_for_the_same_tasks(self):
        tasks = [_task(tid=f"m{i}", kind="mechanical") for i in range(6)]
        a = batch_fusion.plan_sessions(tasks)
        b = batch_fusion.plan_sessions(tasks)
        self.assertEqual([s["session_key"] for s in a], [s["session_key"] for s in b])

    def test_session_carries_every_task_id(self):
        tasks = [_task(tid=f"m{i}", kind="mechanical") for i in range(7)]
        ids = {i for s in batch_fusion.plan_sessions(tasks) for i in s["task_ids"]}
        self.assertEqual(ids, {f"m{i}" for i in range(7)})

    def test_plan_sessions_is_fail_soft_on_garbage(self):
        self.assertEqual(batch_fusion.plan_sessions([]), [])
        self.assertEqual(batch_fusion.plan_sessions([{"id": "x"}]), [])

    def test_batch_session_of_empty_batch_is_none(self):
        self.assertIsNone(batch_fusion.batch_session([]))


class TestDrainSemanticsUntouched(unittest.TestCase):
    """batch_fusion must not change how speculative generators are drained."""

    def test_drain_policy_still_allows_batch_fusion(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        import drain_policy
        self.assertIn("batch_fusion.py", drain_policy.DEFAULT_ALLOW_JOBS)
        self.assertFalse(drain_policy.should_skip("batch_fusion.py", queue_depth=10_000))

    def test_speculative_generators_are_still_skipped_when_draining(self):
        import drain_policy
        for job in ("scout", "spec", "roadmap"):
            self.assertIn(job, drain_policy.DEFAULT_SKIP_JOBS)
            self.assertTrue(drain_policy.should_skip(job, queue_depth=10_000))


if __name__ == "__main__":
    unittest.main()
