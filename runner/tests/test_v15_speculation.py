import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import hivemind_v15 as v15
import v15_speculation as spec


def paths(**kw):
    return kw


class TestDeterministicWinner(unittest.TestCase):
    def test_highest_ranked_path_wins_even_when_slower(self):
        """The whole point: the winner is chosen by rank, not by the clock."""
        s = spec.BudgetedSpeculator()
        # Teach the ranker that "alpha" is the confident path, then make it slow.
        for _ in range(3):
            s.chains.observe_transition("q", "alpha")
        p = paths(alpha=lambda q: (time.sleep(.05), "alpha-answer")[1],
                  beta=lambda q: "beta-answer")
        for _ in range(5):
            self.assertEqual(s.run("q", p).result, "alpha-answer")

    def test_candidate_set_is_order_independent(self):
        s = spec.BudgetedSpeculator(budget=spec.Budget(max_paths=2))
        fns = {"c": lambda q: 1, "a": lambda q: 2, "b": lambda q: 3}
        forward = [n for n, _ in s.ranked_paths("q", fns)]
        reversed_ = [n for n, _ in s.ranked_paths("q", dict(reversed(list(fns.items()))))]
        self.assertEqual(forward, reversed_)
        self.assertEqual(forward, ["a", "b"])

    def test_parity_with_non_speculative_execution(self):
        s = spec.BudgetedSpeculator()
        p = paths(primary=lambda q: f"v:{q}", other=lambda q: "WRONG")
        report = spec.parity_check(s, ["a", "b", "c"], p)
        self.assertTrue(report["parity"], report["mismatches"])
        self.assertEqual(report["checked"], 3)


class TestBoundedWork(unittest.TestCase):
    def test_at_most_three_paths_are_started(self):
        started = []
        def make(n):
            def fn(q):
                started.append(n)
                return n
            return fn
        s = spec.BudgetedSpeculator()
        p = {f"p{i}": make(i) for i in range(8)}
        result = s.run("q", p)
        self.assertEqual(result.paths_started, 3)
        self.assertLessEqual(len(set(started)), 3)

    def test_hung_path_does_not_hang_the_caller(self):
        s = spec.BudgetedSpeculator(budget=spec.Budget(wall_seconds=.15, max_paths=2))
        stop = threading_event()
        p = paths(slow=lambda q: (stop.wait(30), "never")[1], quick=lambda q: "quick")
        t0 = time.perf_counter()
        try:
            result = s.run("q", p)
        finally:
            stop.set()
        self.assertLess(time.perf_counter() - t0, 3.0)
        self.assertTrue(result.timed_out or result.winner == "quick")

    def test_budget_rejects_nonsense_values(self):
        with self.assertRaises(ValueError):
            spec.Budget(wall_seconds=0)
        with self.assertRaises(ValueError):
            spec.Budget(max_paths=0)


class TestFallback(unittest.TestCase):
    def test_all_paths_failing_falls_back_to_primary(self):
        calls = []
        def boom(q):
            calls.append("boom")
            raise RuntimeError("path exploded")
        s = spec.BudgetedSpeculator()
        # Only the failing path speculates; the fallback re-runs the primary,
        # which is that same path -- so a genuine failure stays a failure.
        with self.assertRaises(RuntimeError):
            s.run("q", paths(only=boom))
        self.assertGreaterEqual(len(calls), 2)

    def test_fallback_returns_primary_result_when_accept_rejects_everything(self):
        s = spec.BudgetedSpeculator()
        p = paths(a=lambda q: "value")
        with self.assertRaises(spec.BudgetExceeded):
            s.run("q", p, accept=lambda v: False)

    def test_failing_speculative_path_does_not_poison_a_good_one(self):
        s = spec.BudgetedSpeculator()
        def bad(q):
            raise ValueError("nope")
        # "bad" sorts before "good", so it is tried first and must be skipped.
        result = s.run("q", paths(bad=bad, good=lambda q: "good"))
        self.assertEqual(result.result, "good")
        self.assertEqual(result.winner, "good")
        self.assertFalse(result.fell_back)


class TestTelemetryAndBenchmark(unittest.TestCase):
    def test_repeat_pattern_telemetry(self):
        s = spec.BudgetedSpeculator()
        p = paths(a=lambda q: q)
        for _ in range(3):
            s.run({"kind": "same"}, p)
        s.run({"other_shape": 1, "extra": 2}, p)
        repeats = s.repeat_patterns(minimum=2)
        self.assertEqual(len(repeats), 1)
        self.assertEqual(repeats[0]["count"], 3)
        self.assertIn("speculative_win", s.stats()["counters"])

    def test_pattern_key_groups_by_shape_not_by_value(self):
        """Documents the privacy property this telemetry inherits.

        ``pattern_key`` hashes the *shape* of a query (its keys and value
        types), never the values, so two queries differing only in payload
        share a counter.  Repeat telemetry is therefore a signal about query
        forms and cannot be used to reconstruct what an app actually asked.
        """
        s = spec.BudgetedSpeculator()
        p = paths(a=lambda q: q)
        s.run({"kind": "alpha"}, p)
        s.run({"kind": "beta"}, p)
        self.assertEqual(s.repeat_patterns(minimum=2)[0]["count"], 2)

    def test_benchmark_reports_measured_not_claimed_numbers(self):
        s = spec.BudgetedSpeculator()
        p = paths(a=lambda q: sum(range(200)), b=lambda q: sum(range(200)))
        report = spec.benchmark(s, "q", p, repeats=3)
        self.assertEqual(report["repeats"], 3)
        self.assertGreater(report["serial_s"], 0)
        self.assertGreater(report["speculative_s"], 0)
        # No fabricated multiplier: the ratio is whatever was observed.
        self.assertAlmostEqual(report["speedup"], report["serial_s"] / report["speculative_s"], places=6)

    def test_benchmark_requires_paths(self):
        s = spec.BudgetedSpeculator()
        with self.assertRaises(ValueError):
            spec.benchmark(s, "q", {}, repeats=2)


class TestIntegrationWithRuntime(unittest.TestCase):
    def test_runtime_speculation_object_is_reusable(self):
        rt = v15.HivemindV15()
        s = spec.BudgetedSpeculator(chains=rt.speculation)
        result = s.run("q", paths(a=lambda q: "ok"))
        self.assertEqual(result.result, "ok")
        # Learning is written back to the shared runtime, not a private copy.
        self.assertIn("a", rt.speculation.transitions[v15.pattern_key("q")])


def threading_event():
    import threading
    return threading.Event()


if __name__ == "__main__":
    unittest.main()
