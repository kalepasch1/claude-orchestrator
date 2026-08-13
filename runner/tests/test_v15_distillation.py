import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import hivemind_v15 as v15
import v15_distillation as dist


def teacher(q):
    return q["x"] * 2


def good_student(q):
    return q["x"] * 2


def bad_student(q):
    return q["x"] * 2 + 1


QUERIES = [{"x": i} for i in range(12)]
OPEN_POLICY = dist.Policy(enabled=True, min_hits=1, min_fixtures=4, shadow_calls=4)


def cluster(hits=10, app="tomorrow", pattern="p1"):
    c = v15.QueryCluster(app=app, pattern=pattern, node=v15.DistilledNode(teacher))
    c.hits = hits
    return c


def fixtures(policy=OPEN_POLICY, queries=QUERIES):
    return dist.capture_fixtures(teacher, queries, policy)


class TestEligibility(unittest.TestCase):
    def test_distillation_is_off_unless_opted_in(self):
        ok, reasons = dist.eligibility(cluster(), fixtures(), dist.Policy())
        self.assertFalse(ok)
        self.assertIn("policy_disabled", reasons)

    def test_cold_cluster_is_refused_with_a_reason(self):
        ok, reasons = dist.eligibility(cluster(hits=2), fixtures(),
                                       dist.Policy(enabled=True, min_hits=10))
        self.assertFalse(ok)
        self.assertTrue(any(r.startswith("cold_cluster") for r in reasons))

    def test_too_few_fixtures_cannot_prove_parity(self):
        ok, reasons = dist.eligibility(cluster(), fixtures(queries=QUERIES[:2]),
                                       dist.Policy(enabled=True, min_hits=1, min_fixtures=8))
        self.assertFalse(ok)
        self.assertTrue(any(r.startswith("insufficient_fixtures") for r in reasons))

    def test_recursive_compression_is_depth_bounded(self):
        policy = dist.Policy(enabled=True, min_hits=1, min_fixtures=4, max_lineage_depth=2)
        ok, reasons = dist.eligibility(cluster(), fixtures(), policy, depth=2)
        self.assertFalse(ok)
        self.assertTrue(any(r.startswith("lineage_depth_exceeded") for r in reasons))

    def test_eligible_cluster_passes(self):
        ok, reasons = dist.eligibility(cluster(), fixtures(), OPEN_POLICY)
        self.assertTrue(ok)
        self.assertEqual(reasons, [])


class TestFixtures(unittest.TestCase):
    def test_fixtures_are_bounded_by_the_byte_budget(self):
        tiny = dist.Policy(enabled=True, max_fixture_bytes=40)
        captured = dist.capture_fixtures(teacher, QUERIES, tiny)
        self.assertLess(len(captured), len(QUERIES))

    def test_fixtures_freeze_teacher_behaviour(self):
        captured = fixtures()
        self.assertEqual([f.expected for f in captured], [teacher(q) for q in QUERIES])


class TestParityGate(unittest.TestCase):
    def test_matching_student_is_accepted(self):
        reg = dist.DistillationRegistry(OPEN_POLICY)
        manifest = reg.propose(cluster(), teacher, good_student, fixtures())
        self.assertEqual(manifest.parity, 1.0)
        self.assertEqual(manifest.depth, 0)

    def test_divergent_student_is_refused_not_shipped(self):
        reg = dist.DistillationRegistry(OPEN_POLICY)
        with self.assertRaises(dist.DistillationRefused) as ctx:
            reg.propose(cluster(), teacher, bad_student, fixtures())
        self.assertIn("parity", str(ctx.exception))

    def test_student_that_raises_counts_as_a_fixture_failure(self):
        def exploding(q):
            raise RuntimeError("boom")
        parity, misses = dist.score_parity(exploding, fixtures())
        self.assertEqual(parity, 0.0)
        self.assertTrue(all("error" in m for m in misses))

    def test_calibration_catches_a_right_but_drifting_student(self):
        policy = dist.Policy(enabled=True, min_hits=1, min_fixtures=4,
                             min_parity=.0, max_calibration_error=.01)
        reg = dist.DistillationRegistry(policy)
        with self.assertRaises(dist.DistillationRefused) as ctx:
            reg.propose(cluster(), teacher, lambda q: q["x"] * 2 + 5, fixtures())
        self.assertIn("calibration", str(ctx.exception))

    def test_calibration_is_zero_for_non_numeric_outputs_not_invented(self):
        text_fixtures = [dist.Fixture({"x": i}, f"v{i}") for i in range(4)]
        self.assertEqual(dist.calibration_error(lambda q: f"v{q['x']}", text_fixtures), 0.0)


class TestShadowPeriod(unittest.TestCase):
    def test_shadow_serves_the_teacher_answer(self):
        reg = dist.DistillationRegistry(OPEN_POLICY)
        node = reg.propose(cluster(), teacher, good_student, fixtures())
        shadow = reg.shadow(node.id)
        # Even a student that is wrong must not affect what callers receive.
        shadow.student = bad_student
        self.assertEqual(shadow({"x": 5}), 10)

    def test_promotion_requires_a_complete_shadow_period(self):
        reg = dist.DistillationRegistry(OPEN_POLICY)
        node = reg.propose(cluster(), teacher, good_student, fixtures())
        shadow = reg.shadow(node.id)
        shadow({"x": 1})
        with self.assertRaises(dist.DistillationRefused) as ctx:
            reg.promote(node.id, shadow)
        self.assertIn("shadow period incomplete", str(ctx.exception))

    def test_shadow_disagreement_blocks_promotion(self):
        reg = dist.DistillationRegistry(OPEN_POLICY)
        node = reg.propose(cluster(), teacher, good_student, fixtures())
        shadow = reg.shadow(node.id)
        shadow.student = bad_student
        for i in range(6):
            shadow({"x": i})
        with self.assertRaises(dist.DistillationRefused) as ctx:
            reg.promote(node.id, shadow)
        self.assertIn("shadow parity", str(ctx.exception))

    def test_tail_latency_regression_blocks_promotion(self):
        policy = dist.Policy(enabled=True, min_hits=1, min_fixtures=4,
                             shadow_calls=4, max_tail_latency_ratio=1.5)
        reg = dist.DistillationRegistry(policy)
        node = reg.propose(cluster(), teacher, good_student, fixtures())
        shadow = reg.shadow(node.id)
        shadow.student = lambda q: (time.sleep(.01), q["x"] * 2)[1]
        for i in range(5):
            shadow({"x": i})
        with self.assertRaises(dist.DistillationRefused) as ctx:
            reg.promote(node.id, shadow)
        self.assertIn("tail latency", str(ctx.exception))

    def test_sub_millisecond_timing_noise_does_not_refuse_a_good_student(self):
        """Two identical microsecond functions routinely differ 1.5-2x at p95.

        Without a significance floor the tail gate refuses good students at
        random, which is worse than having no gate at all.
        """
        report = dist.ShadowReport(
            calls=5, agreements=5,
            teacher_latencies=[0.000004] * 5,
            student_latencies=[0.000007] * 5)
        self.assertGreater(report.tail_ratio(floor_s=0.0), 1.5)   # raw ratio is noise
        self.assertEqual(report.tail_ratio(floor_s=1e-3), 1.0)    # floor suppresses it

    def test_a_real_slowdown_above_the_floor_is_still_caught(self):
        report = dist.ShadowReport(
            calls=5, agreements=5,
            teacher_latencies=[0.010] * 5,
            student_latencies=[0.050] * 5)
        self.assertAlmostEqual(report.tail_ratio(floor_s=1e-3), 5.0, places=3)

    def test_clean_shadow_period_promotes_and_serves(self):
        reg = dist.DistillationRegistry(OPEN_POLICY)
        c = cluster()
        node = reg.propose(c, teacher, good_student, fixtures())
        shadow = reg.shadow(node.id)
        for i in range(5):
            shadow({"x": i})
        promoted = reg.promote(node.id, shadow)
        self.assertEqual(promoted.parity, 1.0)
        self.assertIs(reg.resolve(c.app, c.pattern), good_student)


class TestLineageAndRollback(unittest.TestCase):
    def test_manifest_id_is_content_addressed_and_reproducible(self):
        reg = dist.DistillationRegistry(OPEN_POLICY)
        fx = fixtures()
        node = reg.propose(cluster(), teacher, good_student, fx)
        self.assertTrue(reg.reproduce(node.id, fx))
        # Different fixtures must not reproduce the same node id.
        self.assertFalse(reg.reproduce(node.id, fx[:-1]))

    def test_recursive_compression_records_a_traceable_chain(self):
        reg = dist.DistillationRegistry(OPEN_POLICY)
        c = cluster()
        first = reg.propose(c, teacher, good_student, fixtures())
        second = reg.propose(c, good_student, good_student, fixtures(), parent_id=first.id)
        chain = reg.lineage(second.id)
        self.assertEqual([m["node_id"] for m in chain], [second.id, first.id])
        self.assertEqual(second.depth, 1)
        self.assertIsNone(chain[-1]["parent_id"])

    def test_rollback_restores_the_teacher_and_keeps_the_manifest(self):
        reg = dist.DistillationRegistry(OPEN_POLICY)
        c = cluster()
        node = reg.propose(c, teacher, good_student, fixtures())
        shadow = reg.shadow(node.id)
        for i in range(5):
            shadow({"x": i})
        reg.promote(node.id, shadow)
        self.assertIsNotNone(reg.resolve(c.app, c.pattern))

        result = reg.rollback(node.id)
        self.assertTrue(result["was_promoted"])
        self.assertIs(result["restored"], teacher)
        self.assertTrue(result["manifest_retained"])   # audit trail survives
        self.assertIsNone(reg.resolve(c.app, c.pattern))

    def test_rollback_of_an_unknown_node_is_an_error_not_a_silent_noop(self):
        reg = dist.DistillationRegistry(OPEN_POLICY)
        with self.assertRaises(KeyError):
            reg.rollback("does-not-exist")

    def test_policy_change_changes_the_node_identity(self):
        reg = dist.DistillationRegistry(OPEN_POLICY)
        fx = fixtures()
        node = reg.propose(cluster(), teacher, good_student, fx)
        stricter = dist.Policy(enabled=True, min_hits=1, min_fixtures=4,
                               shadow_calls=4, max_calibration_error=.001)
        self.assertFalse(reg.reproduce(node.id, fx, policy=stricter))


if __name__ == "__main__":
    unittest.main()
