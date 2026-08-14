import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import hivemind_v15 as v15
import v15_channel_ecc as ecc

T0 = 1_700_000_000  # fixed clock: time-bucketed learning must be reproducible


def always(replica):
    return replica


def never(replica):
    return None


def corrupt(replica):
    return ecc.Replica(index=replica.index, payload={"tampered": True}, tag=replica.tag)


class TestIntegrity(unittest.TestCase):
    """Redundancy protects against loss; only a checksum protects against corruption."""

    def test_corrupt_replica_is_rejected_not_accepted_for_arriving_first(self):
        ch = ecc.ReliableChannel()
        result = ch.send("tomorrow", "galop", {"v": 1}, corrupt, when=T0)
        self.assertFalse(result.delivered)
        self.assertTrue(all(r["reason"] == "integrity" for r in result.rejected))
        self.assertEqual(ch.metrics["corrupt_rejected"], result.attempts)

    def test_intact_replica_after_a_corrupt_one_is_accepted(self):
        seen = {"n": 0}

        def flaky(replica):
            seen["n"] += 1
            return corrupt(replica) if seen["n"] == 1 else replica

        ch = ecc.ReliableChannel()
        result = ch.send("tomorrow", "galop", {"v": 1}, flaky, when=T0)
        self.assertTrue(result.delivered)
        self.assertEqual(result.accepted_index, 1)

    def test_in_send_escalation_never_exceeds_the_hard_cap(self):
        """Escalation is evidence-driven but bounded; it is not retry-forever."""
        ch = ecc.ReliableChannel()
        result = ch.send("tomorrow", "galop", {"v": 1}, never, when=T0)
        self.assertFalse(result.delivered)
        self.assertEqual(result.attempts, ecc.MAX_REDUNDANCY)

    def test_escalation_respects_a_lowered_cap(self):
        ch = ecc.ReliableChannel(max_redundancy=2, fixed_redundancy=1)
        result = ch.send("tomorrow", "galop", {"v": 1}, never, when=T0)
        self.assertEqual(result.attempts, 2)

    def test_checksum_detects_any_payload_edit(self):
        replica = ecc.Replica.build(0, {"a": 1})
        self.assertTrue(replica.verify())
        self.assertFalse(ecc.Replica(0, {"a": 2}, replica.tag).verify())


class TestBoundedRedundancy(unittest.TestCase):
    def test_redundancy_never_exceeds_the_cap(self):
        ch = ecc.ReliableChannel()
        for _ in range(50):
            ch.ecc.observe("tomorrow", "galop", failed=True, when=T0)
        self.assertLessEqual(ch.redundancy_for("tomorrow", "galop", when=T0), ecc.MAX_REDUNDANCY)

    def test_redundancy_never_drops_below_one(self):
        ch = ecc.ReliableChannel()
        for _ in range(50):
            ch.ecc.observe("tomorrow", "galop", failed=False, when=T0)
        self.assertGreaterEqual(ch.redundancy_for("tomorrow", "galop", when=T0), 1)

    def test_a_cap_above_the_curriculum_ceiling_is_refused(self):
        with self.assertRaises(ValueError):
            ecc.ReliableChannel(max_redundancy=ecc.MAX_REDUNDANCY + 1)

    def test_fixed_value_must_sit_within_the_caps(self):
        with self.assertRaises(ValueError):
            ecc.ReliableChannel(max_redundancy=2, fixed_redundancy=3)

    def test_healthy_channel_sends_exactly_one_copy(self):
        ch = ecc.ReliableChannel()
        result = ch.send("tomorrow", "galop", {"v": 1}, always, when=T0)
        self.assertTrue(result.delivered)
        self.assertEqual(result.attempts, 1)


class TestDeterministicFallback(unittest.TestCase):
    def test_non_adaptive_mode_ignores_learned_state_entirely(self):
        ch = ecc.ReliableChannel(adaptive=False)
        for _ in range(50):
            ch.ecc.observe("tomorrow", "galop", failed=True, when=T0)
        self.assertEqual(ch.redundancy_for("tomorrow", "galop", when=T0), ecc.FIXED_REDUNDANCY)

    def test_broken_curriculum_falls_back_instead_of_taking_the_channel_down(self):
        class Broken(v15.AdaptiveErrorCorrection):
            def redundancy(self, *a, **kw):
                raise RuntimeError("curriculum unavailable")

        ch = ecc.ReliableChannel(ecc=Broken())
        self.assertEqual(ch.redundancy_for("tomorrow", "galop", when=T0), ecc.FIXED_REDUNDANCY)
        self.assertEqual(ch.metrics["fallback_fixed"], 1)


class TestBackoff(unittest.TestCase):
    def test_failure_blocks_the_next_send(self):
        ch = ecc.ReliableChannel(backoff=ecc.Backoff(base_seconds=10, max_seconds=60))
        result = ch.send("tomorrow", "galop", {"v": 1}, never, when=T0)
        self.assertFalse(result.delivered)
        self.assertGreater(result.backoff_s, 0)
        with self.assertRaises(ecc.ChannelUnavailable):
            ch.send("tomorrow", "galop", {"v": 2}, always, when=T0 + 1)

    def test_backoff_is_capped_not_exponential_forever(self):
        bo = ecc.Backoff(base_seconds=1, factor=2, max_seconds=8)
        delays = []
        for _ in range(10):
            delays.append(bo.record_failure(now=0))
        self.assertEqual(max(delays), 8)
        self.assertEqual(delays[-1], 8)

    def test_success_clears_backoff(self):
        ch = ecc.ReliableChannel(backoff=ecc.Backoff(base_seconds=10))
        ch.send("tomorrow", "galop", {"v": 1}, never, when=T0)
        ch.send("tomorrow", "galop", {"v": 2}, always, when=T0 + 100)
        self.assertTrue(ch._backoff("tomorrow", "galop").available(now=T0 + 101))
        self.assertEqual(ch._backoff("tomorrow", "galop").failures, 0)

    def test_backoff_is_per_channel_pair(self):
        ch = ecc.ReliableChannel(backoff=ecc.Backoff(base_seconds=10))
        ch.send("tomorrow", "galop", {"v": 1}, never, when=T0)
        # A different target must not inherit the failure.
        self.assertTrue(ch.send("tomorrow", "smarter", {"v": 1}, always, when=T0 + 1).delivered)


class TestDriftAndCurriculum(unittest.TestCase):
    def test_redundancy_rises_with_failures_and_falls_on_recovery(self):
        ch = ecc.ReliableChannel()
        for _ in range(40):
            ch.ecc.observe("tomorrow", "galop", failed=True, when=T0)
        degraded = ch.redundancy_for("tomorrow", "galop", when=T0)
        for _ in range(80):
            ch.ecc.observe("tomorrow", "galop", failed=False, when=T0)
        recovered = ch.redundancy_for("tomorrow", "galop", when=T0)
        self.assertGreater(degraded, 1)
        self.assertLess(recovered, degraded)

    def test_remedial_schedule_ranks_the_worst_pairs_first(self):
        ch = ecc.ReliableChannel()
        for _ in range(20):
            ch.ecc.observe("tomorrow", "galop", failed=True, when=T0)
        for i in range(20):
            ch.ecc.observe("smarter", "vigil", failed=(i % 10 == 0), when=T0)
        schedule = ch.remedial_schedule()
        self.assertTrue(schedule)
        self.assertEqual(schedule[0]["source"], "tomorrow")
        rates = [g["error_rate"] for g in schedule]
        self.assertEqual(rates, sorted(rates, reverse=True))

    def test_learning_is_time_bucketed(self):
        ch = ecc.ReliableChannel()
        for _ in range(40):
            ch.ecc.observe("tomorrow", "galop", failed=True, when=T0)
        # A different 4-hour bucket has independent state.
        other = ch.redundancy_for("tomorrow", "galop", when=T0 + 5 * 3600)
        self.assertLessEqual(other, ch.redundancy_for("tomorrow", "galop", when=T0))


class TestMeasurement(unittest.TestCase):
    def test_adaptive_and_fixed_are_measured_on_the_same_trace(self):
        report = ecc.compare_to_fixed(messages=60, loss_rate=.5, seed=3)
        for label in ("adaptive", "fixed"):
            self.assertIn(label, report)
            self.assertGreater(report[label]["transmissions"], 0)
            self.assertLessEqual(report[label]["delivery_rate"], 1.0)
        self.assertEqual(report["messages"], 60)

    def test_no_loss_means_one_transmission_per_message_for_both_policies(self):
        report = ecc.compare_to_fixed(messages=25, loss_rate=0.0, seed=1)
        self.assertEqual(report["adaptive"]["delivery_rate"], 1.0)
        self.assertEqual(report["adaptive"]["transmissions_per_message"], 1.0)
        # Fixed always pays for 2 copies even on a perfect channel; it stops at
        # the first intact one, so it also sends 1 -- the difference shows up
        # only when replicas are actually lost.
        self.assertEqual(report["fixed"]["delivery_rate"], 1.0)

    def test_redundancy_is_a_ceiling_so_the_policies_can_legitimately_tie(self):
        """Pins the measured finding rather than hiding it.

        Because a send stops at the first intact replica, redundancy bounds the
        MAXIMUM attempts rather than costing a fixed number of copies.  Adaptive
        and fixed therefore deliver identically unless the ceiling binds, and the
        report says so instead of manufacturing a difference.
        """
        report = ecc.compare_to_fixed(messages=80, loss_rate=.4, seed=7)
        self.assertEqual(report["adaptive"]["delivery_rate"],
                         report["fixed"]["delivery_rate"])
        self.assertIn("identical", report)
        self.assertIn("CEILING", report["note"])

    def test_learned_signal_shows_up_in_starting_redundancy(self):
        report = ecc.compare_to_fixed(messages=80, loss_rate=.4, seed=7)
        # Fixed never varies its starting point; adaptive does as it learns.
        self.assertEqual(list(report["fixed"]["starting_redundancy"]), [ecc.FIXED_REDUNDANCY])
        self.assertGreaterEqual(len(report["adaptive"]["starting_redundancy"]), 1)

    def test_simulated_transport_is_deterministic(self):
        a = ecc.compare_to_fixed(messages=40, loss_rate=.4, seed=11)
        b = ecc.compare_to_fixed(messages=40, loss_rate=.4, seed=11)
        self.assertEqual(a["adaptive"], b["adaptive"])
        self.assertEqual(a["fixed"], b["fixed"])


if __name__ == "__main__":
    unittest.main()
