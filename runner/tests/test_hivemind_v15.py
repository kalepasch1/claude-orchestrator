import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import hivemind_v15 as v15


class TestFleetAdapters(unittest.TestCase):
    def test_all_requested_apps_are_canonical(self):
        expected = {"galop", "tomorrow", "smarter", "pareto", "apparently", "orchestrator",
                    "vigil", "hisanta", "predictions", "trojun"}
        self.assertEqual(set(v15.FLEET_APPS), expected)
        self.assertEqual(v15.canonical_app("beethoven"), "orchestrator")
        self.assertEqual(v15.canonical_app("racefeed"), "galop")
        self.assertEqual(v15.canonical_app("illuminati"), "trojun")

    def test_every_app_has_end_to_end_adapter(self):
        rt = v15.HivemindV15()
        for app in v15.FLEET_APPS:
            result = rt.adapter(app).query({"app": app}, {"default": lambda query: query["app"]})
            self.assertEqual(result["result"], app)

    def test_federated_anomaly_curriculum_uses_all_sources(self):
        rt = v15.HivemindV15()
        batch = rt.federated_anomaly_batch({"galop": [1, 2], "vigil": [3, 4]}, count=2)
        self.assertEqual({row["source"] for row in batch}, {"galop", "vigil"})
        self.assertEqual(len(batch), 4)


class TestMemoryFederation(unittest.TestCase):
    def test_fractal_memory_round_trip_and_zero_copy_view(self):
        memory = v15.HolographicMemory()
        fed = v15.ZeroCopyFederation(memory)
        memory.put("tomorrow", {"query": "risk 42"}, {"answer": 7})
        hit, view = fed.query("smarter", {"query": "risk 42"})
        self.assertIsNotNone(hit)
        self.assertEqual(hit.value, {"answer": 7})
        self.assertIsInstance(view, memoryview)
        self.assertTrue(view.readonly)

    def test_sleep_cycle_deduplicates(self):
        memory = v15.HolographicMemory()
        memory.put("tomorrow", [1, 2, 3], "old")
        memory.put("smarter", [1, 2, 3], "new")
        result = memory.consolidate()
        self.assertGreaterEqual(result["removed"], 1)


class TestBudgetsAndCorrection(unittest.TestCase):
    def test_idle_module_spends_zero(self):
        budget = v15.SpikeBudget(threshold=.5)
        self.assertEqual(budget.signal("vigil", .2), 0)
        self.assertGreater(budget.signal("vigil", .9), 0)

    def test_predictive_redundancy_adapts(self):
        ecc = v15.AdaptiveErrorCorrection(alpha=.5)
        for _ in range(4): ecc.observe("galop", "predictions", True)
        self.assertEqual(ecc.redundancy("galop", "predictions"), 3)
        for _ in range(20): ecc.observe("galop", "predictions", False)
        self.assertEqual(ecc.redundancy("galop", "predictions"), 1)


class TestExecutionTopology(unittest.TestCase):
    def test_top_three_paths_and_learning(self):
        chains = v15.SpeculativeChains(max_paths=3)
        paths = {f"p{i}": (lambda q, i=i: i) for i in range(5)}
        result = chains.execute("query", paths, accept=lambda value: value == 2)
        self.assertEqual(result["result"], 2)
        self.assertLessEqual(len(result["attempts"]), 3)
        self.assertEqual(chains.likely("query", paths)[0][0], "p2")

    def test_coarse_path_delegates_candidates_to_fine_executor(self):
        import speculative_executor as fine
        chains = v15.SpeculativeChains(max_paths=1)
        candidate = fine.TaskCandidate("fine", lambda: "fine-winner")
        result = chains.execute("query", {"coarse": lambda q: [candidate]})
        self.assertEqual(result["result"], "fine-winner")

    def test_ephemeral_cluster_forms_and_dissolves(self):
        topology = v15.QueryTopology(formation_threshold=2, ttl_seconds=.01)
        teacher = lambda q: q["x"] * 2
        self.assertIsNone(topology.observe("pareto", {"x": 1}, teacher))
        cluster = topology.observe("pareto", {"x": 2}, teacher)
        self.assertIsNotNone(cluster)
        self.assertEqual(cluster.node({"x": 3}), 6)
        cluster.last_seen = time.time() - 1
        self.assertEqual(topology.dissolve(), 1)

    def test_runtime_memory_short_circuit(self):
        rt = v15.HivemindV15()
        paths = {"fast": lambda q: q["x"] + 1}
        first = rt.execute_query("trojun", {"x": 1}, paths)
        second = rt.execute_query("predictions", {"x": 1}, paths)
        self.assertEqual(first["result"], 2)
        self.assertEqual(second["source"], "federated_memory")


class TestLearning(unittest.TestCase):
    def test_multiscale_causal_prediction(self):
        graph = v15.FractalCausalGraph(scales=(1, 4))
        for i in range(40): graph.observe({"driver": i, "target": max(0, i - 1)})
        result = graph.predict("target", ["driver"])
        self.assertTrue(result["causes"])
        self.assertGreater(result["prediction"], 38)

    def test_adversarial_curriculum_promotes(self):
        cur = v15.AdversarialAnomalyCurriculum(seed=1)
        batch = cur.generate([1, 2, 3])
        self.assertEqual(len(batch), 8)
        for _ in range(16): cur.record(True)
        self.assertEqual(cur.level, 2)

    def test_distilled_node_replays_without_teacher(self):
        calls = []
        node = v15.DistilledNode(lambda q: calls.append(q) or q["x"])
        self.assertEqual(node({"x": 4}), 4)
        self.assertEqual(node({"x": 9}), 9)  # different value must not stale-replay
        self.assertEqual(node({"x": 4}), 4)
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
